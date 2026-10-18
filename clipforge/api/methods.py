"""엔진 API 메서드 (전송 방식과 무관). HTTP(server.py)와 stdio(stdio.py)가 이 함수들을 그대로 노출한다.

메서드는 모두 순수 dict 입출력. 오류는 ApiError(code, message, hint) 로 올린다.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

from ..jobs import STAGES, JobRunner
from ..project import Project


class ApiError(Exception):
    def __init__(self, code: str, message: str, hint: str = ""):
        super().__init__(message)
        self.code, self.message, self.hint = code, message, hint

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "hint": self.hint}


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

    def episode_add(self, video_path: str, vid: str | None = None, title: str = "", game: str = "d2r") -> dict:
        """영상 파일을 videos/ 에 등록(복사하지 않고 링크/복사 선택 — 지금은 복사 없이 같은 드라이브면 하드링크, 아니면 복사)."""
        src = Path(video_path)
        if not src.exists():
            raise ApiError("E_NOT_FOUND", f"파일 없음: {video_path}")
        vid = vid or src.stem
        dst = self.project.videos / f"{vid}{src.suffix.lower()}"
        if not dst.exists():
            try:
                import os
                os.link(src, dst)
            except OSError:
                import shutil
                shutil.copy2(src, dst)
        if title:
            self._upsert_episode_row(vid, game, title)
        return self.project.episode_info(vid)

    def _upsert_episode_row(self, vid: str, game: str, title: str) -> None:
        p = self.project.episodes_csv
        rows: list[dict] = []
        if p.exists():
            with open(p, encoding="utf-8", newline="") as f:
                rows = list(csv.DictReader(f))
        fields = ["id", "game", "title", "url", "views", "uploaded", "raw_hours", "note"]
        found = False
        for r in rows:
            if r.get("id") == vid:
                r["title"] = title; r["game"] = game; found = True
        if not found:
            rows.append({"id": vid, "game": game, "title": title, "url": "", "views": "", "uploaded": "", "raw_hours": "", "note": ""})
        with open(p, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields); w.writeheader()
            for r in rows:
                w.writerow({k: r.get(k, "") for k in fields})

    # ---- jobs ----
    def job_run(self, episode: str, stages: list[str] | None = None, params: dict | None = None) -> dict:
        if episode not in self.project.episode_ids():
            raise ApiError("E_NOT_FOUND", f"회차 없음: {episode}")
        bad = [s for s in (stages or []) if s not in STAGES]
        if bad:
            raise ApiError("E_BAD_STAGE", f"알 수 없는 단계: {bad}", f"가능: {STAGES}")
        job = self.runner.submit(episode, stages or ["prep", "transcribe", "signals", "shorts", "export", "xml"], params)
        return job.to_dict()

    def job_get(self, job_id: str) -> dict:
        job = self.runner.jobs.get(job_id)
        if not job:
            raise ApiError("E_NOT_FOUND", f"job 없음: {job_id}")
        return job.to_dict()

    def job_list(self) -> list[dict]:
        return [j.to_dict() for j in self.runner.jobs.values()]

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
            return json.loads(sj.read_text(encoding="utf-8"))
        rows = json.loads(idx_p.read_text(encoding="utf-8"))
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

    def decision_set(self, vid: str, start: float, end: float, label: str, reason: str = "", file: str = "") -> dict:
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

    # ---- metrics ----
    def metrics_summary(self) -> list[dict]:
        from ..eval_shorts import evaluate_shorts
        from ..shorts import ShortCandidate
        from ..timeline import Segments
        out = []
        for vid in self.project.episode_ids():
            lab = self._labels_path(vid); sj = self.project.cache / vid / "shorts.json"
            if not (lab.exists() and sj.exists()):
                continue
            cands = [ShortCandidate(**d) for d in json.loads(sj.read_text(encoding="utf-8"))]
            labels = Segments.from_csv(lab)
            reps = evaluate_shorts(cands, labels)
            r = reps[0] if reps else None
            out.append({"episode": vid, "labels": len(labels.items),
                        "keep": sum(1 for l in labels.items if l.label == "keep"),
                        "no": sum(1 for l in labels.items if l.label == "no"),
                        "hit1": r.hits_at.get(1) if r else None, "hit3": r.hits_at.get(3) if r else None,
                        "mrr": round(r.mrr(), 2) if r else None})
        return out
