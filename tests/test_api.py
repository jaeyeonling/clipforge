"""엔진 API 테스트: 임시 데이터 폴더의 Engine + FastAPI TestClient. ffmpeg/GPU 없이 도는 것만."""
import json

import pytest
from fastapi.testclient import TestClient

from clipforge.api.methods import ApiError, Engine
from clipforge.api.server import create_app


@pytest.fixture
def engine(tmp_project):
    return Engine(tmp_project)


@pytest.fixture
def client(engine):
    return TestClient(create_app(engine))


def _fake_episode(engine, vid="epX"):
    cache = engine.project.cache / vid
    cache.mkdir(parents=True)
    (cache / "meta.json").write_text(json.dumps({"duration": 100.0, "width": 1920, "height": 1080, "fps": 30.0, "game": "d2r",
                                                 "source": str(engine.project.videos / f"{vid}.mp4")}), encoding="utf-8")
    (engine.project.videos / f"{vid}.mp4").write_bytes(b"\x00")
    (cache / "shorts.json").write_text(json.dumps([
        {"start": 10.0, "end": 30.0, "anchor": 15.0, "variant": "story", "score": 0.9, "axes": {}, "evidence": {"anchor_kinds": ["item"]},
         "hook_mode": "cold_open", "overlay_text": "", "hook_lines": ["와, 뭐야!", "지존참 직득!"]},
        {"start": 50.0, "end": 70.0, "anchor": 55.0, "variant": "short", "score": 0.5, "axes": {}, "evidence": {},
         "hook_mode": "cold_open", "overlay_text": "", "hook_lines": ["x"]}], ensure_ascii=False), encoding="utf-8")
    return vid


def test_health_and_episode_list(engine):
    h = engine.health()
    assert "ffmpeg_ok" in h and "fonts_ok" in h
    assert engine.episode_list() == []
    vid = _fake_episode(engine)
    eps = engine.episode_list()
    assert eps[0]["id"] == vid and eps[0]["stages"]["shorts"] is True and eps[0]["stages"]["prep"] is False


def test_decision_roundtrip_and_metrics(engine):
    vid = _fake_episode(engine)
    engine.decision_set(vid, 10.0, 30.0, "keep", "", "01.mp4")
    engine.decision_set(vid, 50.0, 70.0, "no", "임팩트없음", "02.mp4")
    cands = engine.candidates_list(vid)
    assert cands[0]["start"] == 10.0            # index.json 없으면 shorts.json 그대로
    m = engine.metrics_summary()
    assert m[0]["keep"] == 1 and m[0]["no"] == 1 and m[0]["hit1"] == 1
    engine.decision_set(vid, 10.0, 30.0, "", "")   # 해제
    assert engine.metrics_summary()[0]["keep"] == 0
    with pytest.raises(ApiError):
        engine.decision_set(vid, 1, 2, "maybe")


def test_job_run_rejects_unknown(engine):
    with pytest.raises(ApiError):
        engine.job_run("nope", ["shorts"])
    vid = _fake_episode(engine)
    with pytest.raises(ApiError):
        engine.job_run(vid, ["fly"])


def test_http_endpoints(client, engine):
    assert client.get("/api/health").status_code == 200
    vid = _fake_episode(engine)
    assert client.get("/api/episodes").json()[0]["id"] == vid
    r = client.post(f"/api/episodes/{vid}/decision", json={"start": 10.0, "end": 30.0, "label": "no", "reason": "중복"})
    assert r.status_code == 200 and r.json()["ok"]
    r = client.post(f"/api/episodes/{vid}/decision", json={"start": 10.0, "end": 30.0, "label": "bad"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "E_BAD_LABEL"
    r = client.post("/api/jobs", json={"episode": vid, "stages": ["eval"], "params": {}})
    assert r.status_code == 200 and r.json()["status"] in ("queued", "running", "done")
    assert client.get("/api/profiles/d2r").json()["rois"]["banner"]
    assert client.get("/api/profiles/nope").status_code == 404      # E_NOT_FOUND → 404, 그 외 ApiError → 400
    assert client.get("/media/review/../../secrets").status_code == 404


def test_profile_set_validates(engine, tmp_path):
    # 프로필 파일은 앱 폴더(저장소)에 있으므로 복사본으로 테스트
    import shutil
    from clipforge.project import Project
    app = tmp_path / "app"; (app / "games").mkdir(parents=True)
    shutil.copy(engine.project.games / "d2r.yaml", app / "games" / "d2r.yaml")
    shutil.copytree(engine.project.app_root / "assets", app / "assets")
    e2 = Engine(Project(app_root=app, data_root=tmp_path / "data"))
    prof = e2.profile_get("d2r")
    rois = dict(prof["rois"]); rois["banner"] = [0.0, 0.0, 0.5, 0.2]
    assert e2.profile_set("d2r", rois)["ok"]
    assert e2.profile_get("d2r")["rois"]["banner"] == [0.0, 0.0, 0.5, 0.2]
    with pytest.raises(ApiError):
        e2.profile_set("d2r", {"banner": [0, 0, 2, 2]})
