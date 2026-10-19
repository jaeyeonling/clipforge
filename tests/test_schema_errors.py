"""§10-6 오류 분류·로그·매니페스트, §10-8 스키마 버전."""
import json
import subprocess
import time

import pytest
from fastapi.testclient import TestClient

from clipforge.api.methods import ApiError, Engine
from clipforge.api.server import create_app
from clipforge.errors import EngineError, classify
from clipforge.schema import KEY, SCHEMA, load_json, load_project_file, migrate, write_json


# ---------- errors ----------
def test_classify_known_patterns():
    assert classify(FileNotFoundError("cache/ep1/transcript.json 없음"))["code"] == "E_NO_TRANSCRIPT"
    assert classify(FileNotFoundError("videos/x.mp4"))["code"] == "E_FILE_MISSING"
    assert classify(subprocess.CalledProcessError(1, ["ffmpeg", "-i", "x"], stderr=b"moov atom not found"))["code"] == "E_FFMPEG_FAILED"
    assert classify(RuntimeError("CUDA driver version is insufficient"))["code"] == "E_GPU"
    internal = classify(KeyError("duration"))
    assert internal["code"] == "E_INTERNAL" and internal["kind"] == "internal" and internal["hint"]
    e = EngineError("E_X", "m", "h")
    assert classify(e) == {"code": "E_X", "message": "m", "hint": "h", "kind": "user"}
    for info in (classify(FileNotFoundError("a")), classify(ValueError("b"))):
        assert info["hint"], info          # 모든 오류에 힌트 문장


# ---------- schema ----------
def test_schema_roundtrip_and_v0_migration(tmp_path):
    p = tmp_path / "shorts.json"
    p.write_text(json.dumps([{"start": 1}, {"start": 2}]), encoding="utf-8")          # v0: 맨 리스트
    assert load_json(p, "shorts") == [{"start": 1}, {"start": 2}]
    assert json.loads(p.read_text())[0] == {"start": 1}                                 # rewrite=False → 파일 그대로
    assert load_json(p, "shorts", rewrite=True) == [{"start": 1}, {"start": 2}]
    raw = json.loads(p.read_text(encoding="utf-8"))
    assert raw[KEY] == SCHEMA["shorts"] and raw["candidates"][1] == {"start": 2}        # rewrite → v1 래퍼
    m = tmp_path / "meta.json"
    write_json(m, "meta", {"duration": 3.0})
    d = load_json(m, "meta")
    assert d["duration"] == 3.0 and d[KEY] == SCHEMA["meta"]
    assert migrate("profile", {"name": "d2r"})[KEY] == SCHEMA["profile"]                # dict v0 → v1


def test_schema_newer_refused_and_bad_json(tmp_path):
    p = tmp_path / "meta.json"
    p.write_text(json.dumps({KEY: SCHEMA["meta"] + 5, "duration": 1}), encoding="utf-8")
    with pytest.raises(EngineError) as ei:
        load_json(p, "meta")
    assert ei.value.code == "E_SCHEMA_NEWER"
    p.write_text("{not json", encoding="utf-8")
    with pytest.raises(EngineError) as ei:
        load_json(p, "meta")
    assert ei.value.code == "E_SCHEMA_BAD"


def test_project_file_created_and_newer_blocks_jobs(tmp_path, monkeypatch):
    from clipforge.project import Project
    from tests.conftest import ROOT
    d = load_project_file(tmp_path)
    assert (tmp_path / "project.json").exists() and d["engine_version"]
    # 엔진보다 새 project.json → Project 는 열리되 schema_error 가 잡히고 job.run 이 막힌다
    (tmp_path / "project.json").write_text(json.dumps({KEY: 99}), encoding="utf-8")
    prj = Project(app_root=ROOT, data_root=tmp_path)
    assert prj.schema_error and prj.schema_error["code"] == "E_SCHEMA_NEWER"
    h = prj.health()
    assert any(p["code"] == "E_SCHEMA_NEWER" for p in h["problems"]) and h["engine_version"]
    eng = Engine(prj)
    with pytest.raises(ApiError) as ei:
        eng.job_run("whatever", ["eval"])
    assert ei.value.code == "E_SCHEMA_NEWER"


# ---------- jobs: 전제 조건 오류 → 코드+힌트, 매니페스트, 로그 ----------
def _wait(engine, job_id, timeout=30.0):   # 빌드·렌더가 같이 돌 때 10초는 모자랐다
    t0 = time.time()
    while time.time() - t0 < timeout:
        j = engine.job_get(job_id)
        if j["status"] in ("done", "error", "cancelled"):
            return j
        time.sleep(0.05)
    raise AssertionError("job did not finish")


def test_job_precondition_error_manifest_and_log(tmp_project):
    engine = Engine(tmp_project)
    vid = "epZ"
    (tmp_project.videos / f"{vid}.mp4").write_bytes(b"\x00")
    j = engine.job_run(vid, ["export"])                      # shorts.json 없음 → E_NO_SHORTS
    j = _wait(engine, j["id"])
    assert j["status"] == "error" and j["error_info"]["code"] == "E_NO_SHORTS" and "shorts" in j["error_info"]["hint"]
    mp = j["manifest_path"]
    m = json.loads(open(mp, encoding="utf-8").read())
    assert m["status"] == "error" and m["error"]["code"] == "E_NO_SHORTS" and m["engine_version"] and m["schema"]["shorts"]
    lg = engine.job_log(j["id"])
    assert any(l["level"] == "error" for l in lg["lines"]) and lg["path"].endswith(".jsonl")
    # 이력: 새 엔진(재시작 가정)도 매니페스트로 작업을 본다
    e2 = Engine(tmp_project)
    hist = e2.job_list()
    assert any(x["id"] == j["id"] and x.get("from_manifest") for x in hist)
    assert e2.job_log(j["id"])["lines"]


def test_http_error_shapes(tmp_project):
    engine = Engine(tmp_project)
    client = TestClient(create_app(engine), raise_server_exceptions=False)
    r = client.post("/api/jobs", json={"stages": ["eval"]})                     # episode 누락 → 검증 오류도 같은 형태
    assert r.status_code == 400 and r.json()["error"]["code"] == "E_BAD_REQUEST" and r.json()["error"]["hint"]
    r = client.get("/api/jobs/nope")
    assert r.status_code == 404 and r.json()["error"]["code"] == "E_NOT_FOUND"
    r = client.get("/api/jobs/nope/log")
    assert r.status_code == 404
    h = client.get("/api/health").json()
    assert "problems" in h and "engine_version" in h and h["schema"]["meta"] == SCHEMA["meta"]


# ---------- 배포 번들: ffmpeg 탐색 순서 (번들 bin/ > CLIPFORGE_FFMPEG > PATH) ----------
def test_find_ffmpeg_prefers_bundle_bin(tmp_path, monkeypatch):
    from clipforge import project
    (tmp_path / "bin").mkdir(); (tmp_path / "bin" / "ffmpeg.exe").write_bytes(b"")
    monkeypatch.setattr(project, "APP_ROOT", tmp_path)
    assert project.find_ffmpeg() == tmp_path / "bin"
    (tmp_path / "bin" / "ffmpeg.exe").unlink()
    other = tmp_path / "x"; other.mkdir(); (other / "ffmpeg.exe").write_bytes(b"")
    monkeypatch.setenv("CLIPFORGE_FFMPEG", str(other))
    assert project.find_ffmpeg() == other


def test_health_problems_levels():
    from clipforge.project import health_problems
    h = {"ffmpeg_ok": True, "fonts_ok": True, "rapidocr": True, "nvenc": True, "whisper_gpu": True, "whisper_model": True, "disk_free_gb": 100}
    assert health_problems(h) == []
    h2 = {**h, "ffmpeg_ok": False, "whisper_model": False, "disk_free_gb": 3}
    codes = {p["code"]: p["level"] for p in health_problems(h2)}
    assert codes == {"E_FFMPEG_MISSING": "error", "W_NO_WHISPER_MODEL": "warn", "W_DISK_LOW": "warn"}
    assert all(p["hint"] for p in health_problems(h2))
