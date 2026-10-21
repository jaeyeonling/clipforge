"""신호: 컷 밀도 (Phase 1 편집본용).

prep 이 scdet 로 뽑은 cuts.json(장면 전환 시각) 을 읽어, 각 초를 중심으로 ±window/2 안의 컷 개수를 센다.
편집자가 잘게 자른 구간 = 긴장·리액션 구간이라는 가설. 원본 녹화에는 컷이 없으므로 전부 0 → 가중치 0 으로 두면 무해.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from ..timeline import Curve
from .base import signal


@signal("cut_density")
def cut_density(cache: Path, window: float = 30.0, hop: float = 1.0) -> Curve:
    meta = json.loads((cache / "meta.json").read_text(encoding="utf-8"))
    cuts_p = cache / "cuts.json"
    cuts = np.asarray(json.loads(cuts_p.read_text(encoding="utf-8")) if cuts_p.exists() else [], dtype=np.float32)
    n = int(meta["duration"] / hop) + 1
    t = np.arange(n) * hop
    if len(cuts):
        lo = np.searchsorted(cuts, t - window / 2)
        hi = np.searchsorted(cuts, t + window / 2)
        vals = (hi - lo).astype(np.float32)
    else:
        vals = np.zeros(n, dtype=np.float32)
    return Curve(
        name="cut_density",
        hop=hop,
        values=[float(v) for v in vals],
        meta={"unit": f"cuts per {window:.0f}s window", "n_cuts": len(cuts)},
    )
