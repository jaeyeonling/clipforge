"""신호: 발화 키워드 (리액션·득템 어휘). 전사(cache/transcript.json)가 있어야 한다.

games/common.yaml 의 speech_keywords 그룹(강/중/약/득템)을 전사 텍스트에서 부분 일치로 찾아
키워드 시각(단어 타임스탬프가 있으면 단어, 없으면 세그먼트 시작)을 이벤트로 낸다. 같은 그룹은 cooldown 초 안에 한 번만.
출력: Segments("speech_keyword"), label=그룹명, score=weight, meta={"word", "text"}.
전사가 없으면 빈 Segments (신호는 선택적).
"""

from __future__ import annotations

import json
from pathlib import Path

from ..timeline import Segment, Segments
from .base import signal

ROOT = Path(__file__).resolve().parent.parent.parent


@signal("speech_keyword")
def speech_keyword(cache: Path) -> Segments:
    tr_p = cache / "transcript.json"
    if not tr_p.exists():
        return Segments(
            "speech_keyword", [], meta={"note": "transcript.json 없음 — python -m clipforge.run transcribe <id>"}
        )
    tr = json.loads(tr_p.read_text(encoding="utf-8"))
    from ..profiles import episode_game, load_settings

    cfg = load_settings(episode_game(cache))
    groups = cfg.get("speech_keywords", {})
    cooldown = float((cfg.get("speech_kernel") or {}).get("cooldown", 8))
    items: list[Segment] = []
    last: dict[str, float] = {}
    for s in tr.get("segments", []):
        units = [(w["start"], w["word"]) for w in s.get("words", [])] or [(s["start"], s["text"])]
        for t, text in units:
            norm = text.replace(" ", "")
            for g, ent in groups.items():
                hit = next((w for w in ent.get("words", []) if w.replace(" ", "") and w.replace(" ", "") in norm), None)
                if hit and t - last.get(g, -1e9) >= cooldown:
                    items.append(
                        Segment(
                            float(t), float(t), g, float(ent.get("weight", 0.5)), {"word": hit, "text": s["text"][:60]}
                        )
                    )
                    last[g] = t
    return Segments(
        "speech_keyword", items, meta={"backend": tr.get("backend"), "n_segments": len(tr.get("segments", []))}
    ).sorted()
