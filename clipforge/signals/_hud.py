"""HUD 구슬 가시성 (frames/ 1fps). edit_emphasis 와 ui_state 가 공유. 결과는 cache/<id>/hud_orbs.json 에 캐시.

red/blue = 체력/마나 구슬 ROI 안의 "구슬 색" 픽셀 비율.
  둘 다 ≈0  → 게임 화면 아님 (줌·카드·로딩·엔딩)
  red 만 ≈0 → 왼쪽 패널(캐릭터창·스킬트리 등)이 구슬을 가림
  blue 만 ≈0→ 오른쪽 패널(인벤토리·창고·큐브 등)이 구슬을 가림  ← 툴팁이 뜨는 자리
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image


def orb_fractions(cache: Path, force: bool = False) -> list[tuple[float, float]]:
    out_p = cache / "hud_orbs.json"
    if out_p.exists() and not force:
        return [tuple(x) for x in json.loads(out_p.read_text(encoding="utf-8"))]
    meta = json.loads((cache / "meta.json").read_text(encoding="utf-8"))
    rois = meta.get("rois", {})
    if "hud_red_orb" not in rois or "hud_blue_orb" not in rois:
        raise KeyError("게임 프로필 rois 에 hud_red_orb / hud_blue_orb 필요")
    frames = sorted((cache / "frames").glob("*.jpg"))
    W0, H0 = meta["width"], meta["height"]
    vals = []
    for p in frames:
        im = Image.open(p)
        im.draft("RGB", (640, 360))
        a = np.asarray(im.convert("RGB"), dtype=np.float32)
        H, W = a.shape[:2]
        sx, sy = W / W0, H / H0                      # 네이티브 ROI → 이 이미지 좌표

        def sub(name):
            x, y, w, h = rois[name]
            return a[int(y * sy):int((y + h) * sy), int(x * sx):int((x + w) * sx)]
        r, b = sub("hud_red_orb"), sub("hud_blue_orb")
        red = float(((r[..., 0] > 120) & (r[..., 0] > r[..., 1] * 1.8) & (r[..., 0] > r[..., 2] * 1.8)).mean()) if r.size else 0.0
        blue = float(((b[..., 2] > 120) & (b[..., 2] > b[..., 0] * 1.8) & (b[..., 2] > b[..., 1] * 1.5)).mean()) if b.size else 0.0
        vals.append((round(red, 3), round(blue, 3)))
    out_p.write_text(json.dumps(vals), encoding="utf-8")
    return vals


def runs(flags: list[bool], min_len: int) -> list[tuple[int, int]]:
    out, i, n = [], 0, len(flags)
    while i < n:
        if flags[i]:
            j = i
            while j < n and flags[j]:
                j += 1
            if j - i >= min_len:
                out.append((i, j))
            i = j
        else:
            i += 1
    return out
