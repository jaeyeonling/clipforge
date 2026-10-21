"""Job 러너: 파이프라인 단계를 순서대로 실행하며 진행률·로그·취소를 제공한다 (docs/ARCHITECTURE.md · 작업(Job)).

    runner = JobRunner(project)
    job = runner.submit("ep59", stages=["prep","transcribe","signals","shorts","export","xml"], params={})
    job.events  ← {"type": "progress"|"log"|"done"|"error", ...}  (서버가 WebSocket 으로 중계)

단계는 run.py 의 cmd_* 와 같은 모듈 함수를 호출한다. 각 단계는 캐시가 있으면 빠르게 지나간다(기존 캐시 규칙 그대로).
취소: cancel_event 가 set 되면 다음 단계 경계에서 멈춘다. 단계 내부(ffmpeg 등)는 현재 패스를 끝내고 멈춘다.
"""

from __future__ import annotations

import json
import threading
import time
import traceback
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from . import __version__ as ENGINE_VERSION
from .errors import EngineError, classify
from .project import Project
from .schema import SCHEMA

STAGES = [
    "prep",
    "transcribe",
    "subtitles",
    "signals",
    "candidates",
    "align",
    "shorts",
    "export",
    "xml",
    "weaklabel",
    "eval",
]
# 회차 종류별 기본 단계. edited = Phase 1 (쇼츠), original = Phase 2 (편집 포인트). subtitles 는 선택 단계(영상 전체 자막 파일)라 기본에 넣지 않는다.
DEFAULT_STAGES = {
    "edited": ["prep", "transcribe", "signals", "shorts", "export", "xml"],
    "original": ["prep", "transcribe", "signals", "candidates", "align", "eval"],
}


def episode_kind(project: Project, vid: str, params: dict | None = None) -> str:
    k = (params or {}).get("kind") or project.episode_rows().get(vid, {}).get("kind") or ""
    if not k:
        try:
            import json as _json

            k = _json.loads((project.cache / vid / "meta.json").read_text(encoding="utf-8")).get("kind", "")
        except OSError:
            k = ""
    return k if k in ("edited", "original") else "edited"


# 진행 줄에 보일 신호 이름
SIGNAL_LABEL = {
    "audio_loudness": "소리 크기",
    "frame_motion": "화면 움직임",
    "chat_burst": "채팅 폭주",
    "chat_text": "채팅 글자",
    "cut_density": "장면 전환",
    "edit_emphasis": "편집 강조",
    "item_banner": "득템 배너",
    "speech_keyword": "리액션 말",
    "ui_state": "템 창 위치",
}


def pipeline_cfg(project: Project, kind: str, game: str | None = None) -> dict:
    """회차 종류별 신호 묶음·장면 전환 설정. 게임 프로필의 pipelines 가 있으면 그 게임에서는 그것을 쓴다."""
    from .profiles import load_settings

    cfg = load_settings(game, project.games).get("pipelines", {})
    return cfg.get(kind) or {"signals": "all", "scene_cuts": kind != "original"}


def episode_game_of(project: Project, vid: str) -> str | None:
    """회차의 게임: 전처리 결과(meta.json) → 등록 정보(episodes.csv) 순."""
    from .profiles import episode_game

    return episode_game(project.cache / vid) or (project.episode_rows().get(vid) or {}).get("game") or None


# ---- 캐시 로더 (run.py 의 CACHE 전역은 저장소 기준이라 데이터 폴더가 분리된 설치본에서는 쓰면 안 된다) ----
def _meta(project: Project, vid: str) -> dict:
    from .schema import load_json

    return load_json(project.cache / vid / "meta.json", "meta")


def _signals(project: Project, vid: str):
    from .signals import REGISTRY
    from .timeline import Curve, Segments

    curves, events = {}, {}
    for name in REGISTRY:
        p = project.cache / vid / f"{name}.json"
        if not p.exists():
            continue
        try:
            curves[name] = Curve.load(p)
        except TypeError:
            events[name] = Segments.load(p)
    return curves, events


def _shorts(project: Project, vid: str):
    from .schema import load_json
    from .shorts import ShortCandidate

    return [ShortCandidate(**d) for d in load_json(project.cache / vid / "shorts.json", "shorts")]


@dataclass
class Job:
    id: str
    episode: str
    stages: list[str]
    params: dict
    status: str = "queued"  # queued | running | done | error | cancelled
    stage: str = ""
    pct: float = 0.0
    message: str = ""
    started: float = 0.0
    finished: float = 0.0
    error: str | None = None
    error_info: dict | None = None  # classify() 결과 {code, message, hint, kind}
    stage_durations: dict = field(default_factory=dict)
    eta_s: float | None = None  # 남은 예상 시간(초). 과거 매니페스트의 단계별 소요 × 이 회차 길이로 추정
    stage_eta: dict = field(default_factory=dict)  # 단계별 예상 소요
    warnings: list = field(default_factory=list)  # [{code, message, hint}] — 완료했지만 사람이 볼 것 (캘리브레이션 등)
    events: list[dict] = field(default_factory=list)
    cancel_event: threading.Event = field(default_factory=threading.Event)
    log_path: Path | None = None
    manifest_path: Path | None = None

    def emit(self, ev: dict) -> None:
        ev = {"job_id": self.id, "t": round(time.time(), 3), **ev}
        self.events.append(ev)
        if self.log_path:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(ev, ensure_ascii=False) + "\n")
        for cb in _listeners:
            try:
                cb(ev)
            except Exception:
                pass

    def progress(self, stage: str, pct: float, message: str = "") -> None:
        self.stage, self.pct, self.message = stage, round(pct, 1), message
        self.emit({"type": "progress", "stage": stage, "pct": self.pct, "message": message, "eta_s": self.eta_s})

    def log(self, message: str) -> None:
        self.emit({"type": "log", "stage": self.stage, "message": message})

    def to_dict(self) -> dict:
        return {
            k: v for k, v in self.__dict__.items() if k not in ("events", "cancel_event", "log_path", "manifest_path")
        } | {
            "log_path": str(self.log_path) if self.log_path else None,
            "manifest_path": str(self.manifest_path) if self.manifest_path else None,
        }

    def manifest(self) -> dict:
        """run 매니페스트: 무엇을 어떤 파라미터로 돌렸고 얼마나 걸렸고 어떻게 끝났는지. 재현·대시보드용."""
        return {
            "id": self.id,
            "episode": self.episode,
            "stages": self.stages,
            "params": self.params,
            "status": self.status,
            "started": self.started,
            "finished": self.finished,
            "stage_durations": self.stage_durations,
            "error": self.error_info,
            "warnings": self.warnings,
            "media_duration": self.params.get("_media_duration"),
            "engine_version": ENGINE_VERSION,
            "schema": dict(SCHEMA),
            "log_path": str(self.log_path) if self.log_path else None,
        }

    def write_manifest(self) -> None:
        if not self.manifest_path:
            return
        try:
            self.manifest_path.write_text(json.dumps(self.manifest(), ensure_ascii=False, indent=1), encoding="utf-8")
        except OSError:
            pass


_listeners: list[Callable[[dict], None]] = []


def add_listener(cb: Callable[[dict], None]) -> None:
    _listeners.append(cb)


class JobRunner:
    def __init__(self, project: Project):
        self.project = project
        self.jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._worker: threading.Thread | None = None
        self._queue: list[str] = []

    def submit(self, episode: str, stages: list[str], params: dict | None = None) -> Job:
        job = Job(
            id=uuid.uuid4().hex[:8],
            episode=episode,
            stages=[s for s in STAGES if s in (stages or STAGES)],
            params=params or {},
        )
        try:
            job.stage_eta = estimate_stage_eta(self.project, episode, job.stages, job.params)
            job.eta_s = round(sum(job.stage_eta.values()), 1)
        except Exception:
            pass
        (self.project.reports / "jobs").mkdir(parents=True, exist_ok=True)
        job.log_path = self.project.reports / "jobs" / f"{job.id}_{episode}.jsonl"
        job.manifest_path = self.project.reports / "jobs" / f"{job.id}_{episode}.manifest.json"
        with self._lock:
            self.jobs[job.id] = job
            self._queue.append(job.id)
            if not self._worker or not self._worker.is_alive():
                self._worker = threading.Thread(target=self._loop, daemon=True)
                self._worker.start()
        job.emit({"type": "queued", "stages": job.stages})
        return job

    def cancel(self, job_id: str) -> bool:
        job = self.jobs.get(job_id)
        if not job:
            return False
        job.cancel_event.set()
        if job.status == "queued":
            job.status = "cancelled"
            with self._lock:
                if job_id in self._queue:
                    self._queue.remove(job_id)
            job.emit({"type": "done", "status": "cancelled"})
            job.write_manifest()
        return True

    def _loop(self) -> None:
        while True:
            with self._lock:
                if not self._queue:
                    return
                job = self.jobs[self._queue.pop(0)]
            self._run(job)

    def _run(self, job: Job) -> None:
        job.status, job.started = "running", time.time()
        job.emit({"type": "started"})
        try:
            for i, stage in enumerate(job.stages):
                if job.cancel_event.is_set():
                    job.status, job.finished = "cancelled", time.time()
                    job.emit({"type": "done", "status": "cancelled", "episode": job.episode})
                    return
                base = 100.0 * i / len(job.stages)
                span = 100.0 / len(job.stages)
                job.progress(stage, base, f"{stage} 시작")
                t0 = time.time()
                remaining_after = sum(job.stage_eta.get(s, 0) for s in job.stages[i + 1 :])
                est_this = job.stage_eta.get(stage, 0)

                def _prog(
                    frac, msg="", _t0=t0, _base=base, _span=span, _stage=stage, _after=remaining_after, _est=est_this
                ):
                    job.eta_s = round(max(0.0, _est * (1 - frac)) + _after, 1) if _est else job.eta_s
                    job.progress(_stage, _base + _span * frac, msg)

                run_stage(self.project, job, stage, _prog)
                job.stage_durations[stage] = round(time.time() - t0, 1)
                job.eta_s = round(sum(job.stage_eta.get(s, 0) for s in job.stages[i + 1 :]), 1)
                job.log(f"{stage} 완료 ({time.time() - t0:.0f}s)")
            job.status, job.finished = "done", time.time()
            job.eta_s = 0.0
            job.progress("done", 100.0, "완료")
            job.emit(
                {
                    "type": "done",
                    "status": "done",
                    "warnings": job.warnings,
                    "stages": job.stages,
                    "episode": job.episode,
                }
            )
        except (Exception, SystemExit) as e:
            job.status, job.finished = "error", time.time()
            info = classify(e)
            job.error, job.error_info = info["message"], info
            job.emit({"type": "log", "stage": job.stage, "level": "error", "message": traceback.format_exc()})
            job.emit({"type": "error", "stage": job.stage, "episode": job.episode, **info})
        finally:
            job.write_manifest()


# 단계별 기본 소요 (초 / 영상 1분). 4K60 11.7분 ep59 실측 기준. 매니페스트가 쌓이면 그 평균으로 대체.
DEFAULT_RATE = {
    "prep": 15.0,
    "transcribe": 3.0,
    "subtitles": 0.1,
    "signals": 32.0,
    "candidates": 0.3,
    "align": 1.0,
    "shorts": 0.5,
    "export": 6.0,
    "xml": 0.2,
    "weaklabel": 0.2,
    "eval": 0.2,
}


def estimate_stage_eta(project: Project, vid: str, stages: list[str], params: dict | None = None) -> dict[str, float]:
    """단계별 예상 소요(초). 과거 매니페스트(같은 종류 회차)의 '초/영상분' 평균 → 없으면 DEFAULT_RATE. 캐시가 있는 단계는 짧게."""
    import glob

    minutes = None
    try:
        minutes = float(_meta(project, vid)["duration"]) / 60.0
    except Exception:
        vp = project.video_path(vid)
        if vp:
            try:
                from .preprocess import probe

                minutes = float(probe(vp)["duration"]) / 60.0
            except Exception:
                minutes = None
    minutes = minutes or 10.0
    (params or {}).__setitem__("_media_duration", round(minutes * 60, 1)) if isinstance(params, dict) else None
    rates: dict[str, list[float]] = {}
    for mp in glob.glob(str(project.reports / "jobs" / "*.manifest.json")):
        try:
            m = json.loads(Path(mp).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        md = m.get("media_duration")
        if m.get("status") != "done" or not md:
            continue
        for st, sec in (m.get("stage_durations") or {}).items():
            if sec and sec > 1.0:  # 캐시 적중(수 초)은 제외
                rates.setdefault(st, []).append(float(sec) / (md / 60.0))
    cache = project.cache / vid
    cached = {
        "prep": (cache / "frames").exists(),
        "transcribe": (cache / "transcript.json").exists(),
        "subtitles": (project.premiere / vid / f"{vid}.srt").exists(),
        "signals": (cache / "item_banner.json").exists() or (cache / "audio_loudness.json").exists(),
    }
    force = bool((params or {}).get("force"))
    out = {}
    for st in stages:
        if cached.get(st) and not force:
            out[st] = 2.0
            continue
        r = (sum(rates[st]) / len(rates[st])) if rates.get(st) else DEFAULT_RATE.get(st, 1.0)
        out[st] = round(r * minutes, 1)
    return out


def hint_for(e: Exception) -> str:  # 하위 호환
    return classify(e)["hint"]


def _require(path: Path, code: str, what: str, stage_hint: str) -> None:
    if not path.exists():
        raise EngineError(code, f"{what} 없음: {path}", stage_hint)


# ---------- 단계 실행 (run.py 의 cmd_* 와 동일한 동작) ----------
def _stage_prep(project: Project, job: Job, prog: Callable[[float, str], None]) -> None:
    """영상 읽기: 한 번의 디코드로 오디오 · 1초 프레임 · 화면 영역 원본 크롭 · 장면 전환을 뽑는다."""
    vid = job.episode
    cache = project.cache / vid
    from .preprocess import preprocess

    video = project.video_path(vid)
    if video is None:
        raise EngineError(
            "E_FILE_MISSING",
            f"회차 {vid} 의 영상을 찾지 못했어요",
            "videos/ 폴더에 영상을 넣거나, 참조 등록한 원본 파일이 아직 그 자리에 있는지 확인하세요.",
        )
    kind = episode_kind(project, vid, job.params)
    pcfg = pipeline_cfg(project, kind, episode_game_of(project, vid))
    prog(0.02, f"영상을 읽는 중이에요 ({'편집본' if kind == 'edited' else '원본'})")
    # 진행률: ffmpeg 가 쓰는 frames/*.jpg 개수를 폴링해 기대 프레임 수(길이 × fps) 대비 비율로
    done_flag = threading.Event()
    err: list[BaseException] = []

    def work():
        try:
            preprocess(
                video,
                project.cache,
                force=bool(job.params.get("force")),
                game=job.params.get("game"),
                proxy=bool(job.params.get("proxy")),
                vid=vid,
                kind=kind,
                scene_cuts=job.params.get("scene_cuts", pcfg.get("scene_cuts")),
            )
        except BaseException as e:
            err.append(e)
        finally:
            done_flag.set()

    th = threading.Thread(target=work, daemon=True)
    th.start()
    expected = None
    while not done_flag.wait(2.0):
        meta_p = cache / "meta.json"
        if expected is None and meta_p.exists():
            try:
                m = json.loads(meta_p.read_text(encoding="utf-8"))
                expected = max(1, int(m["duration"] * float(m.get("frames", {}).get("fps", 1.0))))
            except Exception:
                pass
        if expected:
            n = len(list((cache / "frames").glob("*.jpg"))) if (cache / "frames").exists() else 0
            prog(0.05 + 0.9 * min(1.0, n / expected), f"화면 {n}/{expected}장을 읽었어요")
        if job.cancel_event.is_set():
            job.log("취소 요청 — 현재 ffmpeg 패스가 끝나면 멈춰요")
    if err:
        raise err[0]
    prog(1.0, "영상 읽기가 끝났어요")


def _stage_transcribe(project: Project, job: Job, prog: Callable[[float, str], None]) -> None:
    """말을 글로: faster-whisper 전사 → transcript.json."""
    cache = project.cache / job.episode
    from .transcribe import transcribe

    _require(cache / "audio.wav", "E_NO_PREP", "오디오(prep 결과)", "prep 단계를 먼저 실행하세요.")
    prog(0.05, "말을 글로 바꾸는 중이에요")
    tr = transcribe(cache, force=bool(job.params.get("force")))
    prog(
        1.0,
        f"말 {len(tr.get('segments', []))}마디를 글로 바꿨어요 ({'GPU' if tr.get('device') == 'cuda' else 'CPU'})",
    )


def _stage_subtitles(project: Project, job: Job, prog: Callable[[float, str], None]) -> None:
    """자막 파일: 영상 전체 자막을 SRT · VTT · VEGAS 텍스트로."""
    vid = job.episode
    cache = project.cache / vid
    # 영상 전체 자막 파일 (SRT + VTT). 쇼츠 초안 옆 .srt 와 달리 회차 하나를 통째로 — '자막만 달고 싶을 때' 경로.
    from .subtitles import cues_for_clip, write_srt, write_vegas_txt, write_vtt

    tr_p = cache / "transcript.json"
    _require(tr_p, "E_NO_TRANSCRIPT", "전사 결과(transcript.json)", "transcribe 단계를 먼저 실행하세요.")
    tr = json.loads(tr_p.read_text(encoding="utf-8"))
    segs = tr.get("segments", [])
    try:
        meta = _meta(project, vid)
        duration = float(meta["duration"])
        fps = float(meta.get("fps") or 30.0)
    except Exception:
        duration = max((float(sg.get("end", 0.0)) for sg in segs), default=0.0)
        fps = 30.0
    max_chars = int(job.params.get("max_chars", 28))  # 가로 전체 영상이라 쇼츠(18자)보다 길게
    cues = cues_for_clip(tr, 0.0, duration, max_chars=max_chars)
    out_dir = project.premiere / vid
    out_dir.mkdir(parents=True, exist_ok=True)
    write_srt(cues, out_dir / f"{vid}.srt", 0.0)
    write_vtt(cues, out_dir / f"{vid}.vtt", 0.0)
    write_vegas_txt(cues, out_dir / f"{vid}.vegas.txt", 0.0, fps)  # VEGAS Pro 는 SRT 대신 TXT/CSV 만 공식 지원
    if not cues:
        job.warnings.append(
            {
                "code": "W_NO_SPEECH",
                "message": "들리는 말이 없어 자막이 비었어요",
                "hint": "영상에 목소리가 있는지, 전사(transcribe)가 제대로 됐는지 확인하세요. 파일은 만들어졌지만 큐가 0개예요.",
            }
        )
    job.log(f"subtitles: {len(cues)} cues · {out_dir / (vid + '.srt')}")
    prog(1.0, f"자막 {len(cues)}줄을 만들었어요 (SRT · VTT · VEGAS)")


def _stage_signals(project: Project, job: Job, prog: Callable[[float, str], None]) -> None:
    """순간 신호: 회차 종류·게임에 맞는 신호 묶음을 돌리고, 화면 영역 적중률이 낮으면 경고를 남긴다."""
    vid = job.episode
    cache = project.cache / vid
    from .signals import REGISTRY, run_signal

    _require(cache / "meta.json", "E_NO_PREP", "prep 결과(meta.json)", "prep 단계를 먼저 실행하세요.")
    kind = episode_kind(project, vid, job.params)
    want = job.params.get("signals") or pipeline_cfg(project, kind, episode_game_of(project, vid)).get("signals", "all")
    names = list(REGISTRY) if want == "all" else [n for n in want if n in REGISTRY]
    job.log(f"signals [{kind}]: {', '.join(names)}")
    for i, name in enumerate(names):
        if job.cancel_event.is_set():
            return
        prog(i / len(names), f"{SIGNAL_LABEL.get(name, name)} 찾는 중이에요")
        run_signal(name, cache, bool(job.params.get("force")))
    # 신호가 끝나면 ROI 적중률을 자동 점검 — 화면 레이아웃이 바뀐 회차를 사람이 모르고 지나가지 않게
    try:
        from .calibrate import check as calib_check

        rep = calib_check(project, vid)
        bad = [c for c in rep.get("checks", []) if c.get("status") in ("fail", "warn")]
        if rep.get("ok") and bad:
            job.warnings.append(
                {
                    "code": "W_CALIBRATION",
                    "message": "화면 영역(ROI) 점검에서 경고: " + ", ".join(f"{c['name']} {c['status']}" for c in bad),
                    "hint": "캘리브레이션 탭에서 미리보기를 확인하세요. 오버레이 위치가 바뀐 회차면 ROI 를 조정하고 prep 을 다시 실행해요.",
                }
            )
            job.emit({"type": "log", "stage": "signals", "level": "warn", "message": job.warnings[-1]["message"]})
        else:
            job.log("캘리브레이션 점검 통과" if rep.get("ok") else f"캘리브레이션 점검 생략: {rep.get('error', '')}")
    except Exception as e:
        job.log(f"캘리브레이션 점검 실패(무시): {str(e)[:120]}")
    prog(1.0, f"순간 신호 {len(names)}가지를 찾았어요")


def _stage_candidates(project: Project, job: Job, prog: Callable[[float, str], None]) -> None:
    """편집 포인트 후보 (원본): 신호 가중합 → 구간."""
    vid = job.episode
    cache = project.cache / vid
    # Phase 2: 신호 → 편집 포인트 후보 (candidates.json). 가중치·커널은 프로필, 임계값은 파라미터
    from .candidates import SIGNAL_WEIGHTS, make_candidates
    from .profiles import load_profile

    _require(cache / "meta.json", "E_NO_PREP", "prep 결과(meta.json)", "prep 단계를 먼저 실행하세요.")
    meta = _meta(project, vid)
    curves, events = _signals(project, vid)
    if not curves and not events:
        raise EngineError("E_NO_SIGNALS", "신호 결과가 없어요", "signals 단계를 먼저 실행하세요.")
    weights = dict(SIGNAL_WEIGHTS)
    weights.update(job.params.get("weights") or {})
    kernels = load_profile(meta.get("game", "d2r")).get("events", {}) or {}
    segs = make_candidates(
        curves, meta["duration"], weights, events, kernels, threshold=float(job.params.get("threshold", 1.5))
    )
    segs.save(cache / "candidates.json")
    cov = segs.total_duration() / max(1.0, meta["duration"])
    job.log(f"candidates: {len(segs.items)}개, coverage {cov:.1%}, signals={segs.meta.get('signals')}")
    prog(1.0, f"편집 포인트 후보 {len(segs.items)}개 · 원본의 {cov:.0%}")


def _stage_align(project: Project, job: Job, prog: Callable[[float, str], None]) -> None:
    """정답 만들기: 편집본(또는 올린 쇼츠)을 원본·편집본 오디오에 정렬해 살아남은 구간을 라벨로."""
    vid = job.episode
    cache = project.cache / vid
    # Phase 2 정답: 최종본 ↔ 원본 정렬 → labels/<vid>.csv kept
    from .align import (
        align_files,
        align_shorts,
        collect_shorts,
        extract_audio,
        pretty,
        pretty_shorts,
        write_labels,
        write_shorts_labels,
    )

    final = job.params.get("final")
    shorts = job.params.get("shorts")
    if not final and not shorts:
        raise EngineError(
            "E_BAD_PARAMS",
            "align 에는 최종본 파일(final) 또는 쇼츠 파일(shorts)이 필요해요",
            "원본이면 스트리머 편집본을, 편집본이면 스트리머 쇼츠를 지정하세요.",
        )
    _require(cache / "audio.wav", "E_NO_PREP", "오디오(prep 결과)", "prep 단계를 먼저 실행하세요.")
    if shorts:
        files = collect_shorts(shorts if isinstance(shorts, list) else [shorts])
        if not files:
            raise EngineError("E_FILE_MISSING", f"쇼츠 파일이 없어요: {shorts}", "mp4 파일이나 폴더 경로를 확인하세요.")
        res = align_shorts(
            cache / "audio.wav", files, cache, progress=lambda f, m="": prog(0.05 + (0.45 if final else 0.9) * f, m)
        )
        n = write_shorts_labels(project.labels / f"{vid}.shorts.csv", res)
        job.log(pretty_shorts(res))
        (cache / "align_shorts.json").write_text(
            json.dumps(
                [
                    {
                        "file": r["file"],
                        "path": r["path"],
                        "segments": [s.to_dict() for s in r["segments"]],
                        "matched_frac": r["diag"]["matched_frac"],
                    }
                    for r in res
                ],
                ensure_ascii=False,
                indent=1,
            ),
            encoding="utf-8",
        )
        if not final:
            prog(1.0, f"쇼츠 {len(files)}개를 맞춰 정답 {n}구간을 찾았어요")
            return
    fp = Path(str(final))
    if (project.cache / str(final) / "audio.wav").exists():
        final_wav, final_name = project.cache / str(final) / "audio.wav", str(final)
    elif fp.is_file():
        prog(0.02, "편집본에서 소리를 꺼내는 중이에요")
        final_wav, final_name = extract_audio(fp, cache / "align" / f"{fp.stem}.wav"), fp.name
    else:
        raise EngineError(
            "E_FILE_MISSING",
            f"최종본을 찾지 못했어요: {final}",
            "영상 파일 경로 또는 prep 된 회차 id 를 확인하세요.",
        )
    segs, diag = align_files(
        cache / "audio.wav", final_wav, cache_dir=cache, progress=lambda f, m="": prog(0.05 + 0.9 * f, m)
    )
    (cache / "align.json").write_text(
        json.dumps(
            {"final": final_name, "segments": [s.to_dict() for s in segs], **diag}, ensure_ascii=False, indent=1
        ),
        encoding="utf-8",
    )
    n = write_labels(project.labels / f"{vid}.csv", segs, final_name)
    job.log(pretty(segs, diag))
    prog(1.0, f"정답 구간 {n}개 · 편집본의 {diag['matched_frac'] * 100:.0f}%를 원본에서 찾았어요")


def _stage_shorts(project: Project, job: Job, prog: Callable[[float, str], None]) -> None:
    """쇼츠 후보: 판정으로 맞춘 축 가중치로 앵커 → 창 → 점수 → 같은 순간 하나만."""
    vid = job.episode
    cache = project.cache / vid
    from .preference import current_preference
    from .shorts import make_shorts, save_shorts

    _require(cache / "meta.json", "E_NO_PREP", "prep 결과(meta.json)", "prep 단계를 먼저 실행하세요.")
    _require(cache / "item_banner.json", "E_NO_SIGNALS", "신호 결과", "signals 단계를 먼저 실행하세요.")
    meta = _meta(project, vid)
    curves, events = _signals(project, vid)
    # 지금까지의 판정(모든 회차)으로 축 가중치를 맞춘다. 판정이 적으면 기본값 그대로.
    pref = current_preference(project.labels, project.cache, save_to=project.reports / "preference.json")
    job.log(
        f"판정 반영: {pref.reason} (쓸 만함 {pref.n_keep} · 안 씀 {pref.n_no})"
        + (" — " + " · ".join(f"{k} {v:.2f}" for k, v in pref.weights.items()) if pref.learned else "")
    )
    cands = make_shorts(cache, events, curves, meta["duration"], k=int(job.params.get("k", 5)), weights=pref.weights)
    save_shorts(cands, cache / "shorts.json")
    prog(1.0, f"쇼츠 후보 {len(cands)}개를 골랐어요")


def _stage_export(project: Project, job: Job, prog: Callable[[float, str], None]) -> None:
    """세로 초안 렌더."""
    from .timeline import Segments

    vid = job.episode
    cache = project.cache / vid
    from .render import render_shorts
    from .weaklabel import load_episode, short_episode_label

    _require(cache / "shorts.json", "E_NO_SHORTS", "후보(shorts.json)", "shorts 단계를 먼저 실행하세요.")
    meta = _meta(project, vid)
    cands = _shorts(project, vid)
    tr_p = cache / "transcript.json"
    tr = json.loads(tr_p.read_text(encoding="utf-8")) if tr_p.exists() else None
    chat_p = cache / "chat_text.json"
    chat = (
        [
            {"t": s.start, "nick": s.meta.get("nick", ""), "text": s.meta.get("text", "")}
            for s in Segments.load(chat_p).items
        ]
        if chat_p.exists()
        else None
    )
    ui_p = cache / "ui_state.json"
    ui = (
        [{"start": s.start, "end": s.end, "label": s.label} for s in Segments.load(ui_p).items]
        if ui_p.exists()
        else None
    )
    ep = load_episode(vid, project.episodes_csv) or {}
    out = project.review / vid / "shorts"
    (out / "keep").mkdir(parents=True, exist_ok=True)
    (out / "no").mkdir(parents=True, exist_ok=True)
    prog(0.05, "세로 초안을 만드는 중이에요")
    idx = render_shorts(
        cands,
        meta,
        out,
        k=int(job.params.get("k", 5)),
        transcript=tr,
        chat=chat,
        ui=ui,
        layout=job.params.get("layout", "card"),
        top_mode=job.params.get("top", "title"),
        brand=job.params.get("brand", "디아블로2 하이라이트"),
        episode_label=short_episode_label(ep.get("title", "")) or vid,
        progress=lambda f, m="": prog(0.05 + 0.9 * f, m),
    )
    prog(1.0, f"세로 초안 {len(idx)}개를 만들었어요")


def _stage_xml(project: Project, job: Job, prog: Callable[[float, str], None]) -> None:
    """Premiere 파일 (세로 시퀀스 · 리뷰 시퀀스)."""
    from .timeline import Segments

    vid = job.episode
    cache = project.cache / vid
    from .export_xml import export_xml

    meta = _meta(project, vid)
    cands_p = cache / "candidates.json"
    cands = Segments.load(cands_p) if cands_p.exists() else Segments("candidates", [])
    ui_p = cache / "ui_state.json"
    ui = (
        [{"start": s.start, "end": s.end, "label": s.label} for s in Segments.load(ui_p).items]
        if ui_p.exists()
        else None
    )
    shorts = _shorts(project, vid) if (cache / "shorts.json").exists() else []
    if not shorts and not cands.items:
        raise EngineError(
            "E_NO_SHORTS",
            "후보가 없어요 (shorts.json / candidates.json)",
            "shorts 또는 candidates 단계를 먼저 실행하세요.",
        )
    export_xml(meta, cands, shorts, ui, project.premiere, vid, k=int(job.params.get("k", 5)))
    prog(1.0, "Premiere 파일을 만들었어요")


def _stage_weaklabel(project: Project, job: Job, prog: Callable[[float, str], None]) -> None:
    """제목의 득템 이름으로 약한 정답."""
    from .timeline import Segments

    vid = job.episode
    cache = project.cache / vid
    from .weaklabel import load_episode, load_slang, match_banner, title_keywords, write_weak_labels

    meta = _meta(project, vid)
    ep = load_episode(vid, project.episodes_csv)
    title = job.params.get("title") or (ep or {}).get("title")
    if title and (cache / "item_banner.json").exists():
        kws = title_keywords(title, load_slang(meta.get("game", "d2r")))
        matches = match_banner(kws, Segments.load(cache / "item_banner.json"))
        write_weak_labels(vid, matches, project.labels, duration=meta["duration"])
        prog(1.0, f"제목에서 정답 {len(matches)}개를 찾았어요")
    else:
        prog(1.0, "제목이 없어 건너뛰었어요")


def _stage_eval(project: Project, job: Job, prog: Callable[[float, str], None]) -> None:
    """점수: 쇼츠 hit@K · MRR, 편집 포인트 recall · coverage."""
    from .timeline import Segments

    vid = job.episode
    cache = project.cache / vid
    from .eval_shorts import evaluate_shorts
    from .evaluate import evaluate

    done = []
    lab_p = project.labels / f"{vid}.shorts.csv"
    if lab_p.exists() and (cache / "shorts.json").exists():
        reps = evaluate_shorts(_shorts(project, vid), Segments.from_csv(lab_p))
        job.log("[shorts]\n" + "\n".join(r.pretty() for r in reps))
        done.append("shorts")
    lab2 = project.labels / f"{vid}.csv"
    if lab2.exists() and (cache / "candidates.json").exists():
        meta = _meta(project, vid)
        rep = evaluate(Segments.load(cache / "candidates.json"), Segments.from_csv(lab2), meta["duration"])
        job.log("[editpoints]\n" + rep.pretty())
        done.append("editpoints")
        (project.reports / f"{vid}_editpoints_eval.json").write_text(
            json.dumps(
                {
                    "recall": rep.recall,
                    "precision": rep.precision,
                    "coverage": rep.coverage,
                    "n_labels": rep.n_labels,
                    "n_candidates": rep.n_candidates,
                    "missed": [{"start": m.start, "end": m.end, "label": m.label} for m in rep.missed],
                },
                ensure_ascii=False,
                indent=1,
            ),
            encoding="utf-8",
        )
    if not done:
        job.log("eval: 정답(labels/<id>.shorts.csv 또는 labels/<id>.csv)과 후보가 아직 없어요")
    prog(1.0, "점수를 매겼어요" if done else "점수를 매길 정답이 아직 없어요")


# 단계 이름 → 함수. 새 단계는 _stage_<이름> 을 만들고 여기와 STAGES 에 더한다.
STAGE_FNS: dict[str, Callable[[Project, Job, Callable[[float, str], None]], None]] = {
    "prep": _stage_prep,
    "transcribe": _stage_transcribe,
    "subtitles": _stage_subtitles,
    "signals": _stage_signals,
    "candidates": _stage_candidates,
    "align": _stage_align,
    "shorts": _stage_shorts,
    "export": _stage_export,
    "xml": _stage_xml,
    "weaklabel": _stage_weaklabel,
    "eval": _stage_eval,
}


def run_stage(project: Project, job: Job, stage: str, prog: Callable[[float, str], None]) -> None:
    fn = STAGE_FNS.get(stage)
    if fn is None:
        raise EngineError("E_BAD_STAGE", f"알 수 없는 단계: {stage}", f"가능: {STAGES}")
    fn(project, job, prog)
