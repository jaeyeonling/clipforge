"""판정 층 (v0): 신호 → 하이라이트 후보 구간.

지금은 "가중합 + 임계값"이라는 가장 단순한 규칙. 나중에 정답 레이블이 쌓이면
같은 입력(Curve들)을 받아 같은 출력(Segments)을 내는 분류기로 교체한다.

규칙:
  1. 각 Curve를 z-score로 정규화해 공통 hop(0.5s)으로 리샘플
  2. 가중합 score(t) 계산
  3. score > threshold 인 구간을 잡고, 전후 pad초 확장, gap초 이내는 병합
  4. min_len 미만 버림, 상위 max_candidates개만 남김
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from .timeline import Curve, Segment, Segments

DEFAULT_WEIGHTS = {"audio_loudness": 1.0, "frame_motion": 0.0}  # 베이스라인: 음량만


def resample(curve: Curve, hop: float, n: int) -> np.ndarray:
    src_t = curve.times
    dst_t = np.arange(n) * hop
    return np.interp(dst_t, src_t, curve.as_array())


def zscore(x: np.ndarray) -> np.ndarray:
    s = x.std()
    return (x - x.mean()) / (s if s > 1e-6 else 1.0)


def make_candidates(
    curves: dict[str, Curve],
    duration: float,
    weights: dict[str, float] | None = None,
    hop: float = 0.5,
    threshold: float = 1.5,      # z-score 단위
    pad_before: float = 4.0,
    pad_after: float = 3.0,
    gap: float = 3.0,
    min_len: float = 3.0,
    max_candidates: int = 40,
) -> Segments:
    weights = weights or DEFAULT_WEIGHTS
    n = int(duration / hop) + 1
    score = np.zeros(n, dtype=np.float32)
    used = []
    for name, w in weights.items():
        if w == 0 or name not in curves:
            continue
        score += w * zscore(resample(curves[name], hop, n))
        used.append(name)

    above = score > threshold
    items: list[Segment] = []
    i = 0
    while i < n:
        if above[i]:
            j = i
            while j < n and above[j]:
                j += 1
            peak = float(score[i:j].max())
            items.append(Segment(
                start=max(0.0, i * hop - pad_before),
                end=min(duration, j * hop + pad_after),
                label="candidate",
                score=round(peak, 3),
            ))
            i = j
        else:
            i += 1

    segs = Segments("candidates", items, meta={"weights": weights, "threshold": threshold, "signals": used})
    segs = segs.merge_close(gap)
    segs.items = [s for s in segs.items if s.duration >= min_len]
    segs.items.sort(key=lambda s: -s.score)
    segs.items = segs.items[:max_candidates]
    return segs.sorted()
