"""제안 레이아웃 목업 (정지 프레임 1장). 실제 ep59 프레임·채팅·배너 상태로 그린다.

    python scripts/mock_layout.py --frame 195 --out review/ep59/_mock.png

렌더 파이프라인과 무관한 디자인 검토용. 확정되면 layout_*.py 로 옮긴다.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from clipforge.textdraw import FontStack, draw_text, fit_size  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
W, H = 1080, 1920
YELLOW = (240, 246, 96)      # 브랜드 노랑 (ep59 인트로 타이틀 실측)
RED = (230, 60, 50)
BG = (14, 13, 12)
PANEL = (26, 24, 22)
INK = (245, 242, 232)
MUTED = (150, 142, 128)
BLACK = FontStack("black", "gothic")
GOTHIC = FontStack("gothic", "gothic_regular")
PEN = FontStack("pen", "gothic")


def chip(d, xy, text, stack, size, fill, bg, pad=(26, 12), radius=18, weight=0, outline=None):
    x, y = xy
    w = stack.width(text, size) + pad[0] * 2
    h = size + pad[1] * 2
    d.rounded_rectangle((x, y, x + w, y + h), radius=radius, fill=bg)
    draw_text(d, (x + pad[0], y + pad[1] - size * 0.12), text, stack, size, fill=fill, weight=weight,
              outline=outline, outline_weight=2 if outline else 0)
    return w, h


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--vid", default="ep59")
    ap.add_argument("--frame", type=int, default=195)
    ap.add_argument("--out", default="review/ep59/_mock.png")
    a = ap.parse_args()
    cache = ROOT / "cache" / a.vid
    frame = Image.open(cache / "frames" / f"{a.frame:06d}.jpg").convert("RGB")
    chat = json.loads((cache / "chat_text.json").read_text(encoding="utf-8"))["items"]
    banner = json.loads((cache / "item_banner.json").read_text(encoding="utf-8"))["items"]
    t = float(a.frame)

    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    # ── 0. 상단: 브랜드 칩(좌) + DAY 카운터 칩(우)  (0~100)
    chip(d, (40, 26), "채널명", BLACK, 40, YELLOW, PANEL, outline=(0, 0, 0))
    wday = BLACK.width("DAY 59 · 노거래 맨땅", 40) + 52
    chip(d, (W - 40 - wday, 26), "DAY 59 · 노거래 맨땅", BLACK, 40, INK, PANEL)

    # ── 1. 영상 16:9 전체 (110~718) + 얇은 노란 밑줄(채널 악센트)
    vid = frame.resize((1080, 608))
    img.paste(vid, (0, 110))
    d.rectangle((0, 718, W, 724), fill=YELLOW)
    # 발화 자막: 영상 하단 중앙, 흰 글자 + 검은 테두리, 상자 없음 (방송 자막 관례)
    sub = "와, 뭐야!"
    sz = 54
    draw_text(d, ((W - GOTHIC.width(sub, sz)) / 2, 718 - 54 - 28), sub, GOTHIC, sz, fill=(255, 255, 255),
              outline=(0, 0, 0), outline_weight=3)
    # 시청자 반응 하이라이트: 영상 우상단 노란 말풍선 칩 (마골의 '화면 하단 큰 줄' 과 다른 자리)
    hi = "“헐 지참 나왔어요??”"
    szh = 44
    wh = GOTHIC.width(hi, szh) + 52
    chip(d, (W - 40 - wh, 110 + 24), hi, GOTHIC, szh, (20, 18, 10), YELLOW, pad=(26, 12), radius=22, weight=1)

    # ── 2. 득템 로그 패널(좌 62%) + 가치 메모(우 38%)  (750~1010)  ← 채널 고유 모티프
    px, py, pw, ph = 40, 750, 640, 260
    d.rounded_rectangle((px, py, px + pw, py + ph), radius=22, fill=PANEL)
    draw_text(d, (px + 28, py + 18), "오늘 득템", GOTHIC, 32, fill=MUTED)
    # 현재 시점까지의 배너 토큰 (append 이벤트) — 마지막 것 강조
    toks = []
    for s in banner:
        if s["label"] == "append" and s["start"] <= t:
            for tok in s["meta"].get("added", "").split(","):
                tok = tok.strip().lstrip("템엄,")
                if len(tok) >= 2 and tok not in toks:
                    toks.append(tok)
    toks = toks[-6:] or ["화염5/3주얼", "슬가", "3맥20어레20피"]
    yy = py + 66
    for i, tok in enumerate(toks):
        last = i == len(toks) - 1
        if last:
            d.rounded_rectangle((px + 20, yy - 6, px + pw - 20, yy + 44), radius=12, fill=(48, 44, 24))
            draw_text(d, (px + 32, yy), "★ " + tok, GOTHIC, 36, fill=YELLOW, weight=1)
        else:
            draw_text(d, (px + 32, yy), "· " + tok, GOTHIC, 32, fill=INK)
        yy += 48 if not last else 56
    # 가치 메모 (메모장 모티프: 미색 카드 + 손글씨)
    mx, my, mw, mh = px + pw + 24, 750, W - 40 - (px + pw + 24), 260
    d.rounded_rectangle((mx, my, mx + mw, my + mh), radius=22, fill=(244, 240, 226))
    d.rectangle((mx, my, mx + mw, my + 34), fill=(226, 214, 180))
    draw_text(d, (mx + 24, my + 2), "메모", GOTHIC, 26, fill=(110, 96, 60))
    draw_text(d, (mx + 24, my + 56), "지존참", PEN, 64, fill=(30, 28, 24), weight=2)
    draw_text(d, (mx + 24, my + 132), "현금 7만원↑", PEN, 60, fill=RED, weight=2)
    draw_text(d, (mx + 24, my + 200), "3맥 20어레 20피", GOTHIC, 28, fill=(110, 96, 60))

    # ── 3. 시청자 반응 피드 (1040~1580): 닉 없이, 3~5줄, 최신이 아래. 글자 56
    fy = 1040
    draw_text(d, (40, fy), "시청자 반응", GOTHIC, 32, fill=MUTED)
    msgs = [s["meta"]["text"] for s in chat if s["meta"].get("nick") and t - 20 <= s["start"] <= t][-5:]
    yy = fy + 56
    for m in msgs:
        line = m if len(m) <= 20 else m[:20] + "…"
        draw_text(d, (40, yy), line, GOTHIC, 54, fill=INK)
        yy += 86
    # ── 4. 하단 (1640~): 회차·해시태그 작은 글씨 (쇼츠 UI 안전영역이라 중요 정보 금지)
    draw_text(d, (40, 1660), "래더 12기 59일차 · 지존참 직득  #디아블로2 #레저렉션 #채널명", GOTHIC, 28, fill=MUTED)
    img.save(a.out)
    print("saved", a.out)


if __name__ == "__main__":
    main()
