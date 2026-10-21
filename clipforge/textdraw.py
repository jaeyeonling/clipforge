"""PIL 텍스트 렌더 공용 모듈. 모든 PNG 텍스트(상단 카드·채팅 피드)는 이 모듈로만 그린다.

왜 따로 두나 (2026-10-18 '참' 사건):
  PIL 의 stroke_width 는 FreeType 스트로커를 쓰는데, 윤곽선 방향이 특이한 글리프(나눔손글씨 펜의 '참' 등)를
  속 빈 획으로 그린다. 또 PIL 은 폰트에 없는 글자를 □(tofu)로 찍고 폴백이 없다.
해결:
  - 굵기/테두리 = 글자를 작은 오프셋으로 여러 번 찍는 스탬핑 (윤곽선 방향 무관, 잉크가 단조 증가)
  - 글자 단위 폰트 폴백: FontStack 이 각 글자를 cmap 에 있는 첫 폰트로 배정
  - scripts/check_fonts.py 가 번들 폰트의 커버리지와 스탬핑 단조성을 검사
"""

from __future__ import annotations

from functools import cache
from pathlib import Path

from PIL import ImageDraw, ImageFont

from .paths import APP_ROOT

FONT_FILES = {
    "pen": APP_ROOT / "assets" / "fonts" / "NanumPenScript-Regular.ttf",
    "black": APP_ROOT / "assets" / "fonts" / "BlackHanSans-Regular.ttf",
    "gothic": Path("C:/Windows/Fonts/malgunbd.ttf"),
    "gothic_regular": Path("C:/Windows/Fonts/malgun.ttf"),
}


@cache
def coverage(path: str) -> frozenset[int]:
    """폰트의 cmap 코드포인트 집합. fontTools 가 없으면 빈 집합(= 전부 있다고 가정)."""
    try:
        from fontTools.ttLib import TTFont

        t = TTFont(path, lazy=True)
        return frozenset(t.getBestCmap().keys())
    except Exception:
        return frozenset()


@cache
def _load(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size)


class FontStack:
    """primary 폰트 + 폴백 폰트들. 글자마다 cmap 에 있는 첫 폰트를 쓴다."""

    def __init__(self, *kinds: str):
        self.paths = [str(FONT_FILES[k]) for k in kinds if FONT_FILES[k].exists()]
        if not self.paths:
            raise FileNotFoundError(f"폰트 없음: {kinds}")

    def font_for(self, ch: str, size: int) -> ImageFont.FreeTypeFont:
        cp = ord(ch)
        for p in self.paths:
            cov = coverage(p)
            if not cov or cp in cov:
                return _load(p, size)
        return _load(self.paths[-1], size)

    def runs(self, text: str, size: int) -> list[tuple[ImageFont.FreeTypeFont, str]]:
        out: list[tuple[ImageFont.FreeTypeFont, str]] = []
        for ch in text:
            f = self.font_for(ch, size)
            if out and out[-1][0] is f:
                out[-1] = (f, out[-1][1] + ch)
            else:
                out.append((f, ch))
        return out

    def width(self, text: str, size: int) -> float:
        return sum(f.getlength(s) for f, s in self.runs(text, size))

    def height(self, text: str, size: int) -> tuple[int, int]:
        """(top, bottom) bbox y 범위 — 줄 높이 계산용."""
        tops, bots = [], []
        for f, s in self.runs(text, size):
            b = f.getbbox(s)
            tops.append(b[1])
            bots.append(b[3])
        return (min(tops) if tops else 0, max(bots) if bots else size)


def _offsets(r: int) -> list[tuple[int, int]]:
    return [(dx, dy) for dx in range(-r, r + 1) for dy in range(-r, r + 1) if dx * dx + dy * dy <= r * r + 1]


def draw_text(
    draw: ImageDraw.ImageDraw,
    xy: tuple[float, float],
    text: str,
    stack: FontStack,
    size: int,
    fill=(0, 0, 0),
    weight: int = 0,
    outline=None,
    outline_weight: int = 0,
) -> float:
    """text 를 (x, y) 에서 시작해 그린다. weight = 가짜 볼드 반경(px), outline = 테두리 색(스탬핑 반경 weight+outline_weight).
    stroke_width 는 절대 쓰지 않는다. 반환: 그린 폭."""
    x, y = xy
    runs = stack.runs(text, size)
    if outline is not None and outline_weight > 0:
        cx = x
        for f, s in runs:
            for dx, dy in _offsets(weight + outline_weight):
                draw.text((cx + dx, y + dy), s, font=f, fill=outline)
            cx += f.getlength(s)
    cx = x
    for f, s in runs:
        for dx, dy in _offsets(weight) if weight > 0 else [(0, 0)]:
            draw.text((cx + dx, y + dy), s, font=f, fill=fill)
        cx += f.getlength(s)
    return cx - x


def fit_size(stack: FontStack, text: str, max_w: int, start: int, floor: int = 40, step: int = 6) -> int:
    size = start
    while size > floor and stack.width(text, size) > max_w:
        size -= step
    return max(size, floor)
