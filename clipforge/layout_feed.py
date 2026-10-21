"""쇼츠 레이아웃 'feed' — 스트리머 피드백(2026-10-18, 레퍼런스 @마골 쇼츠).

1080×1920 구성 (위→아래)
  0~  90   채널 띠            "디아블로2 하이라이트"  (정적 PNG)
  110~718  게임 화면 16:9 전체  크롭 없음. 위에 두 층:
              · 발화 자막 (좌상단, 작은 흰 글자 + 반투명 상자)        ← transcript
              · 채팅 하이라이트 (화면 하단 중앙, 큰 글자 + 어두운 상자)  ← 반응 어휘가 있는 채팅, 3초
  740~800  회차 라벨 띠         "래더 12기 노거래 맨땅 59일차"          (정적 PNG)
  820~900  고정 훅 한 줄        "지존참 직득!"                        (정적 PNG)
  930~1700 채팅 피드            닉네임 없이 본문만, 시간 따라 아래로 쌓임   ← chat_text (ASS 상태 전환)
  1720~    하단 띠              채널 핸들/회차                        (정적 PNG)
인트로(0~1.6s): 게임 화면을 60% 로 가운데 작게, 그 아래 큰 제목 2줄(흰/금). 이후 풀 사이즈로 컷.

구현: 텍스트 층은 ASS 한 파일(libass) — 발화(Talk)·하이라이트(Hi)·채팅 피드(Feed)·인트로(Intro) 스타일.
정적 요소는 PNG 한 장(textdraw). 영상은 scale→overlay(인트로 enable 식). 한 번의 ffmpeg 패스.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

from .shorts import ShortCandidate, _load_chat_keywords, clean_chat
from .subtitles import _ts, cues_for_clip
from .textdraw import FontStack, draw_text, fit_size

W, H = 1080, 1920
VID_W, VID_H, VID_Y = 1080, 608, 110  # 16:9
BAR_Y, HOOK_Y, FEED_Y0, FEED_Y1, FOOT_Y = 740, 820, 930, 1700, 1720
INTRO_SEC = 1.6
GOTHIC = FontStack("gothic", "gothic_regular")
BLACK = FontStack("black", "gothic")
PEN = FontStack("pen", "gothic")

ASS_HEAD = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Talk,Malgun Gothic,40,&H00FFFFFF,&H00FFFFFF,&H00000000,&H99000000,-1,0,0,0,100,100,0,0,3,10,0,7,40,40,0,1
Style: Hi,Malgun Gothic,54,&H00FFFFFF,&H00FFFFFF,&H00000000,&HAA000000,-1,0,0,0,100,100,0,0,3,14,0,2,60,60,0,1
Style: Feed,Malgun Gothic,64,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,0,0,7,56,56,0,1
Style: IntroW,Black Han Sans,86,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,8,40,40,0,1
Style: IntroG,Black Han Sans,86,&H0040C8F0,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,8,40,40,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def _esc(t: str) -> str:
    return t.replace("{", "(").replace("}", ")").replace("\\", "/")


def _wrap_chars(text: str, per_line: int) -> list[str]:
    out, cur = [], ""
    for w in text.split(" "):
        if len(cur) + len(w) + (1 if cur else 0) <= per_line:
            cur = (cur + " " + w).strip()
        else:
            if cur:
                out.append(cur)
            while len(w) > per_line:
                out.append(w[:per_line])
                w = w[per_line:]
            cur = w
    if cur:
        out.append(cur)
    return out or [""]


# ---------- ASS 텍스트 층 ----------
def build_ass(
    c: ShortCandidate,
    transcript: dict | None,
    chat: list[dict] | None,
    intro_lines: list[str],
    intro_sec: float = INTRO_SEC,
) -> str:
    ev: list[str] = []
    t0 = c.start

    def dlg(style: str, a: float, b: float, text: str, layer: int = 0) -> None:
        if b - a > 0.05 and text.strip():
            ev.append(f"Dialogue: {layer},{_ts(a)},{_ts(b)},{style},,0,0,0,,{text}")

    # 인트로 제목 (화면 중앙, 작은 영상 아래)
    if intro_lines:
        y = VID_Y + int(VID_H * 0.6) + 70
        for i, line in enumerate(intro_lines[:2]):
            dlg(
                "IntroG" if i == 1 else "IntroW",
                0.0,
                intro_sec,
                f"{{\\an8\\pos({W // 2},{y + i * 110})}}{_esc(line)}",
                2,
            )

    # 발화 자막: 영상 좌상단 (인트로 뒤부터)
    if transcript:
        for a, b, text in cues_for_clip(transcript, c.start, c.end, max_chars=26):
            a, b = max(a - t0, intro_sec), b - t0
            dlg("Talk", a, b, f"{{\\an7\\pos(40,{VID_Y + 30})}}{_esc(text)}", 1)

    # 채팅: 피드(닉 없이) + 하이라이트(반응 어휘)
    kws = _load_chat_keywords()
    msgs = []
    for m in chat or []:
        if not m.get("nick") or not m.get("text", "").strip():
            continue
        if c.start - 25.0 <= m["t"] <= c.end:
            text = clean_chat(m["text"])
            score = sum(float(e.get("weight", 0.3)) for e in kws.values() if any(w in text for w in e.get("words", [])))
            msgs.append((m["t"] - t0, text, score))
    msgs.sort()
    # 하이라이트: 점수 ≥ 1.0, 3초, 겹치면 뒤로 밀기
    last_end = intro_sec
    for t, text, score in msgs:
        if score >= 1.0 and 0 <= t <= c.end - t0:
            a = max(t, last_end)
            b = min(a + 3.0, c.end - t0)
            dlg("Hi", a, b, f"{{\\an2\\pos({W // 2},{VID_Y + VID_H - 24})}}{_esc(text)}", 1)
            last_end = b
    # 피드: 메시지 등장 시각마다 상태(최근 N줄) 교체. 클립 시작 전 메시지는 0초에 이미 보임
    per_line, line_h = 16, 82
    max_lines = (FEED_Y1 - FEED_Y0) // line_h
    times = sorted({max(0.0, t) for t, _, _ in msgs})
    states = [(0.0, [m for m in msgs if m[0] <= 0.0])] + [
        (tt, [m for m in msgs if m[0] <= tt]) for tt in times if tt > 0
    ]
    for i, (tt, shown) in enumerate(states):
        nxt = states[i + 1][0] if i + 1 < len(states) else c.end - t0
        lines: list[str] = []
        for _, text, _ in shown:
            lines += _wrap_chars(text, per_line)
        lines = lines[-max_lines:]
        if not lines:
            continue
        body = "\\N".join(_esc(l) for l in lines)
        dlg("Feed", max(tt, intro_sec), nxt, f"{{\\an7\\pos(56,{FEED_Y0})}}{body}", 0)
    return ASS_HEAD + "\n".join(ev) + "\n"


# ---------- 정적 PNG (채널 띠·회차 띠·훅·하단) ----------
def build_static(c: ShortCandidate, brand: str, episode_label: str, hook: str, path: Path) -> Path:
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # 배경 전체를 어두운 색으로 (영상이 그 위에 올라감)
    d.rectangle((0, 0, W, H), fill=(16, 16, 18, 255))
    # 채널 띠
    d.rectangle((0, 0, W, 92), fill=(28, 24, 22, 255))
    sz = fit_size(BLACK, brand, W - 80, 48, floor=32)
    draw_text(d, ((W - BLACK.width(brand, sz)) / 2, (92 - sz) / 2 - 4), brand, BLACK, sz, fill=(236, 208, 120))
    # 회차 라벨 띠
    d.rectangle((0, BAR_Y, W, BAR_Y + 60), fill=(36, 30, 26, 255))
    sz = fit_size(GOTHIC, episode_label, W - 120, 34, floor=24)
    draw_text(d, (40, BAR_Y + (60 - sz) / 2 - 4), episode_label, GOTHIC, sz, fill=(230, 220, 200))
    # 고정 훅 한 줄
    sz = fit_size(GOTHIC, hook, W - 100, 60, floor=36)
    draw_text(d, (48, HOOK_Y + (80 - sz) / 2 - 6), hook, GOTHIC, sz, fill=(255, 255, 255), weight=1)
    d.line((48, HOOK_Y + 86, W - 48, HOOK_Y + 86), fill=(70, 62, 54, 255), width=2)
    # 하단 띠
    d.rectangle((0, FOOT_Y, W, H), fill=(28, 24, 22, 255))
    foot = f"{brand}  ·  {episode_label}"
    sz = fit_size(GOTHIC, foot, W - 80, 30, floor=22)
    draw_text(d, ((W - GOTHIC.width(foot, sz)) / 2, FOOT_Y + 70), foot, GOTHIC, sz, fill=(150, 140, 125))
    img.save(path)
    return path


# ---------- ffmpeg 명령 ----------
def build_cmd(
    src: Path,
    c: ShortCandidate,
    meta: dict,
    out_name: str,
    static_png: str,
    ass_file: str,
    nvenc: bool = True,
    intro_sec: float = INTRO_SEC,
) -> list[str]:
    dur = c.end - c.start
    small_w = int(VID_W * 0.6) // 2 * 2
    small_h = int(VID_H * 0.6) // 2 * 2
    fc = [
        f"[0:v]scale={VID_W}:{VID_H}:force_original_aspect_ratio=decrease,pad={VID_W}:{VID_H}:(ow-iw)/2:(oh-ih)/2,split=2[full][sm0]",
        f"[sm0]scale={small_w}:{small_h}[small]",
        "[1:v]format=rgba[bg]",
        f"[bg][full]overlay=0:{VID_Y}:enable='gte(t,{intro_sec})'[v1]",
        f"[v1][small]overlay={(W - small_w) // 2}:{VID_Y}:enable='lt(t,{intro_sec})'[v2]",
        f"[v2]subtitles={ass_file}[v]",
    ]
    cmd = ["ffmpeg", "-y", "-v", "error"]
    if nvenc:
        cmd += ["-hwaccel", "cuda"]
    cmd += [
        "-ss",
        f"{c.start:.2f}",
        "-t",
        f"{dur:.2f}",
        "-i",
        str(src.resolve()),
        "-loop",
        "1",
        "-framerate",
        "1",
        "-i",
        static_png,
        "-filter_complex",
        ";".join(fc),
        "-map",
        "[v]",
        "-map",
        "0:a?",
        "-c:v",
        "h264_nvenc" if nvenc else "libx264",
        "-preset",
        "p4" if nvenc else "veryfast",
    ]
    cmd += ["-cq", "23"] if nvenc else ["-crf", "23"]
    cmd += ["-c:a", "aac", "-b:a", "128k", "-shortest", "-movflags", "+faststart", out_name]
    return cmd
