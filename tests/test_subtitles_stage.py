"""subtitles 단계: 합성 transcript → premiere/<id>/<id>.srt + .vtt (영상 전체 자막 파일)."""
import json

from clipforge.jobs import DEFAULT_STAGES, STAGES, Job, run_stage


def test_subtitles_stage_writes_srt_and_vtt(tmp_project):
    vid = "epS"
    cache = tmp_project.cache / vid
    cache.mkdir(parents=True)
    (cache / "meta.json").write_text(json.dumps({"duration": 40.0, "width": 1920, "height": 1080, "fps": 30.0, "game": "d2r"}), encoding="utf-8")
    words = "아 이거 진짜 말도 안 되는 득템인데요 여러분 지존참이 떴어요 진짜 미쳤다".split()
    (cache / "transcript.json").write_text(json.dumps({"backend": "fake", "segments": [
        {"start": 1.0, "end": 9.0, "text": " ".join(words),
         "words": [{"start": 1 + i * 0.5, "end": 1.5 + i * 0.5, "word": w} for i, w in enumerate(words)]},
        {"start": 20.0, "end": 21.5, "text": "와, 뭐야!", "words": []},
    ]}, ensure_ascii=False), encoding="utf-8")

    job = Job(id="t1", episode=vid, stages=["subtitles"], params={})
    run_stage(tmp_project, job, "subtitles", lambda f, m="": None)

    srt = tmp_project.premiere / vid / f"{vid}.srt"
    vtt = tmp_project.premiere / vid / f"{vid}.vtt"
    assert srt.exists() and vtt.exists()
    txt = srt.read_text(encoding="utf-8")
    assert txt.startswith("1\n00:00:01,000 -->")                       # 영상 시작 기준 (clip_start=0)
    assert "와, 뭐야!" in txt
    cue_lines = [l for l in txt.splitlines() if l and not l.isdigit() and "-->" not in l]
    assert len(cue_lines) >= 3 and all(len(l) <= 28 for l in cue_lines)   # 가로 영상용 28자 안
    assert vtt.read_text(encoding="utf-8").startswith("WEBVTT\n\n1\n00:00:01.000 -->")
    assert not job.warnings
    assert tmp_project.episode_info(vid)["stages"]["subtitles"] is True
    assert "subtitles" in STAGES and all("subtitles" not in v for v in DEFAULT_STAGES.values())   # 선택 단계

    from clipforge.api.methods import Engine
    paths = Engine(tmp_project).episode_paths(vid)
    assert paths["subtitles_srt"]["exists"] and paths["subtitles_srt"]["path"] == str(srt)


def test_subtitles_stage_requires_transcript(tmp_project):
    import pytest
    from clipforge.errors import EngineError
    (tmp_project.cache / "epN").mkdir(parents=True)
    job = Job(id="t2", episode="epN", stages=["subtitles"], params={})
    with pytest.raises(EngineError) as ei:
        run_stage(tmp_project, job, "subtitles", lambda f, m="": None)
    assert ei.value.code == "E_NO_TRANSCRIPT"
