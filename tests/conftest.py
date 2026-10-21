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
    x += 0.002 * np.random.default_rng(0).standard_normal(len(t))  # 바닥 소음
    p = tmp_path / "audio.wav"
    with wave.open(str(p), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((x * 32767).astype(np.int16).tobytes())
    return p


def draw_drop_label(text: str = "카이트 쉴드", color=(0, 255, 0), size=(1920, 1080), at=(900, 520), seed: int = 1):
    """합성 게임 화면: 어두운 바닥 위 검은 상자에 등급색 아이템 이름 (디아블로2 바닥 라벨 모양). text=None 이면 라벨 없음."""
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont

    a = np.random.default_rng(seed).normal(40, 12, (size[1], size[0], 3)).clip(0, 255).astype(np.uint8)
    frame = Image.fromarray(a)
    if text:
        malgun = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "malgun.ttf"
        font_path = malgun if malgun.exists() else ROOT / "assets" / "fonts" / "BlackHanSans-Regular.ttf"
        d = ImageDraw.Draw(frame)
        font = ImageFont.truetype(str(font_path), 20)
        left, top, right, bottom = d.textbbox((0, 0), text, font=font)
        x, y = at
        d.rectangle([x, y, x + right - left + 12, y + bottom - top + 8], fill=(8, 8, 8))
        d.text((x + 6 - left, y + 4 - top), text, font=font, fill=color)
    return frame


@pytest.fixture
def live_frames(tmp_path):
    """20장짜리 프레임 폴더: 5~14번째에만 세트 아이템 라벨이 보인다 (실제 방송 프레임 없이 라이브 감지를 검증)."""
    d = tmp_path / "frames"
    d.mkdir()
    for i in range(20):
        draw_drop_label("카이트 쉴드" if 5 <= i < 15 else None, seed=i).save(d / f"{i:06d}.jpg", quality=92)
    return d
