"""stdio JSON Lines 전송 (데스크톱 껍데기가 엔진을 자식 프로세스로 띄울 때).

    python -m clipforge.api.stdio
    → stdin: {"id":1,"method":"episode.list","params":{}}
    ← stdout: {"id":1,"result":[...]}  /  {"event":"progress", ...}  (Job 이벤트는 요청 없이 흘러나온다)
"""
from __future__ import annotations

import json
import sys
import threading

from .. import jobs as jobs_mod
from ..errors import classify
from .methods import ApiError, Engine

METHODS = {
    "engine.health": lambda e, p: e.health(),
    "episode.list": lambda e, p: e.episode_list(),
    "episode.get": lambda e, p: e.episode_get(p["vid"]),
    "episode.add": lambda e, p: e.episode_add(p["video_path"], p.get("id"), p.get("title", ""), p.get("game", "d2r"), p.get("link", True), p.get("kind", "edited")),
    "editpoints.list": lambda e, p: e.editpoints_list(p["vid"]),
    "kept.list": lambda e, p: e.kept_list(p["vid"]),
    "kept.set": lambda e, p: e.kept_set(p["vid"], p["start"], p["end"], p.get("label", "kept"), p.get("new_start"), p.get("new_end")),
    "kept.add": lambda e, p: e.kept_add(p["vid"], p["start"], p["end"], p.get("label", "kept"), p.get("note", "")),
    "kept.delete": lambda e, p: e.kept_delete(p["vid"], p["start"], p["end"]),
    "labels.categories": lambda e, p: e.label_categories(),
    "episode.paths": lambda e, p: e.episode_paths(p["vid"]),
    "feedback.export": lambda e, p: e.feedback_export(),
    "live.status": lambda e, p: e.live_status(),
    "live.start": lambda e, p: e.live_start(p.get("config")),
    "live.stop": lambda e, p: e.live_stop(),
    "live.mark": lambda e, p: e.live_mark(p.get("note", "")),
    "live.approve": lambda e, p: e.live_approve(p["id"], p.get("text")),
    "live.dismiss": lambda e, p: e.live_dismiss(p["id"]),
    "live.approve_latest": lambda e, p: e.live_approve_latest(),
    "live.dismiss_latest": lambda e, p: e.live_dismiss_latest(),
    "games.list": lambda e, p: e.games_list(),
    "live.banner": lambda e, p: e.live_banner(p["items"]),
    "live.obs.probe": lambda e, p: e.live_obs_inputs(p.get("url", "ws://127.0.0.1:4455"), p.get("password", "")),
    "job.run": lambda e, p: e.job_run(p["episode"], p.get("stages"), p.get("params")),
    "job.get": lambda e, p: e.job_get(p["job_id"]),
    "job.list": lambda e, p: e.job_list(),
    "job.cancel": lambda e, p: e.job_cancel(p["job_id"]),
    "job.log": lambda e, p: e.job_log(p["job_id"], int(p.get("tail", 400))),
    "candidates.list": lambda e, p: e.candidates_list(p["vid"]),
    "decision.set": lambda e, p: e.decision_set(p["vid"], p["start"], p["end"], p["label"], p.get("reason", ""), p.get("file", ""), p.get("kind", "shorts")),
    "metrics.summary": lambda e, p: e.metrics_summary(),
    "calibrate.check": lambda e, p: e.calibrate_check(p["vid"]),
    "calibrate.preview": lambda e, p: e.calibrate_preview(p["vid"], p.get("t"), p.get("rois")),
    "profile.get": lambda e, p: e.profile_get(p["game"]),
    "profile.set": lambda e, p: e.profile_set(p["game"], p["rois"], p.get("panel_bands")),
}


def main() -> None:
    engine = Engine()
    out_lock = threading.Lock()

    def write(obj: dict) -> None:
        with out_lock:
            sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n"); sys.stdout.flush()

    jobs_mod.add_listener(lambda ev: write({"event": ev.get("type"), **ev}))
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
            fn = METHODS.get(req.get("method"))
            if not fn:
                write({"id": req.get("id"), "error": {"code": "E_NO_METHOD", "message": req.get("method")}}); continue
            write({"id": req.get("id"), "result": fn(engine, req.get("params") or {})})
        except ApiError as e:
            write({"id": req.get("id"), "error": e.to_dict()})
        except Exception as e:  # noqa: BLE001
            write({"id": req.get("id") if isinstance(req, dict) else None, "error": classify(e)})


if __name__ == "__main__":
    main()
