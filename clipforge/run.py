"""CLI 진입점.

  python -m clipforge.run prep     videos/foo.mp4 [--game d2r] [--proxy] [--force]   # 전처리 캐시 (단일 패스)
  python -m clipforge.run signals  foo                     # 등록된 신호 전부 계산
  python -m clipforge.run cands    foo [--threshold 1.5] [--w audio_loudness=1 --w frame_motion=0.3]
  python -m clipforge.run eval     foo                     # labels/foo.csv 와 비교
  python -m clipforge.run export   foo                     # 후보 클립 mp4로 잘라 review/foo/ 에 저장
  python -m clipforge.run sweep    foo                     # threshold 를 바꿔가며 recall/coverage 표

<video_id> 는 영상 파일명(확장자 제외).
"""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from .candidates import DEFAULT_WEIGHTS, make_candidates
from .evaluate import evaluate
from .preprocess import preprocess
from .signals import REGISTRY, run_signal
from .timeline import Curve, Segments, fmt_time

ROOT = Path(__file__).resolve().parent.parent
CACHE, LABELS, REVIEW = ROOT / "cache", ROOT / "labels", ROOT / "review"


def load_meta(vid: str) -> dict:
    return json.loads((CACHE / vid / "meta.json").read_text(encoding="utf-8"))


def load_curves(vid: str) -> dict[str, Curve]:
    out = {}
    for name in REGISTRY:
        p = CACHE / vid / f"{name}.json"
        if p.exists():
            out[name] = Curve.load(p)
    return out


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
    segs = make_candidates(load_curves(a.vid), meta["duration"], parse_weights(a.w), threshold=a.threshold)
    segs.save(CACHE / a.vid / "candidates.json")
    print(f"[cands] {len(segs.items)} candidates, coverage {segs.total_duration() / meta['duration']:.1%}")
    for s in segs.items:
        print(f"  {fmt_time(s.start)}-{fmt_time(s.end)}  score={s.score:.2f}")
    return segs


def cmd_eval(a):
    meta = load_meta(a.vid)
    labels = Segments.from_csv(LABELS / f"{a.vid}.csv")
    cands = Segments.load(CACHE / a.vid / "candidates.json")
    print(evaluate(cands, labels, meta["duration"]).pretty())


def cmd_sweep(a):
    meta = load_meta(a.vid)
    labels = Segments.from_csv(LABELS / f"{a.vid}.csv")
    curves = load_curves(a.vid)
    w = parse_weights(a.w)
    print(f"weights={w}")
    print(f"{'thr':>5} {'recall':>7} {'prec':>7} {'cover':>7} {'n':>4}")
    for thr in [0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0]:
        c = make_candidates(curves, meta["duration"], w, threshold=thr)
        r = evaluate(c, labels, meta["duration"])
        print(f"{thr:5.2f} {r.recall:7.1%} {r.precision:7.1%} {r.coverage:7.1%} {r.n_candidates:4d}")


def cmd_export(a):
    """후보를 mp4 클립으로 잘라 review/<vid>/ 에 저장. 쓸 것은 keep/ 로 옮기면 그게 레이블이 된다."""
    meta = load_meta(a.vid)
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


def cmd_harvest(a):
    """review/<vid>/keep/ 에 들어간 클립을 labels/<vid>.csv 에 추가 → 피드백 루프."""
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
    for name, fn in [("eval", cmd_eval), ("export", cmd_export), ("harvest", cmd_harvest)]:
        p = sp.add_parser(name); p.add_argument("vid"); p.set_defaults(f=fn)

    a = ap.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()
