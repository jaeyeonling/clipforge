"""전처리 캐시.

원본 영상을 한 번만 디코딩해서 아래를 `cache/<video_id>/`에 저장한다.
이후 모든 신호 함수는 원본이 아니라 이 캐시만 읽는다 → 신호 하나 추가/수정의 사이클이 분 단위로 떨어진다.

  meta.json          ffprobe 메타데이터 (길이, fps, 해상도)
  audio.wav          16kHz mono PCM  (음량 분석, Whisper 입력)
  proxy.mp4          480p 저해상도 프록시 (장면 전환, VLM 리액션 판단용)
  thumbs/%06d.jpg    1fps 썸네일 (OCR, 빠른 눈검수용)

video_id = 파일명(확장자 제외). 이미 있는 산출물은 건너뛴다(--force로 재생성).
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path


def run(cmd: list[str]) -> None:
    print("  $", " ".join(cmd[:8]) + (" ..." if len(cmd) > 8 else ""))
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def probe(video: Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(video)],
        check=True, capture_output=True, text=True,
    ).stdout
    info = json.loads(out)
    v = next(s for s in info["streams"] if s["codec_type"] == "video")
    num, den = v.get("avg_frame_rate", "30/1").split("/")
    return {
        "duration": float(info["format"]["duration"]),
        "width": int(v["width"]),
        "height": int(v["height"]),
        "fps": float(num) / float(den or 1),
        "codec": v.get("codec_name"),
    }


def hw_decode_args() -> list[str]:
    """NVIDIA 머신이면 NVDEC 하드웨어 디코딩. 실패하면 호출부에서 CPU로 재시도."""
    return ["-hwaccel", "cuda"]


def preprocess(video: Path, cache_root: Path, force: bool = False, thumb_fps: float = 1.0) -> Path:
    vid = video.stem
    out = cache_root / vid
    out.mkdir(parents=True, exist_ok=True)
    print(f"[preprocess] {video.name} -> {out}")

    meta_p = out / "meta.json"
    if force or not meta_p.exists():
        meta = probe(video)
        meta["source"] = str(video.resolve())
        meta_p.write_text(json.dumps(meta, indent=1), encoding="utf-8")
    meta = json.loads(meta_p.read_text(encoding="utf-8"))
    print(f"  duration={meta['duration']:.0f}s  {meta['width']}x{meta['height']}@{meta['fps']:.1f}")

    audio_p = out / "audio.wav"
    if force or not audio_p.exists():
        run(["ffmpeg", "-y", "-i", str(video), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(audio_p)])

    proxy_p = out / "proxy.mp4"
    thumbs_d = out / "thumbs"
    if force or not proxy_p.exists() or not thumbs_d.exists():
        if thumbs_d.exists():
            shutil.rmtree(thumbs_d)
        thumbs_d.mkdir()
        # 프록시와 썸네일을 한 번의 디코딩으로 동시에 뽑는다.
        base = ["ffmpeg", "-y"]
        tail = [
            "-i", str(video),
            "-filter_complex", f"[0:v]split=2[p][t];[p]scale=-2:480[pv];[t]fps={thumb_fps},scale=-2:360[tv]",
            "-map", "[pv]", "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "28", str(proxy_p),
            "-map", "[tv]", "-q:v", "4", str(thumbs_d / "%06d.jpg"),
        ]
        try:
            run(base + hw_decode_args() + tail)
        except subprocess.CalledProcessError:
            print("  (hw decode failed, falling back to CPU)")
            run(base + tail)
    print("  done")
    return out


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="원본 영상을 캐시로 전처리")
    ap.add_argument("videos", nargs="+", type=Path)
    ap.add_argument("--cache", type=Path, default=Path("cache"))
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    for v in a.videos:
        preprocess(v, a.cache, a.force)
