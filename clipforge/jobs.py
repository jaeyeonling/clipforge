"""Job 러너: 파이프라인 단계를 순서대로 실행하며 진행률·로그·취소를 제공한다 (PRODUCT_ARCHITECTURE §10-2).

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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .project import Project

STAGES = ["prep", "transcribe", "signals", "shorts", "export", "xml", "weaklabel", "eval"]


@dataclass
class Job:
    id: str
    episode: str
    stages: list[str]
    params: dict
    status: str = "queued"            # queued | running | done | error | cancelled
    stage: str = ""
    pct: float = 0.0
    message: str = ""
    started: float = 0.0
    finished: float = 0.0
    error: str | None = None
    events: list[dict] = field(default_factory=list)
    cancel_event: threading.Event = field(default_factory=threading.Event)
    log_path: Path | None = None

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
        self.emit({"type": "progress", "stage": stage, "pct": self.pct, "message": message})

    def log(self, message: str) -> None:
        self.emit({"type": "log", "stage": self.stage, "message": message})

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if k not in ("events", "cancel_event", "log_path")} | {
            "log_path": str(self.log_path) if self.log_path else None}


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
        job = Job(id=uuid.uuid4().hex[:8], episode=episode, stages=[s for s in STAGES if s in (stages or STAGES)],
                  params=params or {})
        (self.project.reports / "jobs").mkdir(parents=True, exist_ok=True)
        job.log_path = self.project.reports / "jobs" / f"{job.id}_{episode}.jsonl"
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
                    job.status = "cancelled"; job.emit({"type": "done", "status": "cancelled"}); return
                base = 100.0 * i / len(job.stages)
                span = 100.0 / len(job.stages)
                job.progress(stage, base, f"{stage} 시작")
                t0 = time.time()
                run_stage(self.project, job, stage, lambda frac, msg="": job.progress(stage, base + span * frac, msg))
                job.log(f"{stage} 완료 ({time.time() - t0:.0f}s)")
            job.status, job.finished = "done", time.time()
            job.progress("done", 100.0, "완료")
            job.emit({"type": "done", "status": "done"})
        except Exception as e:  # noqa: BLE001
            job.status, job.finished = "error", time.time()
            job.error = f"{type(e).__name__}: {e}"
            job.log(traceback.format_exc())
            job.emit({"type": "error", "code": type(e).__name__, "message": str(e)[:400],
                      "hint": hint_for(e)})


def hint_for(e: Exception) -> str:
    s = str(e)
    if "ffmpeg" in s.lower() or "ffprobe" in s.lower():
        return "ffmpeg 를 찾지 못했거나 실패했습니다. 설치 폴더의 bin/ 또는 PATH 를 확인하세요."
    if "transcript.json" in s:
        return "전사가 아직 없습니다. transcribe 단계를 먼저 실행하세요."
    if "rois" in s and "banner" in s:
        return "게임 프로필(games/<game>.yaml)의 ROI 설정을 확인하세요."
    if "CUDA" in s or "cudnn" in s.lower():
        return "GPU 런타임 문제입니다. nvidia-cublas-cu12 / nvidia-cudnn-cu12 설치 또는 CPU 폴백을 확인하세요."
    return ""


# ---------- 단계 실행 (run.py 의 cmd_* 와 동일한 동작) ----------
def run_stage(project: Project, job: Job, stage: str, prog: Callable[[float, str], None]) -> None:
    import csv

    from .timeline import Segments
    vid = job.episode
    cache = project.cache / vid
    if stage == "prep":
        from .preprocess import preprocess
        video = next((p for p in project.videos.glob(f"{vid}.*") if p.suffix.lower() in (".mp4", ".mkv", ".mov")), None)
        if video is None:
            raise FileNotFoundError(f"videos/{vid}.mp4 없음")
        prog(0.02, "ffprobe / 단일 패스 디코딩")
        # 진행률: ffmpeg 가 쓰는 frames/*.jpg 개수를 폴링해 기대 프레임 수(길이 × fps) 대비 비율로
        done_flag = threading.Event()
        err: list[BaseException] = []

        def work():
            try:
                preprocess(video, project.cache, force=bool(job.params.get("force")), game=job.params.get("game"),
                           proxy=bool(job.params.get("proxy")))
            except BaseException as e:  # noqa: BLE001
                err.append(e)
            finally:
                done_flag.set()
        th = threading.Thread(target=work, daemon=True); th.start()
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
                prog(0.05 + 0.9 * min(1.0, n / expected), f"디코딩 {n}/{expected} 프레임")
            if job.cancel_event.is_set():
                job.log("취소 요청 — 현재 ffmpeg 패스가 끝나면 멈춥니다")
        if err:
            raise err[0]
        prog(1.0, "frames/rois/audio 준비됨")
    elif stage == "transcribe":
        from .transcribe import transcribe
        prog(0.05, "Whisper (GPU → CPU 폴백)")
        tr = transcribe(cache, force=bool(job.params.get("force")))
        prog(1.0, f"{tr.get('backend')} {len(tr.get('segments', []))} segments")
    elif stage == "signals":
        from .signals import REGISTRY, run_signal
        names = list(REGISTRY)
        for i, name in enumerate(names):
            if job.cancel_event.is_set():
                return
            prog(i / len(names), f"signal {name}")
            run_signal(name, cache, bool(job.params.get("force")))
        prog(1.0, f"{len(names)} signals")
    elif stage == "shorts":
        from .run import load_kernels, load_meta, load_signals  # 기존 로더 재사용
        from .shorts import make_shorts, save_shorts
        meta = load_meta(vid)
        curves, events = load_signals(vid)
        cands = make_shorts(cache, events, curves, meta["duration"], k=int(job.params.get("k", 5)))
        save_shorts(cands, cache / "shorts.json")
        prog(1.0, f"{len(cands)} candidates")
    elif stage == "export":
        from .render import render_shorts
        from .run import load_episode, load_meta, load_shorts, short_episode_label
        meta = load_meta(vid)
        cands = load_shorts(vid)
        tr_p = cache / "transcript.json"
        tr = json.loads(tr_p.read_text(encoding="utf-8")) if tr_p.exists() else None
        chat_p = cache / "chat_text.json"
        chat = [{"t": s.start, "nick": s.meta.get("nick", ""), "text": s.meta.get("text", "")} for s in Segments.load(chat_p).items] if chat_p.exists() else None
        ui_p = cache / "ui_state.json"
        ui = [{"start": s.start, "end": s.end, "label": s.label} for s in Segments.load(ui_p).items] if ui_p.exists() else None
        ep = load_episode(vid) or {}
        out = project.review / vid / "shorts"
        (out / "keep").mkdir(parents=True, exist_ok=True); (out / "no").mkdir(parents=True, exist_ok=True)
        prog(0.05, "렌더 (NVENC)")
        idx = render_shorts(cands, meta, out, k=int(job.params.get("k", 5)), transcript=tr, chat=chat, ui=ui,
                            layout=job.params.get("layout", "feed"), brand=job.params.get("brand", "디아블로2 하이라이트"),
                            episode_label=short_episode_label(ep.get("title", "")) or vid,
                            progress=lambda f, m="": prog(0.05 + 0.9 * f, m))
        prog(1.0, f"{len(idx)} drafts")
    elif stage == "xml":
        from .export_xml import export_xml
        from .run import load_meta, load_shorts
        meta = load_meta(vid)
        cands_p = cache / "candidates.json"
        cands = Segments.load(cands_p) if cands_p.exists() else Segments("candidates", [])
        ui_p = cache / "ui_state.json"
        ui = [{"start": s.start, "end": s.end, "label": s.label} for s in Segments.load(ui_p).items] if ui_p.exists() else None
        export_xml(meta, cands, load_shorts(vid), ui, project.premiere, vid, k=int(job.params.get("k", 5)))
        prog(1.0, "xml")
    elif stage == "weaklabel":
        from .run import load_meta
        from .weaklabel import load_episode, load_slang, match_banner, title_keywords, write_weak_labels
        meta = load_meta(vid)
        ep = load_episode(vid)
        title = job.params.get("title") or (ep or {}).get("title")
        if title and (cache / "item_banner.json").exists():
            kws = title_keywords(title, load_slang(meta.get("game", "d2r")))
            matches = match_banner(kws, Segments.load(cache / "item_banner.json"))
            write_weak_labels(vid, matches, project.labels, duration=meta["duration"])
            prog(1.0, f"{len(matches)} weak labels")
        else:
            prog(1.0, "제목 없음 — 건너뜀")
    elif stage == "eval":
        from .eval_shorts import evaluate_shorts
        from .run import load_shorts
        lab_p = project.labels / f"{vid}.shorts.csv"
        if lab_p.exists():
            reps = evaluate_shorts(load_shorts(vid), Segments.from_csv(lab_p))
            job.log("\n".join(r.pretty() for r in reps))
        prog(1.0, "eval")
    else:
        raise ValueError(f"unknown stage {stage}")
