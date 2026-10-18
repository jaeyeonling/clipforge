"""캘리브레이션: 게임 프로필 ROI 가 지금 화면과 맞는지 점검하고, 미리보기·수정 저장을 제공한다 (PRODUCT_ARCHITECTURE §10-5).

check(project, vid)   → 각 ROI 의 적중률과 판정 (pass / warn / fail) + 힌트
preview(project, vid, t) → ROI 박스를 그린 PNG (frames/ 의 1080p 프레임 위)
set_rois(project, game, rois) → games/<game>.yaml 의 rois 갱신 (비율). meta.json 은 다음 prep 때 반영되므로 안내
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import yaml
from PIL import Image, ImageDraw

from .project import Project
from .schema import load_json
from .signals._panels import DEFAULT_BANDS
from .textdraw import FontStack, draw_text

HEADER_RE = re.compile(r"(득템|득렘|득램|특템|특램)")
COLORS = {"banner": (240, 246, 96), "chat": (120, 200, 255), "zone": (200, 160, 255), "hud_red_orb": (255, 90, 80),
          "hud_blue_orb": (90, 140, 255), "panel_left": (120, 255, 160), "panel_right": (120, 255, 160)}


def _rate(xs: list[bool]) -> float:
    return round(sum(1 for x in xs if x) / len(xs), 3) if xs else 0.0


def check(project: Project, vid: str) -> dict:
    cache = project.cache / vid
    meta_p = cache / "meta.json"
    if not meta_p.exists():
        return {"ok": False, "error": "prep 이 아직 안 됨", "checks": []}
    meta = load_json(meta_p, "meta")
    checks: list[dict] = []

    def add(name, rate, warn, fail, detail, hint):
        status = "pass" if rate >= warn else ("warn" if rate >= fail else "fail")
        checks.append({"name": name, "rate": rate, "status": status, "detail": detail, "hint": hint if status != "pass" else ""})

    # 1) 득템 배너: OCR 캐시에서 머리말이 읽힌 초의 비율
    b = cache / "banner_ocr.json"
    if b.exists():
        d = json.loads(b.read_text(encoding="utf-8"))
        vals = list(d.values())
        hit = [bool(HEADER_RE.search(v)) for v in vals]
        add("득템 배너 ROI", _rate(hit), 0.5, 0.15, f"OCR {len(vals)}초 중 '득템' 머리말 {sum(hit)}초",
            "배너 위치/크기가 화면과 안 맞습니다. 미리보기에서 노란 박스가 '득템 :' 줄을 덮는지 확인하고 rois.banner 를 조정하세요.")
    else:
        checks.append({"name": "득템 배너 ROI", "rate": None, "status": "skip", "detail": "signals(item_banner) 미실행", "hint": ""})
    # 2) 패널 제목: 초당 OCR 에서 좌/우 패널명이 1개라도 읽힌 비율 (인벤토리는 자주 열리므로 10% 이상이면 정상)
    pt = cache / "panel_titles.json"
    if pt.exists():
        d = json.loads(pt.read_text(encoding="utf-8"))
        hit = [bool(v.get("left") or v.get("right")) for v in d.values()]
        add("패널 제목 ROI (소지품/캐릭터)", _rate(hit), 0.08, 0.02, f"{len(d)}초 중 패널 검출 {sum(hit)}초",
            "인벤토리를 여는 장면이 있는데도 검출이 없으면 panel_bands 위치가 틀린 것입니다. 미리보기의 초록 박스가 창 제목을 덮어야 합니다.")
    else:
        checks.append({"name": "패널 제목 ROI", "rate": None, "status": "skip", "detail": "signals(ui_state) 미실행", "hint": ""})
    # 3) 채팅: OCR 캐시에서 '닉 : 메시지' 줄이 읽힌 비율
    ch = cache / "chat_ocr.json"
    if ch.exists():
        d = json.loads(ch.read_text(encoding="utf-8"))
        hit = [any(re.match(r"^\s*[0-9A-Za-z가-힣_\-]{2,24}\s*[:：]", ln.get("text", "")) for ln in lines) for lines in d.values()]
        add("채팅 ROI", _rate(hit), 0.5, 0.15, f"OCR {len(d)}초 중 채팅 줄 검출 {sum(hit)}초",
            "채팅 오버레이 위치가 다릅니다. 파란 박스가 채팅 영역을 덮도록 rois.chat 을 조정하세요.")
    else:
        checks.append({"name": "채팅 ROI", "rate": None, "status": "skip", "detail": "signals(chat_text) 미실행", "hint": ""})
    # 4) HUD 구슬: 둘 다 보이는 초의 비율
    hud = cache / "hud_orbs.json"
    if hud.exists():
        d = json.loads(hud.read_text(encoding="utf-8"))
        hit = [r >= 0.05 or b_ >= 0.05 for r, b_ in d]
        add("HUD 구슬 ROI", _rate(hit), 0.7, 0.3, f"{len(d)}초 중 구슬 검출 {sum(hit)}초",
            "체력/마나 구슬 박스(빨강/파랑)가 구슬 위에 있어야 합니다. 게임 UI 배율이 다르면 hud_*_orb 를 조정하세요.")
    else:
        checks.append({"name": "HUD 구슬 ROI", "rate": None, "status": "skip", "detail": "signals(ui_state) 미실행", "hint": ""})
    worst = "pass"
    for c in checks:
        if c["status"] == "fail":
            worst = "fail"
        elif c["status"] == "warn" and worst != "fail":
            worst = "warn"
    return {"ok": True, "game": meta.get("game"), "resolution": [meta.get("width"), meta.get("height")],
            "status": worst, "checks": checks}


def preview(project: Project, vid: str, t: int | None = None, rois_override: dict | None = None) -> Path:
    """frames/<t>.jpg 위에 ROI 박스를 그려 cache/<vid>/calib_preview.png 로 저장. rois_override 는 비율 dict (저장 전 미리보기)."""
    cache = project.cache / vid
    meta = load_json(cache / "meta.json", "meta")
    frames = sorted((cache / "frames").glob("*.jpg"))
    if not frames:
        raise FileNotFoundError("frames 없음 — prep 먼저")
    if t is None:
        t = min(len(frames) - 1, max(0, int(meta["duration"] * 0.3)))
    im = Image.open(frames[min(t, len(frames) - 1)]).convert("RGB")
    W, H = im.size
    d = ImageDraw.Draw(im)
    font = FontStack("gothic", "gothic_regular")
    rois_frac = rois_override
    if rois_frac is None:                      # meta 의 픽셀 ROI → 비율
        rois_frac = {k: [v[0] / meta["width"], v[1] / meta["height"], v[2] / meta["width"], v[3] / meta["height"]]
                     for k, v in meta.get("rois", {}).items()}
    for name, (fx, fy, fw, fh) in rois_frac.items():
        col = COLORS.get(name, (255, 255, 255))
        x, y, w, h = int(fx * W), int(fy * H), int(fw * W), int(fh * H)
        d.rectangle((x, y, x + w, y + h), outline=col, width=3)
        draw_text(d, (x + 6, y + 4), name, font, 22, fill=col, outline=(0, 0, 0), outline_weight=1)
    bands = meta.get("panel_bands") or DEFAULT_BANDS
    for side, (fx, fy, fw, fh) in bands.items():
        x, y, w, h = int(fx * W), int(fy * H), int(fw * W), int(fh * H)
        d.rectangle((x, y, x + w, y + h), outline=COLORS["panel_left"], width=2)
        draw_text(d, (x + 4, y - 26), f"panel_{side}", font, 20, fill=COLORS["panel_left"], outline=(0, 0, 0), outline_weight=1)
    out = cache / "calib_preview.png"
    im.save(out)
    return out


def get_rois(project: Project, game: str) -> dict:
    p = project.games / f"{game}.yaml"
    prof = yaml.safe_load(p.read_text(encoding="utf-8"))
    return {"game": game, "resolution_ref": prof.get("resolution_ref"), "rois": prof.get("rois", {}),
            "roi_crops": prof.get("roi_crops", []), "panel_bands": prof.get("panel_bands") or DEFAULT_BANDS}


def set_rois(project: Project, game: str, rois: dict, panel_bands: dict | None = None) -> dict:
    """비율 ROI 저장. 값 검증(0~1, w/h > 0) 후 yaml 갱신. 주석은 보존하지 않는다(yaml 덤프) — 변경 이력은 git 으로."""
    p = project.games / f"{game}.yaml"
    prof = yaml.safe_load(p.read_text(encoding="utf-8"))
    clean = {}
    for k, v in rois.items():
        v = [float(x) for x in v]
        if len(v) != 4 or not all(0.0 <= x <= 1.0 for x in v) or v[2] <= 0 or v[3] <= 0:
            raise ValueError(f"ROI 값 오류: {k}={v} (비율 0~1, w/h > 0)")
        clean[k] = [round(x, 4) for x in v]
    prof["rois"] = clean
    if panel_bands:
        prof["panel_bands"] = {k: [round(float(x), 4) for x in v] for k, v in panel_bands.items()}
    p.write_text(yaml.safe_dump(prof, allow_unicode=True, sort_keys=False, width=200), encoding="utf-8")
    return {"ok": True, "note": "저장됨. 네이티브 크롭(rois/)이 바뀌는 ROI 는 다음 prep(강제 재계산)부터 반영됩니다."}
