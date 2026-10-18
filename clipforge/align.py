"""align — 최종본(편집본) ↔ 원본 오디오 정렬로 "살아남은 구간" 자동 추출 (docs/design/ALIGN.md).

    fp = fingerprint(wav_path)                      # 랜드마크 해시 (hash, t_frame) — 원본은 npz 로 캐시
    segs = align(fp_orig, fp_final)                 # [{final_start, final_end, orig_start, orig_end, offset_s, votes, margin}]
    write_labels(labels_csv, segs)                  # label=kept, note=auto align …

numpy 만 쓴다. 16kHz mono WAV 입력(prep 산출물). 7시간 원본은 120초 청크로 STFT → 피크만 보관.
"""
from __future__ import annotations

import csv
import json
import time
import wave
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

SR = 16000


@dataclass
class Params:
    n_fft: int = 1024
    hop: int = 256                  # 16ms
    fmax_bin: int = 320             # 0~5kHz (16k/1024 = 15.6Hz/bin)
    peak_dt: int = 10               # 국소 최대 이웃: ±10 프레임(160ms)
    peak_df: int = 15               # ±15 bin
    peaks_per_sec: int = 20
    fanout: int = 6
    max_pair_dt: int = 64           # 쌍 최대 간격 1초
    max_pair_df: int = 96
    common_hash_cap: int = 200      # 원본에서 이보다 자주 나오는 해시는 버림
    win_s: float = 3.0
    step_s: float = 0.5
    min_votes: int = 8
    margin: float = 1.5             # 1위/2위 득표 비
    join_tol_frames: int = 4        # 같은 offset 으로 볼 허용 오차 (64ms)
    min_seg_s: float = 1.0
    chunk_s: float = 120.0

    @property
    def fps(self) -> float:
        return SR / self.hop


@dataclass
class Fingerprint:
    hashes: np.ndarray      # int64, hash 로 정렬
    times: np.ndarray       # int32 프레임 (hashes 와 같은 순서)
    duration_s: float
    n_peaks: int
    params: dict

    def save(self, path: Path) -> None:
        np.savez_compressed(path, hashes=self.hashes, times=self.times, duration_s=self.duration_s, n_peaks=self.n_peaks,
                            params=json.dumps(self.params))

    @classmethod
    def load(cls, path: Path) -> "Fingerprint":
        z = np.load(path, allow_pickle=False)
        return cls(z["hashes"], z["times"], float(z["duration_s"]), int(z["n_peaks"]), json.loads(str(z["params"])))


# ---------- WAV ----------
def read_wav(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as w:
        assert w.getframerate() == SR and w.getnchannels() == 1 and w.getsampwidth() == 2, f"{path}: 16kHz mono 16bit WAV 이어야 함 (prep 산출물)"
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0


def write_wav(path: Path, x: np.ndarray) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype(np.int16).tobytes())


# ---------- 지문 ----------
def _sliding_max_1d(a: np.ndarray, r: int, axis: int) -> np.ndarray:
    """축 방향 ±r 창의 최대 (경계는 edge 패딩)."""
    pad = [(0, 0)] * a.ndim
    pad[axis] = (r, r)
    ap = np.pad(a, pad, mode="edge")
    v = np.lib.stride_tricks.sliding_window_view(ap, 2 * r + 1, axis=axis)
    return v.max(axis=-1)


def _peaks(logmag: np.ndarray, p: Params, t0_frame: int) -> tuple[np.ndarray, np.ndarray]:
    """logmag[frames, bins] → (t_frames, f_bins) 피크. 분리 max 필터로 국소 최대, 1초마다 상위 K."""
    mx = _sliding_max_1d(_sliding_max_1d(logmag, p.peak_dt, 0), p.peak_df, 1)
    is_peak = (logmag >= mx) & (logmag > logmag.mean() + 0.5 * logmag.std())
    ts, fs = np.nonzero(is_peak)
    if not len(ts):
        return np.zeros(0, np.int64), np.zeros(0, np.int64)
    vals = logmag[ts, fs]
    fps = int(round(p.fps))
    keep_t, keep_f = [], []
    for sec in np.unique(ts // fps):
        m = (ts // fps) == sec
        idx = np.nonzero(m)[0]
        if len(idx) > p.peaks_per_sec:
            idx = idx[np.argsort(vals[idx])[-p.peaks_per_sec:]]
        keep_t.append(ts[idx]); keep_f.append(fs[idx])
    t = np.concatenate(keep_t) + t0_frame
    f = np.concatenate(keep_f)
    order = np.argsort(t, kind="stable")
    return t[order].astype(np.int64), f[order].astype(np.int64)


def _hashes(t: np.ndarray, f: np.ndarray, p: Params) -> tuple[np.ndarray, np.ndarray]:
    """앵커 i 와 뒤따르는 fanout 개 피크 j: hash = f_i<<15 | f_j<<6 | dt (f 9bit, dt 6bit)."""
    hs, ts = [], []
    n = len(t)
    for i in range(n):
        cnt = 0
        for j in range(i + 1, n):
            dt = t[j] - t[i]
            if dt > p.max_pair_dt:
                break
            if dt < 1 or abs(f[j] - f[i]) > p.max_pair_df:
                continue
            hs.append((int(f[i]) << 15) | (int(f[j]) << 6) | int(dt)); ts.append(int(t[i]))
            cnt += 1
            if cnt >= p.fanout:
                break
    return np.asarray(hs, dtype=np.int64), np.asarray(ts, dtype=np.int64)


def fingerprint(wav: Path | np.ndarray, p: Params | None = None, progress=None) -> Fingerprint:
    p = p or Params()
    x = read_wav(wav) if isinstance(wav, (str, Path)) else np.asarray(wav, dtype=np.float32)
    win = np.hanning(p.n_fft).astype(np.float32)
    chunk = int(p.chunk_s * SR)
    overlap = p.n_fft + p.peak_dt * p.hop * 2
    all_h, all_t, n_peaks = [], [], 0
    pos = 0
    while pos < len(x):
        a = max(0, pos - overlap)
        seg = x[a: pos + chunk + overlap]
        if len(seg) < p.n_fft:
            break
        n_frames = 1 + (len(seg) - p.n_fft) // p.hop
        frames = np.lib.stride_tricks.sliding_window_view(seg, p.n_fft)[:: p.hop][:n_frames] * win
        mag = np.abs(np.fft.rfft(frames, axis=1))[:, 1: p.fmax_bin + 1]
        logmag = np.log1p(mag * 100.0).astype(np.float32)
        t, f = _peaks(logmag, p, a // p.hop)
        # 청크 본체 구간의 피크만 (겹침 구간 중복 방지)
        lo, hi = pos // p.hop, (pos + chunk) // p.hop
        m = (t >= lo) & (t < hi)
        t, f = t[m], f[m]
        h, th = _hashes(t, f, p)
        all_h.append(h); all_t.append(th); n_peaks += len(t)
        pos += chunk
        if progress:
            progress(min(1.0, pos / len(x)))
    hashes = np.concatenate(all_h) if all_h else np.zeros(0, np.int64)
    times = np.concatenate(all_t) if all_t else np.zeros(0, np.int64)
    order = np.argsort(hashes, kind="stable")
    return Fingerprint(hashes[order], times[order].astype(np.int32), len(x) / SR, n_peaks, asdict(p))


# ---------- 매칭 ----------
@dataclass
class Match:
    final_start: float
    final_end: float
    orig_start: float
    orig_end: float
    offset_s: float
    votes: int
    margin: float

    def to_dict(self) -> dict:
        return {k: (round(v, 3) if isinstance(v, float) else v) for k, v in asdict(self).items()}


def _pairs(orig: Fingerprint, final: Fingerprint, p: Params) -> tuple[np.ndarray, np.ndarray]:
    """최종본 해시 → 원본의 모든 시각. 반환 (t_final, t_orig) 프레임 배열."""
    lo = np.searchsorted(orig.hashes, final.hashes, side="left")
    hi = np.searchsorted(orig.hashes, final.hashes, side="right")
    cnt = hi - lo
    ok = (cnt > 0) & (cnt <= p.common_hash_cap)
    tf, to = [], []
    for i in np.nonzero(ok)[0]:
        o = orig.times[lo[i]: hi[i]]
        tf.append(np.full(len(o), final.times[i], dtype=np.int64)); to.append(o.astype(np.int64))
    if not tf:
        return np.zeros(0, np.int64), np.zeros(0, np.int64)
    tf = np.concatenate(tf); to = np.concatenate(to)
    order = np.argsort(tf, kind="stable")
    return tf[order], to[order]


def align(orig: Fingerprint, final: Fingerprint, p: Params | None = None) -> tuple[list[Match], dict]:
    """창 투표 → 구간 병합 → 경계 다듬기. 반환 (구간, 진단)."""
    p = p or Params()
    fps = p.fps
    tf, to = _pairs(orig, final, p)
    off = to - tf
    q = p.join_tol_frames // 2 or 1
    offq = off // q
    win = int(round(p.win_s * fps)); step = int(round(p.step_s * fps))
    n_final = int(final.duration_s * fps)
    windows = []          # (w_start, w_end, offset_frames, votes, margin) — 채택된 창만
    diag_windows = []
    for ws in range(0, max(1, n_final - win + 1), step):
        a, b = np.searchsorted(tf, ws), np.searchsorted(tf, ws + win)
        if b - a < p.min_votes:
            diag_windows.append({"t": round(ws / fps, 2), "votes": int(b - a), "accepted": False}); continue
        u, c = np.unique(offq[a:b], return_counts=True)
        # 이웃 bin 합산 (양자화 경계에 걸린 투표)
        csum = c.copy()
        for d in (-1, 1):
            idx = np.searchsorted(u, u + d)
            hit = (idx < len(u)) & (u[np.minimum(idx, len(u) - 1)] == u + d)
            csum[hit] += c[idx[hit]]
        best = int(np.argmax(csum)); v1 = int(csum[best])
        rest = np.delete(csum, [best] + [k for k in (best - 1, best + 1) if 0 <= k < len(csum)])
        v2 = int(rest.max()) if len(rest) else 0
        margin = v1 / max(1, v2)
        accepted = v1 >= p.min_votes and margin >= p.margin
        diag_windows.append({"t": round(ws / fps, 2), "votes": v1, "second": v2, "accepted": accepted, "offset_s": round(float(u[best] * q) / fps, 3)})
        if accepted:
            # 대표 offset = 최다 bin 안의 실제 offset 중앙값
            sel = off[a:b][np.abs(offq[a:b] - u[best]) <= 1]
            windows.append((ws, ws + win, int(np.median(sel)), v1, margin))
    # 병합
    segs: list[Match] = []
    cur = None
    for ws, we, o, v, m in windows:
        if cur and abs(o - cur["o"]) <= p.join_tol_frames and ws <= cur["we"] + step:
            cur["we"] = we; cur["votes"] += v; cur["n"] += 1; cur["margin"] = max(cur["margin"], m)
            cur["o_list"].append(o)
        else:
            if cur: segs.append(_finalize(cur, tf, off, fps, p))
            cur = {"ws": ws, "we": we, "o": o, "votes": v, "n": 1, "margin": m, "o_list": [o]}
    if cur:
        segs.append(_finalize(cur, tf, off, fps, p))
    segs = [s for s in segs if s.final_end - s.final_start >= p.min_seg_s]
    # 미매칭 구간 (최종본 기준)
    unmatched, t = [], 0.0
    for s in segs:
        if s.final_start - t >= 0.5:
            unmatched.append([round(t, 2), round(s.final_start, 2)])
        t = s.final_end
    if final.duration_s - t >= 0.5:
        unmatched.append([round(t, 2), round(final.duration_s, 2)])
    matched = sum(s.final_end - s.final_start for s in segs)
    diag = {"final_duration_s": round(final.duration_s, 2), "orig_duration_s": round(orig.duration_s, 2),
            "n_pairs": int(len(tf)), "n_windows": len(diag_windows), "n_accepted": len(windows), "n_segments": len(segs),
            "matched_s": round(matched, 2), "matched_frac": round(matched / max(1e-6, final.duration_s), 3),
            "unmatched": unmatched, "windows": diag_windows, "params": asdict(p)}
    return segs, diag


def _finalize(cur: dict, tf: np.ndarray, off: np.ndarray, fps: float, p: Params) -> Match:
    o = int(np.median(cur["o_list"]))
    a, b = np.searchsorted(tf, cur["ws"]), np.searchsorted(tf, cur["we"])
    sel = np.sort(tf[a:b][np.abs(off[a:b] - o) <= p.join_tol_frames])
    # 경계 = 매칭 쌍이 '밀집'한 첫/마지막 시각 (0.5초 창에 k 개 이상). 우연히 하나 맞는 쌍이 경계를 끌고 가지 않게.
    dense = int(round(0.5 * fps)); k = 3
    if len(sel) >= k:
        cnt_fwd = np.searchsorted(sel, sel + dense, side="right") - np.arange(len(sel))        # [t, t+0.5s) 안의 쌍 수
        cnt_bwd = np.arange(len(sel)) + 1 - np.searchsorted(sel, sel - dense, side="left")      # (t-0.5s, t] 안의 쌍 수
        starts = np.nonzero(cnt_fwd >= k)[0]; ends = np.nonzero(cnt_bwd >= k)[0]
        t_start = int(sel[starts[0]]) if len(starts) else int(sel[0])
        t_end = int(sel[ends[-1]]) if len(ends) else int(sel[-1])
    else:
        t_start, t_end = cur["ws"], cur["we"]
    fs = t_start / fps
    fe = t_end / fps + p.n_fft / SR + 0.1          # 마지막 앵커 뒤로 창 길이 + 여유
    return Match(fs, fe, fs + o / fps, fe + o / fps, o / fps, int(cur["votes"]), round(float(cur["margin"]), 2))


# ---------- 파일 I/O ----------
def align_files(orig_wav: Path, final_wav: Path, cache_dir: Path | None = None, p: Params | None = None, progress=None) -> tuple[list[Match], dict]:
    """원본 지문은 cache_dir/fingerprint.npz 에 캐시(파라미터가 같을 때만 재사용)."""
    p = p or Params()
    fp_o = None
    cache_p = (cache_dir / "fingerprint.npz") if cache_dir else None
    if cache_p and cache_p.exists():
        try:
            c = Fingerprint.load(cache_p)
            if c.params == asdict(p):
                fp_o = c
        except Exception:  # noqa: BLE001
            fp_o = None
    t0 = time.time()
    if fp_o is None:
        fp_o = fingerprint(orig_wav, p, progress=lambda f: progress and progress(0.8 * f, "원본 지문"))
        if cache_p:
            fp_o.save(cache_p)
    t_fp = time.time() - t0
    fp_f = fingerprint(final_wav, p)
    if progress:
        progress(0.9, "매칭")
    segs, diag = align(fp_o, fp_f, p)
    diag["fingerprint_s"] = round(t_fp, 1); diag["orig_hashes"] = int(len(fp_o.hashes)); diag["final_hashes"] = int(len(fp_f.hashes))
    return segs, diag


def write_labels(path: Path, segs: list[Match], final_name: str = "final", keep_manual: bool = True) -> int:
    """labels CSV 에 kept 행을 쓴다. 이전 auto align 행은 교체, 사람이 쓴 행은 보존."""
    rows: list[dict] = []
    if keep_manual and path.exists():
        with open(path, encoding="utf-8", newline="") as f:
            rows = [r for r in csv.DictReader(f) if not (r.get("note", "").startswith("auto align"))]
    for s in segs:
        rows.append({"start": f"{s.orig_start:.2f}", "end": f"{s.orig_end:.2f}", "label": "kept",
                     "note": f"auto align {final_name} {s.final_start:.1f}-{s.final_end:.1f} votes={s.votes} margin={s.margin}"})
    rows.sort(key=lambda r: float(r["start"]))
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["start", "end", "label", "note"]); w.writeheader(); w.writerows(rows)
    return len(segs)


# ---------- 쇼츠 역매핑 (Phase 1 정답 늘리기) ----------
VIDEO_EXTS = (".mp4", ".mkv", ".mov", ".m4v", ".webm", ".m4a", ".wav", ".mp3", ".aac")


def collect_shorts(paths: list[str | Path]) -> list[Path]:
    """파일/폴더 목록 → 쇼츠 파일 목록 (폴더는 영상 확장자만, 이름순)."""
    out: list[Path] = []
    for p in paths:
        p = Path(p)
        if p.is_dir():
            out.extend(sorted(q for q in p.iterdir() if q.is_file() and q.suffix.lower() in VIDEO_EXTS))
        elif p.is_file():
            out.append(p)
    return out


def align_shorts(episode_wav: Path, shorts: list[Path], cache_dir: Path, p: Params | None = None, progress=None) -> list[dict]:
    """쇼츠 하나하나를 회차(편집본 또는 원본) 오디오에 정렬. 반환 [{file, segments: [Match…], diag}]. 회차 지문은 캐시."""
    p = p or Params()
    results = []
    work = cache_dir / "align"; work.mkdir(parents=True, exist_ok=True)
    for i, s in enumerate(shorts):
        if progress:
            progress(i / max(1, len(shorts)), f"쇼츠 {s.name}")
        wav = s if s.suffix.lower() == ".wav" else extract_audio(s, work / f"shorts_{s.stem}.wav")
        segs, diag = align_files(episode_wav, wav, cache_dir=cache_dir, p=p)
        results.append({"file": s.name, "path": str(s), "segments": segs, "diag": diag})
    if progress:
        progress(1.0, "쇼츠 정렬 완료")
    return results


def write_shorts_labels(path: Path, results: list[dict], min_seg_s: float = 3.0) -> int:
    """labels/<id>.shorts.csv 에 쇼츠마다 keep 행(회차 시각). 같은 파일의 이전 auto 행은 교체, 사람 행은 보존.
    쇼츠가 여러 순간을 이어 붙인 것이면 구간이 여러 개 — 각각 keep (쇼츠에 들어간 순간은 전부 정답)."""
    rows: list[dict] = []
    if path.exists():
        with open(path, encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
    names = {r["file"] for r in results}
    rows = [r for r in rows if not any(str(r.get("note", "")).startswith(f"auto align shorts {n} ") for n in names)]
    n = 0
    for r in results:
        for s in r["segments"]:
            if s.orig_end - s.orig_start < min_seg_s:
                continue
            rows.append({"start": f"{s.orig_start:.2f}", "end": f"{s.orig_end:.2f}", "label": "keep",
                         "note": f"auto align shorts {r['file']} {s.final_start:.1f}-{s.final_end:.1f} votes={s.votes} margin={s.margin}"})
            n += 1
    rows.sort(key=lambda r: float(r["start"]))
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["start", "end", "label", "note"]); w.writeheader()
        w.writerows({k: r.get(k, "") for k in ("start", "end", "label", "note")} for r in rows)
    return n


def pretty_shorts(results: list[dict]) -> str:
    from .timeline import fmt_time
    lines = [f"[align shorts] {len(results)}개"]
    for r in results:
        segs = r["segments"]; d = r["diag"]
        if not segs:
            lines.append(f"  {r['file']}: 매칭 없음 (이 회차의 소리가 아니거나 BGM 으로 덮임)"); continue
        lines.append(f"  {r['file']} ({fmt_time(d['final_duration_s'])}, {d['matched_frac'] * 100:.0f}% 매칭) → " +
                     ", ".join(f"{fmt_time(s.orig_start)}-{fmt_time(s.orig_end)}" for s in segs))
    return "\n".join(lines)


def extract_audio(video: Path, out_wav: Path) -> Path:
    """최종본 영상 → 16k mono WAV (ffmpeg)."""
    import subprocess
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(video), "-vn", "-ac", "1", "-ar", str(SR), "-c:a", "pcm_s16le", str(out_wav)], check=True)
    return out_wav


def pretty(segs: list[Match], diag: dict) -> str:
    from .timeline import fmt_time
    lines = [f"[align] 최종본 {fmt_time(diag['final_duration_s'])} 중 {diag['matched_frac'] * 100:.0f}% 매칭 → 구간 {diag['n_segments']}개 "
             f"(창 {diag['n_accepted']}/{diag['n_windows']} 채택, 쌍 {diag['n_pairs']})"]
    for s in segs:
        lines.append(f"  final {fmt_time(s.final_start)}-{fmt_time(s.final_end)}  →  orig {fmt_time(s.orig_start)}-{fmt_time(s.orig_end)}"
                     f"  ({s.final_end - s.final_start:.1f}s, votes {s.votes}, margin {s.margin})")
    if diag["unmatched"]:
        lines.append("  미매칭(인트로·카드·교체 구간): " + ", ".join(f"{fmt_time(a)}-{fmt_time(b)}" for a, b in diag["unmatched"]))
    return "\n".join(lines)
