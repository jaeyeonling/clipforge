"""엔진 API 메서드 (전송 방식과 무관). HTTP(server.py)와 stdio(stdio.py)가 이 함수들을 그대로 노출한다.

메서드는 모두 순수 dict 입출력. 오류는 ApiError(code, message, hint) 로 올린다.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

from ..errors import EngineError
from ..jobs import STAGES, JobRunner
from ..project import Project
from ..schema import load_json

ApiError = EngineError      # 전송층 오류 = 엔진 오류 같은 타입 (code, message, hint, kind)


class Engine:
    def __init__(self, project: Project | None = None):
        self.project = project or Project()
        self.runner = JobRunner(self.project)

    # ---- engine ----
    def health(self) -> dict:
        return self.project.health()

    # ---- episodes ----
    def episode_list(self) -> list[dict]:
        return [self.project.episode_info(v) for v in self.project.episode_ids()]

    def episode_get(self, vid: str) -> dict:
        if vid not in self.project.episode_ids():
            raise ApiError("E_NOT_FOUND", f"회차 없음: {vid}", "videos/ 에 <id>.mp4 를 넣고 다시 시도하세요")
        return self.project.episode_info(vid)

    def episode_add(self, video_path: str, vid: str | None = None, title: str = "", game: str = "d2r", link: bool = True, kind: str = "edited") -> dict:
        if kind not in ("edited", "original"):
            raise ApiError("E_BAD_PARAMS", f"kind 는 edited | original: {kind}")
        """영상 파일을 videos/ 에 등록(복사하지 않고 링크/복사 선택 — 지금은 복사 없이 같은 드라이브면 하드링크, 아니면 복사)."""
        src = Path(video_path)
        if not src.exists():
            raise ApiError("E_NOT_FOUND", f"파일 없음: {video_path}")
        if src.suffix.lower() not in self.project.VIDEO_EXTS:
            raise ApiError("E_BAD_FILE", f"영상 파일이 아닙니다: {src.name}", f"가능: {', '.join(self.project.VIDEO_EXTS)}")
        vid = self._safe_id(vid or src.stem)
        if vid in self.project.episode_ids() and (self.project.cache / vid / "meta.json").exists():
            existing = self.project.video_path(vid)
            if existing and existing.resolve() != src.resolve():
                raise ApiError("E_EXISTS", f"회차 {vid} 는 이미 다른 영상으로 등록돼 있습니다", "다른 id 를 지정하세요")
        dst = self.project.videos / f"{vid}{src.suffix.lower()}"
        linked = dst.exists()
        if not linked and link:
            try:
                import os
                os.link(src, dst); linked = True            # 같은 볼륨: 즉시, 용량 0
            except OSError:
                linked = False                               # 다른 볼륨: 복사하지 않고 원본 경로를 참조 (수 GB 복사 금지)
        self._upsert_episode_row(vid, game, title, source="" if linked else str(src.resolve()), kind=kind)
        return self.project.episode_info(vid)

    @staticmethod
    def _safe_id(s: str) -> str:
        """파일/URL/폴더 이름으로 쓸 수 있는 id. 공백 → _, 그 외 특수문자 제거 (한글·영숫자·-_. 허용)."""
        import re
        s = re.sub(r"\s+", "_", s.strip())
        s = re.sub(r"[^\w\-.]", "", s)
        return s.strip("._") or "ep"

    def _upsert_episode_row(self, vid: str, game: str, title: str, source: str | None = None, kind: str | None = None) -> None:
        p = self.project.episodes_csv
        rows: list[dict] = []
        if p.exists():
            with open(p, encoding="utf-8", newline="") as f:
                rows = list(csv.DictReader(f))
        fields = ["id", "game", "title", "url", "views", "uploaded", "raw_hours", "note", "source", "kind"]
        found = False
        for r in rows:
            if r.get("id") == vid:
                if title: r["title"] = title
                r["game"] = game or r.get("game", "")
                if source is not None: r["source"] = source
                if kind: r["kind"] = kind
                found = True
        if not found:
            rows.append({"id": vid, "game": game, "title": title, "url": "", "views": "", "uploaded": "", "raw_hours": "", "note": "", "source": source or "", "kind": kind or "edited"})
        with open(p, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields); w.writeheader()
            for r in rows:
                w.writerow({k: r.get(k, "") for k in fields})

    # ---- jobs ----
    def job_run(self, episode: str, stages: list[str] | None = None, params: dict | None = None) -> dict:
        if self.project.schema_error:
            se = self.project.schema_error
            raise ApiError(se["code"], se["message"], se["hint"])
        if episode not in self.project.episode_ids():
            raise ApiError("E_NOT_FOUND", f"회차 없음: {episode}")
        bad = [s for s in (stages or []) if s not in STAGES]
        if bad:
            raise ApiError("E_BAD_STAGE", f"알 수 없는 단계: {bad}", f"가능: {STAGES}")
        if "align" in (stages or []) and not (params or {}).get("final"):
            raise ApiError("E_BAD_PARAMS", "align 단계에는 최종본(편집본) 파일이 필요합니다", "파라미터 final 에 영상 경로를 주세요.")
        from ..jobs import DEFAULT_STAGES, episode_kind
        job = self.runner.submit(episode, stages or DEFAULT_STAGES[episode_kind(self.project, episode, params)], params)
        return job.to_dict()

    def job_get(self, job_id: str) -> dict:
        j = self.runner.jobs.get(job_id)
        if j:
            return j.to_dict()
        m = self._manifests().get(job_id)
        if not m:
            raise ApiError("E_NOT_FOUND", f"job 없음: {job_id}")
        return m

    def job_list(self) -> list[dict]:
        """메모리의 작업 + 이전 실행의 매니페스트(reports/jobs/*.manifest.json). 재시작해도 이력이 남는다."""
        live = {j.id: j.to_dict() for j in self.runner.jobs.values()}
        hist = {k: v for k, v in self._manifests().items() if k not in live}
        rows = list(hist.values()) + list(live.values())
        rows.sort(key=lambda r: r.get("started") or 0)
        return rows[-50:]

    def _manifests(self) -> dict[str, dict]:
        out = {}
        d = self.project.reports / "jobs"
        if not d.exists():
            return out
        for p in d.glob("*.manifest.json"):
            try:
                m = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            m.setdefault("stage", "done" if m.get("status") == "done" else ""); m.setdefault("pct", 100.0 if m.get("status") == "done" else 0.0)
            m.setdefault("message", ""); m["error"] = (m.get("error") or {}).get("message") if isinstance(m.get("error"), dict) else m.get("error")
            m["error_info"] = m.get("error") and (json.loads(p.read_text(encoding="utf-8")).get("error"))
            m["manifest_path"] = str(p); m["from_manifest"] = True
            out[m["id"]] = m
        return out

    def job_log(self, job_id: str, tail: int = 400) -> dict:
        """작업 로그(JSONL) 읽기: [{t, type, stage, level, message}]. UI 의 '로그 보기'."""
        j = self.runner.jobs.get(job_id)
        path = j.log_path if j else None
        if path is None:
            m = self._manifests().get(job_id)
            if not m or not m.get("log_path"):
                raise ApiError("E_NOT_FOUND", f"job 로그 없음: {job_id}")
            path = Path(m["log_path"])
        lines = []
        if path.exists():
            for raw in path.read_text(encoding="utf-8").splitlines()[-tail:]:
                try:
                    ev = json.loads(raw)
                except ValueError:
                    continue
                if ev.get("type") in ("log", "error", "progress", "started", "queued", "done"):
                    lines.append({"t": ev.get("t"), "type": ev["type"], "stage": ev.get("stage", ""),
                                  "level": ev.get("level") or ("error" if ev["type"] == "error" else "info"),
                                  "message": ev.get("message") or (f"[{ev.get('code')}] {ev.get('hint', '')}" if ev["type"] == "error" else ev["type"])})
        return {"job_id": job_id, "path": str(path), "lines": lines}

    def job_cancel(self, job_id: str) -> dict:
        if not self.runner.cancel(job_id):
            raise ApiError("E_NOT_FOUND", f"job 없음: {job_id}")
        return self.job_get(job_id)

    def job_events(self, job_id: str, since: int = 0) -> list[dict]:
        job = self.runner.jobs.get(job_id)
        if not job:
            raise ApiError("E_NOT_FOUND", f"job 없음: {job_id}")
        return job.events[since:]

    # ---- candidates / decisions ----
    def candidates_list(self, vid: str) -> list[dict]:
        idx_p = self.project.review / vid / "shorts" / "index.json"
        if not idx_p.exists():
            sj = self.project.cache / vid / "shorts.json"
            if not sj.exists():
                return []
            return load_json(sj, "shorts")
        rows = load_json(idx_p, "index")
        decisions = self._decisions(vid)
        for r in rows:
            key = (f"{r['start']:.1f}", f"{r['end']:.1f}")
            r["decision"] = decisions.get(key, {}).get("label", "")
            r["reason"] = decisions.get(key, {}).get("reason", "")
            r["media_url"] = f"/media/review/{vid}/shorts/{r['file']}"
        return rows

    def _labels_path(self, vid: str) -> Path:
        return self.project.labels / f"{vid}.shorts.csv"

    def _decisions(self, vid: str) -> dict:
        p = self._labels_path(vid)
        out = {}
        if p.exists():
            with open(p, encoding="utf-8", newline="") as f:
                for r in csv.DictReader(f):
                    if r.get("label") in ("keep", "no"):
                        note = r.get("note", "")
                        reason = note.split("|")[-1].strip() if "|" in note else ""
                        out[(f"{float(r['start']):.1f}", f"{float(r['end']):.1f}")] = {"label": r["label"], "reason": reason}
        return out

    # ---- Phase 2: 편집 포인트 ----
    def editpoints_list(self, vid: str) -> dict:
        """candidates.json + labels/<vid>.csv(kept·판정) → 후보 목록(겹침 표시), 정답 구간, 지표."""
        from ..evaluate import evaluate
        from ..timeline import Segments
        cp = self.project.cache / vid / "candidates.json"
        lab = self.project.labels / f"{vid}.csv"
        cands = Segments.load(cp) if cp.exists() else Segments("candidates", [])
        labels = Segments.from_csv(lab) if lab.exists() else Segments("labels", [])
        kept = [l for l in labels.items if l.label not in ("no", "")]
        rows = []
        for i, c in enumerate(cands.items):
            ov = [l for l in kept if l.overlap(c) >= min(1.0, l.duration)]
            dec = next((l for l in labels.items if abs(l.start - c.start) < 0.05 and abs(l.end - c.end) < 0.05 and str(l.meta.get("note", "")).startswith("ui")), None)
            rows.append({"idx": i, "start": c.start, "end": c.end, "score": round(c.score, 3), "label": c.label, "meta": c.meta,
                         "kept": bool(ov), "kept_labels": sorted({l.label for l in ov}), "decision": (dec.label if dec else "")})
        meta_p = self.project.cache / vid / "meta.json"
        duration = load_json(meta_p, "meta").get("duration", 0) if meta_p.exists() else 0
        rep = evaluate(cands, Segments("labels", kept), duration) if kept and cands.items and duration else None
        align_p = self.project.cache / vid / "align.json"
        align = json.loads(align_p.read_text(encoding="utf-8")) if align_p.exists() else None
        return {"episode": vid, "duration": duration, "candidates": rows, "signals": cands.meta.get("signals", []),
                "kept": [{"start": l.start, "end": l.end, "label": l.label, "note": l.meta.get("note", "")} for l in kept],
                "report": ({"recall": rep.recall, "precision": rep.precision, "coverage": rep.coverage, "n_labels": rep.n_labels, "n_candidates": rep.n_candidates,
                            "missed": [{"start": m.start, "end": m.end, "label": m.label} for m in rep.missed]} if rep else None),
                "align": ({"final": align.get("final"), "matched_frac": align.get("matched_frac"), "n_segments": align.get("n_segments"), "unmatched": align.get("unmatched")} if align else None),
                "video_url": f"/media/video/{vid}" if self.project.video_path(vid) else None}

    def decision_set(self, vid: str, start: float, end: float, label: str, reason: str = "", file: str = "", kind: str = "shorts") -> dict:
        if kind == "editpoints":
            return self._decision_editpoint(vid, start, end, label, reason)
        if label not in ("keep", "no", ""):
            raise ApiError("E_BAD_LABEL", "label 은 keep | no | '' (해제)")
        p = self._labels_path(vid)
        rows: list[dict] = []
        if p.exists():
            with open(p, encoding="utf-8", newline="") as f:
                rows = list(csv.DictReader(f))
        key = (f"{float(start):.1f}", f"{float(end):.1f}")
        rows = [r for r in rows if not (r.get("label") in ("keep", "no") and (f"{float(r['start']):.1f}", f"{float(r['end']):.1f}") == key)]
        if label:
            rows.append({"start": key[0], "end": key[1], "label": label,
                         "note": f"ui {file} | {reason}".strip(" |")})
        with open(p, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["start", "end", "label", "note"]); w.writeheader(); w.writerows(rows)
        return {"ok": True, "labels": len(rows)}

    def _decision_editpoint(self, vid: str, start: float, end: float, label: str, reason: str) -> dict:
        """Phase 2 사람 판정 → labels/<vid>.csv (kept|no, note 'ui …'). align 의 auto 행과 공존."""
        if label not in ("kept", "no", ""):
            raise ApiError("E_BAD_LABEL", "편집 포인트 label 은 kept | no | '' (해제)")
        p = self.project.labels / f"{vid}.csv"
        rows: list[dict] = []
        if p.exists():
            with open(p, encoding="utf-8", newline="") as f:
                rows = list(csv.DictReader(f))
        key = (f"{float(start):.2f}", f"{float(end):.2f}")
        rows = [r for r in rows if not (str(r.get("note", "")).startswith("ui") and (f"{float(r['start']):.2f}", f"{float(r['end']):.2f}") == key)]
        if label:
            rows.append({"start": key[0], "end": key[1], "label": label, "note": f"ui | {reason}".strip(" |")})
        rows.sort(key=lambda r: float(r["start"]))
        with open(p, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["start", "end", "label", "note"]); w.writeheader(); w.writerows(rows)
        return {"ok": True, "labels": len(rows)}

    # ---- calibration / profile ----
    def calibrate_check(self, vid: str) -> dict:
        from .. import calibrate
        return calibrate.check(self.project, vid)

    def calibrate_preview(self, vid: str, t: int | None = None, rois: dict | None = None) -> dict:
        from .. import calibrate
        try:
            out = calibrate.preview(self.project, vid, t, rois)
            frame, idx, meta = calibrate.frame_for(self.project, vid, t)
        except FileNotFoundError as e:
            raise ApiError("E_NO_FRAMES", str(e), "prep 단계를 먼저 실행하세요")
        from PIL import Image
        with Image.open(frame) as im:
            fw, fh = im.size
        return {"path": str(out), "url": f"/media/cache/{vid}/calib_preview.png?ts={int(out.stat().st_mtime)}",
                "t": idx, "n_frames": len(sorted((self.project.cache / vid / "frames").glob("*.jpg"))),
                "frame_url": f"/media/cache/{vid}/frames/{frame.name}", "frame_size": [fw, fh],       # 화면 편집기: 원본 프레임 + 비율 박스
                "rois": rois if rois is not None else calibrate.effective_rois(meta),
                "panel_bands": meta.get("panel_bands") or calibrate.DEFAULT_BANDS, "colors": {k: "#%02x%02x%02x" % v for k, v in calibrate.COLORS.items()}}

    def profile_get(self, game: str) -> dict:
        from .. import calibrate
        if not (self.project.games / f"{game}.yaml").exists():
            raise ApiError("E_NOT_FOUND", f"프로필 없음: {game}")
        return calibrate.get_rois(self.project, game)

    def profile_set(self, game: str, rois: dict, panel_bands: dict | None = None) -> dict:
        from .. import calibrate
        try:
            return calibrate.set_rois(self.project, game, rois, panel_bands)
        except ValueError as e:
            raise ApiError("E_BAD_ROI", str(e))

    # ---- metrics ----
    def metrics_summary(self) -> list[dict]:
        from ..eval_shorts import evaluate_shorts
        from ..evaluate import evaluate
        from ..shorts import ShortCandidate
        from ..timeline import Segments
        out = []
        for vid in self.project.episode_ids():
            # Phase 2 (편집 포인트): labels/<vid>.csv × candidates.json
            lab2 = self.project.labels / f"{vid}.csv"; cp = self.project.cache / vid / "candidates.json"; meta_p = self.project.cache / vid / "meta.json"
            if lab2.exists() and cp.exists() and meta_p.exists():
                labels = Segments("labels", [l for l in Segments.from_csv(lab2).items if l.label not in ("no", "")])
                if labels.items:
                    rep = evaluate(Segments.load(cp), labels, load_json(meta_p, "meta").get("duration", 1))
                    out.append({"episode": vid, "phase": "editpoints", "labels": rep.n_labels, "recall": round(rep.recall, 3),
                                "precision": round(rep.precision, 3), "coverage": round(rep.coverage, 3), "n_candidates": rep.n_candidates})
            lab = self._labels_path(vid); sj = self.project.cache / vid / "shorts.json"
            if not (lab.exists() and sj.exists()):
                continue
            cands = [ShortCandidate(**d) for d in load_json(sj, "shorts")]
            labels = Segments.from_csv(lab)
            reps = evaluate_shorts(cands, labels)
            r = reps[0] if reps else None
            out.append({"episode": vid, "phase": "shorts", "labels": len(labels.items),
                        "keep": sum(1 for l in labels.items if l.label == "keep"),
                        "no": sum(1 for l in labels.items if l.label == "no"),
                        "hit1": r.hits_at.get(1) if r else None, "hit3": r.hits_at.get(3) if r else None,
                        "mrr": round(r.mrr(), 2) if r else None})
        return out
