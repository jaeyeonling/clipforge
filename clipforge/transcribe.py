"""전사 (Whisper). 두 백엔드를 같은 형식으로 통일해 cache/<id>/transcript.json 에 저장한다.

  faster_whisper : CTranslate2 + CUDA. 단어 타임스탬프, VAD. 빠름 (GPU). 설치: faster-whisper nvidia-cublas-cu12 nvidia-cudnn-cu12
  ffmpeg_whisper : FFmpeg 내장 whisper.cpp 필터. 설치 없음, CPU ~0.6x 실시간. 세그먼트 단위 타임스탬프만.

transcript.json: {"backend", "model", "language", "segments": [{"start", "end", "text", "words": [{"start","end","word"}]}]}
시간 단위는 초. 세그먼트 끝 = 말이 끝나는 지점 → shorts 의 경계 스냅이 이걸 우선 쓴다.
"""
from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def _cfg() -> dict:
    p = ROOT / "games" / "common.yaml"
    return (yaml.safe_load(p.read_text(encoding="utf-8")) or {}).get("transcribe", {}) if p.exists() else {}


def transcribe_ffmpeg(wav: Path, out_json: Path, cfg: dict, language: str) -> dict:
    """ffmpeg whisper 필터. 필터 옵션 경로에 'C:' 콜론이 못 들어가므로 ROOT 를 cwd 로 두고 상대경로를 쓴다."""
    model = cfg.get("model", "models/ggml-large-v3-turbo-q8_0.bin")
    vad = cfg.get("vad_model")
    tmp = out_json.with_suffix(".jsonl")
    rel = lambda p: str(Path(p).resolve().relative_to(ROOT)).replace("\\", "/")
    af = f"whisper=model={rel(ROOT / model)}:language={language}:queue={cfg.get('queue', 20)}:format=json:destination={rel(tmp)}"
    if vad:
        af += f":vad_model={rel(ROOT / vad)}"
    t0 = time.time()
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", rel(wav), "-af", af, "-f", "null", "-"],
                   check=True, cwd=ROOT)
    segs = []
    for line in tmp.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        d = json.loads(line)
        segs.append({"start": d["start"] / 1000.0, "end": d["end"] / 1000.0, "text": d.get("text", "").strip(), "words": []})
    return {"backend": "ffmpeg_whisper", "model": model, "language": language, "elapsed_s": round(time.time() - t0, 1),
            "segments": segs}


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
    model = WhisperModel(cfg.get("model", "large-v3-turbo"), device=cfg.get("device", "cuda"),
                         compute_type=cfg.get("compute_type", "int8_float16"))
    # PyAV 버전 충돌(av.open metadata_errors)을 피하려고 WAV 를 직접 읽어 16kHz float32 배열로 넘긴다.
    import wave
    import numpy as np
    with wave.open(str(wav), "rb") as w:
        assert w.getframerate() == 16000 and w.getnchannels() == 1, "audio.wav 는 16kHz mono 여야 함 (prep 산출물)"
        audio = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
    segments, info = model.transcribe(audio, language=language, vad_filter=bool(cfg.get("vad", True)),
                                      word_timestamps=bool(cfg.get("word_timestamps", True)), beam_size=5)
    segs = []
    for s in segments:
        segs.append({"start": round(s.start, 3), "end": round(s.end, 3), "text": s.text.strip(),
                     "words": [{"start": round(w.start, 3), "end": round(w.end, 3), "word": w.word} for w in (s.words or [])]})
    return {"backend": "faster_whisper", "model": cfg.get("model", "large-v3-turbo"), "language": language,
            "elapsed_s": round(time.time() - t0, 1), "segments": segs}


def transcribe(cache: Path, backend: str | None = None, force: bool = False) -> dict:
    out = cache / "transcript.json"
    if out.exists() and not force:
        return json.loads(out.read_text(encoding="utf-8"))
    cfg = _cfg()
    language = cfg.get("language", "ko")
    order = [backend] if backend else list(cfg.get("backends", ["faster_whisper", "ffmpeg_whisper"]))
    last_err = None
    for b in order:
        try:
            if b == "faster_whisper":
                res = transcribe_faster(cache / "audio.wav", cfg.get("faster_whisper", {}), language)
            elif b == "ffmpeg_whisper":
                res = transcribe_ffmpeg(cache / "audio.wav", out, cfg.get("ffmpeg_whisper", {}), language)
            else:
                raise ValueError(f"unknown backend {b}")
            out.write_text(json.dumps(res, ensure_ascii=False, indent=0), encoding="utf-8")
            return res
        except Exception as e:      # 설치 안 됨 / CUDA 없음 / 모델 없음 → 다음 백엔드
            last_err = e
            print(f"  ({b} 실패: {str(e)[:120]} → 다음 백엔드)")
    raise RuntimeError(f"전사 실패: {last_err}")


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
