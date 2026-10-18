"""쇼츠 후보 생성기 (Phase 1). 설계: docs/ARCHITECTURE.md 8.2 ~ 8.3.

임계 초과 구간이 아니라 **페이오프 앵커**에서 창을 만든다.
  앵커 = item_banner(append) > edit_emphasis(zoom/note) > chat_burst 피크
  창   = [anchor - pre, anchor + post] 의 시작을 말이 시작되는 지점, 끝을 말이 끝나는 지점(+0.3s)에 스냅. 두 variant: short / story
  점수 = Payoff .35 + Reaction .25 + Chat .15 + Completeness .15 + Hook .10 − 감점(컷 수·길이)

출력 후보마다 편집 지시가 붙는다: hook_mode(cold_open | payoff_flash), overlay_text(배너에서 읽은 아이템명), 앵커 시각.
정답이 쌓이면 가중치는 hit@K 로 조정한다 (evaluate_shorts).
"""
from __future__ import annotations

import json
import re
import wave
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

from .timeline import Curve, Segments, fmt_time

WEIGHTS = {"payoff": 0.35, "reaction": 0.25, "chat": 0.15, "completeness": 0.15, "hook": 0.10}
VARIANTS = {"short": {"pre": 5.0, "post": 12.0}, "story": {"pre": 12.0, "post": 22.0}}
MIN_LEN, MAX_LEN = 15.0, 60.0


@dataclass
class ShortCandidate:
    start: float
    end: float
    anchor: float
    variant: str
    score: float = 0.0
    axes: dict = field(default_factory=dict)
    evidence: dict = field(default_factory=dict)
    hook_mode: str = "cold_open"
    overlay_text: str = ""            # 배너 OCR 원문 (사전 매칭용)
    hook_lines: list = field(default_factory=list)   # 상단 자막 제안 [인용 대사, 아이템 맥락]

    @property
    def duration(self) -> float:
        return self.end - self.start


# ---------- 오디오: 발화 구간 ----------
def speech_segments(wav: Path, frame: float = 0.02, on_db: float = 12.0, off_db: float = 8.0,
                    min_gap: float = 0.25, min_len: float = 0.2) -> list[tuple[float, float]]:
    """에너지 VAD. 바닥 소음(p10) 대비 on_db 이상이면 발화 시작, off_db 아래로 떨어지면 끝(히스테리시스).
    min_gap 미만의 끊김은 같은 발화로 합친다. 마스터링된 편집본에서도 문장 사이 쉼(0.4~0.9s)을 잡는다."""
    with wave.open(str(wav), "rb") as w:
        sr, n = w.getframerate(), w.getnframes()
        x = np.frombuffer(w.readframes(n), dtype=np.int16).astype(np.float32) / 32768.0
    hop = int(sr * frame)
    m = len(x) // hop
    db = 20 * np.log10(np.sqrt((x[: m * hop].reshape(m, hop) ** 2).mean(axis=1) + 1e-12) + 1e-9)
    floor = float(np.percentile(db, 10))
    raw, on, st = [], False, 0
    for i, v in enumerate(db):
        if not on and v > floor + on_db:
            on, st = True, i
        elif on and v < floor + off_db:
            on = False
            raw.append([st * frame, i * frame])
    if on:
        raw.append([st * frame, m * frame])
    out: list[list[float]] = []
    for a, b in raw:
        if out and a - out[-1][1] < min_gap:
            out[-1][1] = b
        else:
            out.append([a, b])
    return [(a, b) for a, b in out if b - a >= min_len]


def pauses_from(segs: list[tuple[float, float]], min_pause: float = 0.35) -> list[tuple[float, float]]:
    return [(segs[i][1], segs[i + 1][0]) for i in range(len(segs) - 1) if segs[i + 1][0] - segs[i][1] >= min_pause]


MARGIN = 0.3   # 발화 경계 바깥 여유(초)


def snap_end(e0: float, segs: list[tuple[float, float]], max_fwd: float = 8.0, max_back: float = 3.0) -> float:
    """끝점을 말이 끝나는 지점으로. e0 가 발화 중이면 그 발화의 끝(+MARGIN), 쉼이면 직전 발화 끝(+MARGIN)."""
    for a, b in segs:
        if a <= e0 <= b:
            if b - e0 <= max_fwd:
                return b + MARGIN
            if e0 - a <= max_back:            # 너무 긴 발화: 차라리 그 발화 앞에서 끊는다
                return max(a - MARGIN, 0.0)
            return e0
    prev = [b for _, b in segs if b <= e0]
    if prev and e0 - prev[-1] <= 1.5:
        return prev[-1] + MARGIN
    return e0


def snap_start(s0: float, segs: list[tuple[float, float]], max_back: float = 4.0, max_fwd: float = 3.0) -> float:
    """시작점을 말이 시작되는 지점으로. s0 가 발화 중이면 그 발화의 시작(−MARGIN), 쉼이면 다음 발화 시작(−MARGIN)."""
    for a, b in segs:
        if a <= s0 <= b:
            if s0 - a <= max_back:
                return max(a - MARGIN, 0.0)
            nxt = [x for x, _ in segs if x > s0]
            if nxt and nxt[0] - s0 <= max_fwd:
                return max(nxt[0] - MARGIN, 0.0)
            return s0
    nxt = [a for a, _ in segs if a >= s0]
    if nxt and nxt[0] - s0 <= max_fwd:
        return max(nxt[0] - MARGIN, 0.0)
    return s0


def snap(t: float, points: list[float], max_shift: float, direction: int) -> float:
    """t 를 points 중 direction(-1: 앞쪽, +1: 뒤쪽) max_shift 이내의 가장 가까운 점으로."""
    best = None
    for p in points:
        d = (t - p) if direction < 0 else (p - t)
        if 0 <= d <= max_shift and (best is None or d < best[0]):
            best = (d, p)
    return best[1] if best else t


# ---------- 앵커 ----------
def collect_anchors(events: dict[str, Segments], curves: dict[str, Curve], duration: float,
                    chat_pct: float = 97.0, min_gap: float = 10.0) -> list[dict]:
    anchors: list[dict] = []
    for s in events.get("item_banner", Segments("", [])).items:
        if s.label == "append":
            anchors.append({"t": s.start, "kind": "item", "strength": 1.0, "text": s.meta.get("added", "")})
    for s in events.get("edit_emphasis", Segments("", [])).items:
        if s.end >= duration - 8:          # 엔딩 크레딧류
            continue
        anchors.append({"t": s.start, "kind": s.label, "strength": 0.8 if s.label == "zoom" else 0.7,
                        "text": "", "span": [s.start, s.end]})
    for s in events.get("speech_keyword", Segments("", [])).items:
        if s.label in ("강", "득템"):
            anchors.append({"t": s.start, "kind": "speech", "strength": 0.6 * float(s.score or 1.0),
                            "text": "", "word": s.meta.get("word", "")})
    if "chat_burst" in curves:
        c = curves["chat_burst"]; v = c.as_array(); thr = np.percentile(v, chat_pct)
        for i in range(1, len(v) - 1):
            if v[i] >= thr and v[i] >= v[i - 1] and v[i] >= v[i + 1]:
                anchors.append({"t": i * c.hop, "kind": "chat", "strength": 0.5, "text": ""})
    # 가까운 앵커 병합: 강한 것 유지, 종류는 합집합
    anchors.sort(key=lambda a: a["t"])
    merged: list[dict] = []
    for a in anchors:
        if merged and a["t"] - merged[-1]["t"] <= min_gap:
            m = merged[-1]
            m["kinds"].add(a["kind"])
            if a["strength"] > m["strength"]:
                m.update(t=a["t"], kind=a["kind"], strength=a["strength"])
            if a.get("text") and not m.get("text"):
                m["text"] = a["text"]
        else:
            merged.append({**a, "kinds": {a["kind"]}})
    return merged


# ---------- 점수 ----------
def _curve_max(curve: Curve | None, a: float, b: float) -> float:
    if curve is None:
        return 0.0
    v = curve.as_array(); i, j = int(a / curve.hop), int(np.ceil(b / curve.hop)) + 1
    return float(v[max(0, i):max(1, j)].max()) if j > i else 0.0


def score_candidate(c: ShortCandidate, anchor: dict, events: dict[str, Segments], curves: dict[str, Curve],
                    cuts: list[float], pauses: list[tuple[float, float]], chat_ref: float, duration: float) -> None:
    items = [s for s in events.get("item_banner", Segments("", [])).items
             if s.label == "append" and c.start <= s.start <= c.end]
    emph = [s for s in events.get("edit_emphasis", Segments("", [])).items
            if s.start < c.end and s.end > c.start and s.end < duration - 8]

    payoff = 1.0 if items else 0.0
    reaction = 0.0
    if any(s.label == "zoom" for s in emph):
        reaction = max(reaction, 0.6)        # 편집자의 줌 = 강조 신호지만 날것 리액션은 아님
    if any(s.label == "note" for s in emph):
        reaction = max(reaction, 0.6)
    kw_after = [k for k in events.get("speech_keyword", Segments("", [])).items if c.anchor - 2.0 <= k.start <= c.end]
    if any(k.label == "강" for k in kw_after):
        reaction = max(reaction, 1.0)
    elif any(k.label in ("중", "득템") for k in kw_after):
        reaction = max(reaction, 0.7)
    aud = curves.get("audio_loudness")
    if aud is not None:
        z = (aud.as_array() - aud.as_array().mean()) / (aud.as_array().std() or 1.0)
        zc = Curve("z", aud.hop, [float(x) for x in z])
        reaction = max(reaction, float(np.clip(_curve_max(zc, c.anchor, c.end) / 3.0, 0, 1)) * 0.6)
    chat = float(np.clip(_curve_max(curves.get("chat_burst"), c.start, c.end) / (chat_ref or 1.0), 0, 1))

    # 완결성: 앵커 앞뒤로 비(非)줌 게임플레이 ≥3s, 경계가 쉼/컷에 닿았는가
    before_ok = (c.anchor - c.start) >= 3.0 and not any(s.start <= c.start + 3 <= s.end and s.label == "zoom" for s in emph)
    after_ok = (c.end - c.anchor) >= 3.0
    on_pause = lambda t: any(p0 - 0.3 <= t <= p1 + 0.3 for p0, p1 in pauses) or any(abs(t - k) <= 0.3 for k in cuts)
    completeness = (0.5 if before_ok else 0.0) + (0.3 if after_ok else 0.0) + (0.1 if on_pause(c.start) else 0.0) + (0.1 if on_pause(c.end) else 0.0)

    # 훅: 첫 2초에 에너지/이벤트가 있는가, 줌·메모장·무음으로 시작하면 감점
    head_zoom = any(s.start <= c.start + 1 <= s.end for s in emph)
    head_quiet = any(p0 <= c.start and p1 >= c.start + 1.5 for p0, p1 in pauses)
    head_energy = aud is not None and _curve_max(zc, c.start, c.start + 2.0) > 0.0
    hook = 0.0 if head_zoom or head_quiet else (1.0 if head_energy or (c.anchor - c.start) <= 3.0 else 0.5)

    n_cuts = sum(1 for k in cuts if c.start + 0.5 < k < c.end - 0.5)
    penalty = 0.05 * max(0, n_cuts - 2)
    if not (MIN_LEN <= c.duration <= MAX_LEN):
        penalty += 0.2

    # 임팩트 게이트 (친구 피드백 2026-10-18 "임팩트 없음"): 리액션도 채팅 반응도 약하면 득템이 있어도 감점
    if reaction < 0.3 and chat < 0.5:
        penalty += 0.15
    axes = {"payoff": payoff, "reaction": round(reaction, 2), "chat": round(chat, 2),
            "completeness": round(completeness, 2), "hook": hook, "penalty": round(penalty, 2)}
    c.axes = axes
    c.score = round(sum(WEIGHTS[k] * axes[k] for k in WEIGHTS) - penalty, 3)
    c.evidence = {"anchor_kinds": sorted(anchor["kinds"]), "items": [s.meta.get("added", "") for s in items],
                  "emphasis": [s.label for s in emph], "n_cuts": n_cuts,
                  "chat_peak": round(_curve_max(curves.get("chat_burst"), c.start, c.end), 3)}
    c.overlay_text = (items[0].meta.get("added", "") if items else anchor.get("text", "")) or ""
    c.hook_mode = "payoff_flash" if (c.anchor - c.start) > 6.0 and payoff else "cold_open"


KW_RANK = {"강": 3.0, "득템": 2.5, "중": 1.5, "약": 0.5}
PUNCT = ",.!?~ "


def _trim_quote(text: str, limit: int = 20) -> str:
    t = text.strip().strip("\"'")
    if len(t) <= limit:
        return t
    cut = max((t.rfind(ch, 0, limit + 1) for ch in ",. ?!"), default=-1)
    t = t[:cut] if cut >= 8 else t[:limit]
    return t.rstrip(PUNCT) + "…"


def _load_chat_keywords() -> dict:
    import yaml
    p = Path(__file__).resolve().parent.parent / "games" / "common.yaml"
    return ((yaml.safe_load(p.read_text(encoding="utf-8")) or {}).get("chat_keywords") or {}) if p.exists() else {}


OCR_FIX = {"혈": "헐", "슷츠": "쇼츠", "솟츠": "쇼츠"}


def clean_chat(text: str) -> str:
    """채팅 OCR 표시용 교정: 알려진 오인식 치환, 숫자/단위 뒤·문장 끝 감탄사 앞 띄어쓰기, 중복 공백 정리."""
    for a, b in OCR_FIX.items():
        text = text.replace(a, b)
    inter = r"(헐|대박|미쳤다|미쳤네|실화|ㄷㄷ+|ㅋㅋ+|마이갓|레전드)"
    text = re.sub(r"(?<=\S)" + inter + r"$", r" \1", text)                     # 끝에 붙은 감탄사
    text = re.sub(r"(?<=[0-9A-Za-z원룬개])" + inter, r" \1", text)               # 숫자/단위 뒤
    return re.sub(r"\s+", " ", text).strip()


def best_chat_quote(c: ShortCandidate, chat: Segments | None, pre: float = 8.0) -> tuple[str, float]:
    """창 [anchor−pre, end] 안의 채팅 중 반응 어휘 가중치가 가장 큰 메시지 (닉네임 제외). (텍스트, 점수)"""
    if not chat:
        return "", 0.0
    kws = _load_chat_keywords()
    best, best_s = "", 0.0
    for m in chat.items:
        if not (c.anchor - pre <= m.start <= c.end):
            continue
        text = clean_chat(m.meta.get("text", ""))
        sc = sum(float(ent.get("weight", 0.3)) for ent in kws.values() if any(w in text for w in ent.get("words", [])))
        sc += 0.2 if m.start >= c.anchor else 0.0
        sc -= 0.01 * max(0, len(text) - 20)
        if sc > best_s and 2 <= len(text) <= 40:
            best, best_s = text, sc
    return best, best_s


def suggest_hook(c: ShortCandidate, transcript: dict | None, kw_events: Segments | None, lexicon=None,
                 chat: Segments | None = None) -> list[str]:
    """[인용, 아이템 맥락]. 인용 = 줌/채팅 앵커면 채팅 원문 우선, 아니면 전사 대사. 둘 다 있으면 점수 높은 쪽."""
    quote = ""
    if transcript:
        segs = [sg for sg in transcript.get("segments", []) if sg["end"] >= c.anchor - 3.0 and sg["start"] <= c.end and sg["text"].strip()]
        kws = [k for k in (kw_events.items if kw_events else []) if c.anchor - 3.0 <= k.start <= c.end]
        def score(sg):
            w = sum(KW_RANK.get(k.label, 0.5) for k in kws if sg["start"] - 0.2 <= k.start <= sg["end"] + 0.2)
            near = 1.0 if sg["start"] >= c.anchor else 0.3          # 앵커 이후 대사 선호
            return w + near - 0.01 * max(0, len(sg["text"]) - 20)
        if segs:
            best = max(segs, key=score)
            quote = _trim_quote(best["text"])
            quote_score = score(best)
        else:
            quote_score = 0.0
    else:
        quote_score = 0.0
    chat_q, chat_s = best_chat_quote(c, chat)
    kinds = set(c.evidence.get("anchor_kinds", []))
    # 채팅 원문 우선 조건: 편집자가 채팅을 강조한 줌 구간이거나, 전사에 쓸 만한 대사가 없을 때.
    # 그 외엔 스트리머 본인 리액션(전사)이 더 자연스럽다.
    if chat_q and ("zoom" in kinds or not quote or (chat_s >= 1.0 and quote_score < 1.5)):
        quote = "“" + _trim_quote(chat_q, 22) + "”"
    ctx = ""
    heads = []
    for tok in c.evidence.get("items", []):
        for piece in tok.split(","):
            piece = piece.strip()
            if not piece:
                continue
            m = lexicon.lookup(piece) if lexicon else None
            if m and m.head and m.kind not in ("meta", "unknown", None):
                heads.append(m.head)
    heads = list(dict.fromkeys(heads))
    if heads:
        ctx = " · ".join(heads[:2]) + " 직득!"
    elif "zoom" in c.evidence.get("emphasis", []):
        ctx = "채팅 폭발"
    elif c.evidence.get("anchor_kinds") == ["chat"]:
        ctx = "채팅 반응"
    lines = [l for l in (quote, ctx) if l]
    return lines or ["하이라이트"]


def make_shorts(cache: Path, events: dict[str, Segments], curves: dict[str, Curve], duration: float,
                k: int = 5, variants: dict | None = None) -> list[ShortCandidate]:
    variants = variants or VARIANTS
    cuts_p = cache / "cuts.json"
    cuts = json.loads(cuts_p.read_text()) if cuts_p.exists() else []
    tr_p = cache / "transcript.json"
    if tr_p.exists():                                   # 전사가 있으면 단어/세그먼트 경계가 더 정확하다
        from .transcribe import speech_segments_from_transcript
        segs = speech_segments_from_transcript(json.loads(tr_p.read_text(encoding="utf-8")))
    else:
        segs = speech_segments(cache / "audio.wav") if (cache / "audio.wav").exists() else []
    pauses = pauses_from(segs)
    chat_ref = float(np.percentile(curves["chat_burst"].as_array(), 99)) if "chat_burst" in curves else 1.0

    anchors = collect_anchors(events, curves, duration)
    out: list[ShortCandidate] = []
    for a in anchors:
        for vname, v in variants.items():
            s0, e0 = max(0.0, a["t"] - v["pre"]), min(duration, a["t"] + v["post"])
            s = snap_start(s0, segs)
            s = snap(s, cuts, 1.0, -1)                       # 1초 안에 장면 컷이 있으면 컷에서 시작 (더 깨끗)
            e = snap_end(e0, segs)
            # 끝점 직후(≤3s)에 리액션/득템 대사가 시작하면 그 대사까지 포함 — "와, 뭐야!" 를 잘라먹지 않도록
            for kw in events.get("speech_keyword", Segments("", [])).items:
                if kw.label in ("강", "중", "득템") and e < kw.start <= e + 3.0:
                    seg_end = next((b for a_, b in segs if a_ <= kw.start <= b), kw.start + 1.5)
                    if seg_end + MARGIN - s <= MAX_LEN:
                        e = seg_end + MARGIN
                    break
            if e - s < MIN_LEN:                               # 짧으면 다음 발화 끝까지
                nxt = [b for _, b in segs if b + MARGIN > s + MIN_LEN]
                e = min(duration, (nxt[0] + MARGIN) if nxt else s + MIN_LEN)
            if e - s > MAX_LEN:                               # 길면 MAX 안의 마지막 발화 끝까지
                prv = [b for _, b in segs if b + MARGIN <= s + MAX_LEN]
                e = (prv[-1] + MARGIN) if prv and prv[-1] + MARGIN > s + MIN_LEN else s + MAX_LEN
            e = min(duration, e)
            c = ShortCandidate(round(s, 2), round(e, 2), a["t"], vname)
            score_candidate(c, a, events, curves, cuts, pauses, chat_ref, duration)
            out.append(c)
    # 같은 variant 끼리 IoU > 0.5 중복 제거 (높은 점수 유지)
    out.sort(key=lambda c: -c.score)
    kept: list[ShortCandidate] = []
    for c in out:
        dup = False
        for o in kept:
            if o.variant != c.variant:
                continue
            inter = max(0.0, min(c.end, o.end) - max(c.start, o.start))
            union = max(c.end, o.end) - min(c.start, o.start)
            if union > 0 and inter / union > 0.5:
                dup = True; break
        if not dup:
            kept.append(c)
    # 순간(moment) 단위 중복 제거 (친구 피드백 2026-10-18 "중복"): 한 순간에서는 variant 를 통틀어 점수 최고 1개만.
    # 같은 순간 = 앵커 간격 ≤ moment_gap 또는 창이 1/3 이상 겹침. 드랍→리액션이 이어지는 긴 창이 리액션만 있는 창보다 선호되도록
    # story 에 +0.02 타이브레이크.
    moment_gap = 45.0
    # (a) 클러스터링: 앵커 간격 ≤ moment_gap 또는 창 겹침 ≥ 1/3
    clusters: list[list[ShortCandidate]] = []
    for c in sorted(kept, key=lambda c: c.anchor):
        for cl in clusters:
            if any(abs(c.anchor - o.anchor) <= moment_gap or
                   max(0.0, min(c.end, o.end) - max(c.start, o.start)) >= 0.33 * min(c.duration, o.duration) for o in cl):
                cl.append(c); break
        else:
            clusters.append([c])
    # (b) 대표: 순간의 '원인'(가장 이른 득템 앵커)을 담은 창 중 점수 최고. 없으면 점수 최고.
    #     친구 피드백 2026-10-18: 같은 지존참 순간에서 드랍→리액션 전체(2:38~3:17)를 고르고 줌 리액션만 있는 창은 거절.
    moments: list[ShortCandidate] = []
    for cl in clusters:
        cause = min((c.anchor for c in cl if "item" in c.evidence.get("anchor_kinds", [])), default=None)
        pool = [c for c in cl if cause is not None and c.start <= cause <= c.end] or cl
        best = max(pool, key=lambda c: (c.score + (0.02 if c.variant == "story" else 0.0)))
        moments.append(best)
    moments.sort(key=lambda c: -c.score)
    final: list[ShortCandidate] = moments[:k]
    # 참고용: 같은 순간의 다른 variant 는 meta 로만 남긴다 (index 에서 '대안' 으로 표시 가능)
    for c in final:
        c.evidence["alternatives"] = [f"{o.variant} {fmt_time(o.start)}-{fmt_time(o.end)} {o.score:.2f}" for o in kept
                                      if o is not c and (abs(o.anchor - c.anchor) <= moment_gap)][:3]
    # 상단 자막 제안: 전사 대사 + 사전 아이템명
    tr = json.loads(tr_p.read_text(encoding="utf-8")) if tr_p.exists() else None
    try:
        from .lexicon import Lexicon
        lex = Lexicon()
    except Exception:
        lex = None
    for c in final:
        c.hook_lines = suggest_hook(c, tr, events.get("speech_keyword"), lex, events.get("chat_text"))
    return final


def save_shorts(cands: list[ShortCandidate], path: Path) -> None:
    path.write_text(json.dumps([asdict(c) for c in cands], ensure_ascii=False, indent=1), encoding="utf-8")


def pretty(cands: list[ShortCandidate]) -> str:
    lines = ["[moments]  (한 순간에 한 클립, variant 혼합. 대안은 evidence.alternatives)"]
    if True:
        for i, c in enumerate(cands, 1):
            ax = c.axes
            lines.append(f"  {i}. [{c.variant}] {fmt_time(c.start)}-{fmt_time(c.end)} ({c.duration:.0f}s)  score={c.score:.2f}  "
                         f"anchor={fmt_time(c.anchor)} {'+'.join(c.evidence['anchor_kinds'])}  "
                         f"P{ax['payoff']:.0f} R{ax['reaction']:.1f} C{ax['chat']:.1f} K{ax['completeness']:.1f} H{ax['hook']:.1f} -{ax['penalty']:.1f}"
                         f"  cuts={c.evidence['n_cuts']}  hook={c.hook_mode}  자막={' / '.join(c.hook_lines)}")
    return "\n".join(lines)
