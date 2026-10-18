"""대사 자막 (ASS). 전사(transcript.json)를 클립 구간에 맞춰 큐로 자르고 ffmpeg `subtitles` 필터로 굽는다.

규칙 (한국 쇼츠 관례: 4~7단어/컷, 흰 글자 + 검은 테두리, 마침표 생략)
  - 세그먼트가 max_chars 를 넘으면 단어 타임스탬프로 나눠 여러 큐로. 단어가 없으면 길이 비례로 시간 분할.
  - 큐 최소 0.6s, 다음 큐와 겹치지 않게. 클립 시작 전·끝 후는 잘라낸다.
  - 위치: 게임 영역 하단 (하단 채팅 띠 위). 상단 훅 자막과 겹치지 않는다.
"""
from __future__ import annotations

import re
from pathlib import Path

ASS_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Talk,Malgun Gothic,{size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,4,1,2,60,60,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def _ts(sec: float) -> str:
    sec = max(0.0, sec)
    h, r = divmod(sec, 3600)
    m, s = divmod(r, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def _clean(text: str) -> str:
    t = text.strip().rstrip(".。")
    return re.sub(r"\s+", " ", t)


def _split_words(words: list[dict], max_chars: int) -> list[tuple[float, float, str]]:
    """단어 리스트를 max_chars 안에서 묶어 (start, end, text) 큐로."""
    cues, buf, b0 = [], [], None
    for w in words:
        tok = w["word"].strip()
        if not tok:
            continue
        cand = (" ".join(x["word"].strip() for x in buf) + " " + tok).strip()
        if buf and len(cand) > max_chars:
            cues.append((b0, buf[-1]["end"], _clean(" ".join(x["word"].strip() for x in buf))))
            buf, b0 = [], None
        if b0 is None:
            b0 = w["start"]
        buf.append(w)
    if buf:
        cues.append((b0, buf[-1]["end"], _clean(" ".join(x["word"].strip() for x in buf))))
    return cues


def cues_for_clip(transcript: dict, start: float, end: float, max_chars: int = 18, min_dur: float = 0.6) -> list[tuple[float, float, str]]:
    out: list[tuple[float, float, str]] = []
    for sg in transcript.get("segments", []):
        if sg["end"] <= start or sg["start"] >= end or not sg.get("text", "").strip():
            continue
        text = _clean(sg["text"])
        if len(text) <= max_chars or not sg.get("words"):
            if len(text) > max_chars:            # 단어 없음: 길이 비례 시간 분할
                parts = re.findall(rf".{{1,{max_chars}}}(?:\s|$)", text)
                parts = [p.strip() for p in parts if p.strip()]
                total = sum(len(p) for p in parts) or 1
                t = sg["start"]
                for p in parts:
                    d = (sg["end"] - sg["start"]) * len(p) / total
                    out.append((t, t + d, p)); t += d
            else:
                out.append((sg["start"], sg["end"], text))
        else:
            out.extend(_split_words(sg["words"], max_chars))
    # 클립 구간으로 자르고, 최소 길이·겹침 정리
    cues = []
    for a, b, t in sorted(out):
        a, b = max(a, start), min(b, end)
        if b - a <= 0.05:
            continue
        if cues and a < cues[-1][1]:
            a = cues[-1][1]
        if b - a < min_dur:
            b = min(end, a + min_dur)
        if b > a:
            cues.append((a, b, t))
    return cues


def write_srt(cues: list[tuple[float, float, str]], path: Path, clip_start: float) -> Path:
    """Premiere 캡션 임포트용 SRT (같은 큐)."""
    def ts(sec):
        sec = max(0.0, sec); h, r = divmod(sec, 3600); m, s = divmod(r, 60)
        return f"{int(h):02d}:{int(m):02d}:{int(s):02d},{int(round((s - int(s)) * 1000)):03d}"
    lines = []
    for i, (a, b, t) in enumerate(cues, 1):
        lines += [str(i), f"{ts(a - clip_start)} --> {ts(b - clip_start)}", t, ""]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def write_ass(cues: list[tuple[float, float, str]], path: Path, clip_start: float, size: int = 58, margin_v: int = 500) -> Path:
    lines = [ASS_HEADER.format(size=size, margin_v=margin_v)]
    for a, b, t in cues:
        t = t.replace("{", "(").replace("}", ")")
        lines.append(f"Dialogue: 0,{_ts(a - clip_start)},{_ts(b - clip_start)},Talk,,0,0,0,,{t}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
