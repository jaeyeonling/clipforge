"""번들 폰트 검사. 렌더 파이프라인이 쓰는 글자 집합이 (1) 폰트(+폴백)에 전부 있고 (2) 굵게 그렸을 때 잉크가 줄지 않는지.

    python scripts/check_fonts.py            # 전체 (완성형 한글 2,350자 + 숫자/기호), 실패 시 exit 1
    python scripts/check_fonts.py --quick    # 샘플 300자

(2) 는 2026-10-18 '참' 사건의 회귀 테스트: FreeType 스트로커가 특정 글리프를 속 빈 획으로 그리던 문제.
textdraw 는 스트로커를 안 쓰므로 통과해야 하고, 누군가 stroke_width 를 다시 쓰면 여기서 잡힌다.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from clipforge.textdraw import FONT_FILES, FontStack, coverage, draw_text  # noqa: E402

KS_SYLLABLES = [chr(c) for c in range(0xAC00, 0xD7A4)]       # 완성형 11,172 중 KS X 1001 2,350 은 cmap 으로 거른다
EXTRA = list("0123456789!?.,:()·★…~%+-/ ") + list("“”‘’")


def ks2350(path: str) -> list[str]:
    cov = coverage(path)
    return [ch for ch in KS_SYLLABLES if ord(ch) in cov] if cov else KS_SYLLABLES[:2350]


def ink(ch: str, stack: FontStack, size: int, weight: int) -> int:
    img = Image.new("L", (size * 2, size * 2), 0)
    draw_text(ImageDraw.Draw(img), (size // 4, size // 4), ch, stack, size, fill=255, weight=weight)
    return int((np.asarray(img) > 128).sum())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--size", type=int, default=120)
    a = ap.parse_args()
    failures = 0
    for kind in ("pen", "black", "gothic"):
        p = FONT_FILES[kind]
        if not p.exists():
            print(f"[{kind}] 없음: {p}"); failures += 1; continue
        cov = coverage(str(p))
        stack = FontStack(kind, "gothic")
        chars = ks2350(str(p)) + EXTRA
        if a.quick:
            chars = chars[::8][:300] + EXTRA
        missing = [ch for ch in EXTRA if cov and ord(ch) not in cov]
        tofu = [ch for ch in chars if cov and ord(ch) not in cov and ord(ch) not in coverage(str(FONT_FILES["gothic"]))]
        bad = []
        for ch in chars:
            if ch == " ":
                continue
            i0, i2 = ink(ch, stack, a.size, 0), ink(ch, stack, a.size, 2)
            if i0 == 0 or i2 < i0:
                bad.append((ch, i0, i2))
        print(f"[{kind}] cmap={len(cov) or '?'}  검사 {len(chars)}자  폴백으로 처리되는 기호={missing}  "
              f"폴백도 없는 글자={tofu[:10]}  굵기 단조성 위반={bad[:10]}")
        failures += len(tofu) + len(bad)
    # 가드: PIL stroke_width 재사용 금지 (textdraw 외). 스트로커가 다시 들어오면 여기서 실패한다.
    src_dir = Path(__file__).resolve().parent.parent / "clipforge"
    offenders = [f.name for f in src_dir.rglob("*.py") if f.name != "textdraw.py"
                 and any(line.lstrip().startswith(("d.text", "draw.text")) and "stroke_width" in line
                         for line in f.read_text(encoding="utf-8").splitlines())]
    if offenders:
        print(f"[guard] PIL stroke_width 사용 금지 — textdraw.draw_text 를 쓰세요: {offenders}")
        failures += len(offenders)
    print("OK" if failures == 0 else f"FAIL ({failures})")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
