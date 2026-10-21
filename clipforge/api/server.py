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
from urllib.parse import urlsplit

from fastapi import APIRouter, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
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


LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1")


class LocalOnlyMiddleware:
    """엔진은 127.0.0.1 에만 열리지만, 사용자가 브라우저로 연 다른 사이트도 그 주소로 요청을 보낼 수 있다.
    - Host 가 로컬 이름이 아니면 거절한다 (DNS 리바인딩: 공격자 도메인이 127.0.0.1 을 가리키게 해서 응답을 읽는 것).
    - Origin 이 있고 로컬이 아니면 거절한다 (다른 사이트의 fetch · WebSocket · 폼 전송).
    Origin 이 없는 요청(데스크톱 셸, curl, 같은 페이지의 GET)은 통과하고, Origin: null 은 거절한다. HTTP 와 WebSocket 모두에 걸린다."""

    def __init__(self, app, allowed_hosts: tuple[str, ...] = LOCAL_HOSTS):
        self.app = app
        self.allowed = set(allowed_hosts)

    def _host_ok(self, value: str) -> bool:
        host = urlsplit(f"//{value}").hostname or ""
        return host in self.allowed

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)
        headers = {k.decode("latin-1"): v.decode("latin-1") for k, v in scope.get("headers", [])}
        origin = headers.get("origin")
        # Origin 이 'null' 인 요청(샌드박스 iframe·data: 페이지)은 어느 사이트든 만들 수 있으므로 거절한다.
        ok = self._host_ok(headers.get("host", "")) and (
            origin is None or (origin != "null" and (urlsplit(origin).hostname or "") in self.allowed)
        )
        if ok:
            return await self.app(scope, receive, send)
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        body = json.dumps(
            {
                "error": {
                    "code": "E_FORBIDDEN_ORIGIN",
                    "message": "이 주소에서는 엔진을 쓸 수 없어요",
                    "hint": "",
                    "kind": "user",
                }
            },
            ensure_ascii=False,
        ).encode("utf-8")
        await send({"type": "http.response.start", "status": 403, "headers": [(b"content-type", b"application/json")]})
        await send({"type": "http.response.body", "body": body})


def create_app(engine: Engine | None = None, allowed_hosts: tuple[str, ...] = LOCAL_HOSTS) -> FastAPI:
    """엔진 앱. 라우트는 영역별 함수에 있고, 여기서는 이벤트 중계(Job 스레드 → /ws)와 조립만 한다."""
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
    app.add_middleware(LocalOnlyMiddleware, allowed_hosts=allowed_hosts)
    _add_error_handlers(app)
    for router in (_episode_routes(engine), _job_routes(engine), _live_routes(engine), _media_routes(engine)):
        app.include_router(router)

    @app.websocket("/ws")
    async def ws(websocket: WebSocket):
        await websocket.accept()
        clients.add(websocket)
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            clients.discard(websocket)

    _add_ui(app, engine.project.ui_dir)  # "/" 에 붙으므로 마지막
    return app


def _add_error_handlers(app: FastAPI) -> None:
    """오류 응답은 전부 {"error": {code, message, hint, kind}} 한 형태 (UI 가 한 군데서 파싱)."""
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


def _episode_routes(engine: Engine) -> APIRouter:
    """엔진 상태 · 회차 · 후보와 판정 · 편집 포인트 · 화면 영역 · 지표."""
    r = APIRouter()

    @r.get("/api/health")
    def health():
        return engine.health()

    @r.get("/api/games")
    def games():
        return engine.games_list()

    @r.get("/api/episodes")
    def episodes():
        return engine.episode_list()

    @r.get("/api/episodes/{vid}")
    def episode(vid: str):
        return engine.episode_get(vid)

    @r.post("/api/episodes")
    def episode_add(body: AddEpisode):
        return engine.episode_add(body.video_path, body.id, body.title, body.game, body.link, body.kind)

    @r.get("/api/episodes/{vid}/paths")
    def episode_paths(vid: str):
        return engine.episode_paths(vid)

    @r.get("/api/episodes/{vid}/candidates")
    def candidates(vid: str):
        return engine.candidates_list(vid)

    @r.post("/api/episodes/{vid}/decision")
    def decision(vid: str, body: Decision):
        return engine.decision_set(vid, body.start, body.end, body.label, body.reason, body.file, body.kind)

    @r.get("/api/episodes/{vid}/editpoints")
    def editpoints(vid: str):
        return engine.editpoints_list(vid)

    @r.get("/api/episodes/{vid}/kept")
    def kept_list(vid: str):
        return engine.kept_list(vid)

    @r.put("/api/episodes/{vid}/kept")
    def kept_set(vid: str, body: KeptSet):
        return engine.kept_set(vid, body.start, body.end, body.label, body.new_start, body.new_end)

    @r.post("/api/episodes/{vid}/kept")
    def kept_add(vid: str, body: KeptAdd):
        return engine.kept_add(vid, body.start, body.end, body.label, body.note)

    @r.delete("/api/episodes/{vid}/kept")
    def kept_delete(vid: str, start: float, end: float):
        return engine.kept_delete(vid, start, end)

    @r.get("/api/episodes/{vid}/calibrate")
    def calibrate_check(vid: str):
        return engine.calibrate_check(vid)

    @r.post("/api/episodes/{vid}/calibrate/preview")
    def calibrate_preview(vid: str, body: PreviewReq):
        return engine.calibrate_preview(vid, body.t, body.rois)

    @r.get("/api/profiles/{game}")
    def profile_get(game: str):
        return engine.profile_get(game)

    @r.put("/api/profiles/{game}")
    def profile_set(game: str, body: ProfileSet):
        return engine.profile_set(game, body.rois, body.panel_bands)

    @r.get("/api/label-categories")
    def label_categories(game: str | None = None):
        return engine.label_categories(game)

    @r.post("/api/feedback/export")
    def feedback_export():
        return engine.feedback_export()

    @r.get("/api/metrics")
    def metrics():
        return engine.metrics_summary()

    @r.get("/api/preference")
    def preference():
        return engine.preference()

    return r


def _job_routes(engine: Engine) -> APIRouter:
    """분석 작업 실행 · 조회 · 취소. 진행 이벤트는 /ws 로도 온다."""
    r = APIRouter()

    @r.post("/api/jobs")
    def job_run(body: RunJob):
        return engine.job_run(body.episode, body.stages, body.params)

    @r.get("/api/jobs")
    def job_list():
        return engine.job_list()

    @r.get("/api/jobs/{job_id}")
    def job_get(job_id: str):
        return engine.job_get(job_id)

    @r.get("/api/jobs/{job_id}/events")
    def job_events(job_id: str, since: int = 0):
        return engine.job_events(job_id, since)

    @r.get("/api/jobs/{job_id}/log")
    def job_log(job_id: str, tail: int = 400):
        return engine.job_log(job_id, tail)

    @r.post("/api/jobs/{job_id}/cancel")
    def job_cancel(job_id: str):
        return engine.job_cancel(job_id)

    return r


def _live_routes(engine: Engine) -> APIRouter:
    """라이브 감지 세션과 제안 승인. 'latest' 경로는 {sid} 보다 먼저 등록해야 한다."""
    r = APIRouter()

    @r.get("/api/live")
    def live_status():
        return engine.live_status()

    @r.post("/api/live/start")
    def live_start(body: LiveStart):
        return engine.live_start(body.config)

    @r.post("/api/live/stop")
    def live_stop():
        return engine.live_stop()

    @r.post("/api/live/mark")
    def live_mark(body: LiveMark):
        return engine.live_mark(body.note)

    @r.post("/api/live/suggestions/latest/approve")
    def live_approve_latest():
        return engine.live_approve_latest()

    @r.post("/api/live/suggestions/latest/dismiss")
    def live_dismiss_latest():
        return engine.live_dismiss_latest()

    @r.post("/api/live/suggestions/{sid}/approve")
    def live_approve(sid: str, body: LiveApprove):
        return engine.live_approve(sid, body.text)

    @r.post("/api/live/suggestions/{sid}/dismiss")
    def live_dismiss(sid: str):
        return engine.live_dismiss(sid)

    @r.put("/api/live/banner")
    def live_banner(body: LiveBanner):
        return engine.live_banner(body.items)

    @r.post("/api/live/obs/probe")
    def live_obs_probe(body: ObsProbe):
        return engine.live_obs_inputs(body.url, body.password)

    return r


def _serve_under(root: Path, rel: str, suffixes: tuple[str, ...] | None = None, **kw) -> FileResponse:
    """root 아래 파일만 내준다 (../ 로 빠져나가거나 허용하지 않은 확장자면 404)."""
    root = root.resolve()
    p = (root / rel).resolve()
    if root not in p.parents or not p.is_file() or (suffixes and p.suffix.lower() not in suffixes):
        raise HTTPException(404)
    return FileResponse(str(p), **kw)


def _media_routes(engine: Engine) -> APIRouter:
    """영상 · 초안 · 미리보기 이미지 (API 문서에는 넣지 않는다). HEAD 도 받아야 브라우저 <video> 가 메타데이터를 읽는다. Range 지원."""
    r = APIRouter()
    no_store = {"Cache-Control": "no-store"}

    @r.api_route("/media/video/{vid}", methods=["GET", "HEAD"], include_in_schema=False)
    def media_video(vid: str):
        p = engine.project.video_path(vid)  # 원본/편집본 영상 자체 (편집 포인트 검토용 재생)
        if not p:
            raise HTTPException(404)
        return FileResponse(str(p), media_type="video/mp4")

    @r.api_route("/media/review/{path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    def media(path: str):
        return _serve_under(engine.project.review, path)

    @r.api_route("/media/cache/{path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    def media_cache(path: str):
        return _serve_under(engine.project.cache, path, (".png", ".jpg", ".json"), headers=no_store)

    @r.api_route("/media/live/{sid}/{name}", methods=["GET", "HEAD"], include_in_schema=False)
    def media_live(sid: str, name: str):
        return _serve_under(
            engine.project.data_root / "live", f"{sid}/{name}", (".jpg", ".png", ".json"), headers=no_store
        )

    return r


# 화면이 쓰는 것만 허용한다: 자기 출처의 스크립트 · 스타일 · 미디어, 같은 엔진으로의 WebSocket.
# 인라인 스크립트 · 외부 리소스 · 다른 사이트에 끼워 넣기는 막는다. (React 의 style 속성은 CSSOM 이라 영향 없음)
CSP = "; ".join(
    [
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self'",
        "img-src 'self' data: blob:",
        "media-src 'self' blob:",
        "font-src 'self' data:",
        "connect-src 'self' ws://127.0.0.1:* ws://localhost:*",
        "object-src 'none'",
        "base-uri 'none'",
        "form-action 'none'",
        "frame-ancestors 'none'",
    ]
)
SECURITY_HEADERS = {"X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer"}
API_DOCS = ("/docs", "/redoc")  # FastAPI 문서 페이지는 CDN 스크립트를 써서 CSP 에서 뺀다 (개발용)


def _add_ui(app: FastAPI, ui_dir: Path | None) -> None:
    """화면 정적 파일과 응답 헤더.
    - index.html 은 캐시 금지 (빌드마다 자산 해시가 바뀌므로 오래된 index 가 옛 JS 를 가리키면 안 된다). 해시 붙은 assets/ 는 길게 캐시.
    - 모든 응답에 CSP · nosniff · no-referrer (응답이 직접 CSP 를 정했으면 그대로 둔다)."""

    @app.middleware("http")
    async def _ui_headers(request, call_next):
        resp = await call_next(request)
        path = request.url.path
        if path.startswith("/assets/"):
            resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        elif path == "/" or path.endswith(".html"):
            resp.headers["Cache-Control"] = "no-cache"
        resp.headers.update(SECURITY_HEADERS)
        if not path.startswith(API_DOCS) and "content-security-policy" not in resp.headers:
            resp.headers["Content-Security-Policy"] = CSP
        return resp

    if ui_dir:
        app.mount("/", StaticFiles(directory=str(ui_dir), html=True), name="ui")
    else:

        @app.get("/", response_class=HTMLResponse, include_in_schema=False)
        def _no_ui() -> HTMLResponse:
            # 안내 한 장뿐이라 인라인 스타일만 허용한다 (스크립트 없음)
            return HTMLResponse(
                NO_UI_PAGE, headers={"Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'"}
            )


# 화면 빌드(app/dist)가 없을 때: 엔진 API 는 살아 있고, 화면을 만드는 방법을 알려 준다.
NO_UI_PAGE = """<!doctype html><html lang="ko"><meta charset="utf-8"><title>clipforge engine</title>
<body style="margin:0;background:#17171c;color:#e8e8ea;font:15px/1.6 system-ui,'Malgun Gothic';display:grid;place-items:center;height:100vh">
<div style="max-width:560px;padding:24px"><div style="font-size:24px;font-weight:800;color:#f0f660">clipforge</div>
<p style="font-size:18px;font-weight:700;margin:12px 0 4px">엔진은 켜져 있는데 화면 빌드가 없어요</p>
<p style="color:#8b95a1;margin:0">저장소에서 한 번만 실행해 주세요.</p>
<pre style="background:#202027;border-radius:12px;padding:14px;margin-top:14px">cd app\nnpm install\nnpm run build</pre>
<p style="color:#8b95a1">API 문서: <a style="color:#4593fc" href="/docs">/docs</a></p></div></body></html>"""
