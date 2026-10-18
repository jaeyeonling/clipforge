"""순수 함수 테스트: timeline / adapters / candidates / item_banner 전이 / lexicon / weaklabel / subtitles / textdraw."""
from pathlib import Path

import numpy as np
import pytest

from clipforge.adapters import events_to_curve
from clipforge.candidates import make_candidates
from clipforge.timeline import Curve, Segment, Segments, fmt_time, parse_time


# ---------- timeline ----------
def test_parse_and_format_time():
    assert parse_time("1:30") == 90.0
    assert parse_time("0:00:05") == 5.0
    assert parse_time("12.5") == 12.5
    assert fmt_time(3661) == "1:01:01"
    assert fmt_time(65) == "1:05"


def test_segments_merge_close_and_overlap():
    s = Segments("x", [Segment(0, 5, "a", 0.5), Segment(6, 10, "a", 0.9), Segment(20, 25, "a", 0.1)])
    m = s.merge_close(gap=2.0)
    assert [(i.start, i.end) for i in m.items] == [(0, 10), (20, 25)]
    assert m.items[0].score == 0.9
    assert Segment(0, 10).overlap(Segment(5, 20)) == 5


def test_segments_csv_roundtrip(tmp_path):
    p = tmp_path / "l.csv"
    p.write_text("start,end,label,note\n1:00,1:10,keep,hello\n,,,\n", encoding="utf-8")
    s = Segments.from_csv(p)
    assert len(s.items) == 1 and s.items[0].start == 60 and s.items[0].meta["note"] == "hello"


# ---------- adapters ----------
def test_events_to_curve_trapezoid():
    segs = Segments("ev", [Segment(10, 10, "append", 1.0)])
    c = events_to_curve(segs, duration=30, hop=1.0, pre=4, post=4, labels=["append"])
    v = c.as_array()
    assert v[10] == pytest.approx(1.0)
    assert v[0] == 0.0 and v[29] == 0.0
    assert v[6] == 0.0 and 0 < v[7] < 1.0            # 창 가장자리(6)는 0, 램프 구간(7)은 중간값
    assert c.meta["n_events"] == 1
    assert events_to_curve(segs, 30, labels=["other"]).meta["n_events"] == 0


# ---------- candidates ----------
def test_make_candidates_with_curve_and_event():
    vals = [0.0] * 120
    for i in range(40, 48):
        vals[i] = 10.0                                   # 20~24초 큰 소리 (hop 0.5)
    curves = {"audio_loudness": Curve("audio_loudness", 0.5, vals)}
    events = {"item_banner": Segments("item_banner", [Segment(50, 50, "append", 1.0)])}
    segs = make_candidates(curves, duration=60, weights={"audio_loudness": 1.0, "item_banner": 1.5}, events=events,
                           kernels={"item_banner": {"labels": ["append"], "pre": 3, "post": 3}}, threshold=1.0)
    starts = [round(s.start) for s in segs.items]
    assert any(abs(st - 16) <= 4 for st in starts), starts     # 음량 구간 (pad_before 4)
    assert any(abs(st - 43) <= 4 for st in starts), starts     # 득템 이벤트
    assert "item_banner(ev)" in segs.meta["signals"]


# ---------- item_banner 전이 ----------
def test_banner_transitions_labels():
    from clipforge.signals.item_banner import stable_states, transitions
    seq = (["득템:화염5/3주얼"] * 5 + ["득템:화염5/3주얼,슬가"] * 5 + [""] * 4
           + ["득템:화염5/3주얼,슬가,3맥20어레20피"] * 5 + ["득템:화염5/3주얼,슬가,3맥20어레20피,★★★"] * 4)
    st = stable_states(seq, 3)
    ev = transitions(st)
    labels = [(int(e.start), e.label) for e in ev]
    assert (5, "append") in labels                     # 슬가 추가
    assert (10, "reset") in labels                     # 배너 소실
    assert (14, "append") in labels                    # 사라졌다 돌아오며 늘어남 → append (last_banner 비교)
    assert all(lab != "append" or int(t) != 19 for t, lab in labels)   # ★만 늘어난 건 무시
    added = [e.meta["added"] for e in ev if e.label == "append"]
    assert any("슬가" in a for a in added) and any("3맥20어레20피" in a for a in added)


# ---------- lexicon / weaklabel ----------
def test_lexicon_lookup_known_and_unknown():
    from clipforge.lexicon import Lexicon
    lex = Lexicon("d2r")
    assert lex.lookup("3맥20어레20피").head == "지존참"
    assert lex.lookup("레이븐링").kind == "unique"
    m = lex.lookup("기드참(매찬34)")
    assert m.head == "기드참" and "매찬34" in m.option
    assert lex.lookup("완전모르는토큰zz").head is None


def test_weaklabel_title_to_banner():
    from clipforge.weaklabel import load_slang, match_banner, title_keywords
    slang = load_slang("d2r")
    kws = title_keywords("래더 12기 59일차만에 지존참 직득했습니다", slang)
    assert "지존참" in [k for k, _ in kws]
    banner = Segments("item_banner", [Segment(171, 171, "append", 1.0, {"added": "템엄,슬가,3맥20어레20피"}),
                                     Segment(400, 400, "append", 1.0, {"added": "레이븐링"})])
    m = match_banner(kws, banner)
    assert m and m[0]["t"] == 171


# ---------- subtitles ----------
def test_cues_split_on_words_and_srt():
    from clipforge.subtitles import cues_for_clip, write_srt
    tr = {"segments": [{"start": 10.0, "end": 14.0, "text": "아 이거 진짜 말도 안 되는 득템인데요 여러분",
                        "words": [{"start": 10 + i * 0.5, "end": 10.5 + i * 0.5, "word": w} for i, w in
                                  enumerate("아 이거 진짜 말도 안 되는 득템인데요 여러분".split())]},
                       {"start": 20.0, "end": 21.0, "text": "와, 뭐야!", "words": []}]}
    cues = cues_for_clip(tr, start=9.0, end=25.0, max_chars=12)
    assert len(cues) >= 3
    assert all(len(t) <= 12 or " " not in t for _, _, t in cues)
    assert all(b > a for a, b, _ in cues)
    assert all(cues[i][1] <= cues[i + 1][0] + 1e-6 for i in range(len(cues) - 1))   # 겹침 없음
    import tempfile
    p = Path(tempfile.mkdtemp()) / "x.srt"
    write_srt(cues, p, clip_start=9.0)
    txt = p.read_text(encoding="utf-8")
    assert txt.startswith("1\n00:00:01,000 -->")


# ---------- textdraw ----------
def test_textdraw_fallback_and_bold_monotonic():
    from PIL import Image, ImageDraw
    from clipforge.textdraw import FontStack, draw_text, fit_size
    pen = FontStack("pen", "gothic")
    runs = pen.runs("지존참 · ★", 60)
    assert len(runs) >= 2                       # '·', '★' 는 고딕 폴백으로 분리
    assert fit_size(pen, "아주 긴 제목 글자가 많이 들어가면 줄어든다", 400, 120) < 120

    def ink(weight):
        img = Image.new("L", (300, 200), 0)
        draw_text(ImageDraw.Draw(img), (20, 20), "참", pen, 120, fill=255, weight=weight)
        return int((np.asarray(img) > 128).sum())
    assert ink(2) > ink(0) > 0


# ---------- shorts: 발화 경계 / 채팅 교정 ----------
def test_speech_segments_and_snapping(synth_wav):
    from clipforge.shorts import snap_end, snap_start, speech_segments
    segs = speech_segments(synth_wav)
    assert len(segs) == 1
    a, b = segs[0]
    assert 0.9 <= a <= 1.1 and 1.9 <= b <= 2.1
    assert snap_end(1.5, segs) == pytest.approx(b + 0.3, abs=0.05)      # 발화 중 → 발화 끝 +margin
    assert snap_start(1.5, segs) == pytest.approx(a - 0.3, abs=0.05)
    assert snap_start(0.2, segs) == pytest.approx(a - 0.3, abs=0.05)    # 쉼 → 다음 발화 시작


def test_clean_chat_fixes():
    from clipforge.shorts import clean_chat
    assert clean_chat("120자룬헐") == "120자룬 헐"
    assert clean_chat("혈 지참 나왔어요??") == "헐 지참 나왔어요??"
    assert clean_chat("a  b   c") == "a b c"
