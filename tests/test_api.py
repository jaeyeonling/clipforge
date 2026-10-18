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


def test_episode_add_reference_without_copy(engine, tmp_path):
    """다른 드라이브(또는 link=False)면 복사하지 않고 원본 경로를 참조한다. id 는 안전한 이름으로."""
    src = tmp_path / "raw" / "래더 12기 60일차 (원본).mp4"
    src.parent.mkdir(); src.write_bytes(b"\x00" * 10)
    ep = engine.episode_add(str(src), None, "제목", "d2r", link=False)
    assert ep["id"] == "래더_12기_60일차_원본" and ep["linked"] is False and ep["source"] == str(src.resolve()) and ep["game"] == "d2r"
    assert ep["id"] in engine.project.episode_ids()
    assert engine.project.video_path(ep["id"]) == src.resolve()
    assert not list(engine.project.videos.glob("*.mp4"))            # 복사본 없음
    import pytest as _pt
    with _pt.raises(ApiError) as ei:
        engine.episode_add(str(tmp_path / "x.txt"), None, "", "d2r")
    assert ei.value.code == "E_BAD_FILE" or ei.value.code == "E_NOT_FOUND"


def test_phase2_editpoints_and_metrics(engine, tmp_path):
    """원본 회차: candidates.json + labels/<vid>.csv(kept) → 편집 포인트 목록·지표, 사람 판정, align 파라미터 검증."""
    from clipforge.timeline import Segment, Segments
    vid = _fake_episode(engine, "orig1")
    engine._upsert_episode_row(vid, "d2r", "원본", source="", kind="original")
    assert engine.episode_get(vid)["kind"] == "original"
    Segments("candidates", [Segment(10, 20, "cand", 2.0), Segment(50, 60, "cand", 1.5), Segment(80, 90, "cand", 1.2)],
             meta={"signals": ["audio_loudness"]}).save(engine.project.cache / vid / "candidates.json")
    (engine.project.labels / f"{vid}.csv").write_text("start,end,label,note\n12,18,kept,auto align f.mp4 0-6\n70,75,kept,auto align f.mp4 8-13\n", encoding="utf-8")
    ep = engine.editpoints_list(vid)
    assert [c["kept"] for c in ep["candidates"]] == [True, False, False]
    assert ep["report"]["n_labels"] == 2 and ep["report"]["recall"] == 0.5 and ep["report"]["missed"][0]["start"] == 70
    assert ep["video_url"] == f"/media/video/{vid}"
    engine.decision_set(vid, 50, 60, "kept", "", "", kind="editpoints")
    ep = engine.editpoints_list(vid)
    assert ep["candidates"][1]["decision"] == "kept" and ep["candidates"][1]["kept"] is True   # 사람 판정도 정답
    rows = [r for r in engine.metrics_summary() if r["episode"] == vid]
    assert rows and rows[0]["phase"] == "editpoints" and rows[0]["labels"] == 3
    import pytest as _pt
    with _pt.raises(ApiError) as ei:
        engine.job_run(vid, ["align"], {})
    assert ei.value.code == "E_BAD_PARAMS"
    with _pt.raises(ApiError):
        engine.decision_set(vid, 1, 2, "keep", kind="editpoints")                     # editpoints 는 kept|no


def test_kept_categories_crud_and_by_label(engine):
    from clipforge.timeline import Segment, Segments
    vid = _fake_episode(engine, "orig2")
    cats = {c["key"] for c in engine.label_categories()}
    assert {"drop", "reaction", "fail"} <= cats
    Segments("candidates", [Segment(10, 20, "cand", 2.0)], meta={}).save(engine.project.cache / vid / "candidates.json")
    (engine.project.labels / f"{vid}.csv").write_text("start,end,label,note\n12,18,kept,auto align f.mp4 0-6\n70,75,kept,auto align f.mp4 8-13\n", encoding="utf-8")
    assert [k["source"] for k in engine.kept_list(vid)["kept"]] == ["auto", "auto"]
    engine.kept_set(vid, 12, 18, "drop")
    engine.kept_set(vid, 70, 75, "reaction", new_start=69, new_end=76)
    engine.kept_add(vid, 100, 104, "fail", "직접")
    k = engine.kept_list(vid)["kept"]
    assert [(x["label"], x["start"], x["end"]) for x in k] == [("drop", 12.0, 18.0), ("reaction", 69.0, 76.0), ("fail", 100.0, 104.0)]
    assert k[2]["source"] == "manual"
    rep = engine.editpoints_list(vid)["report"]
    assert rep["by_label"] == {"drop": {"hit": 1, "total": 1}, "fail": {"hit": 0, "total": 1}, "reaction": {"hit": 0, "total": 1}}
    engine.kept_delete(vid, 100, 104)
    assert len(engine.kept_list(vid)["kept"]) == 2
    import pytest as _pt
    with _pt.raises(ApiError):
        engine.kept_set(vid, 12, 18, "nope")
    with _pt.raises(ApiError):
        engine.kept_delete(vid, 1, 2)


def test_candidates_show_shorts_ground_truth(engine):
    vid = _fake_episode(engine)
    idx = engine.project.review / vid / "shorts"; idx.mkdir(parents=True)
    from clipforge.schema import write_json
    write_json(idx / "index.json", "index", [{"file": "01.mp4", "rank": 1, "variant": "story", "start": 10.0, "end": 30.0, "anchor": 15.0, "score": 0.9, "hook_lines": []},
                                              {"file": "02.mp4", "rank": 2, "variant": "short", "start": 50.0, "end": 70.0, "anchor": 55.0, "score": 0.5, "hook_lines": []}])
    (engine.project.labels / f"{vid}.shorts.csv").write_text("start,end,label,note\n12,28,keep,auto align shorts friend1.mp4 0.0-16.0 votes=100 margin=9\n", encoding="utf-8")
    rows = engine.candidates_list(vid)
    assert rows[0]["gt"] == ["friend1.mp4"] and rows[1]["gt"] == []
    import pytest as _pt
    with _pt.raises(ApiError) as ei:
        engine.job_run(vid, ["align"], {})
    assert ei.value.code == "E_BAD_PARAMS"
    assert engine.job_run(vid, ["eval"], {"shorts": ["x"]})["status"] in ("queued", "running", "done")
