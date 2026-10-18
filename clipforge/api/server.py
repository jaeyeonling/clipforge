"""로컬 HTTP + WebSocket 서버 (FastAPI). UI 정적 파일과 미디어(초안 mp4, Range 지원)도 여기서 서빙한다.

    python -m clipforge.app            # 127.0.0.1:8765 에 띄우고 브라우저를 연다
엔드포인트는 methods.Engine 의 얇은 래퍼. 이벤트는 /ws 로 중계 (Job 진행률·로그).
바인딩은 127.0.0.1 전용 — 외부 접근 없음.

주의: Pydantic 모델은 모듈 수준에 둔다. `from __future__ import annotations` 와 함수 내부 정의를 섞으면
FastAPI 가 forward-ref 를 못 풀어 본문 모델을 쿼리 파라미터로 취급한다(422).
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .. import jobs as jobs_mod
from .methods import ApiError, Engine


class AddEpisode(BaseModel):
    video_path: str
    id: str | None = None
    title: str = ""
    game: str = "d2r"


class RunJob(BaseModel):
    episode: str
    stages: list[str] | None = None
    params: dict = {}


class Decision(BaseModel):
    start: float
    end: float
    label: str
    reason: str = ""
    file: str = ""


def create_app(engine: Engine | None = None) -> FastAPI:
    engine = engine or Engine()
    app = FastAPI(title="clipforge engine", version="0.1")
    clients: set[WebSocket] = set()
    loop_holder: dict = {}
    queue: asyncio.Queue = asyncio.Queue()

    def on_event(ev: dict) -> None:          # Job 스레드 → asyncio 큐
        loop = loop_holder.get("loop")
        if loop:
            loop.call_soon_threadsafe(queue.put_nowait, ev)

    jobs_mod.add_listener(on_event)

    @app.on_event("startup")
    async def _startup():
        loop_holder["loop"] = asyncio.get_running_loop()

        async def pump():
            while True:
                ev = await queue.get()
                dead = []
                for ws in list(clients):
                    try:
                        await ws.send_text(json.dumps(ev, ensure_ascii=False))
                    except Exception:
                        dead.append(ws)
                for ws in dead:
                    clients.discard(ws)
        asyncio.create_task(pump())

    @app.exception_handler(ApiError)
    async def _api_error(_, e: ApiError):
        return JSONResponse(status_code=400, content={"error": e.to_dict()})

    # ---- engine / episodes ----
    @app.get("/api/health")
    def health():
        return engine.health()

    @app.get("/api/episodes")
    def episodes():
        return engine.episode_list()

    @app.get("/api/episodes/{vid}")
    def episode(vid: str):
        return engine.episode_get(vid)

    @app.post("/api/episodes")
    def episode_add(body: AddEpisode):
        return engine.episode_add(body.video_path, body.id, body.title, body.game)

    # ---- jobs ----
    @app.post("/api/jobs")
    def job_run(body: RunJob):
        return engine.job_run(body.episode, body.stages, body.params)

    @app.get("/api/jobs")
    def job_list():
        return engine.job_list()

    @app.get("/api/jobs/{job_id}")
    def job_get(job_id: str):
        return engine.job_get(job_id)

    @app.get("/api/jobs/{job_id}/events")
    def job_events(job_id: str, since: int = 0):
        return engine.job_events(job_id, since)

    @app.post("/api/jobs/{job_id}/cancel")
    def job_cancel(job_id: str):
        return engine.job_cancel(job_id)

    # ---- candidates / decisions / metrics ----
    @app.get("/api/episodes/{vid}/candidates")
    def candidates(vid: str):
        return engine.candidates_list(vid)

    @app.post("/api/episodes/{vid}/decision")
    def decision(vid: str, body: Decision):
        return engine.decision_set(vid, body.start, body.end, body.label, body.reason, body.file)

    @app.get("/api/metrics")
    def metrics():
        return engine.metrics_summary()

    # ---- media (초안 mp4 등, review/ 아래만). HEAD 도 받아야 브라우저 <video> 가 메타데이터를 읽는다 ----
    @app.api_route("/media/review/{path:path}", methods=["GET", "HEAD"])
    def media(path: str):
        root = engine.project.review.resolve()
        p = (root / path).resolve()
        if root not in p.parents or not p.is_file():
            raise HTTPException(404)
        return FileResponse(str(p))

    # ---- websocket events ----
    @app.websocket("/ws")
    async def ws(websocket: WebSocket):
        await websocket.accept()
        clients.add(websocket)
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            clients.discard(websocket)

    # ---- UI ----
    ui_dir: Path = engine.project.ui_dir
    if ui_dir.exists():
        app.mount("/", StaticFiles(directory=str(ui_dir), html=True), name="ui")
    return app
