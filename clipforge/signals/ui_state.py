"""신호: UI 패널 상태 (D2R). 세로 크롭 중심을 어디로 둘지, 억제 마스크를 어디에 걸지 알려준다.

  inventory  : 오른쪽에 소지품/보관함/큐브/상점 창 → 아이템 툴팁이 뜨는 자리. 크롭 중심을 오른쪽으로 (_panels.py 제목 OCR)
  left_panel : 왼쪽에 캐릭터/스킬/용병/퀘스트 창 → 크롭 중심을 왼쪽으로
  offscreen  : HUD 구슬 둘 다 없음 (줌·카드·로딩·엔딩) → 게임 화면 아님 (_hud.py)
출력: Segments("ui_state"), label ∈ {inventory, left_panel, offscreen}, meta={"len", "panel"}.
"""
from __future__ import annotations

import json
from pathlib import Path

from ..timeline import Segment, Segments
from ._hud import orb_fractions, runs
from ._panels import RIGHT_SIDE, panel_titles
from .base import signal


@signal("ui_state")
def ui_state(cache: Path, orb_min: float = 0.05, min_len: int = 1) -> Segments:
    meta = json.loads((cache / "meta.json").read_text(encoding="utf-8"))
    hop = 1.0 / float(meta["frames"]["fps"])
    orbs = orb_fractions(cache)
    titles = panel_titles(cache, bands=meta.get("panel_bands"))
    n = len(orbs)
    right = [titles.get(i, {}).get("right") for i in range(n)]
    left = [titles.get(i, {}).get("left") for i in range(n)]
    items = []
    for i, j in runs([bool(r) and r in RIGHT_SIDE for r in right], min_len):
        items.append(Segment(i * hop, j * hop, "inventory", 1.0, {"len": j - i, "panel": right[i]}))
    for i, j in runs([bool(l) and not (right[k] in RIGHT_SIDE) for k, l in enumerate(left)], min_len):
        items.append(Segment(i * hop, j * hop, "left_panel", 1.0, {"len": j - i, "panel": left[i]}))
    for i, j in runs([r < orb_min and b < orb_min for r, b in orbs], min_len):
        items.append(Segment(i * hop, j * hop, "offscreen", 1.0, {"len": j - i}))
    return Segments("ui_state", items, meta={"n_frames": n, "orb_min": orb_min}).sorted()
