"""align 검증 (docs/design/ALIGN.md §5): 합성 신호 + (있으면) ep59 실오디오 재인코딩."""
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from clipforge.align import SR, Params, align, align_files, fingerprint, write_labels, write_wav

ROOT = Path(__file__).resolve().parent.parent


def synth_original(seconds: float, seed: int = 1) -> np.ndarray:
    """120ms 마다 무작위 4음(200~4000Hz) + 잡음. 피크가 뚜렷한 '원본'."""
    rng = np.random.default_rng(seed)
    n = int(seconds * SR); x = np.zeros(n, np.float32)
    step = int(0.12 * SR); t = np.arange(step) / SR
    for s in range(0, n - step, step):
        tones = sum(a * np.sin(2 * np.pi * f * t) for f, a in zip(rng.uniform(200, 4000, 4), rng.uniform(0.2, 1.0, 4)))
        x[s: s + step] = tones * np.hanning(step)
    x += 0.02 * rng.standard_normal(n)
    return (0.5 * x / np.abs(x).max()).astype(np.float32)


def make_final(orig: np.ndarray, cuts: list[tuple[float, float]], intro_s: float = 2.0, card_s: float = 2.0, gain: float = 0.6, seed: int = 2):
    """최종본 = 무음 인트로 + 구간들(사이에 잡음 카드) ; 반환 (신호, 기대 [(final_start, final_end, orig_start)])."""
    rng = np.random.default_rng(seed)
    parts = [np.zeros(int(intro_s * SR), np.float32)]; expect = []; t = intro_s
    for i, (a, b) in enumerate(cuts):
        if i:
            parts.append(0.05 * rng.standard_normal(int(card_s * SR)).astype(np.float32)); t += card_s
        seg = orig[int(a * SR): int(b * SR)] * gain
        parts.append(seg); expect.append((t, t + (b - a), a)); t += b - a
    x = np.concatenate(parts)
    x += 0.01 * rng.standard_normal(len(x)).astype(np.float32)
    return x.astype(np.float32), expect


def check(segs, expect, tol=0.25):
    assert len(segs) == len(expect), f"구간 수 {len(segs)} != {len(expect)}: {[s.to_dict() for s in segs]}"
    for s, (fs, fe, os_) in zip(sorted(segs, key=lambda s: s.final_start), expect):
        assert abs(s.final_start - fs) <= tol and abs(s.final_end - fe) <= tol, (s.to_dict(), fs, fe)
        assert abs(s.offset_s - (os_ - fs)) <= 0.05, (s.offset_s, os_ - fs)


def test_align_synthetic_segments_and_unmatched():
    orig = synth_original(90)
    final, expect = make_final(orig, [(10, 22), (40, 49), (70, 85)])
    fp_o, fp_f = fingerprint(orig), fingerprint(final)
    assert fp_o.n_peaks > 90 * 10 and len(fp_o.hashes) > len(fp_o.times) * 0  # 지문이 생김
    segs, diag = align(fp_o, fp_f)
    check(segs, expect)
    assert diag["matched_frac"] > 0.8          # 기대 36/42 = 0.857, 경계 손실 ~0.1s
    # 인트로(0~2s)와 카드(2 + 12 .. +2) 는 미매칭으로 남는다
    assert any(a <= 0.1 and b >= 1.5 for a, b in diag["unmatched"]), diag["unmatched"]


def test_align_reencoded_real_audio(tmp_path):
    wav = ROOT / "cache" / "ep59" / "audio.wav"
    if not wav.exists() or not shutil.which("ffmpeg"):
        pytest.skip("ep59 audio.wav 또는 ffmpeg 없음")
    from clipforge.align import read_wav
    orig = read_wav(wav)[: 660 * SR]                                # 11분
    final, expect = make_final(orig, [(100, 130), (300, 320), (480, 486), (600, 640)], gain=0.8)
    raw = tmp_path / "final_raw.wav"; write_wav(raw, final)
    m4a = tmp_path / "final.m4a"; back = tmp_path / "final.wav"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(raw), "-c:a", "aac", "-b:a", "64k", str(m4a)], check=True)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(m4a), "-ac", "1", "-ar", str(SR), "-c:a", "pcm_s16le", str(back)], check=True)
    owav = tmp_path / "orig.wav"; write_wav(owav, orig)
    cache = tmp_path / "cache"; cache.mkdir()
    segs, diag = align_files(owav, back, cache_dir=cache)
    check(segs, expect, tol=0.35)
    assert (cache / "fingerprint.npz").exists()
    segs2, _ = align_files(owav, back, cache_dir=cache)             # 캐시 재사용 경로
    assert len(segs2) == len(segs)
    lab = tmp_path / "labels.csv"
    lab.write_text("start,end,label,note\n50,55,manual,사람이 쓴 행\n", encoding="utf-8")
    assert write_labels(lab, segs, "final.mp4") == len(segs)
    txt = lab.read_text(encoding="utf-8")
    assert "사람이 쓴 행" in txt and txt.count("auto align") == len(segs)
    assert write_labels(lab, segs, "final.mp4") == len(segs) and lab.read_text(encoding="utf-8").count("auto align") == len(segs)   # 재실행해도 중복 없음


def test_params_roundtrip_in_cache(tmp_path):
    orig = synth_original(20)
    fp = fingerprint(orig, Params(peaks_per_sec=10))
    p = tmp_path / "fp.npz"; fp.save(p)
    from clipforge.align import Fingerprint
    fp2 = Fingerprint.load(p)
    assert fp2.params["peaks_per_sec"] == 10 and len(fp2.hashes) == len(fp.hashes) and fp2.duration_s == pytest.approx(20)


def test_align_shorts_writes_keep_labels(tmp_path):
    """쇼츠 2개(하나는 두 순간을 이어 붙임) → labels/<id>.shorts.csv keep 행, 재실행 시 교체, 사람 행 보존."""
    from clipforge.align import align_shorts, collect_shorts, write_shorts_labels
    orig = synth_original(80)
    owav = tmp_path / "audio.wav"; write_wav(owav, orig)
    s1, _ = make_final(orig, [(10, 22)], intro_s=0.5, card_s=0)
    s2, _ = make_final(orig, [(30, 38), (60, 70)], intro_s=0.5, card_s=1.0)
    d = tmp_path / "shorts"; d.mkdir()
    write_wav(d / "a.wav", s1); write_wav(d / "b.wav", s2); (d / "readme.txt").write_text("x")
    files = collect_shorts([d])
    assert [f.name for f in files] == ["a.wav", "b.wav"]
    res = align_shorts(owav, files, tmp_path / "cache")
    assert len(res[0]["segments"]) == 1 and len(res[1]["segments"]) == 2
    assert abs(res[0]["segments"][0].orig_start - 10) < 0.3 and abs(res[1]["segments"][1].orig_start - 60) < 0.3
    lab = tmp_path / "ep.shorts.csv"
    lab.write_text("start,end,label,note\n1,2,no,ui x | 중복\n", encoding="utf-8")
    assert write_shorts_labels(lab, res) == 3
    rows = lab.read_text(encoding="utf-8").splitlines()
    assert len(rows) == 1 + 1 + 3 and sum("auto align shorts a.wav" in r for r in rows) == 1 and "ui x" in rows[1] + rows[2]
    assert write_shorts_labels(lab, res) == 3 and len(lab.read_text(encoding="utf-8").splitlines()) == 5
