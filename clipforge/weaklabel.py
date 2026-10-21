"""약한 정답: 영상 제목 → 아이템 키워드 → 득템 배너 추가 시각.

스트리머 채널 제목은 그 회차의 핵심 득템을 명시한다("... 지존참 직득했습니다"). 제목의 키워드를
data/<game>/slang.yaml 의 표제어·별칭으로 찾고, item_banner 의 append 토큰과 퍼지 매칭해
그 시각 주변을 label="title_item" 구간으로 labels/<id>.shorts.csv 에 쓴다. 쇼츠 1순위의 자동 정답.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

import yaml
from rapidfuzz import fuzz

from .timeline import Segments

ROOT = Path(__file__).resolve().parent.parent
NORM = re.compile(r"[\s,.'\"`★()\[\]【】!?/~:·-]")


def norm(s: str) -> str:
    return NORM.sub("", s)


def load_slang(game: str) -> dict:
    p = ROOT / "data" / game / "slang.yaml"
    return yaml.safe_load(p.read_text(encoding="utf-8")) if p.exists() else {}


def load_episode(vid: str, csv_path: Path | None = None) -> dict | None:
    p = Path(csv_path) if csv_path else ROOT / "episodes.csv"
    if not p.exists():
        return None
    with open(p, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            if row.get("id") == vid:
                return row
    return None


def title_keywords(title: str, slang: dict) -> list[tuple[str, list[str]]]:
    """제목에 등장하는 표제어/별칭 → (표제어, 모든 별칭)."""
    t = norm(title)
    hits = []
    for head, ent in slang.items():
        names = [head, *list(ent.get("aliases") or [])]
        if any(norm(n) and norm(n) in t for n in names if len(norm(n)) >= 2):
            hits.append((head, names))
    return hits


def match_banner(keywords: list[tuple[str, list[str]]], banner: Segments, threshold: int = 85) -> list[dict]:
    out = []
    for head, names in keywords:
        best = None
        for s in banner.items:
            if s.label != "append":
                continue
            added = norm(s.meta.get("added", ""))
            if not added:
                continue
            score = max(fuzz.partial_ratio(norm(n), added) for n in names if len(norm(n)) >= 2)
            if score >= threshold and (best is None or score > best[0]):
                best = (score, s)
        if best:
            out.append({"keyword": head, "t": best[1].start, "score": best[0], "added": best[1].meta.get("added", "")})
    return out


def write_weak_labels(
    vid: str,
    matches: list[dict],
    labels_dir: Path,
    pre: float = 30.0,
    post: float = 30.0,
    duration: float | None = None,
) -> Path:
    p = labels_dir / f"{vid}.shorts.csv"
    rows = []
    if p.exists():
        with open(p, encoding="utf-8", newline="") as f:
            rows = [r for r in csv.DictReader(f) if r.get("label") != "title_item"]  # 기존 약한 정답은 교체
    for m in matches:
        s, e = max(0.0, m["t"] - pre), m["t"] + post
        if duration:
            e = min(duration, e)
        rows.append(
            {
                "start": f"{s:.1f}",
                "end": f"{e:.1f}",
                "label": "title_item",
                "note": f"title={m['keyword']} banner@{m['t']:.0f}s fuzz={m['score']} added={m['added'][:30]}",
            }
        )
    with open(p, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["start", "end", "label", "note"])
        w.writeheader()
        w.writerows(rows)
    return p


def short_episode_label(title: str) -> str:
    """제목 → 회차 라벨. "(N시간 편집본) 래더 12기 59일차만에 … 【…】" → "래더 12기 59일차". 못 찾으면 앞 28자."""
    import re as _re

    t = _re.sub(r"^\s*\([^)]*\)\s*", "", title or "")
    m = _re.search(r"(래더\s*\d+기[^0-9]*?\d+\s*(?:~\s*\d+\s*)?일차)", t)
    if m:
        return _re.sub(r"\s+", " ", m.group(1)).strip()
    t = t.split("【")[0].strip(" !")
    return (t[:28] + "…") if len(t) > 28 else t
