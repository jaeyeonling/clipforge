"""item_banner 신호 프로토타입.

입력: 1fps 배너 크롭 폴더 (0001.jpg = t=0s ...)
방법: 3초 간격으로 OCR → 텍스트가 바뀐 구간만 1초 단위로 다시 OCR → "추가된 토큰"과 시각을 이벤트로.
출력: JSON 이벤트 리스트 + 콘솔 요약.
"""

import itertools
import json
import re
import sys
import time
from pathlib import Path

from rapidocr import LangRec, ModelType, OCRVersion, RapidOCR

src = Path(sys.argv[1])
out = Path(sys.argv[2])
step = int(sys.argv[3]) if len(sys.argv) > 3 else 3
files = sorted(src.glob("*.jpg"))
n = len(files)
eng = RapidOCR(
    params={
        "Rec.lang_type": LangRec.KOREAN,
        "Rec.model_type": ModelType.MOBILE,
        "Rec.ocr_version": OCRVersion.PPOCRV5,
        "Global.log_level": "error",
    }
)

cache: dict[int, str] = {}
IGNORE = {"준영"}  # 배너 왼쪽 끝 용병 초상화 아래의 용병 이름 (엔진은 이름 대신 위치로 거른다: banner_skip_left)


def ocr(i: int) -> str:
    """i초 프레임의 배너 본문 텍스트(줄 합침, 공백/따옴표 제거)."""
    if i in cache:
        return cache[i]
    r = eng(str(files[i]))
    txts = [t for t in (r.txts or []) if t not in IGNORE]
    s = re.sub(r"[\s'\"`]", "", ",".join(txts))
    cache[i] = s
    return s


def tokens(s: str) -> list[str]:
    return [t for t in re.split(r"[,:]", s) if t]


t0 = time.time()
coarse = list(range(0, n, step))
for k, i in enumerate(coarse):
    ocr(i)
    if k % 20 == 0:
        print(f"  coarse {k}/{len(coarse)}  {time.time() - t0:.0f}s", flush=True)

# 바뀐 구간을 1초 단위로 정밀화
events = []
for a, b in itertools.pairwise(coarse):
    if ocr(a) == ocr(b):
        continue
    for i in range(a, b):
        if ocr(i) != ocr(i + 1):
            before, after = tokens(ocr(i)), tokens(ocr(i + 1))
            added = [t for t in after if t not in before]
            removed = [t for t in before if t not in after]
            events.append(
                {
                    "t": i + 1,
                    "len_delta": len(ocr(i + 1)) - len(ocr(i)),
                    "added": added,
                    "removed": removed,
                    "after": ocr(i + 1),
                }
            )

print(f"OCR calls: {len(cache)}  elapsed {time.time() - t0:.0f}s")
print("--- banner change events ---")
for e in events:
    m, s = divmod(e["t"], 60)
    kind = "APPEND" if e["len_delta"] > 5 and e["added"] else ("SWAP" if e["added"] else "noise")
    print(f"{m}:{s:02d}  {kind:6s} Δ{e['len_delta']:+4d}  +{e['added']}  -{e['removed']}")
out.write_text(
    json.dumps({"events": events, "ocr": {str(k): v for k, v in sorted(cache.items())}}, ensure_ascii=False, indent=1),
    encoding="utf-8",
)
print("saved", out)
