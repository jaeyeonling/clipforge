"""라이브 모듈: 감지(ep59 프레임, 있을 때만) · 세션 루프(프레임 소스, OBS 없이) · OBS 클라이언트(가짜 서버)."""
import asyncio
import base64
import hashlib
import json
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FRAMES = ROOT / "cache" / "ep59" / "frames"


def test_drop_labels_on_real_frames():
    if not (FRAMES / "000171.jpg").exists():
        pytest.skip("ep59 frames 없음")
    from PIL import Image
    from clipforge.live.detect import LabelOCR, drop_labels
    im = Image.open(FRAMES / "000171.jpg").convert("RGB")
    labs = drop_labels(im)
    assert len(labs) == 1 and labs[0].grade == "set", [l.to_dict() for l in labs]
    LabelOCR().read(im, labs[0])
    assert labs[0].text.replace(" ", "") == "카이트쉴드" and labs[0].score > 0.9 and labs[0].item.get("head") == "카이트쉴드"
    for idx in (300, 450, 600):
        assert drop_labels(Image.open(FRAMES / f"{idx:06d}.jpg").convert("RGB")) == [], idx


def test_session_frames_source_suggests_and_bookmarks(tmp_project):
    if not (FRAMES / "000180.jpg").exists():
        pytest.skip("ep59 frames 없음")
    from clipforge.live.session import LiveSession
    events = []
    s = LiveSession(tmp_project, {"source": "frames", "frames_dir": str(FRAMES), "start": 160, "end": 180, "interval": 0.0,
                                  "approval": True, "chat_burst_thr": 0.05, "chat_cooldown": 1.0}, on_event=lambda e: events.append(e["event"]))
    s.start()
    for _ in range(600):
        if not s.running:
            break
        time.sleep(0.1)
    assert not s.running and s.frames == 20
    sug = [e for e in events if e["type"] == "suggestion"]
    assert sug and sug[0]["head"] == "카이트쉴드" and sug[0]["status"] == "pending"
    assert len(s.suggestions) == 1, "같은 이름은 쿨다운 안에 한 번만"
    s.approve(sug[0]["id"])
    assert s.banner_text() == "득템 : 카이트쉴드" and (s.dir / "banner.txt").read_text(encoding="utf-8") == "득템 : 카이트쉴드"
    assert any(b["kind"] == "drop" for b in s.bookmarks)
    s.mark("손으로")
    s.stop()
    bm = json.loads((s.dir / "bookmarks.json").read_text(encoding="utf-8"))
    assert any(b["note"] == "손으로" and b["kind"] == "manual" for b in bm)
    assert (s.dir / "events.jsonl").exists() and (s.dir / "suggestions.json").exists()
    assert s.set_banner(["a", "b"]) == "득템 : a,b"


def _fake_obs(password: str, texts: dict, port_holder: list):
    """obs-websocket v5 흉내: Hello(인증 challenge) → Identify 검증 → 요청 응답."""
    import websockets

    async def handler(ws):
        salt, challenge = "c2FsdA==", "Y2hhbGxlbmdl"
        await ws.send(json.dumps({"op": 0, "d": {"obsStudioVersion": "30.0", "rpcVersion": 1, "authentication": {"salt": salt, "challenge": challenge}}}))
        ident = json.loads(await ws.recv())
        secret = base64.b64encode(hashlib.sha256((password + salt).encode()).digest()).decode()
        expect = base64.b64encode(hashlib.sha256((secret + challenge).encode()).digest()).decode()
        if ident["d"].get("authentication") != expect:
            await ws.close(code=4009); return
        await ws.send(json.dumps({"op": 2, "d": {"negotiatedRpcVersion": 1}}))
        async for raw in ws:
            m = json.loads(raw); d = m["d"]; rt = d["requestType"]; rd = d.get("requestData", {})
            resp = {"requestType": rt, "requestId": d["requestId"], "requestStatus": {"result": True, "code": 100}}
            if rt == "SetInputSettings":
                texts[rd["inputName"]] = rd["inputSettings"]["text"]
            elif rt == "GetInputSettings":
                resp["responseData"] = {"inputSettings": {"text": texts.get(rd["inputName"], "")}}
            elif rt == "GetRecordStatus":
                resp["responseData"] = {"outputActive": True, "outputDuration": 125000, "outputTimecode": "00:02:05.000"}
            elif rt == "GetInputList":
                resp["responseData"] = {"inputs": [{"inputName": "득템 배너", "inputKind": "text_gdiplus_v2"}, {"inputName": "캠", "inputKind": "dshow_input"}]}
            elif rt == "SaveReplayBuffer":
                texts["_replay"] = texts.get("_replay", 0) + 1
            else:
                resp["requestStatus"] = {"result": False, "code": 204, "comment": "unknown"}
            await ws.send(json.dumps({"op": 7, "d": resp}))

    async def main():
        async with websockets.serve(handler, "127.0.0.1", 0) as server:
            port_holder.append(server.sockets[0].getsockname()[1])
            await asyncio.Future()

    loop = asyncio.new_event_loop()
    t = threading.Thread(target=lambda: loop.run_until_complete(main()), daemon=True); t.start()
    for _ in range(50):
        if port_holder:
            return
        time.sleep(0.05)
    raise RuntimeError("fake obs 시작 실패")


def test_obs_client_auth_and_requests():
    from clipforge.live.obs import ObsClient, ObsError
    texts, ports = {}, []
    _fake_obs("pw123", texts, ports)
    url = f"ws://127.0.0.1:{ports[0]}"
    bad = ObsClient(url, "wrong")
    with pytest.raises(Exception):
        bad.connect()
    bad.close()
    c = ObsClient(url, "pw123")
    info = c.connect()
    assert info["obs"] == "30.0" and c.connected
    c.set_text("득템 배너", "득템 : 슬가")
    assert c.get_text("득템 배너") == "득템 : 슬가" and texts["득템 배너"] == "득템 : 슬가"
    st = c.record_status(); assert st["outputActive"] and st["outputDuration"] == 125000
    assert [i["inputName"] for i in c.get_input_list()] == ["득템 배너", "캠"]
    c.save_replay_buffer(); assert texts["_replay"] == 1
    with pytest.raises(ObsError):
        c.request("Nope")
    c.close()


def test_live_api_roundtrip(tmp_project):
    if not (FRAMES / "000180.jpg").exists():
        pytest.skip("ep59 frames 없음")
    from clipforge.api.methods import ApiError, Engine
    e = Engine(tmp_project)
    assert e.live_status()["active"] is False
    with pytest.raises(ApiError):
        e.live_mark("x")
    st = e.live_start({"source": "frames", "frames_dir": str(FRAMES), "start": 165, "end": 175, "interval": 0.0})
    assert st["running"] is True
    for _ in range(300):
        if not e.live_status()["active"]:
            break
        time.sleep(0.1)
    s = e.live_status()
    assert s["active"] is False and s["suggestions"] and s["suggestions"][0]["head"] == "카이트쉴드"
    sid = s["suggestions"][0]["id"]
    assert e.live_approve(sid)["status"] == "approved"
    assert e.live_banner(["x"])["text"] == "득템 : x"
    with pytest.raises(ApiError):
        e.live_approve("nope")
