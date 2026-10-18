"""베이스라인 신호: 음량 곡선.

가장 멍청한 신호. 이것만으로 정답 recall이 몇 %인지가 프로젝트의 출발점이다.
- RMS를 dBFS로 변환 (hop=0.5s, window=1.0s)
- 전체 영상의 중앙값 기준 상대값으로 정규화 → 녹화 볼륨 차이에 둔감
"""
from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

from ..timeline import Curve
from .base import signal


def read_wav_mono(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as w:
        sr = w.getframerate()
        n = w.getnframes()
        raw = w.readframes(n)
        data = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        if w.getnchannels() > 1:
            data = data.reshape(-1, w.getnchannels()).mean(axis=1)
    return data, sr


def rms_db_curve(x: np.ndarray, sr: int, hop: float, window: float) -> np.ndarray:
    hop_n, win_n = int(sr * hop), int(sr * window)
    n_frames = max(1, (len(x) - win_n) // hop_n + 1)
    out = np.empty(n_frames, dtype=np.float32)
    for i in range(n_frames):
        seg = x[i * hop_n: i * hop_n + win_n]
        out[i] = np.sqrt(np.mean(seg * seg) + 1e-12)
    return 20 * np.log10(out + 1e-9)


@signal("audio_loudness")
def audio_loudness(cache: Path, hop: float = 0.5, window: float = 1.0) -> Curve:
    x, sr = read_wav_mono(cache / "audio.wav")
    db = rms_db_curve(x, sr, hop, window)
    rel = db - np.median(db)             # 중앙값 대비 dB
    return Curve(
        name="audio_loudness",
        hop=hop,
        values=[round(float(v), 2) for v in rel],
        meta={"unit": "dB rel. median", "window": window},
    )
