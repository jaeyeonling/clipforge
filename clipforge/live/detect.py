"""경량 감지기 (CPU, 프레임 1장 단위).

drop_labels(frame)  : 바닥 아이템 라벨 — D2R 은 등급별 색 텍스트(유니크 금색·세트 초록·희귀 노랑·매직 파랑)를 검은 상자 위에 띄운다.
                      색 마스크 → 격자 연결 성분 → 상자 모양 필터 → (선택) OCR. 라벨은 Alt 를 누르거나 커서를 올릴 때만 보이므로
                      방송에서 '템을 보여주는 순간' = 라벨이 뜬 순간이다. 그 자체가 득템 배너 제안의 트리거.
chat_activity(prev, cur, roi) : 채팅 오버레이 영역의 변화량 — 채팅 폭주 북마크 입력.
panel_open(frame)   : 소지품/캐릭터창 열림 (signals._panels 의 제목 OCR 재사용, 선택적)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import numpy as np
from PIL import Image

if TYPE_CHECKING:
    from ..lexicon import Lexicon

# 등급 → (이름, RGB 조건). 1080p 기준 JPEG 에서 잰 값. 라벨 텍스트 픽셀만 통과해야 하므로 좁게 잡는다.
GRADES = ["set", "unique", "rare", "magic"]


def grade_masks(a: np.ndarray) -> dict[str, np.ndarray]:
    r, g, b = a[..., 0].astype(np.int16), a[..., 1].astype(np.int16), a[..., 2].astype(np.int16)
    return {
        "set": (g > 150) & (r < 130) & (b < 130) & (g - r > 60) & (g - b > 60),  # #00FF00 계열
        "rare": (r > 190) & (g > 190) & (b < 120) & (np.abs(r - g) < 50),  # #FFFF64 계열
        "unique": (r > 150)
        & (r < 235)
        & (g > 120)
        & (g < 205)
        & (b > 50)
        & (b < 150)
        & (r - b > 55)
        & (np.abs(r - g) < 55)
        & (g - b > 25),  # #C7B377 금색
        "magic": (b > 170) & (r < 150) & (g < 150) & (b - r > 60) & (b - g > 40),  # #6969FF
    }


@dataclass
class Label:
    grade: str
    bbox: tuple[int, int, int, int]  # 프레임 좌표 (x0, y0, x1, y1)
    pixels: int
    text: str = ""
    score: float = 0.0
    item: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "grade": self.grade,
            "bbox": list(self.bbox),
            "pixels": self.pixels,
            "text": self.text,
            "score": round(self.score, 3),
            "item": self.item,
        }


def _components(mask: np.ndarray, cell: int) -> list[tuple[int, int, int, int, int]]:
    """mask 를 cell×cell 격자로 줄여 셀 단위 연결 성분 → (x0,y0,x1,y1,pixels). scipy 없이 간단 BFS."""
    H, W = mask.shape
    gh, gw = H // cell, W // cell
    grid = mask[: gh * cell, : gw * cell].reshape(gh, cell, gw, cell).sum(axis=(1, 3))
    occ = grid >= max(2, cell * cell // 12)  # 셀 안에 라벨 픽셀이 조금이라도 모여 있으면
    seen = np.zeros_like(occ, dtype=bool)
    out: list[tuple[int, int, int, int, int]] = []
    ys, xs = np.nonzero(occ)
    for y, x in zip(ys, xs, strict=True):
        if seen[y, x]:
            continue
        stack = [(y, x)]
        seen[y, x] = True
        cells = []
        while stack:
            cy, cx = stack.pop()
            cells.append((cy, cx))
            for dy in (-1, 0, 1):
                for dx in (-2, -1, 0, 1, 2):  # 글자 사이 틈은 가로로 조금 떨어질 수 있다
                    ny, nx = cy + dy, cx + dx
                    if 0 <= ny < gh and 0 <= nx < gw and occ[ny, nx] and not seen[ny, nx]:
                        seen[ny, nx] = True
                        stack.append((ny, nx))
        rows = [int(c[0]) for c in cells]
        cols = [int(c[1]) for c in cells]
        y0, y1, x0, x1 = min(rows) * cell, (max(rows) + 1) * cell, min(cols) * cell, (max(cols) + 1) * cell
        out.append((x0, y0, x1, y1, int(mask[y0:y1, x0:x1].sum())))
    return out


def drop_labels(
    frame: Image.Image,
    game_region: tuple[float, float, float, float] = (0.0, 0.07, 1.0, 0.86),
    grades: tuple[str, ...] = ("set", "unique", "rare"),
    work_width: int = 1920,
    min_h: int = 14,
    max_h: int = 48,
    min_w: int = 30,
    max_w: int = 520,
    min_pixels: int = 60,
) -> list[Label]:
    """프레임 → 라벨 후보 상자. game_region 은 배너·HUD 를 뺀 비율 영역. 반환은 프레임 원본 좌표."""
    W, H = frame.size
    scale = work_width / W if work_width < W else 1.0
    im = frame.resize((int(W * scale), int(H * scale))) if scale != 1.0 else frame
    a = np.asarray(im)
    gx0, gy0, gx1, gy1 = [
        int(v * s) for v, s in zip(game_region, (im.width, im.height, im.width, im.height), strict=True)
    ]
    sub = a[gy0:gy1, gx0:gx1]
    masks = grade_masks(sub)
    out: list[Label] = []
    for grade in grades:
        comps = _merge_row(_components(masks[grade], cell=4), gap=18)  # 단어 사이 띄어쓰기로 갈라진 상자 합치기
        for x0, y0, x1, y1, px in comps:
            w, h = x1 - x0, y1 - y0
            if not (min_h <= h <= max_h and min_w <= w <= max_w and px >= min_pixels and w >= h * 1.6):
                continue
            # 라벨은 검은 상자 위에 뜬다: 상자 안은 '어두운 배경 + 등급색 글자' 뿐이어야 한다. 금색 UI 테두리·불꽃은 중간톤 픽셀이 많다.
            box = sub[y0:y1, x0:x1]
            dark = box.max(axis=2) < 70
            other = (~dark) & (~masks[grade][y0:y1, x0:x1])
            if dark.mean() < 0.25 or other.mean() > 0.35:
                continue
            pad = 4
            bx0, by0 = max(0, x0 - pad) + gx0, max(0, y0 - pad) + gy0
            bx1, by1 = min(sub.shape[1], x1 + pad) + gx0, min(sub.shape[0], y1 + pad) + gy0
            out.append(Label(grade, (int(bx0 / scale), int(by0 / scale), int(bx1 / scale), int(by1 / scale)), px))
    # 같은 자리 중복(등급 마스크 겹침) 제거: 많이 겹치면 픽셀 수 큰 쪽
    out.sort(key=lambda l: -l.pixels)
    kept: list[Label] = []
    for l in out:
        if any(_iou(l.bbox, k.bbox) > 0.5 for k in kept):
            continue
        kept.append(l)
    return sorted(kept, key=lambda l: (l.bbox[1], l.bbox[0]))


def _merge_row(comps: list[tuple[int, int, int, int, int]], gap: int) -> list[tuple[int, int, int, int, int]]:
    """같은 줄(세로 겹침 ≥ 50%)에서 가로로 gap 이내인 상자들을 합친다."""
    comps = sorted(comps, key=lambda c: (c[1], c[0]))
    merged: list[list[int]] = []
    for x0, y0, x1, y1, px in comps:
        for m in merged:
            vy = min(y1, m[3]) - max(y0, m[1])
            if vy > 0.5 * min(y1 - y0, m[3] - m[1]) and (x0 - m[2] <= gap and m[0] - x1 <= gap):
                m[0], m[1], m[2], m[3], m[4] = min(m[0], x0), min(m[1], y0), max(m[2], x1), max(m[3], y1), m[4] + px
                break
        else:
            merged.append([x0, y0, x1, y1, px])
    return [(m[0], m[1], m[2], m[3], m[4]) for m in merged]


def _iou(a, b) -> float:
    ix0, iy0, ix1, iy1 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    inter = max(0, ix1 - ix0) * max(0, iy1 - iy0)
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua if ua else 0.0


class LabelOCR:
    """라벨 상자 → 텍스트 (RapidOCR, CPU). 2배 확대 후 인식. 결과는 lexicon 으로 정규화."""

    def __init__(self, game: str = "d2r"):
        self._eng: Any = None  # RapidOCR (첫 사용 때 만든다)
        self.game = game
        self._lex: Lexicon | None = None

    def _engine(self):
        if self._eng is None:
            from rapidocr import LangRec, ModelType, OCRVersion, RapidOCR

            self._eng = RapidOCR(
                params={
                    "Rec.lang_type": LangRec.KOREAN,
                    "Rec.model_type": ModelType.MOBILE,
                    "Rec.ocr_version": OCRVersion.PPOCRV5,
                    "Global.log_level": "error",
                }
            )
        return self._eng

    def read(self, frame: Image.Image, label: Label) -> Label:
        x0, y0, x1, y1 = label.bbox
        pad = 6
        crop = frame.crop((max(0, x0 - pad), max(0, y0 - pad), min(frame.width, x1 + pad), min(frame.height, y1 + pad)))
        crop = crop.resize((crop.width * 3, crop.height * 3), Image.Resampling.LANCZOS)
        # 상자가 이미 한 줄 텍스트라 검출(det)을 건너뛰고 인식만 (det 은 작은 크롭에서 단어 일부를 놓친다)
        r = self._engine()(np.asarray(crop), use_det=False, use_cls=False)
        txt = " ".join(t.strip() for t in (r.txts or []) if t.strip()).replace("*", "").strip()
        label.score = float(r.scores[0]) if getattr(r, "scores", None) else 0.0
        label.text = txt
        if txt:
            try:
                if self._lex is None:
                    from ..lexicon import Lexicon  # 사전은 처음 읽을 때만 불러온다

                    self._lex = Lexicon(self.game)
                m = self._lex.lookup(txt)
                if m and m.head:
                    label.item = {"head": m.head, "kind": getattr(m, "kind", ""), "score": getattr(m, "score", None)}
            except Exception:
                pass
        return label


def chat_activity(
    prev: np.ndarray | None, cur: Image.Image, roi: tuple[float, float, float, float]
) -> tuple[float, np.ndarray]:
    """채팅 영역의 평균 절대차(0~1). 반환 (activity, 다음 비교용 썸네일)."""
    W, H = cur.size
    x0, y0, w, h = roi
    box = cur.crop((int(x0 * W), int(y0 * H), int((x0 + w) * W), int((y0 + h) * H))).convert("L").resize((96, 48))
    a = np.asarray(box, dtype=np.float32) / 255.0
    act = float(np.abs(a - prev).mean()) if prev is not None else 0.0
    return act, a
