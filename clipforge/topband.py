"""쇼츠 상단 카드 (PNG). 두 모드.

  title : 종이 질감 배경 + 손글씨체 대형 제목 2줄 (레퍼런스: @HOTL-LEE "거상에 빠진 남친"). 득템·발화 앵커 기본.
  chat  : 어두운 배경에 확대한 채팅 피드 3~4줄 (닉네임 색 + 흰 굵은 본문) (레퍼런스: 같은 채널 채팅형). 줌·채팅 앵커 기본.
          친구는 페이스캠이 없고 방송 중 채팅을 줌인하므로 채팅 피드가 곧 리액션 화면이다.

텍스트는 전부 textdraw.py 로만 그린다 (스트로커 금지, 글자 단위 폰트 폴백). 폰트: assets/fonts (OFL) + 맑은 고딕.
출력 PNG 는 1080×height. 렌더가 [1:v] 로 받아 vstack 한다.
"""

from __future__ import annotations

import hashlib
import random
from pathlib import Path

from PIL import Image, ImageDraw

from .textdraw import FontStack, draw_text, fit_size

W = 1080
TITLE_H, CHAT_H_TOP = 400, 560  # 모드별 상단 높이
PEN = FontStack("pen", "gothic")  # 손글씨 + 폴백(가운뎃점·★ 등 손글씨체에 없는 기호)
GOTHIC = FontStack("gothic", "gothic_regular")
BLACK = FontStack("black", "gothic")


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


def title_band(lines: list[str], path: Path, height: int = TITLE_H, stack: FontStack = PEN) -> Path:
    lines = [l for l in lines if l][:2] or ["하이라이트"]
    img = paper(W, height)
    d = ImageDraw.Draw(img)
    start = int(height * (0.42 if len(lines) == 2 else 0.6))
    sizes = [fit_size(stack, l, W - 120, start, floor=48) for l in lines]
    boxes = [stack.height(l, s) for l, s in zip(lines, sizes, strict=True)]
    heights = [b - t for t, b in boxes]
    gap = int(height * 0.06)
    total = sum(heights) + gap * (len(lines) - 1)
    y = (height - total) // 2
    for l, s, (top, _), h in zip(lines, sizes, boxes, heights, strict=True):
        x = (W - stack.width(l, s)) / 2
        draw_text(d, (x, y - top), l, stack, s, fill=(20, 20, 20), weight=2)
        y += h + gap
    img.save(path)
    return path


def _nick_color(nick: str) -> tuple[int, int, int]:
    h = int(hashlib.md5(nick.encode("utf-8")).hexdigest(), 16)
    palette = [(255, 170, 120), (160, 220, 255), (190, 255, 160), (255, 150, 200), (255, 230, 120), (200, 180, 255)]
    return palette[h % len(palette)]


def _wrap(stack: FontStack, text: str, size: int, max_w: int, max_lines: int = 2) -> list[str]:
    words, lines, cur = text.split(" "), [], ""
    for w in words:
        cand = (cur + " " + w).strip()
        if stack.width(cand, size) <= max_w or not cur:
            cur = cand
        else:
            lines.append(cur)
            cur = w
        if len(lines) == max_lines:
            break
    if cur and len(lines) < max_lines:
        lines.append(cur)
    out = []
    for l in lines:  # 단어 경계 없는 긴 한국어: 글자 단위로 자른다
        while stack.width(l, size) > max_w and len(l) > 1:
            cut = len(l)
            while cut > 1 and stack.width(l[:cut], size) > max_w:
                cut -= 1
            out.append(l[:cut])
            l = l[cut:]
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
    nick_size, body_size = 44, 58
    pad_x, y = 48, 36
    blocks = [(m.get("nick", ""), _wrap(GOTHIC, m.get("text", ""), body_size, W - pad_x * 2, 2)) for m in msgs]
    line_h = 70

    def needed(b) -> int:
        return (52 if b[0] else 0) + line_h * len(b[1]) + 26

    while blocks and sum(needed(b) for b in blocks) > height - 40:
        blocks.pop(0)
    for nick, body in blocks:
        if nick:
            d.ellipse((pad_x, y + 10, pad_x + 26, y + 36), fill=_nick_color(nick))
            draw_text(d, (pad_x + 40, y), nick, GOTHIC, nick_size, fill=_nick_color(nick))
            y += 52
        for l in body:
            draw_text(d, (pad_x, y), l, GOTHIC, body_size, fill=(255, 255, 255), outline=(0, 0, 0), outline_weight=2)
            y += line_h
        y += 26
    if not blocks:
        draw_text(d, (pad_x, height // 2 - 40), "채팅 반응", BLACK, 72, fill=(255, 255, 255))
    img.save(path)
    return path
