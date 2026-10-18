"""신호: 득템 배너 (D2R, 기준 채널 방송 화면).

좌상단 "득템 :" 배너는 스트리머가 획득 아이템을 OBS 텍스트로 누적 기록하는 영역이다.
배너 텍스트가 **길어지는 순간 = 드랍 직후**. 바닥 아이템 라벨 OCR 보다 쉽고 정확하다.

방법 (experiments/banner_proto.py 에서 검증):
  1. rois/banner/%06d.jpg 를 step(기본 3초) 간격으로 OCR (RapidOCR 한국어 PP-OCRv5)
  2. 인접 coarse 샘플의 텍스트가 다르면 그 사이를 1초 단위로 OCR
  3. 정규화 텍스트가 min_stable(기본 3)초 이상 유지되는 구간만 "안정 상태"로 인정 (프레임 간 OCR jitter 제거)
  4. 안정 상태 간 전이에서 글자가 늘면 APPEND(득템), 거의 사라지면 RESET(배너 소실: 줌·카드·로딩)

출력: Segments("item_banner") — start=end=전이 시각, label="append"|"appear"|"switch"|"reset",
      meta={"added", "removed", "text"}. RESET 은 edit_emphasis 의 입력이 된다.
OCR 결과는 cache/<id>/banner_ocr.json 에 초 단위로 캐시되어 파라미터를 바꿔도 재사용된다.
"""
from __future__ import annotations

import difflib
import json
import re
import time
from pathlib import Path

from ..timeline import Segment, Segments
from .base import signal

IGNORE_TOKENS = {"준영"}          # 배너 본문이 아닌 고정 텍스트(스트리머 이름 라벨)
NORM_RE = re.compile(r"[^0-9A-Za-z가-힣★/()~%,]")   # 쉼표는 토큰 경계라 남긴다
DECOR_RE = re.compile(r"[★츠]")
HEADER_RE = re.compile(r"^(득템|득렘|득램|특템|특램|독템)")   # OCR 변형 포함


def _engine():
    from rapidocr import RapidOCR, LangRec, ModelType, OCRVersion
    return RapidOCR(params={"Rec.lang_type": LangRec.KOREAN, "Rec.model_type": ModelType.MOBILE,
                            "Rec.ocr_version": OCRVersion.PPOCRV5, "Global.log_level": "error"})


def normalize(txts: list[str]) -> str:
    kept = [t for t in txts if t not in IGNORE_TOKENS]
    return re.sub(r",{2,}", ",", NORM_RE.sub("", ",".join(kept))).strip(",")


class BannerOCR:
    """초 → 정규화 텍스트. 디스크 캐시 + 지연 OCR."""

    def __init__(self, roi_dir: Path, cache_path: Path):
        self.files = sorted(roi_dir.glob("*.jpg"))
        self.cache_path = cache_path
        self.cache: dict[int, str] = {}
        if cache_path.exists():
            self.cache = {int(k): v for k, v in json.loads(cache_path.read_text(encoding="utf-8")).items()}
        self._eng = None
        self.calls = 0

    def __len__(self) -> int:
        return len(self.files)

    def text(self, i: int) -> str:
        if i in self.cache:
            return self.cache[i]
        if self._eng is None:
            self._eng = _engine()
        r = self._eng(str(self.files[i]))
        self.calls += 1
        self.cache[i] = normalize(list(r.txts or []))
        return self.cache[i]

    def save(self) -> None:
        self.cache_path.write_text(json.dumps({str(k): v for k, v in sorted(self.cache.items())},
                                              ensure_ascii=False), encoding="utf-8")


def stable_states(seq: list[str], min_stable: int) -> list[tuple[int, int, str]]:
    """같은 텍스트가 min_stable 초 이상 이어진 구간 [(start, end_exclusive, text)]."""
    out, i, n = [], 0, len(seq)
    while i < n:
        j = i
        while j < n and seq[j] == seq[i]:
            j += 1
        if j - i >= min_stable:
            out.append((i, j, seq[i]))
        i = j
    return out


def transitions(states: list[tuple[int, int, str]], min_added: int = 3, reset_drop: int = 20) -> list[Segment]:
    items: list[Segment] = []
    prev: tuple[int, int, str] | None = None
    last_banner = ""          # 마지막으로 확인된 "진짜" 득템 배너 텍스트 (머리말 있고 충분히 긴 것)
    for s, e, t in states:
        if prev is None or t == prev[2]:
            prev = (s, e, t)
            if HEADER_RE.match(t) and len(DECOR_RE.sub("", t)) >= 5:
                last_banner = t
            continue
        pt = prev[2]
        # 직전 상태가 비었거나 깨졌으면(줌·로딩·OCR 실패) 마지막 진짜 배너와 비교한다.
        # 그래야 "사라졌다 다시 나타나며 글자가 늘어난" 경우를 append 로 잡는다.
        if len(DECOR_RE.sub("", pt)) < 5 and last_banner:
            pt = last_banner
        sm = difflib.SequenceMatcher(None, pt, t)
        added = "".join(t[j1:j2] for tag, i1, i2, j1, j2 in sm.get_opcodes() if tag in ("insert", "replace"))
        removed = "".join(pt[i1:i2] for tag, i1, i2, j1, j2 in sm.get_opcodes() if tag in ("delete", "replace"))
        dl = len(t) - len(pt)
        # ★ 는 OCR 이 '츠' 로 읽는 경우가 많아 jitter 의 주범. 장식 문자만 늘어난 전이는 무시한다.
        added_core = DECOR_RE.sub("", added)
        if dl >= min_added and len(added_core) >= min_added:
            # append : 득템 배너에 글자가 늘어남 (드랍)
            # appear : 거의 빈 상태에서 배너가 (재)등장 — 줌/로딩 뒤 복귀. 드랍 아님
            # switch : 다른 종류의 배너(이벤트 공지 등)로 교체 — 내용 유사도 낮고 머리말 없음
            if not HEADER_RE.match(t):
                label = "switch"
            elif len(DECOR_RE.sub("", pt)) < 5:
                label = "appear"
            elif not HEADER_RE.match(pt) and sm.ratio() < 0.3:
                label = "switch"
            else:
                label = "append"
            items.append(Segment(float(s), float(s), label, 1.0,
                                 {"added": added, "removed": removed, "text": t, "stable": e - s}))
        elif dl <= -reset_drop or (len(DECOR_RE.sub("", t)) < 5 <= len(DECOR_RE.sub("", pt)) - 3):
            # 글자가 reset_drop 이상 줄었거나, 짧은 배너라도 사실상 비워졌으면 소실(reset)
            items.append(Segment(float(s), float(s), "reset", 1.0,
                                 {"added": added, "removed": removed, "text": t, "stable": e - s}))
        prev = (s, e, t)
        if HEADER_RE.match(t) and len(DECOR_RE.sub("", t)) >= 5:
            last_banner = t
    return items


def change_runs(files: list[Path], thr: float = 6.0, size: tuple[int, int] = (64, 12)) -> list[tuple[int, int]]:
    """배너 크롭이 '바뀐' 지점으로 프레임을 나눈 구간 [(start, end_exclusive)]. 작은 회색 썸네일의 평균 절대차 > thr.
    OBS 텍스트 배너는 정적이라 7시간에 수십 번만 바뀐다 → OCR 호출이 수천 → 수십 으로 준다."""
    import numpy as np
    from PIL import Image
    runs, start, prev = [], 0, None
    for i, p in enumerate(files):
        cur = np.asarray(Image.open(p).convert("L").resize(size), dtype=np.float32)
        if prev is not None and float(np.abs(cur - prev).mean()) > thr:
            runs.append((start, i)); start = i
        prev = cur
    runs.append((start, len(files)))
    return runs


@signal("item_banner")
def item_banner(cache: Path, step: int = 3, min_stable: int = 3, mode: str | None = None) -> Segments:
    """mode: coarse(기본, 편집본 — step 초마다 OCR 후 변하는 곳만 1초 단위) | change(원본 — 크롭 변화 감지 후 구간당 1회 OCR).
    meta.json 의 kind 가 original 이면 change."""
    roi_dir = cache / "rois" / "banner"
    if not roi_dir.exists():
        raise FileNotFoundError(f"{roi_dir} 없음 — prep 이 games/<game>.yaml 의 roi_crops 에 banner 를 포함해야 함")
    if mode is None:
        try:
            mode = "change" if json.loads((cache / "meta.json").read_text(encoding="utf-8")).get("kind") == "original" else "coarse"
        except OSError:
            mode = "coarse"
    ocr = BannerOCR(roi_dir, cache / "banner_ocr.json")
    n = len(ocr)
    t0 = time.time()
    seq: list[str] = []
    n_runs = 0
    if mode == "change":
        runs = change_runs(ocr.files)
        n_runs = len(runs)
        for k, (s, e) in enumerate(runs):
            mid = (s + e) // 2
            txt = ocr.text(mid)
            seq.extend([txt] * (e - s))
            if k % 20 == 0 and ocr.calls:
                print(f"\n    banner ocr change-run {k}/{n_runs} ({time.time() - t0:.0f}s)", end="", flush=True)
    else:
        coarse = list(range(0, n, step))
        for k, i in enumerate(coarse):
            ocr.text(i)
            if k % 50 == 0 and ocr.calls:
                print(f"\n    banner ocr coarse {k}/{len(coarse)} ({time.time() - t0:.0f}s)", end="", flush=True)
        for a, b in zip(coarse, coarse[1:]):
            if ocr.text(a) != ocr.text(b):
                for i in range(a, b + 1):
                    ocr.text(i)
        # 1초 시퀀스 (OCR 안 한 초는 직전 값으로 채움)
        last = ""
        for i in range(n):
            if i in ocr.cache:
                last = ocr.cache[i]
            seq.append(last)
    ocr.save()
    states = stable_states(seq, min_stable)
    items = transitions(states)
    return Segments("item_banner", items, meta={
        "mode": mode, "step": step, "min_stable": min_stable, "ocr_calls": ocr.calls, "ocr_cached": len(ocr.cache), "n_runs": n_runs,
        "n_frames": n, "n_states": len(states), "elapsed_s": round(time.time() - t0, 1),
    })
