"""전사 (Whisper, faster-whisper/CTranslate2). cache/<id>/transcript.json 에 저장한다.

  GPU(CUDA) 가 되면 int8_float16 으로 12분 영상 30초. CUDA 초기화가 실패하면 같은 모델을 CPU/int8 로 (약 20배 느림).
  모델은 번들 models/faster-whisper-<name>/ 를 우선 쓰고(오프라인), 없으면 HF 캐시/다운로드.

transcript.json: {"backend", "model", "language", "segments": [{"start", "end", "text", "words": [{"start","end","word"}]}]}
시간 단위는 초. 세그먼트 끝 = 말이 끝나는 지점 → shorts 의 경계 스냅이 이걸 우선 쓴다.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def _cfg() -> dict:
    p = ROOT / "games" / "common.yaml"
    return (yaml.safe_load(p.read_text(encoding="utf-8")) or {}).get("transcribe", {}) if p.exists() else {}


def _add_nvidia_dlls() -> None:
    """Windows: pip 의 nvidia-cublas-cu12 / nvidia-cudnn-cu12 가 설치한 DLL 폴더를 로더 검색 경로에 추가."""
    import os
    import sys

    base = Path(sys.prefix) / "Lib" / "site-packages" / "nvidia"
    for sub in ("cublas", "cudnn", "cuda_runtime", "cuda_nvrtc"):
        d = base / sub / "bin"
        if d.exists():
            os.environ["PATH"] = str(d) + os.pathsep + os.environ.get("PATH", "")
            if hasattr(os, "add_dll_directory"):
                os.add_dll_directory(str(d))


def transcribe_faster(wav: Path, cfg: dict, language: str) -> dict:
    _add_nvidia_dlls()
    from faster_whisper import WhisperModel

    t0 = time.time()
    name = cfg.get("model", "large-v3-turbo")
    local = ROOT / "models" / f"faster-whisper-{name}"  # 배포 번들(engine-dist/models) → 오프라인
    src = str(local) if (local / "model.bin").exists() else name
    device, compute = cfg.get("device", "cuda"), cfg.get("compute_type", "int8_float16")
    try:
        model = WhisperModel(src, device=device, compute_type=compute)
    except Exception as e:
        if device == "cpu":
            raise
        print(f"  (faster-whisper {device} 실패: {str(e)[:120]} → cpu/int8 폴백)")
        device, compute = "cpu", "int8"
        model = WhisperModel(src, device=device, compute_type=compute)
    # PyAV 버전 충돌(av.open metadata_errors)을 피하려고 WAV 를 직접 읽어 16kHz float32 배열로 넘긴다.
    import wave

    import numpy as np

    with wave.open(str(wav), "rb") as w:
        assert w.getframerate() == 16000 and w.getnchannels() == 1, "audio.wav 는 16kHz mono 여야 함 (prep 산출물)"
        audio = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
    segments, _info = model.transcribe(
        audio,
        language=language,
        vad_filter=bool(cfg.get("vad", True)),
        word_timestamps=bool(cfg.get("word_timestamps", True)),
        beam_size=5,
    )
    segs = []
    for s in segments:
        segs.append(
            {
                "start": round(s.start, 3),
                "end": round(s.end, 3),
                "text": s.text.strip(),
                "words": [
                    {"start": round(w.start, 3), "end": round(w.end, 3), "word": w.word} for w in (s.words or [])
                ],
            }
        )
    return {
        "backend": "faster_whisper",
        "model": name,
        "device": device,
        "compute_type": compute,
        "source": src,
        "language": language,
        "elapsed_s": round(time.time() - t0, 1),
        "segments": segs,
    }


def transcribe(cache: Path, backend: str | None = None, force: bool = False) -> dict:
    """audio.wav(16kHz mono, prep 산출물) → transcript.json. backend 인자는 하위 호환용(무시)."""
    from .errors import EngineError

    out = cache / "transcript.json"
    if out.exists() and not force:
        return json.loads(out.read_text(encoding="utf-8"))
    wav = cache / "audio.wav"
    if not wav.exists():
        raise EngineError("E_NO_PREP", f"오디오 없음: {wav}", "prep 단계를 먼저 실행하세요.")
    cfg = _cfg()
    language = cfg.get("language", "ko")
    try:
        res = transcribe_faster(wav, cfg.get("faster_whisper", {}), language)
    except EngineError:
        raise
    except ImportError as e:
        raise EngineError(
            "E_TRANSCRIBE",
            f"faster-whisper 가 설치되지 않았습니다: {e}",
            "pip install -r requirements.txt (또는 설치본의 파이썬 런타임 구성요소를 다시 받으세요)",
        ) from e
    except Exception as e:
        msg = str(e)[:300]
        hint = (
            "Whisper 모델을 찾지 못했습니다. 번들 models/ 폴더 또는 네트워크(HF 다운로드)를 확인하세요."
            if "model" in msg.lower() or "huggingface" in msg.lower() or "snapshot" in msg.lower()
            else "GPU 와 CPU 모두 실패했습니다. 로그를 확인하세요."
        )
        raise EngineError("E_TRANSCRIBE", f"전사 실패: {msg}", hint) from e
    out.write_text(json.dumps(res, ensure_ascii=False, indent=0), encoding="utf-8")
    return res


def speech_segments_from_transcript(tr: dict, min_gap: float = 0.3) -> list[tuple[float, float]]:
    """전사 세그먼트(단어가 있으면 단어 경계)로 발화 구간. min_gap 미만 끊김은 병합."""
    raw = []
    for s in tr.get("segments", []):
        if s.get("words"):
            raw.append([s["words"][0]["start"], s["words"][-1]["end"]])
        else:
            raw.append([s["start"], s["end"]])
    out: list[list[float]] = []
    for a, b in sorted(raw):
        if out and a - out[-1][1] < min_gap:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(a, b) for a, b in out]
