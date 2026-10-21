"""통합: ffmpeg 로 만든 합성 방송 영상을 실제 단계(prep → signals → shorts → export → xml)로 끝까지 돌린다.

화면: 테스트 패턴 위 좌상단 득템 배너 영역을 검게 덮고, 12초부터 아이템 이름이 뜬다. 소리: 같은 순간 크게.
→ 배너 OCR 이 12초 무렵 추가를 잡고, 쇼츠 후보가 그 순간을 덮고, 세로 초안(1080×1920)과 Premiere XML 이 나와야 한다.
ffmpeg 가 없으면 건너뛴다. 단 CLIPFORGE_REQUIRE_FFMPEG=1 (CI 통합 작업)이면 건너뛰지 않고 실패한다 — 조용히 빠지지 않게.
전사(Whisper)는 모델이 커서 뺀다.
"""

import json
import os
import subprocess
from pathlib import Path

import pytest

from clipforge.project import find_ffmpeg

ROOT = Path(__file__).resolve().parent.parent
FFMPEG_DIR = find_ffmpeg()
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(FFMPEG_DIR is None and not os.environ.get("CLIPFORGE_REQUIRE_FFMPEG"), reason="ffmpeg 없음"),
]

DROP_AT = 12  # 득템 순간 (초)
LENGTH = 30


def ff(name: str) -> str:
    assert FFMPEG_DIR is not None, "ffmpeg 를 찾지 못했어요 (PATH 또는 CLIPFORGE_FFMPEG)"
    exe = FFMPEG_DIR / (name + ".exe")
    return str(exe if exe.exists() else FFMPEG_DIR / name)


def make_broadcast(dst: Path) -> None:
    """1920×1080 30fps 30초. 배너 영역(좌상단 44%×15%)은 검은 상자, DROP_AT 초부터 그 안에 아이템 이름."""
    banner_w, banner_h = int(1920 * 0.44), int(1080 * 0.145)
    font = "assets/fonts/BlackHanSans-Regular.ttf"  # 상대 경로: Windows 드라이브 콜론을 drawtext 에서 피한다
    video = (
        f"testsrc2=s=1920x1080:r=30:d={LENGTH},"
        f"drawbox=x=0:y=0:w={banner_w}:h={banner_h}:color=black:t=fill,"
        f"drawtext=fontfile={font}:text='KITE SHIELD':x=40:y=60:fontsize=72:fontcolor=white:"
        f"enable='gte(t\\,{DROP_AT})'"
    )
    audio = (
        f"aevalsrc='0.03*sin(2*PI*220*t)*(1-between(t\\,{DROP_AT}\\,{DROP_AT + 3}))"
        f"+0.8*sin(2*PI*440*t)*between(t\\,{DROP_AT}\\,{DROP_AT + 3})':s=48000:d={LENGTH}"
    )
    subprocess.run(
        [ff("ffmpeg"), "-v", "error", "-y", "-f", "lavfi", "-i", video, "-f", "lavfi", "-i", audio,
         "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(dst)],
        check=True,
        cwd=ROOT,
    )  # fmt: skip


def probe(path: Path) -> dict:
    out = subprocess.run(
        [ff("ffprobe"), "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height:format=duration",
         "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout  # fmt: skip
    d = json.loads(out)
    return {**d["streams"][0], "duration": float(d["format"]["duration"])}


def test_broadcast_to_vertical_draft_and_premiere_xml(tmp_project, tmp_path):
    from clipforge.api.methods import Engine
    from clipforge.jobs import STAGE_FNS, Job
    from clipforge.timeline import Segments

    src = tmp_path / "broadcast.mp4"
    make_broadcast(src)
    engine = Engine(tmp_project)
    vid = engine.episode_add(str(src), "drop", title="합성 득템 회차")["id"]
    cache = tmp_project.cache / vid

    job = Job(id="it", episode=vid, stages=["prep", "signals", "shorts", "export", "xml"], params={"k": 2})
    for stage in job.stages:
        STAGE_FNS[stage](tmp_project, job, lambda _f, _m="": None)

    # prep: 길이 · 1초 프레임 · 오디오
    meta = json.loads((cache / "meta.json").read_text(encoding="utf-8"))
    assert abs(meta["duration"] - LENGTH) < 1
    assert len(list((cache / "frames").glob("*.jpg"))) >= LENGTH - 1
    assert (cache / "audio.wav").exists()

    # 배너 OCR: 비어 있던 배너에 아이템이 붙은 순간
    adds = [s for s in Segments.load(cache / "item_banner.json").items if s.label == "switch"]
    assert any(abs(s.start - DROP_AT) <= 3 and "KITE" in s.meta.get("added", "").upper() for s in adds), adds

    # 쇼츠 후보가 그 순간을 덮는다
    cands = json.loads((cache / "shorts.json").read_text(encoding="utf-8"))["candidates"]
    assert cands and any(c["start"] <= DROP_AT <= c["end"] for c in cands), cands

    # 세로 초안 1080×1920
    drafts = sorted((tmp_project.review / vid / "shorts").glob("*.mp4"))
    assert drafts
    p = probe(drafts[0])
    assert (p["width"], p["height"]) == (1080, 1920)
    assert p["duration"] > 5

    # Premiere XML: OTIO 로 다시 읽힌다
    import opentimelineio as otio

    xmls = sorted(tmp_project.premiere.glob(f"**/{vid}*.xml"))
    assert xmls, list(tmp_project.premiere.rglob("*"))
    for x in xmls:
        tl = otio.adapters.read_from_file(str(x), adapter_name="fcp_xml")
        assert tl.tracks, x
