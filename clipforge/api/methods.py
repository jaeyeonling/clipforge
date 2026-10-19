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


def _is_cloud_placeholder(p: Path) -> bool:
    """OneDrive '파일 온디맨드' 자리표시자(내용이 로컬에 없음) 판정. Windows 파일 속성 RECALL_ON_DATA_ACCESS(0x400000) / OFFLINE(0x1000)."""
    try:
        attrs = p.stat().st_file_attributes  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        return False
    return bool(attrs & 0x400000) or bool(attrs & 0x1000)


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
        if _is_cloud_placeholder(src):
            raise ApiError("E_FILE_OFFLINE", f"클라우드 자리표시자 파일입니다 (아직 내려받지 않음): {src.name}",
                           "OneDrive 에서 파일을 우클릭 → '이 장치에 항상 유지' 로 내려받은 뒤 다시 등록하세요.")
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
        if "align" in (stages or []) and not ((params or {}).get("final") or (params or {}).get("shorts")):
            raise ApiError("E_BAD_PARAMS", "align 단계에는 최종본 파일(final) 또는 쇼츠 파일(shorts)이 필요합니다", "원본이면 친구 편집본을, 편집본이면 친구 쇼츠를 지정하세요.")
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
        gt = self._shorts_ground_truth(vid)
        for r in rows:
            key = (f"{r['start']:.1f}", f"{r['end']:.1f}")
            r["decision"] = decisions.get(key, {}).get("label", "")
            r["reason"] = decisions.get(key, {}).get("reason", "")
            r["media_url"] = f"/media/review/{vid}/shorts/{r['file']}"
            ov = [g for g in gt if min(r["end"], g["end"]) - max(r["start"], g["start"]) >= 3.0]
            r["gt"] = [g["name"] for g in ov]                       # 이 후보와 겹치는 친구 쇼츠(역매핑)·확정 정답
        return rows

    def _shorts_ground_truth(self, vid: str) -> list[dict]:
        """labels/<vid>.shorts.csv 의 keep 행 중 사람이 UI 에서 누른 것(note 'ui …')이 아닌 것 = 친구 쇼츠 역매핑·확정본."""
        p = self._labels_path(vid)
        out = []
        if not p.exists():
            return out
        with open(p, encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f):
                note = r.get("note", "")
                if r.get("label") == "keep" and not note.startswith("ui"):
                    name = note.split(" ")[3] if note.startswith("auto align shorts ") and len(note.split(" ")) > 3 else (note[:30] or "keep")
                    out.append({"start": float(r["start"]), "end": float(r["end"]), "name": name})
        return out

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

    def games_list(self) -> list[dict]:
        """등록 화면의 게임 선택: games/*.yaml (common 제외)."""
        import yaml
        out = []
        for p in sorted(self.project.games.glob("*.yaml")):
            if p.stem == "common":
                continue
            try:
                d = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            except Exception:  # noqa: BLE001
                d = {}
            out.append({"key": p.stem, "name": d.get("title") or d.get("name") or p.stem})
        return out

    # ---- 결과물 위치 (화면의 '폴더 열기' 버튼) ----
    def episode_paths(self, vid: str) -> dict:
        p = self.project
        items = {
            "shorts_dir": p.review / vid / "shorts",
            "premiere_review": p.premiere / f"{vid}_review.xml",
            "premiere_shorts": p.premiere / f"{vid}_shorts.xml",
            "premiere_dir": p.premiere,
            "subtitles_srt": p.premiere / vid / f"{vid}.srt",      # 영상 전체 자막 (subtitles 단계)
            "subtitles_vtt": p.premiere / vid / f"{vid}.vtt",
            "subtitles_vegas": p.premiere / vid / f"{vid}.vegas.txt",
            "subtitles_dir": p.premiere / vid,
            "cache_dir": p.cache / vid,
            "labels_shorts": p.labels / f"{vid}.shorts.csv",
            "labels_editpoints": p.labels / f"{vid}.csv",
            "data_dir": p.data_root,
        }
        out = {k: {"path": str(v), "exists": v.exists()} for k, v in items.items()}
        sd = p.review / vid / "shorts"
        out["shorts_count"] = len(list(sd.glob("*.mp4"))) if sd.exists() else 0
        out["video"] = str(p.video_path(vid) or "")
        return out

    def feedback_export(self) -> dict:
        """친구 PC 의 판정·매니페스트·로그를 zip 하나로 (카톡으로 보내는 용도). 영상·캐시는 넣지 않는다."""
        import io
        import time
        import zipfile
        p = self.project
        out_dir = p.data_root / "exports"; out_dir.mkdir(parents=True, exist_ok=True)
        name = f"clipforge-feedback-{time.strftime('%Y%m%d-%H%M%S')}.zip"
        dst = out_dir / name
        n = 0
        with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as z:
            for f in sorted(p.labels.glob("*.csv")):
                z.write(f, f"labels/{f.name}"); n += 1
            if p.episodes_csv.exists():
                z.write(p.episodes_csv, "episodes.csv"); n += 1
            for f in sorted((p.reports / "jobs").glob("*.manifest.json")) if (p.reports / "jobs").exists() else []:
                z.write(f, f"reports/jobs/{f.name}"); n += 1
            for f in sorted(p.reports.glob("*_eval.json")):
                z.write(f, f"reports/{f.name}"); n += 1
            for vid in p.episode_ids():
                for nm in ("align.json", "align_shorts.json", "meta.json"):
                    f = p.cache / vid / nm
                    if f.exists():
                        z.write(f, f"cache/{vid}/{nm}"); n += 1
                idx = p.review / vid / "shorts" / "index.json"
                if idx.exists():
                    z.write(idx, f"review/{vid}/shorts/index.json"); n += 1
            if p.log_path.exists():
                tail = p.log_path.read_text(encoding="utf-8", errors="replace")[-200_000:]
                z.writestr("engine.log", tail); n += 1
            live = p.data_root / "live"
            if live.exists():
                for f in sorted(live.rglob("*.json")):
                    z.write(f, f"live/{f.relative_to(live)}"); n += 1
            h = {k: v for k, v in self.health().items() if k != "problems"}
            z.writestr("health.json", json.dumps(h, ensure_ascii=False, indent=1)); n += 1
        return {"path": str(dst), "dir": str(out_dir), "files": n, "size": dst.stat().st_size}

    # ---- Phase 2: 정답 구간(kept) 과 범주 ----
    def label_categories(self) -> list[dict]:
        import yaml
        p = self.project.games / "common.yaml"
        cats = (yaml.safe_load(p.read_text(encoding="utf-8")) or {}).get("label_categories") if p.exists() else None
        return cats or [{"key": "kept", "label": "kept", "hint": "", "color": "#9be28a", "shortcut": "1"}]

    def _kept_rows(self, vid: str) -> list[dict]:
        p = self.project.labels / f"{vid}.csv"
        if not p.exists():
            return []
        with open(p, encoding="utf-8", newline="") as f:
            return list(csv.DictReader(f))

    def _write_kept_rows(self, vid: str, rows: list[dict]) -> None:
        p = self.project.labels / f"{vid}.csv"
        p.parent.mkdir(parents=True, exist_ok=True)
        rows.sort(key=lambda r: float(r["start"]))
        with open(p, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["start", "end", "label", "note"]); w.writeheader()
            w.writerows({k: r.get(k, "") for k in ("start", "end", "label", "note")} for r in rows)

    @staticmethod
    def _same(r: dict, start: float, end: float) -> bool:
        return abs(float(r["start"]) - float(start)) < 0.05 and abs(float(r["end"]) - float(end)) < 0.05

    def kept_list(self, vid: str) -> dict:
        """정답 구간 목록: [{start, end, label, source: auto|manual|ui, note}] + 범주 정의."""
        rows = []
        for r in self._kept_rows(vid):
            if r.get("label") in ("no", ""):
                continue
            note = r.get("note", "")
            src = "auto" if note.startswith("auto align") else ("ui" if note.startswith("ui") else "manual")
            rows.append({"start": float(r["start"]), "end": float(r["end"]), "label": r.get("label", "kept"), "source": src, "note": note})
        return {"episode": vid, "kept": rows, "categories": self.label_categories()}

    def kept_set(self, vid: str, start: float, end: float, label: str, new_start: float | None = None, new_end: float | None = None) -> dict:
        """구간의 범주(또는 경계)를 바꾼다. label 은 범주 key 또는 'kept'(범주 없음)."""
        keys = {c["key"] for c in self.label_categories()} | {"kept"}
        if label not in keys:
            raise ApiError("E_BAD_LABEL", f"범주가 아닙니다: {label}", f"가능: {sorted(keys)}")
        rows = self._kept_rows(vid)
        hit = [r for r in rows if self._same(r, start, end)]
        if not hit:
            raise ApiError("E_NOT_FOUND", f"정답 구간 없음: {start}-{end}")
        for r in hit:
            r["label"] = label
            if new_start is not None and new_end is not None:
                if not (0 <= float(new_start) < float(new_end)):
                    raise ApiError("E_BAD_PARAMS", "구간은 0 ≤ start < end")
                r["start"], r["end"] = f"{float(new_start):.2f}", f"{float(new_end):.2f}"
        self._write_kept_rows(vid, rows)
        return {"ok": True, "labels": len(rows)}

    def kept_add(self, vid: str, start: float, end: float, label: str = "kept", note: str = "") -> dict:
        """사람이 직접 구간 추가 (최종본이 없을 때, 또는 align 이 놓친 구간)."""
        if not (0 <= float(start) < float(end)):
            raise ApiError("E_BAD_PARAMS", "구간은 0 ≤ start < end")
        keys = {c["key"] for c in self.label_categories()} | {"kept"}
        if label not in keys:
            raise ApiError("E_BAD_LABEL", f"범주가 아닙니다: {label}", f"가능: {sorted(keys)}")
        rows = [r for r in self._kept_rows(vid) if not self._same(r, start, end)]
        rows.append({"start": f"{float(start):.2f}", "end": f"{float(end):.2f}", "label": label, "note": f"manual {note}".strip()})
        self._write_kept_rows(vid, rows)
        return {"ok": True, "labels": len(rows)}

    def kept_delete(self, vid: str, start: float, end: float) -> dict:
        rows = self._kept_rows(vid)
        keep = [r for r in rows if not self._same(r, start, end)]
        if len(keep) == len(rows):
            raise ApiError("E_NOT_FOUND", f"정답 구간 없음: {start}-{end}")
        self._write_kept_rows(vid, keep)
        return {"ok": True, "labels": len(keep)}

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
                            "missed": [{"start": m.start, "end": m.end, "label": m.label} for m in rep.missed],
                            "by_label": {lab: {"hit": rep.hit_by_label.get(lab, 0), "total": rep.hit_by_label.get(lab, 0) + rep.missed_by_label.get(lab, 0)}
                                         for lab in sorted(set(rep.hit_by_label) | set(rep.missed_by_label))}} if rep else None),
                "categories": self.label_categories(),
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

    # ---- live (방송 중) ----
    _live = None

    def _live_emit(self, ev: dict) -> None:
        from .. import jobs as jobs_mod
        for cb in jobs_mod._listeners:
            try:
                cb(ev)
            except Exception:  # noqa: BLE001
                pass

    def live_status(self) -> dict:
        from ..live.source import ScreenSource  # noqa: F401 — 가져오기 확인
        s = self._live
        prev = (s.dir / "last.jpg") if s else None
        return {"active": bool(s and s.running), "session": s.status() if s else None,
                "suggestions": [vars(x) for x in s.suggestions[-50:]] if s else [], "bookmarks": s.bookmarks[-50:] if s else [],
                "preview_url": f"/media/live/{s.id}/last.jpg?ts={int(prev.stat().st_mtime)}" if prev and prev.exists() else None}

    def live_start(self, config: dict | None = None) -> dict:
        from ..live.session import LiveSession
        if self._live and self._live.running:
            raise ApiError("E_LIVE_RUNNING", "라이브 세션이 이미 돌고 있습니다", "먼저 정지하세요.")
        cfg = dict(config or {})
        if cfg.get("source", "screen") == "frames" and not (cfg.get("frames_dir") or cfg.get("episode")):
            raise ApiError("E_BAD_PARAMS", "frames 소스에는 episode 또는 frames_dir 이 필요합니다")
        self._live = LiveSession(self.project, cfg, on_event=self._live_emit)
        return self._live.start()

    def live_stop(self) -> dict:
        if not self._live:
            raise ApiError("E_NOT_FOUND", "라이브 세션이 없습니다")
        return self._live.stop()

    def live_mark(self, note: str = "") -> dict:
        if not self._live or not self._live.running:
            raise ApiError("E_NOT_FOUND", "라이브 세션이 돌고 있지 않습니다", "라이브 탭에서 시작하세요.")
        return self._live.mark(note)

    def live_approve(self, sid: str, text: str | None = None) -> dict:
        if not self._live:
            raise ApiError("E_NOT_FOUND", "라이브 세션이 없습니다")
        try:
            return self._live.approve(sid, text)
        except KeyError:
            raise ApiError("E_NOT_FOUND", f"제안 없음: {sid}")

    def live_approve_latest(self) -> dict:
        """전역 단축키용: 가장 최근 대기 제안을 승인."""
        if not self._live or not self._live.running:
            raise ApiError("E_NOT_FOUND", "라이브 세션이 돌고 있지 않습니다")
        s = self._live.latest_pending()
        if not s:
            raise ApiError("E_NOT_FOUND", "대기 중인 제안이 없습니다")
        return self._live.approve(s.id)

    def live_dismiss_latest(self) -> dict:
        if not self._live or not self._live.running:
            raise ApiError("E_NOT_FOUND", "라이브 세션이 돌고 있지 않습니다")
        s = self._live.latest_pending()
        if not s:
            raise ApiError("E_NOT_FOUND", "대기 중인 제안이 없습니다")
        return self._live.dismiss(s.id)

    def live_dismiss(self, sid: str) -> dict:
        if not self._live:
            raise ApiError("E_NOT_FOUND", "라이브 세션이 없습니다")
        try:
            return self._live.dismiss(sid)
        except KeyError:
            raise ApiError("E_NOT_FOUND", f"제안 없음: {sid}")

    def live_banner(self, items: list[str]) -> dict:
        if not self._live:
            raise ApiError("E_NOT_FOUND", "라이브 세션이 없습니다")
        return {"text": self._live.set_banner(items), "items": self._live.banner_items}

    def live_obs_inputs(self, url: str = "ws://127.0.0.1:4455", password: str = "") -> dict:
        """OBS 연결 점검 + 텍스트 소스 목록 (설정 화면)."""
        from ..live.obs import ObsClient, ObsError
        c = ObsClient(url, password)
        try:
            info = c.connect()
            inputs = [i for i in c.get_input_list() if "text" in str(i.get("inputKind", ""))]
            return {"ok": True, "obs": info, "text_sources": [i.get("inputName") for i in inputs]}
        except (ObsError, OSError, TimeoutError) as e:
            raise ApiError("E_OBS", f"OBS 연결 실패: {str(e)[:160]}", "OBS 가 켜져 있고 도구 → WebSocket 서버 설정에서 서버가 활성화돼 있는지, 포트·비밀번호가 맞는지 확인하세요.")
        except Exception as e:  # noqa: BLE001
            raise ApiError("E_OBS", f"OBS 연결 실패: {str(e)[:160]}", "OBS WebSocket 서버 설정을 확인하세요.")
        finally:
            c.close()

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
