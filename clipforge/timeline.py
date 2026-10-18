"""공통 시간축 데이터 모델.

모든 신호(음량, 전사, OCR 이벤트, 장면 전환, 사람의 채택/거부, 최종 컷)는
이 두 가지 중 하나로 표현된다.

- Curve   : 일정 주기(hop)로 샘플링된 1차원 시계열. 예) 음량 곡선, 프레임 차분량
- Segments: (start, end, label, score, meta) 구간 리스트. 예) 하이라이트 후보, 정답 컷, OCR 이벤트

둘 다 JSON으로 직렬화되며, 파일명 규칙은 `<video_id>/<signal_name>.json`.
신호를 추가할 때는 이 포맷으로만 내놓으면 평가/후보 생성이 그대로 동작한다.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Iterable

import numpy as np


@dataclass
class Curve:
    name: str
    hop: float                       # 샘플 간격(초)
    values: list[float]
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def times(self) -> np.ndarray:
        return np.arange(len(self.values)) * self.hop

    def as_array(self) -> np.ndarray:
        return np.asarray(self.values, dtype=np.float32)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self)), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "Curve":
        return cls(**json.loads(path.read_text(encoding="utf-8")))


@dataclass
class Segment:
    start: float
    end: float
    label: str = ""                  # 예) "candidate", "keep", "rune_drop", "reaction"
    score: float = 1.0               # 신뢰도/강도. 정답 레이블은 1.0
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)

    def overlap(self, other: "Segment") -> float:
        return max(0.0, min(self.end, other.end) - max(self.start, other.start))


@dataclass
class Segments:
    name: str
    items: list[Segment]
    meta: dict[str, Any] = field(default_factory=dict)

    def total_duration(self) -> float:
        return sum(s.duration for s in self.items)

    def sorted(self) -> "Segments":
        return Segments(self.name, sorted(self.items, key=lambda s: s.start), self.meta)

    def merge_close(self, gap: float) -> "Segments":
        """gap초 이내로 붙은 구간을 하나로 합친다 (score는 max)."""
        out: list[Segment] = []
        for s in self.sorted().items:
            if out and s.start - out[-1].end <= gap:
                last = out[-1]
                last.end = max(last.end, s.end)
                last.score = max(last.score, s.score)
            else:
                out.append(Segment(**asdict(s)))
        return Segments(self.name, out, self.meta)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=1), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "Segments":
        d = json.loads(path.read_text(encoding="utf-8"))
        return cls(d["name"], [Segment(**s) for s in d["items"]], d.get("meta", {}))

    @classmethod
    def from_csv(cls, path: Path, name: str = "labels") -> "Segments":
        """labels CSV: start,end,label[,note]  (start/end는 초 또는 mm:ss / hh:mm:ss)"""
        import csv
        items = []
        with open(path, encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                if not row.get("start"):
                    continue
                items.append(Segment(
                    start=parse_time(row["start"]),
                    end=parse_time(row["end"]),
                    label=row.get("label", "").strip(),
                    meta={"note": row.get("note", "")},
                ))
        return cls(name, items)


def parse_time(s: str) -> float:
    s = s.strip()
    parts = s.split(":")
    if len(parts) == 1:
        return float(s)
    parts = [float(p) for p in parts]
    sec = 0.0
    for p in parts:
        sec = sec * 60 + p
    return sec


def fmt_time(t: float) -> str:
    t = max(0.0, t)
    h, r = divmod(int(t), 3600)
    m, s = divmod(r, 60)
    return f"{h:d}:{m:02d}:{s:02d}" if h else f"{m:d}:{s:02d}"
