"""신호: 스트리머/편집자가 강조한 구간 (Phase 1 편집본용, 원본에서도 일부 유효).

frames/ 1fps 에서 두 가지를 본다.
  zoom : 하단 HUD 구슬(체력·마나) 둘 다 안 보임 → 게임 화면이 아님. 편집본에선 채팅 줌인·타이틀·엔딩,
         원본에선 로딩·메뉴. 인벤토리/캐릭터창은 한쪽 구슬만 가리므로 오탐 없음 (ep59 실측).
  note : 화면에 밝은 큰 사각형(근백색 ≥ note_white) 이 min_len 초 이상 → 스트리머가 띄운 메모장(아이템 가치 설명).
         ep59: 5:07~5:21 "10맥 76어레 45피 (현금 30만원이상)", 8:00~8:10 "강철 그늘 아메트 ...".
         메모장 텍스트는 value.yaml 의 소스이므로 구간만 남기고 OCR 은 후속.

출력: Segments("edit_emphasis"), label ∈ {zoom, note}, meta={"len"}.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image

from ..timeline import Segment, Segments
from ._hud import orb_fractions
from ._hud import runs as _runs
from .base import signal


@signal("edit_emphasis")
def edit_emphasis(
    cache: Path, orb_min: float = 0.05, note_white: float = 0.08, zoom_min_len: int = 2, note_min_len: int = 3
) -> Segments:
    meta = json.loads((cache / "meta.json").read_text(encoding="utf-8"))
    frames = sorted((cache / "frames").glob("*.jpg"))
    hop = 1.0 / float(meta["frames"]["fps"])
    rois = meta.get("rois", {})
    if "hud_red_orb" not in rois or "hud_blue_orb" not in rois:
        raise KeyError("게임 프로필 rois 에 hud_red_orb / hud_blue_orb 필요")
    scale = meta["frames"]["height"] / meta["height"]  # 네이티브 픽셀 ROI → frames 해상도

    def box(name, W, H):
        x, y, w, h = rois[name]
        x, y, w, h = int(x * scale), int(y * scale), int(w * scale), int(h * scale)
        return slice(max(0, y), min(H, y + h)), slice(max(0, x), min(W, x + w))

    orbs = orb_fractions(cache)
    zoom_f = [r < orb_min and b < orb_min for r, b in orbs]
    note_f = []
    for p in frames:
        im = Image.open(p)
        im.draft("L", (480, 270))
        a = np.asarray(im.convert("L"), dtype=np.float32)
        note_f.append(float((a > 215).mean()) > note_white)

    items = []
    for i, j in _runs(zoom_f, zoom_min_len):
        items.append(Segment(i * hop, j * hop, "zoom", 1.0, {"len": j - i}))
    for i, j in _runs(note_f, note_min_len):
        items.append(Segment(i * hop, j * hop, "note", 1.0, {"len": j - i}))
    return Segments(
        "edit_emphasis", items, meta={"n_frames": len(frames), "orb_min": orb_min, "note_white": note_white}
    ).sorted()
