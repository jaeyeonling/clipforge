"""CLI 진입점.

  python -m clipforge.run prep     videos/foo.mp4 [--game d2r] [--proxy] [--force]   # 전처리 캐시 (단일 패스)
  python -m clipforge.run signals  foo                     # 등록된 신호 전부 계산
  python -m clipforge.run cands    foo [--threshold 1.5] [--w audio_loudness=1 --w frame_motion=0.3]
  python -m clipforge.run eval     foo                     # labels/foo.csv 와 비교
  python -m clipforge.run export   foo [--shorts --k 3]    # 후보 클립 mp4 (--shorts: 9:16 쇼츠 초안 review/foo/shorts/)
  python -m clipforge.run sweep    foo                     # threshold 를 바꿔가며 recall/coverage 표
  python -m clipforge.run shorts   foo [--k 5]             # 쇼츠 후보 (앵커→창→점수), Phase 1
  python -m clipforge.run weaklabel foo [--title ...]      # 제목→배너 매칭 약한 정답 labels/foo.shorts.csv
  python -m clipforge.run eval     foo --shorts            # hit@K / MRR
  python -m clipforge.run harvest  foo --shorts            # review/foo/shorts/keep/ → labels (label=keep)
  python -m clipforge.run lexicon  foo                     # 배너 토큰 사전 매칭률 + 미매칭 → reports/foo_tokens.md
  python -m clipforge.run xml      foo [--k 3]             # Premiere xmeml: premiere/foo_review.xml, foo_shorts.xml
  python -m clipforge.run transcribe foo [--backend ...]   # Whisper 전사 → cache/foo/transcript.json (speech_keyword, 경계 스냅)

<video_id> 는 영상 파일명(확장자 제외).
"""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from .candidates import DEFAULT_WEIGHTS, make_candidates
from .eval_shorts import evaluate_shorts
from .lexicon import Lexicon, banner_tokens, report_md
from .evaluate import evaluate
from .export_xml import export_xml
from .preprocess import preprocess
from .profiles import load_profile
from .render import render_shorts
from .shorts import ShortCandidate, make_shorts, pretty as shorts_pretty, save_shorts
from .signals import REGISTRY, run_signal
from .timeline import Curve, Segment, Segments, fmt_time
from .transcribe import transcribe
from .weaklabel import load_episode, load_slang, match_banner, title_keywords, write_weak_labels

ROOT = Path(__file__).resolve().parent.parent
CACHE, LABELS, REVIEW = ROOT / "cache", ROOT / "labels", ROOT / "review"


def load_meta(vid: str) -> dict:
    return json.loads((CACHE / vid / "meta.json").read_text(encoding="utf-8"))


def load_signals(vid: str) -> tuple[dict[str, Curve], dict[str, Segments]]:
    curves, events = {}, {}
    for name in REGISTRY:
        p = CACHE / vid / f"{name}.json"
        if not p.exists():
            continue
        try:
            curves[name] = Curve.load(p)
        except TypeError:
            events[name] = Segments.load(p)
    return curves, events


def load_kernels(vid: str) -> dict[str, dict]:
    meta = load_meta(vid)
    return load_profile(meta.get("game", "d2r")).get("events", {}) or {}


def parse_weights(items: list[str] | None) -> dict[str, float]:
    w = dict(DEFAULT_WEIGHTS)
    for it in items or []:
        k, v = it.split("=")
        w[k] = float(v)
    return w


def cmd_prep(a):
    for v in a.videos:
        preprocess(Path(v), CACHE, a.force, a.game, a.proxy)


def cmd_signals(a):
    for name in REGISTRY:
        print(f"[signal] {name} ...", end=" ", flush=True)
        r = run_signal(name, CACHE / a.vid, a.force)
        print(f"ok ({len(r.values) if isinstance(r, Curve) else len(r.items)} samples)")


def cmd_cands(a) -> Segments:
    meta = load_meta(a.vid)
    curves, events = load_signals(a.vid)
    segs = make_candidates(curves, meta["duration"], parse_weights(a.w), events, load_kernels(a.vid), threshold=a.threshold)
    segs.save(CACHE / a.vid / "candidates.json")
    print(f"[cands] {len(segs.items)} candidates, coverage {segs.total_duration() / meta['duration']:.1%}  signals={segs.meta.get('signals')}")
    for s in segs.items:
        print(f"  {fmt_time(s.start)}-{fmt_time(s.end)}  score={s.score:.2f}")
    return segs


def load_shorts(vid: str) -> list[ShortCandidate]:
    p = CACHE / vid / "shorts.json"
    if not p.exists():
        raise SystemExit(f"{p} 없음 — 먼저 python -m clipforge.run shorts {vid}")
    return [ShortCandidate(**d) for d in json.loads(p.read_text(encoding="utf-8"))]


def cmd_eval(a):
    meta = load_meta(a.vid)
    if a.shorts:
        lab_p = LABELS / f"{a.vid}.shorts.csv"
        if not lab_p.exists():
            raise SystemExit(f"{lab_p} 없음 — weaklabel 또는 harvest --shorts 로 정답을 먼저 만드세요")
        labels = Segments.from_csv(lab_p)
        for rep in evaluate_shorts(load_shorts(a.vid), labels):
            print(rep.pretty())
        return
    labels = Segments.from_csv(LABELS / f"{a.vid}.csv")
    cands = Segments.load(CACHE / a.vid / "candidates.json")
    print(evaluate(cands, labels, meta["duration"]).pretty())


def cmd_weaklabel(a):
    """제목 → 아이템 키워드 → 배너 추가 시각 → labels/<vid>.shorts.csv (label=title_item)."""
    meta = load_meta(a.vid)
    ep = load_episode(a.vid)
    title = a.title or (ep or {}).get("title")
    if not title:
        raise SystemExit(f"제목 없음 — episodes.csv 에 {a.vid} 행을 추가하거나 --title 로 주세요")
    slang = load_slang(meta.get("game", "d2r"))
    kws = title_keywords(title, slang)
    print(f"[weaklabel] title: {title}")
    print(f"  keywords: {[k for k, _ in kws]}")
    banner_p = CACHE / a.vid / "item_banner.json"
    if not banner_p.exists():
        raise SystemExit("item_banner.json 없음 — signals 먼저")
    matches = match_banner(kws, Segments.load(banner_p))
    for m in matches:
        print(f"  {m['keyword']:<8} -> banner append @ {fmt_time(m['t'])}  fuzz={m['score']}  added=\"{m['added'][:30]}\"")
    if not matches:
        print("  (매칭 없음 — slang.yaml 별칭 보강 필요. 배너 토큰:",
              [s.meta.get('added', '')[:20] for s in Segments.load(banner_p).items if s.label == 'append'], ")")
    p = write_weak_labels(a.vid, matches, LABELS, duration=meta["duration"])
    print(f"  -> {p}")


def cmd_sweep(a):
    meta = load_meta(a.vid)
    labels = Segments.from_csv(LABELS / f"{a.vid}.csv")
    curves, events = load_signals(a.vid)
    kernels = load_kernels(a.vid)
    w = parse_weights(a.w)
    print(f"weights={w}")
    print(f"{'thr':>5} {'recall':>7} {'prec':>7} {'cover':>7} {'n':>4}")
    for thr in [0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0]:
        c = make_candidates(curves, meta["duration"], w, events, kernels, threshold=thr)
        r = evaluate(c, labels, meta["duration"])
        print(f"{thr:5.2f} {r.recall:7.1%} {r.precision:7.1%} {r.coverage:7.1%} {r.n_candidates:4d}")


def short_episode_label(title: str) -> str:
    """제목 → 회차 라벨. "(7시간 편집본) 래더 12기 59일차만에 … 【래더12기#42】" → "래더 12기 59일차"."""
    import re as _re
    t = _re.sub(r"^\s*\([^)]*\)\s*", "", title or "")
    m = _re.search(r"(래더\s*\d+기[^0-9]*?\d+\s*(?:~\s*\d+\s*)?일차)", t)
    if m:
        return _re.sub(r"\s+", " ", m.group(1)).strip()
    t = t.split("【")[0].strip(" !")
    return (t[:28] + "…") if len(t) > 28 else t


def cmd_export(a):
    """후보를 mp4 클립으로 잘라 review/<vid>/ 에 저장. 쓸 것은 keep/ 로 옮기면 그게 레이블이 된다.
    --shorts: shorts.json 의 후보를 9:16 세로 초안으로 렌더 (review/<vid>/shorts/)."""
    meta = load_meta(a.vid)
    if a.shorts:
        p = CACHE / a.vid / "shorts.json"
        if not p.exists():
            raise SystemExit(f"{p} 없음 — 먼저 python -m clipforge.run shorts {a.vid}")
        cands = [ShortCandidate(**d) for d in json.loads(p.read_text(encoding="utf-8"))]
        out = REVIEW / a.vid / "shorts"
        (out / "keep").mkdir(parents=True, exist_ok=True)
        ui_p = CACHE / a.vid / "ui_state.json"
        ui = [{"start": s.start, "end": s.end, "label": s.label} for s in Segments.load(ui_p).items] if ui_p.exists() else None
        if ui is None:
            print("  (ui_state.json 없음 — 크롭 중심 고정. signals 를 먼저 돌리면 인벤토리를 따라갑니다)")
        tr_p = CACHE / a.vid / "transcript.json"
        tr = json.loads(tr_p.read_text(encoding="utf-8")) if tr_p.exists() else None
        if tr is None:
            print("  (transcript.json 없음 — 대사 자막 생략. python -m clipforge.run transcribe 로 전사 먼저)")
        chat_p = CACHE / a.vid / "chat_text.json"
        chat = [{"t": s.start, "nick": s.meta.get("nick", ""), "text": s.meta.get("text", "")} for s in Segments.load(chat_p).items] if chat_p.exists() else None
        ep = load_episode(a.vid) or {}
        label = short_episode_label(ep.get("title", "")) or a.vid
        # 기본(card + title) = 확정 포맷 → shorts/. 그 외 실험 렌더는 shorts_<layout|top>/ 로 분리
        if a.layout == "feed":
            out = REVIEW / a.vid / "shorts_feed"; (out / "keep").mkdir(parents=True, exist_ok=True)
        elif a.top != "title":
            out = REVIEW / a.vid / f"shorts_{a.top}"; (out / "keep").mkdir(parents=True, exist_ok=True)
        idx = render_shorts(cands, meta, out, k=a.k, cx=a.cx, ui=ui, ease=a.ease, transcript=tr, subs=not a.no_subs,
                            chat=chat, top_mode=a.top, layout=a.layout, brand=a.brand, episode_label=label)
        print(f"[export --shorts] {len(idx)} drafts -> {out}\n  {out / 'index.md'} 를 보고 keep/ 로 옮기세요.")
        return
    cands = Segments.load(CACHE / a.vid / "candidates.json")
    out = REVIEW / a.vid
    (out / "keep").mkdir(parents=True, exist_ok=True)
    src = meta["source"]
    for i, s in enumerate(cands.items, 1):
        name = f"{i:03d}_{fmt_time(s.start).replace(':', '-')}_{s.score:.1f}.mp4"
        subprocess.run([
            "ffmpeg", "-y", "-v", "error", "-ss", f"{s.start:.2f}", "-to", f"{s.end:.2f}", "-i", src,
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-c:a", "aac", str(out / name),
        ], check=True)
        print(f"  {name}")
    print(f"[export] {len(cands.items)} clips -> {out}\n  쓸 클립은 {out / 'keep'} 로 옮기세요. (python -m clipforge.run harvest {a.vid} 로 레이블 생성)")


def cmd_shorts(a):
    """쇼츠 후보: 앵커 → 창 → 점수. cache/<vid>/shorts.json 저장."""
    meta = load_meta(a.vid)
    curves, events = load_signals(a.vid)
    cands = make_shorts(CACHE / a.vid, events, curves, meta["duration"], k=a.k)
    save_shorts(cands, CACHE / a.vid / "shorts.json")
    print(f"[shorts] {len(cands)} candidates (top {a.k} per variant) -> {CACHE / a.vid / 'shorts.json'}")
    print(shorts_pretty(cands))


def cmd_lexicon(a):
    """배너 append 토큰을 사전(items.json + slang.yaml)에 매칭 → 매칭률 + 미매칭 목록."""
    meta = load_meta(a.vid)
    lex = Lexicon(meta.get("game", "d2r"))
    banner = Segments.load(CACHE / a.vid / "item_banner.json")
    matches = [(t, lex.lookup(tok)) for t, tok in banner_tokens(banner.items)]
    ok = sum(1 for _, m in matches if m.head)
    print(f"[lexicon] {ok}/{len(matches)} tokens matched  (items={len(lex.items)}, slang={len(lex.slang)})")
    for t, m in matches:
        print(f"  {fmt_time(t)}  {m.token:<28} -> {m.head or '?':<14} {m.kind or '':<8} {m.source:<12} {m.score:.0f}  {m.option}")
    out = ROOT / "reports"; out.mkdir(exist_ok=True)
    (out / f"{a.vid}_tokens.md").write_text(report_md(a.vid, matches), encoding="utf-8")
    print(f"  -> {out / (a.vid + '_tokens.md')}")


def cmd_xml(a):
    """Premiere xmeml: premiere/<vid>_review.xml (V1 원본 + V2 후보 + 마커), premiere/<vid>_shorts.xml (세로 시퀀스)."""
    meta = load_meta(a.vid)
    cands_p = CACHE / a.vid / "candidates.json"
    cands = Segments.load(cands_p) if cands_p.exists() else Segments("candidates", [])
    shorts = load_shorts(a.vid)
    ui_p = CACHE / a.vid / "ui_state.json"
    ui = [{"start": s.start, "end": s.end, "label": s.label} for s in Segments.load(ui_p).items] if ui_p.exists() else None
    out = ROOT / "premiere"
    for p in export_xml(meta, cands, shorts, ui, out, a.vid, k=a.k):
        print(f"  {p}")
    print(f"[xml] review: V1 원본 + V2 후보 {len(cands.items)}개 + 마커 {len(shorts)}개 / shorts: 세로 시퀀스 (variant 별 {a.k}개)")


def cmd_transcribe(a):
    """Whisper 전사 → cache/<vid>/transcript.json. 백엔드: faster_whisper(GPU) → ffmpeg_whisper(CPU) 순 자동."""
    tr = transcribe(CACHE / a.vid, backend=a.backend, force=a.force)
    segs = tr.get("segments", [])
    print(f"[transcribe] {tr.get('backend')} {tr.get('model')}  segments={len(segs)}  elapsed={tr.get('elapsed_s', '?')}s")
    for s in segs[:5]:
        print(f"  {fmt_time(s['start'])}-{fmt_time(s['end'])}  {s['text'][:70]}")


def cmd_harvest(a):
    """review/<vid>/keep/ 에 들어간 클립을 labels/<vid>.csv 에 추가 → 피드백 루프.
    --shorts: review/<vid>/shorts/keep/*.mp4 → labels/<vid>.shorts.csv (label=keep)."""
    if a.shorts:
        idx_p = REVIEW / a.vid / "shorts" / "index.json"
        if not idx_p.exists():
            raise SystemExit(f"{idx_p} 없음 — export --shorts 먼저")
        index = {r["file"]: r for r in json.loads(idx_p.read_text(encoding="utf-8"))}
        kept = [p.name for p in (REVIEW / a.vid / "shorts" / "keep").glob("*.mp4") if p.name in index]
        lab_p = LABELS / f"{a.vid}.shorts.csv"
        import csv as _csv
        rows = []
        if lab_p.exists():
            with open(lab_p, encoding="utf-8", newline="") as f:
                rows = list(_csv.DictReader(f))
        existing = {(r["start"], r["end"], r["label"]) for r in rows if r.get("label") in ("keep", "no")}
        added = 0
        for name in kept:
            r = index[name]
            key = (f"{r['start']:.1f}", f"{r['end']:.1f}", "keep")
            if key in existing:
                continue
            rows.append({"start": key[0], "end": key[1], "label": "keep", "note": f"harvest {name}"})
            added += 1
        # no/ 폴더: mp4 를 옮기거나 <파일명>.txt 마커(내용 = 사유: 재미없음/임팩트없음/중복/잘림 …)
        no_dir = REVIEW / a.vid / "shorts" / "no"
        for p in list(no_dir.glob("*.mp4")) + list(no_dir.glob("*.mp4.txt")):
            name = p.name[:-4] if p.name.endswith(".txt") else p.name
            if name not in index:
                continue
            r = index[name]
            key = (f"{r['start']:.1f}", f"{r['end']:.1f}", "no")
            if key in existing:
                continue
            reason = p.read_text(encoding="utf-8").strip() if p.suffix == ".txt" else ""
            rows.append({"start": key[0], "end": key[1], "label": "no", "note": f"harvest-no {name} {reason}".strip()})
            added += 1
        with open(lab_p, "w", encoding="utf-8", newline="") as f:
            w = _csv.DictWriter(f, fieldnames=["start", "end", "label", "note"]); w.writeheader(); w.writerows(rows)
        print(f"[harvest --shorts] {added} new labels (keep: {len(kept)} files, no: {len(list(no_dir.glob('*')))} markers) -> {lab_p}")
        return
    cands = Segments.load(CACHE / a.vid / "candidates.json")
    kept = {p.name.split("_")[0] for p in (REVIEW / a.vid / "keep").glob("*.mp4")}
    lab_p = LABELS / f"{a.vid}.csv"
    lines = [] if lab_p.exists() else ["start,end,label,note"]
    for i, s in enumerate(cands.items, 1):
        if f"{i:03d}" in kept:
            lines.append(f"{s.start:.1f},{s.end:.1f},keep,harvested")
    with open(lab_p, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"[harvest] {len(kept)} segments appended to {lab_p}")


def main():
    ap = argparse.ArgumentParser(prog="clipforge")
    sp = ap.add_subparsers(dest="cmd", required=True)

    p = sp.add_parser("prep");    p.add_argument("videos", nargs="+"); p.add_argument("--force", action="store_true")
    p.add_argument("--game", default=None, help="games/<game>.yaml (기본: 파일명 접두어 또는 d2r)")
    p.add_argument("--proxy", action="store_true", help="480p NVENC 프록시도 생성"); p.set_defaults(f=cmd_prep)
    p = sp.add_parser("signals"); p.add_argument("vid"); p.add_argument("--force", action="store_true"); p.set_defaults(f=cmd_signals)
    for name, fn in [("cands", cmd_cands), ("sweep", cmd_sweep)]:
        p = sp.add_parser(name); p.add_argument("vid"); p.add_argument("--threshold", type=float, default=1.5)
        p.add_argument("--w", action="append", help="신호 가중치, 예: --w audio_loudness=1 --w frame_motion=0.3"); p.set_defaults(f=fn)
    p = sp.add_parser("shorts");  p.add_argument("vid"); p.add_argument("--k", type=int, default=5); p.set_defaults(f=cmd_shorts)
    p = sp.add_parser("export"); p.add_argument("vid"); p.add_argument("--shorts", action="store_true", help="shorts.json 후보를 9:16 초안으로")
    p.add_argument("--k", type=int, default=3, help="variant 별 상위 k 개만"); p.add_argument("--cx", type=float, default=0.5, help="게임 크롭 중심 x (0~1)")
    p.add_argument("--ease", type=float, default=0.0, help="크롭 중심 이동 시간(초). 0=즉시 점프(기본)")
    p.add_argument("--no-subs", action="store_true", help="대사 자막(ASS) 생략")
    p.add_argument("--top", default="title", choices=["title", "auto", "chat"], help="상단 카드: title(기본·확정) | auto(앵커 종류별) | chat. title 외는 review/<vid>/shorts_<mode>/ 에 출력")
    p.add_argument("--layout", default="card", choices=["card", "feed"], help="card(기본·친구 확정 2026-10-18: 손글씨 제목 띠+템 창 추적 크롭+방송 채팅) | feed(실험: @마골 구조, shorts_feed/)")
    p.add_argument("--brand", default="디아블로2 하이라이트", help="feed 레이아웃 상단 채널 띠 문구")
    p.set_defaults(f=cmd_export)
    for name, fn in [("eval", cmd_eval), ("harvest", cmd_harvest)]:
        p = sp.add_parser(name); p.add_argument("vid"); p.add_argument("--shorts", action="store_true"); p.set_defaults(f=fn)
    p = sp.add_parser("weaklabel"); p.add_argument("vid"); p.add_argument("--title", default=None); p.set_defaults(f=cmd_weaklabel)
    p = sp.add_parser("lexicon"); p.add_argument("vid"); p.set_defaults(f=cmd_lexicon)
    p = sp.add_parser("xml"); p.add_argument("vid"); p.add_argument("--k", type=int, default=3); p.set_defaults(f=cmd_xml)
    p = sp.add_parser("transcribe"); p.add_argument("vid"); p.add_argument("--backend", default=None, choices=["faster_whisper", "ffmpeg_whisper"]); p.add_argument("--force", action="store_true"); p.set_defaults(f=cmd_transcribe)

    a = ap.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()
