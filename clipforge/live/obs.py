"""obs-websocket v5 클라이언트 (websockets 라이브러리, 비동기 → 세션 스레드에서 동기 래퍼로 사용).

  obs = ObsClient("ws://127.0.0.1:4455", password)
  obs.connect()                                  # Hello → Identify(SHA256 challenge) → Identified
  obs.set_text("득템 배너", "득템 : 슬가, 지존참") # SetInputSettings {text}
  obs.record_status()                            # {outputActive, outputTimecode, outputDuration}
  obs.save_replay_buffer()                       # 리플레이 버퍼 저장 (켜져 있을 때)
  obs.get_input_list(kind="text_gdiplus_v2")     # 텍스트 소스 목록 (설정 화면용)

프로토콜: https://github.com/obsproject/obs-websocket/blob/master/docs/generated/protocol.md
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import threading
import uuid
from typing import Any


class ObsError(Exception):
    pass


class ObsClient:
    def __init__(self, url: str = "ws://127.0.0.1:4455", password: str = "", timeout: float = 5.0):
        self.url, self.password, self.timeout = url, password, timeout
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._ws: Any = None  # websockets 연결 (connect 뒤)
        self._pending: dict[str, asyncio.Future] = {}
        self.connected = False
        self.obs_version = ""

    # ---- 수명 ----
    def connect(self) -> dict:
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._thread.start()
        return self._run(self._connect())

    def close(self) -> None:
        if self._loop and self._ws:
            try:
                self._run(self._ws.close())
            except Exception:
                pass
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)
        self.connected = False

    def _run(self, coro):
        assert self._loop is not None, "connect() 를 먼저"
        fut = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return fut.result(timeout=self.timeout + 2)

    async def _connect(self) -> dict:
        import websockets

        async def open_ws() -> Any:
            return await websockets.connect(self.url, max_size=16 * 1024 * 1024)

        self._ws = await asyncio.wait_for(open_ws(), self.timeout)
        hello = json.loads(await asyncio.wait_for(self._ws.recv(), self.timeout))
        if hello.get("op") != 0:
            raise ObsError(f"Hello 가 아니에요: {hello}")
        d = hello["d"]
        self.obs_version = d.get("obsStudioVersion", "")
        ident = {"rpcVersion": d.get("rpcVersion", 1), "eventSubscriptions": 0}
        if "authentication" in d:
            if not self.password:
                raise ObsError("OBS WebSocket 비밀번호가 필요해요 (OBS → 도구 → WebSocket 서버 설정)")
            a = d["authentication"]
            secret = base64.b64encode(hashlib.sha256((self.password + a["salt"]).encode()).digest()).decode()
            ident["authentication"] = base64.b64encode(
                hashlib.sha256((secret + a["challenge"]).encode()).digest()
            ).decode()
        await self._ws.send(json.dumps({"op": 1, "d": ident}))
        resp = json.loads(await asyncio.wait_for(self._ws.recv(), self.timeout))
        if resp.get("op") != 2:
            raise ObsError(f"인증 실패: {resp}")
        self.connected = True
        self._reader_task = asyncio.ensure_future(
            self._reader(), loop=self._loop
        )  # 참조를 잡아 둬야 GC 가 작업을 거두지 않는다
        return {"obs": self.obs_version, "rpc": resp["d"].get("negotiatedRpcVersion")}

    async def _reader(self):
        try:
            async for raw in self._ws:
                msg = json.loads(raw)
                if msg.get("op") == 7:
                    rid = msg["d"].get("requestId")
                    fut = self._pending.pop(rid, None)
                    if fut and not fut.done():
                        fut.set_result(msg["d"])
        except Exception:
            pass
        finally:
            self.connected = False

    async def _request(self, rtype: str, data: dict | None = None) -> dict:
        if not self._ws:
            raise ObsError("연결되지 않음")
        rid = uuid.uuid4().hex
        assert self._loop is not None
        fut = self._loop.create_future()
        self._pending[rid] = fut
        await self._ws.send(
            json.dumps({"op": 6, "d": {"requestType": rtype, "requestId": rid, "requestData": data or {}}})
        )
        d = await asyncio.wait_for(fut, self.timeout)
        st = d.get("requestStatus", {})
        if not st.get("result"):
            raise ObsError(f"{rtype} 실패: {st.get('comment', st)}")
        return d.get("responseData") or {}

    def request(self, rtype: str, data: dict | None = None) -> dict:
        return self._run(self._request(rtype, data))

    # ---- 편의 ----
    def set_text(self, input_name: str, text: str) -> None:
        self.request("SetInputSettings", {"inputName": input_name, "inputSettings": {"text": text}, "overlay": True})

    def get_text(self, input_name: str) -> str:
        return str(self.request("GetInputSettings", {"inputName": input_name}).get("inputSettings", {}).get("text", ""))

    def get_input_list(self, kind: str | None = None) -> list[dict]:
        return self.request("GetInputList", {"inputKind": kind} if kind else {}).get("inputs", [])

    def record_status(self) -> dict:
        return self.request("GetRecordStatus")

    def save_replay_buffer(self) -> None:
        self.request("SaveReplayBuffer")
