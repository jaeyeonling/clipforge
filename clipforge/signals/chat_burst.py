"""신호: 채팅 오버레이 변화율 (채팅 폭주 proxy).

rois/chat/%06d.jpg (1fps, 네이티브 크롭) 에서 밝은 글자 픽셀 마스크를 만들고, 연속 초 사이의 XOR 비율을 잰다.
새 메시지가 올라오면 글자 배치가 통째로 바뀌므로 값이 튄다. 반투명 배경 뒤 게임 화면 변화가 섞이는 노이즈는
마스크 임계(밝기 ≥ text_thr) 와 이동 평균(smooth 초) 으로 누른다. OCR 기반 메시지 수 세기로 교체 가능한 자리.

한국 클립 채널 관례 "채팅이 몰린 곳이 곧 하이라이트"(Captus) 의 가장 싼 구현.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image

from ..timeline import Curve
from .base import signal


@signal("chat_burst")
def chat_burst(cache: Path, text_thr: int = 200, smooth: int = 5) -> Curve:
    meta = json.loads((cache / "meta.json").read_text(encoding="utf-8"))
    hop = 1.0 / float(meta["frames"]["fps"])
    files = sorted((cache / "rois" / "chat").glob("*.jpg"))
    if not files:
        raise FileNotFoundError(f"{cache / 'rois' / 'chat'} 없음 — 프로필 roi_crops 에 chat 필요")
    prev = None
    vals = []
    for p in files:
        im = Image.open(p)
        im.draft("L", (320, 160))
        m = np.asarray(im.convert("L").resize((300, 134)), dtype=np.uint8) > text_thr
        if prev is None:
            vals.append(0.0)
        else:
            x = np.logical_xor(m, prev).sum()
            u = np.logical_or(m, prev).sum()
            vals.append(float(x / u) if u else 0.0)
        prev = m
    v = np.asarray(vals, dtype=np.float32)
    if smooth > 1:
        k = np.ones(smooth, dtype=np.float32) / smooth
        v = np.convolve(v, k, mode="same")
    return Curve(
        name="chat_burst",
        hop=hop,
        values=[round(float(x), 3) for x in v],
        meta={"unit": "xor ratio of bright-text mask, smoothed", "text_thr": text_thr, "smooth": smooth},
    )
