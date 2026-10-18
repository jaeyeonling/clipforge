"""전처리 캐시 (L0).

원본 영상을 **한 번만** 디코딩해서 아래를 `cache/<video_id>/`에 저장한다.
이후 모든 신호 함수는 원본이 아니라 이 캐시만 읽는다. 4K60 원본은 NVDEC 로도 실시간의 4배 속도라
(2시간 → 패스당 ~30분) 패스 수가 곧 비용이다.

  meta.json            ffprobe 메타 + game + rois(픽셀) + frames 설정
  audio.wav            16kHz mono PCM  (음량, Whisper, 음성 지문 공용)
  frames/%06d.jpg      1fps, 최대 1080p (frame_motion, 바닥 라벨 OCR, 눈검수)
  rois/<name>/%06d.jpg 1fps, 네이티브 해상도 크롭 (득템 배너·채팅 OCR). 게임 프로필 roi_crops
  proxy.mp4            (옵션 --proxy) 480p NVENC 프록시. 기본 생략

video_id = 파일명(확장자 제외). 이미 있는 산출물은 건너뛴다(--force 로 재생성).
"""
from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path

from .profiles import guess_game, load_profile, roi_pixels
from .schema import load_json, write_json


def run(cmd: list[str], quiet: bool = True, cwd: Path | None = None) -> None:
    shown = " ".join(c if len(c) < 60 else c[:57] + "..." for c in cmd[:10])
    print(f"  $ {shown}{' ...' if len(cmd) > 10 else ''}", flush=True)
    t0 = time.time()
    subprocess.run(cmd, check=True, cwd=cwd,
                   stdout=subprocess.DEVNULL if quiet else None,
                   stderr=subprocess.DEVNULL if quiet else None)
    print(f"    ({time.time() - t0:.0f}s)", flush=True)


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
        "has_audio": any(s["codec_type"] == "audio" for s in info["streams"]),
    }


def parse_scdet(path: Path) -> list[float]:
    """metadata=print 출력에서 장면 전환 시각(초) 추출. 'lavfi.scd.time=...' 줄만."""
    cuts = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if line.startswith("lavfi.scd.time="):
            try:
                cuts.append(round(float(line.split("=", 1)[1]), 3))
            except ValueError:
                pass
    return cuts


def hw_decode_args() -> list[str]:
    """NVIDIA 머신이면 NVDEC. 실패하면 호출부에서 CPU로 재시도."""
    return ["-hwaccel", "cuda"]


def build_single_pass(video: Path, out: Path, meta: dict, want_audio: bool) -> list[str]:
    """오디오 + frames + ROI 크롭을 한 번의 디코딩으로 뽑는 ffmpeg 명령."""
    fps = meta["frames"]["fps"]
    frame_h = meta["frames"]["height"]
    crops = meta["roi_crops"]

    scene_cuts = bool(meta.get("scene_cuts", True))
    n_out = 1 + len(crops)
    labels = "".join(f"[s{i}]" for i in range(n_out))
    src = "[v0]" if scene_cuts else "[0:v]"
    fc = []
    if scene_cuts:
        # 전체 프레임레이트 스트림을 320p 로 줄여 장면 전환 감지. 비용 측정 결과 추가 시간 ~0 (디코딩이 병목)
        fc.append("[0:v]split=2[v0][v1]")
        fc.append(f"[v1]scale=320:-2,scdet=t={meta.get('scdet_threshold', 10)},"
                  f"metadata=mode=print:file=scdet.txt[sc]")
    fc.append(f"{src}fps={fps}" + (f",split={n_out}{labels}" if n_out > 1 else "[s0]"))
    fc.append(f"[s0]scale=-2:{frame_h}[frames]")
    for i, name in enumerate(crops, 1):
        x, y, w, h = meta["rois"][name]
        fc.append(f"[s{i}]crop={w}:{h}:{x}:{y}[{name}]")

    # 경로는 전부 cache 디렉터리 기준 상대경로 (subprocess cwd=out). 'C:' 의 콜론이 필터 옵션 파서를 깨뜨리기 때문.
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(video.resolve()), "-filter_complex", ";".join(fc)]
    cmd += ["-map", "[frames]", "-q:v", "3", "frames/%06d.jpg"]
    for name in crops:
        cmd += ["-map", f"[{name}]", "-q:v", "2", f"rois/{name}/%06d.jpg"]
    if scene_cuts:
        cmd += ["-map", "[sc]", "-f", "null", "-"]
    if want_audio:
        cmd += ["-map", "0:a:0", "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", "audio.wav"]
    return cmd


def preprocess(video: Path, cache_root: Path, force: bool = False, game: str | None = None,
               proxy: bool = False, vid: str | None = None) -> Path:
    vid = vid or video.stem                       # 참조 등록이면 파일 이름과 회차 id 가 다를 수 있다
    out = cache_root / vid
    out.mkdir(parents=True, exist_ok=True)
    game = game or guess_game(video)
    prof = load_profile(game)
    print(f"[preprocess] {video.name} -> {out}  (game={game})")

    meta_p = out / "meta.json"
    if force or not meta_p.exists():
        meta = probe(video)
        meta["source"] = str(video.resolve())
        meta["game"] = game
        meta["rois"] = roi_pixels(prof, meta["width"], meta["height"])
        meta["frames"] = {"fps": float(prof["frames"].get("fps", 1.0)),
                          "height": min(int(prof["frames"].get("max_height", 1080)), meta["height"])}
        meta["roi_crops"] = [n for n in prof["roi_crops"] if n in meta["rois"]]
        meta["scene_cuts"] = bool(prof["frames"].get("scene_cuts", True))
        meta["scdet_threshold"] = float(prof["frames"].get("scdet_threshold", 10))
        write_json(meta_p, "meta", meta)
    meta = load_json(meta_p, "meta")
    print(f"  duration={meta['duration']:.0f}s  {meta['width']}x{meta['height']}@{meta['fps']:.2f}  "
          f"frames {meta['frames']['fps']}fps@{meta['frames']['height']}p  rois={meta['roi_crops']}")

    frames_d, rois_d, audio_p = out / "frames", out / "rois", out / "audio.wav"
    need_frames = force or not frames_d.exists() or not any(frames_d.glob("*.jpg"))
    need_audio = meta.get("has_audio", True) and (force or not audio_p.exists())
    if need_frames:
        shutil.rmtree(frames_d, ignore_errors=True)
        shutil.rmtree(rois_d, ignore_errors=True)
        frames_d.mkdir()
        for name in meta["roi_crops"]:
            (rois_d / name).mkdir(parents=True)
        cmd = build_single_pass(video, out, meta, want_audio=need_audio)
        try:
            run(cmd[:1] + hw_decode_args() + cmd[1:], cwd=out)
        except subprocess.CalledProcessError:
            print("  (hw decode failed, falling back to CPU)")
            run(cmd, cwd=out)
        n = len(list(frames_d.glob("*.jpg")))
        print(f"  frames: {n}  (expected ~{int(meta['duration'] * meta['frames']['fps'])})")
        if (out / "scdet.txt").exists():
            cuts = parse_scdet(out / "scdet.txt")
            (out / "cuts.json").write_text(json.dumps(cuts), encoding="utf-8")
            (out / "scdet.txt").unlink()
            print(f"  scene cuts: {len(cuts)}")
    elif need_audio:   # 프레임은 있고 오디오만 빠진 경우: 비디오 디코딩 없이
        run(["ffmpeg", "-y", "-v", "error", "-i", str(video), "-vn", "-ac", "1", "-ar", "16000",
             "-c:a", "pcm_s16le", str(audio_p)])

    proxy_p = out / "proxy.mp4"
    if proxy and (force or not proxy_p.exists()):
        base = ["ffmpeg", "-y", "-v", "error"]
        tail = ["-i", str(video), "-vf", "scale=-2:480", "-an", "-c:v", "h264_nvenc", "-preset", "p4", "-cq", "30",
                str(proxy_p)]
        try:
            run(base + hw_decode_args() + tail)
        except subprocess.CalledProcessError:
            print("  (nvenc proxy failed, falling back to libx264)")
            run(base + ["-i", str(video), "-vf", "scale=-2:480", "-an", "-c:v", "libx264", "-preset", "veryfast",
                        "-crf", "28", str(proxy_p)])
    print("  done")
    return out


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="원본 영상을 캐시로 전처리")
    ap.add_argument("videos", nargs="+", type=Path)
    ap.add_argument("--cache", type=Path, default=Path("cache"))
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--game", default=None)
    ap.add_argument("--proxy", action="store_true")
    a = ap.parse_args()
    for v in a.videos:
        preprocess(v, a.cache, a.force, a.game, a.proxy)
