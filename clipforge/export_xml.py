"""Premiere Pro 용 xmeml(FCP7 XML v5) 출력 (L4, 9단계).

두 가지 시퀀스를 한 파일에 담는다.
  review : 원본 해상도·프레임레이트. V1 = 원본 전체 1클립, V2 = 후보 세그먼트만 원본 시각 위치에(갭 유지),
           시퀀스 마커 = 쇼츠 후보 앵커(이름 "score|근거"). 친구는 마커로 훑고 V2 에서 리플 삭제.
  shorts : 후보마다 1080×1920 시퀀스. 원본 클립에 Basic Motion(scale 50%, center 키프레임)으로 세로 크롭을 재현.
           크롭 중심은 ui_state 를 따라 컷처럼 점프(렌더와 동일 규칙).

AutoEditor 사례에서 배운 것: xmeml v5 를 ElementTree 로 직접 쓴다. 컷을 이어붙이지 않는다(원본 타임라인 유지).
pathurl 은 file://localhost/C:/... 형식, <file> 은 첫 등장에만 본문, 이후엔 id 참조.
검증: OpenTimelineIO fcp_xml 어댑터로 읽어 트랙·클립 수를 확인한다 (Premiere 실제 임포트는 친구 쪽에서).
Basic Motion center 단위는 "시퀀스 폭/높이에 대한 비율" 로 가정 — Premiere 에서 1회 확인 필요 (9.x 메모).
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from xml.dom import minidom

from .render import CX_BY_STATE, GAME_H, TOP_H
from .shorts import ShortCandidate
from .timeline import Segments, fmt_time


def _rate(fps: float) -> tuple[int, bool]:
    tb = round(fps)
    ntsc = abs(fps - tb) > 0.01          # 59.94 → 60/NTSC, 60 → 60
    return tb, ntsc


def _sub(parent, tag, text=None, **kw):
    e = ET.SubElement(parent, tag, **kw)
    if text is not None:
        e.text = str(text)
    return e


def _rate_el(parent, tb: int, ntsc: bool):
    r = _sub(parent, "rate")
    _sub(r, "timebase", tb)
    _sub(r, "ntsc", "TRUE" if ntsc else "FALSE")
    return r


def _pathurl(p: Path) -> str:
    s = str(p.resolve()).replace("\\", "/")
    return "file://localhost/" + s


class XmemlWriter:
    def __init__(self, meta: dict):
        self.meta = meta
        self.fps = float(meta["fps"])
        self.tb, self.ntsc = _rate(self.fps)
        self.src = Path(meta["source"])
        self.total = int(round(meta["duration"] * self.fps))
        self.root = ET.Element("xmeml", version="5")
        self._file_written = False
        self._ids = 0

    def fr(self, sec: float) -> int:
        return int(round(sec * self.fps))

    def _id(self, prefix: str) -> str:
        self._ids += 1
        return f"{prefix}-{self._ids}"

    def _file_el(self, parent):
        f = _sub(parent, "file", id="file-src")
        if self._file_written:
            return f
        self._file_written = True
        _sub(f, "name", self.src.name)
        _sub(f, "pathurl", _pathurl(self.src))
        _rate_el(f, self.tb, self.ntsc)
        _sub(f, "duration", self.total)
        tc = _sub(f, "timecode"); _rate_el(tc, self.tb, self.ntsc); _sub(tc, "string", "00:00:00:00"); _sub(tc, "frame", 0)
        _sub(tc, "displayformat", "DF" if self.ntsc else "NDF")
        media = _sub(f, "media")
        v = _sub(media, "video"); sc = _sub(v, "samplecharacteristics")
        _sub(sc, "width", self.meta["width"]); _sub(sc, "height", self.meta["height"])
        _rate_el(sc, self.tb, self.ntsc); _sub(sc, "pixelaspectratio", "square")
        if self.meta.get("has_audio", True):
            a = _sub(media, "audio"); _sub(a, "channelcount", 2)
        return f

    def _clipitem(self, track, name: str, src_in: float, src_out: float, seq_start: float, mediatype: str,
                  filters: list | None = None, markers: list | None = None):
        c = _sub(track, "clipitem", id=self._id("clip"))
        _sub(c, "name", name)
        _rate_el(c, self.tb, self.ntsc)
        i, o = self.fr(src_in), self.fr(src_out)
        st = self.fr(seq_start)
        _sub(c, "duration", self.total)
        _sub(c, "start", st); _sub(c, "end", st + (o - i))
        _sub(c, "in", i); _sub(c, "out", o)
        self._file_el(c)
        for flt in filters or []:
            c.append(flt)
        for m in markers or []:
            c.append(m)
        src = _sub(c, "sourcetrack"); _sub(src, "mediatype", mediatype); _sub(src, "trackindex", 1)
        return c

    def _seq(self, name: str, width: int, height: int, duration_frames: int):
        s = _sub(self.root, "sequence", id=self._id("seq"))
        _sub(s, "name", name)
        _sub(s, "duration", duration_frames)
        _rate_el(s, self.tb, self.ntsc)
        tc = _sub(s, "timecode"); _rate_el(tc, self.tb, self.ntsc); _sub(tc, "string", "00:00:00:00"); _sub(tc, "frame", 0)
        _sub(tc, "displayformat", "DF" if self.ntsc else "NDF")
        media = _sub(s, "media")
        video = _sub(media, "video")
        fmt = _sub(video, "format"); sc = _sub(fmt, "samplecharacteristics")
        _sub(sc, "width", width); _sub(sc, "height", height); _rate_el(sc, self.tb, self.ntsc)
        _sub(sc, "pixelaspectratio", "square")
        audio = _sub(media, "audio")
        return s, video, audio

    @staticmethod
    def _marker(parent, name: str, comment: str, frame: int, out: int = -1):
        m = _sub(parent, "marker"); _sub(m, "name", name); _sub(m, "comment", comment)
        _sub(m, "in", frame); _sub(m, "out", out)
        return m

    # ---------- review sequence ----------
    def review(self, name: str, candidates: Segments, shorts: list[ShortCandidate]):
        s, video, audio = self._seq(name, self.meta["width"], self.meta["height"], self.total)
        v1 = _sub(video, "track")
        self._clipitem(v1, self.src.name, 0.0, self.meta["duration"], 0.0, "video")
        v2 = _sub(video, "track")
        for i, seg in enumerate(candidates.items, 1):
            ev = seg.meta.get("evidence") or {}
            nm = f"{i:02d} {fmt_time(seg.start)} s={seg.score:.2f}"
            self._clipitem(v2, nm, seg.start, seg.end, seg.start, "video")
        if self.meta.get("has_audio", True):
            a1 = _sub(audio, "track")
            self._clipitem(a1, self.src.name, 0.0, self.meta["duration"], 0.0, "audio")
        for c in shorts:
            why = "+".join(c.evidence.get("anchor_kinds", []))
            self._marker(s, f"{c.variant} {c.score:.2f} {why}",
                         f"{fmt_time(c.start)}-{fmt_time(c.end)} anchor {fmt_time(c.anchor)} hook={c.hook_mode} text={c.overlay_text}",
                         self.fr(c.anchor))
        return s

    # ---------- shorts sequences ----------
    def _basic_motion(self, c: ShortCandidate, ui: list[dict] | None, cx_default: float = 0.5):
        """세로 1080×1920 시퀀스 안에서 원본(3840×2160)을 50% 로 줄여 정사각 크롭 영역이 중단(400~1480px)에 오게.
        center 는 시퀀스 치수 비율 가정. 크롭 중심 cx(원본 폭 비율) → 가로 이동 = (0.5 − cx) × 원본폭 × scale / 시퀀스폭."""
        W, H = self.meta["width"], self.meta["height"]
        scale = GAME_H / H * 100.0                         # 1080/2160 → 50
        seq_w, seq_h = 1080, 1920
        scaled_w = W * scale / 100.0
        vert = ((TOP_H + GAME_H / 2) - seq_h / 2) / seq_h  # 중단 영역의 중심 − 시퀀스 중심

        def horiz(cx: float) -> float:
            return (0.5 - cx) * scaled_w / seq_w

        flt = ET.Element("filter"); eff = _sub(flt, "effect")
        _sub(eff, "name", "Basic Motion"); _sub(eff, "effectid", "basic"); _sub(eff, "effectcategory", "motion")
        _sub(eff, "effecttype", "motion"); _sub(eff, "mediatype", "video")
        p = _sub(eff, "parameter"); _sub(p, "parameterid", "scale"); _sub(p, "name", "Scale")
        _sub(p, "valuemin", 0); _sub(p, "valuemax", 1000); _sub(p, "value", round(scale, 3))
        p = _sub(eff, "parameter"); _sub(p, "parameterid", "center"); _sub(p, "name", "Center")
        # 키프레임: ui_state 전환마다 점프 (렌더의 crop_track 과 같은 규칙)
        states = []
        t = c.start
        cur = None
        step = 0.1
        while t <= c.end + 1e-6:
            cx = cx_default
            for u in ui or []:
                if u["start"] <= t < u["end"] and u["label"] in CX_BY_STATE:
                    cx = CX_BY_STATE[u["label"]]; break
            if cx != cur:
                states.append((t, cx)); cur = cx
            t += step
        if len(states) <= 1:
            v = _sub(p, "value"); _sub(v, "horiz", round(horiz(states[0][1] if states else cx_default), 4)); _sub(v, "vert", round(vert, 4))
        else:
            for k, (t, cx) in enumerate(states):
                for when in ([self.fr(t - c.start)] if k == 0 else [self.fr(t - c.start) - 1, self.fr(t - c.start)]):
                    kf = _sub(p, "keyframe"); _sub(kf, "when", max(0, when))
                    v = _sub(kf, "value"); prev_cx = states[k - 1][1] if (k and when == self.fr(t - c.start) - 1) else cx
                    _sub(v, "horiz", round(horiz(prev_cx), 4)); _sub(v, "vert", round(vert, 4))
        return flt

    def short(self, c: ShortCandidate, rank: int, ui: list[dict] | None):
        dur = self.fr(c.end) - self.fr(c.start)
        name = f"short {c.variant} {rank:02d} {fmt_time(c.start)} {c.score:.2f}"
        s, video, audio = self._seq(name, 1080, 1920, dur)
        v1 = _sub(video, "track")
        mk = [self._marker_el(f"anchor {fmt_time(c.anchor)}", f"{'+'.join(c.evidence.get('anchor_kinds', []))} text={c.overlay_text}",
                              self.fr(c.anchor) - self.fr(c.start))]
        self._clipitem(v1, self.src.name, c.start, c.end, 0.0, "video", filters=[self._basic_motion(c, ui)], markers=mk)
        _sub(video, "track")      # V2: 상단 훅 텍스트 자리 (빈 트랙)
        if self.meta.get("has_audio", True):
            a1 = _sub(audio, "track")
            self._clipitem(a1, self.src.name, c.start, c.end, 0.0, "audio")
        return s

    def _marker_el(self, name, comment, frame):
        m = ET.Element("marker"); _sub(m, "name", name); _sub(m, "comment", comment); _sub(m, "in", frame); _sub(m, "out", -1)
        return m

    def write(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = ET.tostring(self.root, encoding="unicode")
        pretty = minidom.parseString(raw).toprettyxml(indent=" ")
        pretty = pretty.replace('<?xml version="1.0" ?>', '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>')
        path.write_text(pretty, encoding="utf-8")
        return path


def export_xml(meta: dict, candidates: Segments, shorts: list[ShortCandidate], ui: list[dict] | None,
               out_dir: Path, vid: str, k: int = 3) -> list[Path]:
    paths = []
    w = XmemlWriter(meta)
    w.review(f"{vid} review", candidates, shorts)
    paths.append(w.write(out_dir / f"{vid}_review.xml"))
    w2 = XmemlWriter(meta)
    by_variant: dict[str, int] = {}
    for c in shorts:
        by_variant[c.variant] = by_variant.get(c.variant, 0) + 1
        if by_variant[c.variant] > k:
            continue
        w2.short(c, by_variant[c.variant], ui)
    paths.append(w2.write(out_dir / f"{vid}_shorts.xml"))
    return paths
