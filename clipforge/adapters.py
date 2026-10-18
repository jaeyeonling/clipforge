"""Events(Segments) → Curve 어댑터.

이벤트 하나(시각 t, 또는 구간 [start,end])를 비대칭 창 [start-pre, end+post] 의 0~1 곡선으로 펼친다.
창 가장자리 25% 는 선형으로 줄어드는 사다리꼴. 여러 이벤트가 겹치면 max.
커널 파라미터(pre/post/labels)는 게임 프로필 `events:` 절에서 온다.
"""
from __future__ import annotations

import numpy as np

from .timeline import Curve, Segments


def events_to_curve(segs: Segments, duration: float, hop: float = 0.5, pre: float = 8.0, post: float = 6.0,
                    labels: list[str] | None = None, ramp: float = 0.25, name: str | None = None) -> Curve:
    n = int(duration / hop) + 1
    y = np.zeros(n, dtype=np.float32)
    t = np.arange(n) * hop
    used = 0
    for s in segs.items:
        if labels and s.label not in labels:
            continue
        a, b = s.start - pre, s.end + post
        w = max(b - a, hop)
        r = w * ramp
        # 사다리꼴: a..a+r 상승, a+r..b-r 평탄(1), b-r..b 하강
        v = np.clip(np.minimum((t - a) / r, (b - t) / r), 0.0, 1.0) * float(s.score if s.score else 1.0)
        y = np.maximum(y, v.astype(np.float32))
        used += 1
    return Curve(name=name or segs.name, hop=hop, values=[round(float(v), 3) for v in y],
                 meta={"adapter": "trapezoid", "pre": pre, "post": post, "labels": labels, "n_events": used})
