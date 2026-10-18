"""쇼츠 평가: hit@K, MRR. 정답 = labels/<id>.shorts.csv (title_item 약한 정답 + keep 회수 정답).

후보가 정답을 "맞혔다" = 후보 창과 정답 구간의 겹침 ≥ min_overlap 초, 또는 앵커가 정답 구간 안.
variant 별로 따로 계산한다 (short / story 는 서로 다른 목록이므로).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .shorts import ShortCandidate
from .timeline import Segments, fmt_time


@dataclass
class ShortsReport:
    variant: str
    n_labels: int
    hits_at: dict[int, int] = field(default_factory=dict)      # K -> 맞힌 정답 수
    first_rank: dict[str, int | None] = field(default_factory=dict)   # 정답(note) -> 처음 맞힌 순위

    def mrr(self) -> float:
        rs = [1.0 / r for r in self.first_rank.values() if r]
        return sum(rs) / len(self.first_rank) if self.first_rank else 0.0

    def pretty(self) -> str:
        lines = [f"[{self.variant}]  labels={self.n_labels}  MRR={self.mrr():.2f}"]
        for k, h in sorted(self.hits_at.items()):
            lines.append(f"  hit@{k}: {h}/{self.n_labels}")
        for note, r in self.first_rank.items():
            lines.append(f"  {note[:60]:<60} -> {'rank ' + str(r) if r else 'MISS'}")
        return "\n".join(lines)


def evaluate_shorts(cands: list[ShortCandidate], labels: Segments, ks=(1, 3, 5), min_overlap: float = 3.0) -> list[ShortsReport]:
    reports = []
    for variant in ["all"]:                       # 순간 단위 단일 랭킹 (variant 혼합)
        ranked = list(cands)
        rep = ShortsReport(variant, len([l for l in labels.items if l.label != "no"]))
        for lab in labels.items:
            if lab.label == "no":                 # 거절 라벨은 hit 계산에서 제외 (별도 표시)
                continue
            key = f"{fmt_time(lab.start)}-{fmt_time(lab.end)} {lab.label} {lab.meta.get('note', '')}"
            first = None
            for i, c in enumerate(ranked, 1):
                ov = max(0.0, min(c.end, lab.end) - max(c.start, lab.start))
                if ov >= min_overlap or lab.start <= c.anchor <= lab.end:
                    first = i; break
            rep.first_rank[key] = first
        for k in ks:
            rep.hits_at[k] = sum(1 for r in rep.first_rank.values() if r and r <= k)
        nos = [l for l in labels.items if l.label == "no"]
        if nos:
            top3 = ranked[:3]
            bad = sum(1 for l in nos if any(max(0.0, min(c.end, l.end) - max(c.start, l.start)) >= 0.5 * (l.end - l.start) for c in top3))
            rep.first_rank[f"(거절 라벨 {len(nos)}개 중 상위 3 에 남은 것)"] = bad
        reports.append(rep)
    return reports
