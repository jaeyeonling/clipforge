"""신호: 프레임 변화량 (1fps 썸네일 기반).

연속 썸네일 간 평균 절대 차이. 값이 낮게 오래 유지되면 "아무 일도 안 일어나는 구간"(마을 대기, 창고 정리)일 가능성이 높다.
numpy + Pillow만 사용. 장면 전환(PySceneDetect)으로 교체 가능한 자리.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from ..timeline import Curve
from .base import signal


@signal("frame_motion")
def frame_motion(cache: Path) -> Curve:
    thumbs = sorted((cache / "thumbs").glob("*.jpg"))
    prev = None
    vals: list[float] = []
    for p in thumbs:
        img = np.asarray(Image.open(p).convert("L").resize((160, 90)), dtype=np.float32)
        vals.append(0.0 if prev is None else float(np.mean(np.abs(img - prev))))
        prev = img
    return Curve(name="frame_motion", hop=1.0, values=[round(v, 2) for v in vals], meta={"unit": "mean abs diff 0-255"})
