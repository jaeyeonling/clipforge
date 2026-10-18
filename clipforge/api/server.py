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
import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse

from ..errors import classify
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .. import jobs as jobs_mod
from .methods import ApiError, Engine


class AddEpisode(BaseModel):
    video_path: str
    id: str | None = None
    title: str = ""
    game: str = "d2r"
    link: bool = True            # False = 복사/링크 없이 원본 경로 참조


class RunJob(BaseModel):
    episode: str
    stages: list[str] | None = None
    params: dict = {}


class PreviewReq(BaseModel):
    t: int | None = None
    rois: dict | None = None


class ProfileSet(BaseModel):
    rois: dict
    panel_bands: dict | None = None


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

    # 오류 응답은 전부 {"error": {code, message, hint, kind}} 한 형태 (UI 가 한 군데서 파싱)
    log = logging.getLogger("clipforge.api")

    @app.exception_handler(ApiError)
    async def _api_error(_, e: ApiError):
        return JSONResponse(status_code=404 if e.code == "E_NOT_FOUND" else 400, content={"error": e.to_dict()})

    @app.exception_handler(RequestValidationError)
    async def _bad_request(_, e: RequestValidationError):
        msg = "; ".join(f"{'.'.join(str(x) for x in err.get('loc', []))}: {err.get('msg')}" for err in e.errors())[:400]
        return JSONResponse(status_code=400, content={"error": {"code": "E_BAD_REQUEST", "message": msg,
                                                                "hint": "요청 본문의 필드 이름과 형식을 확인하세요.", "kind": "user"}})

    @app.exception_handler(Exception)
    async def _unhandled(request, e: Exception):
        log.exception("unhandled %s %s", request.method, request.url.path)
        return JSONResponse(status_code=500, content={"error": classify(e)})

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
        return engine.episode_add(body.video_path, body.id, body.title, body.game, body.link)

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

    @app.get("/api/jobs/{job_id}/log")
    def job_log(job_id: str, tail: int = 400):
        return engine.job_log(job_id, tail)

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

    @app.get("/api/episodes/{vid}/calibrate")
    def calibrate_check(vid: str):
        return engine.calibrate_check(vid)

    @app.post("/api/episodes/{vid}/calibrate/preview")
    def calibrate_preview(vid: str, body: PreviewReq):
        return engine.calibrate_preview(vid, body.t, body.rois)

    @app.get("/api/profiles/{game}")
    def profile_get(game: str):
        return engine.profile_get(game)

    @app.put("/api/profiles/{game}")
    def profile_set(game: str, body: ProfileSet):
        return engine.profile_set(game, body.rois, body.panel_bands)

    @app.api_route("/media/cache/{path:path}", methods=["GET", "HEAD"])
    def media_cache(path: str):
        root = engine.project.cache.resolve()
        p = (root / path).resolve()
        if root not in p.parents or not p.is_file() or p.suffix.lower() not in (".png", ".jpg", ".json"):
            raise HTTPException(404)
        return FileResponse(str(p), headers={"Cache-Control": "no-store"})

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
    # index.html 은 캐시 금지 (빌드마다 자산 해시가 바뀌므로 오래된 index 가 옛 JS 를 가리키면 안 된다). 해시 붙은 assets/ 는 길게 캐시.
    @app.middleware("http")
    async def _ui_cache_headers(request, call_next):
        resp = await call_next(request)
        path = request.url.path
        if path.startswith("/assets/"):
            resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        elif path == "/" or path.endswith(".html"):
            resp.headers["Cache-Control"] = "no-cache"
        return resp

    ui_dir: Path = engine.project.ui_dir
    if ui_dir.exists():
        app.mount("/", StaticFiles(directory=str(ui_dir), html=True), name="ui")
    return app
