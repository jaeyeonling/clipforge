"""UI 패널 제목 OCR (D2R). frames/ 1fps 에서 좌/우 패널 제목 띠를 읽어 어떤 창이 열렸는지 알아낸다.

HUD 구슬 가림으로 추정하는 방식은 실패했다(구슬은 중독이면 초록, 마나 0이면 검정이 되고 4K 레이아웃에선 패널이 구슬을 안 가림).
제목 띠(패널 상단, "소지품"·"캐릭터"·"보관함"…)를 직접 읽는 게 정확하다. 결과는 cache/<id>/panel_titles.json 에 초 단위 캐시.
비용: 검출 생략(rec only) 시 크롭당 ~0.1s. 검출 포함은 0.55s.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image

# 제목 텍스트 ROI (화면 비율). 패널 제목은 헤더 가운데 고정이라 좁게 잘라야 인식 전용(rec-only) OCR 이 먹는다.
# 기준 채널 4K 레이아웃 실측 ("캐릭터" 좌, "소지품" 우). 다른 UI 배율이면 games/<game>.yaml 의 panel_bands 로 덮어쓴다.
DEFAULT_BANDS = {"left": [0.14, 0.112, 0.14, 0.05], "right": [0.70, 0.112, 0.16, 0.05]}
KEYWORDS = {
    "inventory": ["소지품"], "stash": ["보관함", "개인 보관함", "공유 보관함"], "cube": ["큐브", "호라드릭"],
    "character": ["캐릭터"], "skills": ["스킬"], "stats": ["고급 통계", "고급통계"], "merc": ["용병"], "quest": ["퀘스트"],
    "waypoint": ["경유지"], "vendor": ["거래", "상점", "수리", "도박"],
}
RIGHT_SIDE = {"inventory", "stash", "cube", "vendor"}


def _engine(det: bool):
    from rapidocr import RapidOCR, LangRec, ModelType, OCRVersion
    return RapidOCR(params={"Rec.lang_type": LangRec.KOREAN, "Rec.model_type": ModelType.MOBILE,
                            "Rec.ocr_version": OCRVersion.PPOCRV5, "Global.log_level": "error",
                            "Global.use_det": det, "Global.use_cls": False})


def classify(txts: list[str]) -> str | None:
    joined = "".join(txts).replace(" ", "")
    for label, kws in KEYWORDS.items():
        if any(k.replace(" ", "") in joined for k in kws):
            return label
    return None


def panel_titles(cache: Path, bands: dict | None = None, det: bool = False, force: bool = False) -> dict[int, dict]:
    """초 → {"left": label|None, "right": label|None, "txt": {...}}"""
    out_p = cache / "panel_titles.json"
    if out_p.exists() and not force:
        return {int(k): v for k, v in json.loads(out_p.read_text(encoding="utf-8")).items()}
    bands = bands or DEFAULT_BANDS
    eng = _engine(det)
    frames = sorted((cache / "frames").glob("*.jpg"))
    res: dict[int, dict] = {}
    for i, p in enumerate(frames):
        im = Image.open(p).convert("RGB")
        W, H = im.size
        rec = {"txt": {}}
        for side, (fx, fy, fw, fh) in bands.items():
            crop = im.crop((int(fx * W), int(fy * H), int((fx + fw) * W), int((fy + fh) * H)))
            crop = crop.resize((crop.width * 2, crop.height * 2))
            r = eng(np.asarray(crop))
            txts = [t for t in (r.txts or []) if t]
            rec["txt"][side] = txts
            rec[side] = classify(txts)
        res[i] = rec
        if i % 100 == 0:
            print(f"\n    panel ocr {i}/{len(frames)}", end="", flush=True)
    out_p.write_text(json.dumps({str(k): v for k, v in res.items()}, ensure_ascii=False), encoding="utf-8")
    return res
