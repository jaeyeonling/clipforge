"""신호: 프레임 변화량 (1fps frames/ 기반).

연속 프레임 간 평균 절대 차이. 값이 낮게 오래 유지되면 "아무 일도 안 일어나는 구간"(마을 대기, 창고 정리)일 가능성이 높다.
frames/ 는 최대 1080p 라 메모리에서 160x90 으로 축소해 비교한다. 장면 전환(PySceneDetect)으로 교체 가능한 자리.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image

from ..timeline import Curve
from .base import signal


@signal("frame_motion")
def frame_motion(cache: Path) -> Curve:
    meta = json.loads((cache / "meta.json").read_text(encoding="utf-8"))
    hop = 1.0 / float(meta.get("frames", {}).get("fps", 1.0))
    frames = sorted((cache / "frames").glob("*.jpg"))
    prev = None
    vals: list[float] = []
    for p in frames:
        img = Image.open(p)
        img.draft("L", (320, 180))  # JPEG 디코더 단계에서 축소 → 수 배 빠름
        a = np.asarray(img.convert("L").resize((160, 90)), dtype=np.float32)
        vals.append(0.0 if prev is None else float(np.mean(np.abs(a - prev))))
        prev = a
    return Curve(
        name="frame_motion",
        hop=hop,
        values=[round(v, 2) for v in vals],
        meta={"unit": "mean abs diff 0-255", "n_frames": len(frames)},
    )
