"""신호: 채팅 오버레이 OCR → 새 메시지 이벤트.

rois/chat/%06d.jpg (1fps 네이티브 크롭) 을 RapidOCR(검출+인식) 로 읽는다. 비용 절감: chat_burst(픽셀 변화율) 가
gate 이상인 초 + every 초마다 1번만 OCR (나머지 초는 직전 결과 유지). 초당 OCR 결과는 chat_ocr.json 에 캐시.

메시지 재구성: 줄을 y 순으로 정렬 → "닉 : 메시지" 패턴이면 새 메시지, 아니면 직전 메시지의 이어지는 줄.
새 메시지 판정: 직전 OCR 초의 메시지 집합과 퍼지 비교(partial_ratio ≥ 85, OCR jitter 흡수) 해서 없던 것만 이벤트.
출력: Segments("chat_text"), start=end=초, label="msg", score=1, meta={"nick", "text", "lines"}.
Phase 1 에선 줌·채팅 앵커 클립의 자막 원문으로, 나중엔 채팅 키워드 신호(헐/ㄷㄷ/미쳤다)로 쓴다.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np
from PIL import Image
from rapidfuzz import fuzz

from ..timeline import Curve, Segment, Segments
from .base import signal

NICK_RE = re.compile(r"^\s*([0-9A-Za-z가-힣_\-]{1,24})\s*[:：]\s*(.*)$")


def _engine():
    from rapidocr import RapidOCR, LangRec, ModelType, OCRVersion
    return RapidOCR(params={"Rec.lang_type": LangRec.KOREAN, "Rec.model_type": ModelType.MOBILE,
                            "Rec.ocr_version": OCRVersion.PPOCRV5, "Global.log_level": "error", "Global.use_cls": False})


def ocr_lines(eng, img: Image.Image) -> list[dict]:
    r = eng(np.asarray(img))
    boxes = r.boxes if r.boxes is not None else []
    out = []
    for box, txt, sc in zip(boxes, list(r.txts or []), list(r.scores or [])):
        b = np.asarray(box)
        out.append({"y": float(b[:, 1].min()), "x": float(b[:, 0].min()), "text": txt.strip(), "score": float(sc)})
    return sorted(out, key=lambda d: d["y"])


def messages_from_lines(lines: list[dict], min_score: float = 0.6) -> list[dict]:
    msgs: list[dict] = []
    for ln in lines:
        if ln["score"] < min_score or not ln["text"]:
            continue
        m = NICK_RE.match(ln["text"])
        if m and len(m.group(2)) >= 0 and len(m.group(1)) >= 2:
            msgs.append({"nick": m.group(1), "text": m.group(2).strip()})
        elif msgs:
            msgs[-1]["text"] = (msgs[-1]["text"] + " " + ln["text"]).strip()
        else:
            msgs.append({"nick": "", "text": ln["text"]})
    return [m for m in msgs if m["text"]]


def _key(m: dict) -> str:
    return (m["nick"] + ":" + m["text"]).replace(" ", "")


@signal("chat_text")
def chat_text(cache: Path, gate: float = 0.03, every: int = 5, sim: int = 85) -> Segments:
    meta = json.loads((cache / "meta.json").read_text(encoding="utf-8"))
    hop = 1.0 / float(meta["frames"]["fps"])
    files = sorted((cache / "rois" / "chat").glob("*.jpg"))
    if not files:
        raise FileNotFoundError(f"{cache / 'rois' / 'chat'} 없음 — 프로필 roi_crops 에 chat 필요")
    burst = Curve.load(cache / "chat_burst.json").as_array() if (cache / "chat_burst.json").exists() else None
    cache_p = cache / "chat_ocr.json"
    ocr_cache: dict[int, list] = {int(k): v for k, v in json.loads(cache_p.read_text(encoding="utf-8")).items()} if cache_p.exists() else {}
    eng = None
    calls = 0
    items: list[Segment] = []
    prev_msgs: list[dict] = []
    for i, p in enumerate(files):
        do = (i % every == 0) or (burst is not None and i < len(burst) and float(burst[i]) >= gate)
        if not do:
            continue
        if i not in ocr_cache:
            if eng is None:
                eng = _engine()
            ocr_cache[i] = ocr_lines(eng, Image.open(p).convert("RGB"))
            calls += 1
            if calls % 50 == 0:
                print(f"\n    chat ocr {calls} calls ({i}/{len(files)})", end="", flush=True)
        msgs = messages_from_lines(ocr_cache[i])
        prev_keys = [_key(m) for m in prev_msgs]
        for m in msgs:
            k = _key(m)
            if len(k) < 4 or any(fuzz.partial_ratio(k, pk) >= sim for pk in prev_keys):
                continue
            items.append(Segment(i * hop, i * hop, "msg", 1.0, {"nick": m["nick"], "text": m["text"]}))
        prev_msgs = msgs
    cache_p.write_text(json.dumps({str(k): v for k, v in sorted(ocr_cache.items())}, ensure_ascii=False), encoding="utf-8")
    return Segments("chat_text", items, meta={"ocr_calls": calls, "ocr_cached": len(ocr_cache), "gate": gate, "every": every})
