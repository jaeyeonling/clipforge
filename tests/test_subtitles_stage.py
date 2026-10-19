"""subtitles 단계: 합성 transcript → premiere/<id>/<id>.srt + .vtt (영상 전체 자막 파일)."""
import json

from clipforge.jobs import DEFAULT_STAGES, STAGES, Job, run_stage


def test_subtitles_stage_writes_srt_and_vtt(tmp_project):
    vid = "epS"
    cache = tmp_project.cache / vid
    cache.mkdir(parents=True)
    (cache / "meta.json").write_text(json.dumps({"duration": 40.0, "width": 1920, "height": 1080, "fps": 59.94005994005994, "game": "d2r"}), encoding="utf-8")
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
    vegas = (tmp_project.premiere / vid / f"{vid}.vegas.txt").read_text(encoding="utf-8").splitlines()
    assert len(vegas) == len(cue_lines)
    first = vegas[0].split("\t")
    assert len(first) == 4 and first[0] == "00:00:01;00" and first[3] == cue_lines[0]      # 59.94 → 드롭 프레임 ';'
    assert "와, 뭐야!" in vegas[-1] and vegas[-1].split("\t")[0] == "00:00:19;59"   # 벽시계 20.0s = 1199번째 프레임 (드롭 프레임은 분 경계 전까지 살짝 뒤)
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


def test_vegas_timecode_drop_and_nondrop():
    from clipforge.subtitles import vegas_timecode
    assert vegas_timecode(1.0, 30.0) == "00:00:01:00" and vegas_timecode(61.5, 30.0) == "00:01:01:15"
    assert vegas_timecode(0.0, 29.97) == "00:00:00;00"
    assert vegas_timecode(1800 / 29.97, 29.97) == "00:01:00;02"   # 1800번째 프레임: 1분 경계에서 2프레임 건너뜀 (SMPTE 드롭 프레임)
    assert vegas_timecode(600.0, 29.97) == "00:10:00;00"          # 10분마다는 건너뛰지 않음
    assert vegas_timecode(3600.0, 29.97) == "01:00:00;00"         # 한 시간 뒤에도 벽시계와 일치
    assert vegas_timecode(600.0, 59.94) == "00:10:00;00"
    assert vegas_timecode(600.0, 25.0) == "00:10:00:00"
