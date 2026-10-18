"""쇼츠 상단 카드 (PNG). 두 모드.

  title : 종이 질감 배경 + 손글씨체 대형 제목 2줄 (레퍼런스: @HOTL-LEE "거상에 빠진 남친"). 득템·발화 앵커 기본.
  chat  : 어두운 배경에 확대한 채팅 피드 3~4줄 (닉네임 색 + 흰 굵은 본문) (레퍼런스: 같은 채널 채팅형). 줌·채팅 앵커 기본.
          친구는 페이스캠이 없고 방송 중 채팅을 줌인하므로 채팅 피드가 곧 리액션 화면이다.

폰트: assets/fonts (OFL) — NanumPenScript(손글씨), BlackHanSans(굵은 제목). 본문은 맑은 고딕 Bold.
출력 PNG 는 1080×height. 렌더가 [1:v] 로 받아 vstack 한다.
"""
from __future__ import annotations

import hashlib
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
FONTS = {
    "pen": ROOT / "assets" / "fonts" / "NanumPenScript-Regular.ttf",
    "black": ROOT / "assets" / "fonts" / "BlackHanSans-Regular.ttf",
    "gothic": Path("C:/Windows/Fonts/malgunbd.ttf"),
}
W = 1080
TITLE_H, CHAT_H_TOP = 400, 560          # 모드별 상단 높이


def _font(kind: str, size: int) -> ImageFont.FreeTypeFont:
    p = FONTS.get(kind)
    if p and p.exists():
        return ImageFont.truetype(str(p), size)
    return ImageFont.truetype(str(FONTS["gothic"]), size)


def _fit(draw: ImageDraw.ImageDraw, text: str, kind: str, max_w: int, start: int, floor: int = 48) -> ImageFont.FreeTypeFont:
    size = start
    while size > floor:
        f = _font(kind, size)
        if draw.textlength(text, font=f) <= max_w:
            return f
        size -= 6
    return _font(kind, floor)


def paper(w: int, h: int, seed: int = 7) -> Image.Image:
    """연한 종이 질감: 미색 바탕 + 작은 색 점."""
    img = Image.new("RGB", (w, h), (246, 243, 236))
    d = ImageDraw.Draw(img)
    rnd = random.Random(seed)
    for _ in range(int(w * h / 2600)):
        x, y = rnd.randrange(w), rnd.randrange(h)
        r = rnd.choice([1, 1, 1, 2, 2, 3])
        c = rnd.choice([(60, 60, 60), (40, 70, 160), (190, 60, 50), (120, 120, 110), (200, 170, 60)])
        d.ellipse((x, y, x + r, y + r), fill=c)
    return img


def title_band(lines: list[str], path: Path, height: int = TITLE_H, font_kind: str = "pen") -> Path:
    lines = [l.replace(" · ", ", ") for l in lines if l][:2] or ["하이라이트"]   # 손글씨체에 가운뎃점 글리프 없음
    img = paper(W, height)
    d = ImageDraw.Draw(img)
    # 두 줄이면 각 줄 높이 = height/2.3, 한 줄이면 더 크게
    start = int(height * (0.42 if len(lines) == 2 else 0.6))
    fonts = [_fit(d, l, font_kind, W - 120, start) for l in lines]
    heights = [f.getbbox(l)[3] - f.getbbox(l)[1] for f, l in zip(fonts, lines)]
    gap = int(height * 0.06)
    total = sum(heights) + gap * (len(lines) - 1)
    y = (height - total) // 2
    for f, l, h in zip(fonts, lines, heights):
        tw = d.textlength(l, font=f)
        x = (W - tw) / 2
        bbox = f.getbbox(l)
        d.text((x, y - bbox[1]), l, font=f, fill=(20, 20, 20), stroke_width=3, stroke_fill=(20, 20, 20))
        y += h + gap
    img.save(path)
    return path


def _nick_color(nick: str) -> tuple[int, int, int]:
    h = int(hashlib.md5(nick.encode("utf-8")).hexdigest(), 16)
    palette = [(255, 170, 120), (160, 220, 255), (190, 255, 160), (255, 150, 200), (255, 230, 120), (200, 180, 255)]
    return palette[h % len(palette)]


def _wrap(draw, text: str, font, max_w: int, max_lines: int = 2) -> list[str]:
    words, lines, cur = text.split(" "), [], ""
    for w in words:
        cand = (cur + " " + w).strip()
        if draw.textlength(cand, font=font) <= max_w or not cur:
            cur = cand
        else:
            lines.append(cur); cur = w
        if len(lines) == max_lines:
            break
    if cur and len(lines) < max_lines:
        lines.append(cur)
    # 단어 경계가 없는 긴 한국어 문자열: 글자 단위 자르기
    out = []
    for l in lines:
        while draw.textlength(l, font=font) > max_w and len(l) > 1:
            cut = len(l)
            while cut > 1 and draw.textlength(l[:cut], font=font) > max_w:
                cut -= 1
            out.append(l[:cut]); l = l[cut:]
            if len(out) == max_lines:
                break
        if l and len(out) < max_lines:
            out.append(l)
    return out[:max_lines]


def chat_band(messages: list[dict], path: Path, height: int = CHAT_H_TOP, max_msgs: int = 4) -> Path:
    """messages: [{nick, text}] 시간순. 아래가 최신. 레퍼런스처럼 닉 줄 + 본문 줄."""
    msgs = messages[-max_msgs:]
    img = Image.new("RGB", (W, height), (14, 14, 16))
    d = ImageDraw.Draw(img)
    nick_f, body_f = _font("gothic", 44), _font("gothic", 58)
    pad_x, y = 48, 36
    blocks = []
    for m in msgs:
        body = _wrap(d, m.get("text", ""), body_f, W - pad_x * 2, 2)
        blocks.append((m.get("nick", ""), body))
    # 높이에 맞게 뒤에서부터 채운다
    line_h = 70
    needed = lambda b: (52 if b[0] else 0) + line_h * len(b[1]) + 26
    while blocks and sum(needed(b) for b in blocks) > height - 40:
        blocks.pop(0)
    for nick, body in blocks:
        if nick:
            d.ellipse((pad_x, y + 10, pad_x + 26, y + 36), fill=_nick_color(nick))
            d.text((pad_x + 40, y), nick, font=nick_f, fill=_nick_color(nick))
            y += 52
        for l in body:
            d.text((pad_x, y), l, font=body_f, fill=(255, 255, 255), stroke_width=2, stroke_fill=(0, 0, 0))
            y += line_h
        y += 26
    if not blocks:
        f = _font("black", 72)
        d.text((pad_x, height // 2 - 40), "채팅 반응", font=f, fill=(255, 255, 255))
    img.save(path)
    return path
