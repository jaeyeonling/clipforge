import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture
def tmp_project(tmp_path, monkeypatch):
    """데이터 폴더만 임시로 바꾼 Project (앱 폴더는 저장소 그대로 — games/, assets/ 필요)."""
    monkeypatch.setenv("CLIPFORGE_DATA", str(tmp_path))
    from clipforge.project import Project
    return Project(app_root=ROOT, data_root=tmp_path)


@pytest.fixture
def synth_wav(tmp_path):
    """3초 16kHz mono: 0~1s 무음, 1~2s 톤(발화 대용), 2~3s 무음."""
    import wave
    import numpy as np
    sr = 16000
    t = np.arange(sr * 3) / sr
    x = np.zeros_like(t)
    seg = (t >= 1.0) & (t < 2.0)
    x[seg] = 0.3 * np.sin(2 * np.pi * 220 * t[seg])
    x += 0.002 * np.random.default_rng(0).standard_normal(len(t))   # 바닥 소음
    p = tmp_path / "audio.wav"
    with wave.open(str(p), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes((x * 32767).astype(np.int16).tobytes())
    return p
