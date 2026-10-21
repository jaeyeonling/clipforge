"""도메인 사전 조회 (D2R): OCR 토큰 → 아이템.

두 사전을 합쳐 쓴다.
  data/<game>/items.json  : d2data 조인 공식 사전 (영/한 이름, 종류, 레벨). scripts/build_items.py 가 생성
  data/<game>/slang.yaml  : 커뮤니티·친구 약어 → 표제어 (사람이 관리)
조회 순서: slang 별칭 정확/부분 일치 → items name_ko/aliases 정확 일치 → rapidfuzz partial_ratio ≥ threshold.
매칭 실패 토큰은 unknown 으로 모아 reports/<id>_unknown_tokens.md 와 친구 질문지에 쓴다.
지표: 배너 append 토큰 중 매칭률 (docs/ARCHITECTURE.md 9.4).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

import yaml
from rapidfuzz import fuzz, process

ROOT = Path(__file__).resolve().parent.parent
STRIP = re.compile(r"[\s'\"`★()\[\]【】!?~:·\-]")
PAREN = re.compile(r"\([^)]*\)")  # "기드참(매찬34)" → 괄호 안은 옵션
HEADER = re.compile(r"^(득템|득렘|득램|특템|특램|템|렘|엄|츠)+")


def norm(s: str) -> str:
    return STRIP.sub("", s)


@dataclass
class Match:
    token: str
    head: str | None  # 표제어 (slang) 또는 items name_ko
    kind: str | None
    source: str  # slang | items | fuzzy-slang | fuzzy-items | none
    score: float
    option: str = ""  # 괄호 안 옵션 텍스트


class Lexicon:
    def __init__(self, game: str = "d2r"):
        d = ROOT / "data" / game
        self.items = (
            json.loads((d / "items.json").read_text(encoding="utf-8"))["items"] if (d / "items.json").exists() else []
        )
        self.slang = (
            yaml.safe_load((d / "slang.yaml").read_text(encoding="utf-8")) if (d / "slang.yaml").exists() else {}
        )
        # 조회 테이블: 정규화 이름 → (표제어, kind, source)
        self.exact: dict[str, tuple[str, str, str]] = {}
        for head, ent in self.slang.items():
            for n in [head, *list(ent.get("aliases") or [])]:
                if norm(n):
                    self.exact.setdefault(norm(n), (head, ent.get("kind", "?"), "slang"))
        for it in self.items:
            for n in [it.get("name_ko"), *list(it.get("aliases") or [])]:
                if n and norm(n):
                    self.exact.setdefault(norm(n), (it["name_ko"], it["kind"], "items"))
        self.keys = list(self.exact)

    def lookup(self, token: str, threshold: int = 88) -> Match:
        raw = token
        opt = " ".join(PAREN.findall(token))
        t = norm(PAREN.sub("", token))
        t = HEADER.sub("", t) if len(t) > 3 else t
        if not t:
            return Match(raw, None, None, "none", 0.0, opt)
        if t in self.exact:
            h, k, src = self.exact[t]
            return Match(raw, h, k, src, 100.0, opt)
        # 부분 일치: 토큰이 사전 이름을 포함하거나 그 반대 (길이 ≥ 2)
        for key, (h, k, src) in self.exact.items():
            if len(key) >= 2 and (key in t or (len(t) >= 2 and t in key and len(t) / len(key) >= 0.6)):
                return Match(raw, h, k, src, 95.0, opt)
        best = process.extractOne(t, self.keys, scorer=fuzz.ratio)
        if best and best[1] >= threshold:
            h, k, src = self.exact[best[0]]
            return Match(raw, h, k, "fuzzy-" + src, float(best[1]), opt)
        return Match(raw, None, None, "none", float(best[1]) if best else 0.0, opt)


def banner_tokens(banner_items: list) -> list[tuple[float, str]]:
    """item_banner append 이벤트의 added 텍스트를 쉼표로 쪼갠 (시각, 토큰) 목록."""
    out = []
    for s in banner_items:
        if s.label != "append":
            continue
        for tok in s.meta.get("added", "").split(","):
            tok = tok.strip()
            if len(norm(PAREN.sub("", tok))) >= 2:
                out.append((s.start, tok))
    return out


def report_md(vid: str, matches: list[tuple[float, Match]]) -> str:
    from .timeline import fmt_time

    n = len(matches)
    ok = sum(1 for _, m in matches if m.head)
    lines = [
        f"# {vid} 배너 토큰 사전 매칭",
        "",
        f"매칭률: **{ok}/{n}** ({ok / n:.0%})" if n else "토큰 없음",
        "",
        "| 시각 | 토큰 | 표제어 | 종류 | 소스 | 점수 | 옵션 |",
        "|---|---|---|---|---|---|---|",
    ]
    for t, m in matches:
        lines.append(
            f"| {fmt_time(t)} | `{m.token}` | {m.head or '**?**'} | {m.kind or ''} | {m.source} | {m.score:.0f} | {m.option} |"
        )
    unknown = [m.token for _, m in matches if not m.head]
    if unknown:
        lines += ["", "## 미매칭 (친구에게 물어볼 것)", ""] + [f"- `{u}`" for u in unknown]
    return "\n".join(lines)
