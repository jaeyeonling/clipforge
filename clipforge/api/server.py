"""로컬 HTTP + WebSocket 서버 (FastAPI). UI 정적 파일과 미디어(초안 mp4, Range 지원)도 여기서 서빙한다.

    python -m clipforge.app            # 127.0.0.1:8765 에 띄우고 브라우저를 연다
엔드포인트는 methods.Engine 의 얇은 래퍼. 이벤트는 /ws 로 중계 (Job 진행률·로그).
바인딩은 127.0.0.1 전용 — 외부 접근 없음.

주의: Pydantic 모델은 모듈 수준에 둔다. `from __future__ import annotations` 와 함수 내부 정의를 섞으면
FastAPI 가 forward-ref 를 못 풀어 본문 모델을 쿼리 파라미터로 취급한다(422).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .. import __version__
from .. import jobs as jobs_mod
from ..errors import classify
from .methods import ApiError, Engine


class AddEpisode(BaseModel):
    video_path: str
    id: str | None = None
    title: str = ""
    game: str = "d2r"
    link: bool = True  # False = 복사/링크 없이 원본 경로 참조
    kind: str = "edited"  # edited(편집본→쇼츠) | original(원본→편집 포인트)


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


class KeptSet(BaseModel):
    start: float
    end: float
    label: str = "kept"
    new_start: float | None = None
    new_end: float | None = None


class KeptAdd(BaseModel):
    start: float
    end: float
    label: str = "kept"
    note: str = ""


class LiveStart(BaseModel):
    config: dict = {}


class LiveMark(BaseModel):
    note: str = ""


class LiveApprove(BaseModel):
    text: str | None = None


class LiveBanner(BaseModel):
    items: list[str]


class ObsProbe(BaseModel):
    url: str = "ws://127.0.0.1:4455"
    password: str = ""


class Decision(BaseModel):
    start: float
    end: float
    label: str
    reason: str = ""
    file: str = ""
    kind: str = "shorts"  # shorts | editpoints


def create_app(engine: Engine | None = None) -> FastAPI:
    engine = engine or Engine()
    clients: set[WebSocket] = set()
    loop_holder: dict = {}
    queue: asyncio.Queue = asyncio.Queue()

    def on_event(ev: dict) -> None:  # Job 스레드 → asyncio 큐
        loop = loop_holder.get("loop")
        if loop:
            loop.call_soon_threadsafe(queue.put_nowait, ev)

    jobs_mod.add_listener(on_event)

    async def pump() -> None:
        """작업·라이브 이벤트를 연결된 모든 WebSocket 으로 흘려보낸다. 끊긴 소켓은 정리한다."""
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

    @contextlib.asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        loop_holder["loop"] = asyncio.get_running_loop()
        task = asyncio.create_task(pump())
        try:
            yield
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            loop_holder.pop("loop", None)

    app = FastAPI(title="clipforge engine", version=__version__, lifespan=lifespan)

    # 오류 응답은 전부 {"error": {code, message, hint, kind}} 한 형태 (UI 가 한 군데서 파싱)
    log = logging.getLogger("clipforge.api")

    @app.exception_handler(ApiError)
    async def _api_error(_, e: ApiError):
        return JSONResponse(status_code=404 if e.code == "E_NOT_FOUND" else 400, content={"error": e.to_dict()})

    @app.exception_handler(RequestValidationError)
    async def _bad_request(_, e: RequestValidationError):
        msg = "; ".join(f"{'.'.join(str(x) for x in err.get('loc', []))}: {err.get('msg')}" for err in e.errors())[:400]
        return JSONResponse(
            status_code=400,
            content={
                "error": {
                    "code": "E_BAD_REQUEST",
                    "message": msg,
                    "hint": "요청 본문의 필드 이름과 형식을 확인하세요.",
                    "kind": "user",
                }
            },
        )

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
        return engine.episode_add(body.video_path, body.id, body.title, body.game, body.link, body.kind)

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
        return engine.decision_set(vid, body.start, body.end, body.label, body.reason, body.file, body.kind)

    @app.get("/api/episodes/{vid}/editpoints")
    def editpoints(vid: str):
        return engine.editpoints_list(vid)

    @app.get("/api/episodes/{vid}/paths")
    def episode_paths(vid: str):
        return engine.episode_paths(vid)

    @app.post("/api/feedback/export")
    def feedback_export():
        return engine.feedback_export()

    @app.get("/api/episodes/{vid}/kept")
    def kept_list(vid: str):
        return engine.kept_list(vid)

    @app.put("/api/episodes/{vid}/kept")
    def kept_set(vid: str, body: KeptSet):
        return engine.kept_set(vid, body.start, body.end, body.label, body.new_start, body.new_end)

    @app.post("/api/episodes/{vid}/kept")
    def kept_add(vid: str, body: KeptAdd):
        return engine.kept_add(vid, body.start, body.end, body.label, body.note)

    @app.delete("/api/episodes/{vid}/kept")
    def kept_delete(vid: str, start: float, end: float):
        return engine.kept_delete(vid, start, end)

    @app.get("/api/label-categories")
    def label_categories(game: str | None = None):
        return engine.label_categories(game)

    # ---- live ----
    @app.get("/api/live")
    def live_status():
        return engine.live_status()

    @app.post("/api/live/start")
    def live_start(body: LiveStart):
        return engine.live_start(body.config)

    @app.post("/api/live/stop")
    def live_stop():
        return engine.live_stop()

    @app.post("/api/live/mark")
    def live_mark(body: LiveMark):
        return engine.live_mark(body.note)

    @app.post("/api/live/suggestions/latest/approve")
    def live_approve_latest():
        return engine.live_approve_latest()

    @app.post("/api/live/suggestions/latest/dismiss")
    def live_dismiss_latest():
        return engine.live_dismiss_latest()

    @app.get("/api/games")
    def games():
        return engine.games_list()

    @app.api_route("/media/live/{sid}/{name}", methods=["GET", "HEAD"])
    def media_live(sid: str, name: str):
        root = (engine.project.data_root / "live").resolve()
        p = (root / sid / name).resolve()
        if root not in p.parents or not p.is_file() or p.suffix.lower() not in (".jpg", ".png", ".json"):
            raise HTTPException(404)
        return FileResponse(str(p), headers={"Cache-Control": "no-store"})

    @app.post("/api/live/suggestions/{sid}/approve")
    def live_approve(sid: str, body: LiveApprove):
        return engine.live_approve(sid, body.text)

    @app.post("/api/live/suggestions/{sid}/dismiss")
    def live_dismiss(sid: str):
        return engine.live_dismiss(sid)

    @app.put("/api/live/banner")
    def live_banner(body: LiveBanner):
        return engine.live_banner(body.items)

    @app.post("/api/live/obs/probe")
    def live_obs_probe(body: ObsProbe):
        return engine.live_obs_inputs(body.url, body.password)

    # 원본/편집본 영상 자체 (편집 포인트 검토용 재생). Range 지원.
    @app.api_route("/media/video/{vid}", methods=["GET", "HEAD"])
    def media_video(vid: str):
        p = engine.project.video_path(vid)
        if not p:
            raise HTTPException(404)
        return FileResponse(str(p), media_type="video/mp4")

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

    @app.get("/api/preference")
    def preference():
        return engine.preference()

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

    ui_dir: Path | None = engine.project.ui_dir
    if ui_dir:
        app.mount("/", StaticFiles(directory=str(ui_dir), html=True), name="ui")
    else:

        @app.get("/", response_class=HTMLResponse, include_in_schema=False)
        def _no_ui() -> str:
            return NO_UI_PAGE

    return app


# 화면 빌드(app/dist)가 없을 때: 엔진 API 는 살아 있고, 화면을 만드는 방법을 알려 준다.
NO_UI_PAGE = """<!doctype html><html lang="ko"><meta charset="utf-8"><title>clipforge engine</title>
<body style="margin:0;background:#17171c;color:#e8e8ea;font:15px/1.6 system-ui,'Malgun Gothic';display:grid;place-items:center;height:100vh">
<div style="max-width:560px;padding:24px"><div style="font-size:24px;font-weight:800;color:#f0f660">clipforge</div>
<p style="font-size:18px;font-weight:700;margin:12px 0 4px">엔진은 켜져 있는데 화면 빌드가 없어요</p>
<p style="color:#8b95a1;margin:0">저장소에서 한 번만 실행해 주세요.</p>
<pre style="background:#202027;border-radius:12px;padding:14px;margin-top:14px">cd app\nnpm install\nnpm run build</pre>
<p style="color:#8b95a1">API 문서: <a style="color:#4593fc" href="/docs">/docs</a></p></div></body></html>"""
