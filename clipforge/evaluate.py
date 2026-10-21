"""평가 지표: 후보 vs 정답.

정답(labels) = 친구가 최종본에 실제로 남긴 구간 (labels/<video_id>.csv).

지표
  recall      : 정답 구간 중 후보와 겹치는(≥ min_overlap초) 비율  ← 1순위. 놓치면 치명적
  precision   : 후보 중 정답과 겹치는 비율                          ← 2순위
  coverage    : 후보 총 길이 / 원본 길이                             ← 사람이 검토해야 할 양(비용)
  missed      : 놓친 정답 구간 목록 (라벨별) ← 다음에 어떤 신호를 만들어야 하는지 알려주는 데이터
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from .timeline import Segment, Segments, fmt_time


@dataclass
class Report:
    recall: float
    precision: float
    coverage: float
    n_labels: int
    n_candidates: int
    missed: list[Segment] = field(default_factory=list)
    missed_by_label: Counter = field(default_factory=Counter)
    hit_by_label: Counter = field(default_factory=Counter)

    def pretty(self) -> str:
        lines = [
            f"recall     {self.recall:6.1%}   ({self.n_labels - len(self.missed)}/{self.n_labels} 정답 구간 포착)",
            f"precision  {self.precision:6.1%}   ({self.n_candidates} 후보)",
            f"coverage   {self.coverage:6.1%}   (검토해야 할 영상 비율)",
        ]
        if self.hit_by_label or self.missed_by_label:
            lines.append("라벨별 recall:")
            for lab in sorted(set(self.hit_by_label) | set(self.missed_by_label)):
                h, m = self.hit_by_label[lab], self.missed_by_label[lab]
                lines.append(f"  {lab or '(no label)':<14} {h}/{h + m}")
        if self.missed:
            lines.append("놓친 구간:")
            for s in self.missed:
                lines.append(f"  {fmt_time(s.start)}-{fmt_time(s.end)}  {s.label}  {s.meta.get('note', '')}")
        return "\n".join(lines)


def evaluate(candidates: Segments, labels: Segments, duration: float, min_overlap: float = 1.0) -> Report:
    missed, hit_c, miss_c = [], Counter(), Counter()
    for lab in labels.items:
        if any(lab.overlap(c) >= min(min_overlap, lab.duration) for c in candidates.items):
            hit_c[lab.label] += 1
        else:
            missed.append(lab)
            miss_c[lab.label] += 1
    tp_c = sum(1 for c in candidates.items if any(c.overlap(l) >= min_overlap for l in labels.items))
    n_l, n_c = len(labels.items), len(candidates.items)
    return Report(
        recall=(n_l - len(missed)) / n_l if n_l else 0.0,
        precision=tp_c / n_c if n_c else 0.0,
        coverage=candidates.total_duration() / duration if duration else 0.0,
        n_labels=n_l,
        n_candidates=n_c,
        missed=missed,
        missed_by_label=miss_c,
        hit_by_label=hit_c,
    )
