"""프로젝트/경로/도구 설정 객체. 전역 상수와 PATH 의존을 여기로 모은다 (PRODUCT_ARCHITECTURE §10-1).

- 앱 폴더(코드·모델·폰트·기본 사전)와 데이터 폴더(videos/cache/labels/review/premiere)를 구분한다.
  지금은 둘 다 저장소 루트지만, `CLIPFORGE_DATA` 환경변수나 Project(data_root=...) 로 분리할 수 있다.
- ffmpeg/ffprobe 는 1) 앱 폴더 bin/, 2) 환경변수 CLIPFORGE_FFMPEG, 3) PATH, 4) winget 설치 폴더 순으로 찾아
  찾은 폴더를 PATH 앞에 붙인다. 신호·렌더 코드는 그냥 "ffmpeg" 를 호출하면 된다.
"""
from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_VERSION = 1


def find_ffmpeg() -> Path | None:
    cands: list[Path] = [APP_ROOT / "bin"]
    if os.environ.get("CLIPFORGE_FFMPEG"):
        cands.append(Path(os.environ["CLIPFORGE_FFMPEG"]))
    exe = shutil.which("ffmpeg")
    if exe:
        return Path(exe).parent
    local = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages"
    if local.exists():
        for p in local.glob("Gyan.FFmpeg*/**/bin/ffmpeg.exe"):
            cands.append(p.parent)
    for c in cands:
        if (c / "ffmpeg.exe").exists() or (c / "ffmpeg").exists():
            return c
    return None


@dataclass
class Project:
    app_root: Path = APP_ROOT
    data_root: Path = field(default_factory=lambda: Path(os.environ.get("CLIPFORGE_DATA", str(APP_ROOT))))

    def __post_init__(self):
        self.app_root = Path(self.app_root); self.data_root = Path(self.data_root)
        for d in (self.videos, self.cache, self.labels, self.review, self.premiere, self.reports):
            d.mkdir(parents=True, exist_ok=True)
        ff = find_ffmpeg()
        self.ffmpeg_dir = ff
        if ff and str(ff) not in os.environ.get("PATH", ""):
            os.environ["PATH"] = str(ff) + os.pathsep + os.environ.get("PATH", "")

    # 데이터
    @property
    def videos(self) -> Path: return self.data_root / "videos"
    @property
    def cache(self) -> Path: return self.data_root / "cache"
    @property
    def labels(self) -> Path: return self.data_root / "labels"
    @property
    def review(self) -> Path: return self.data_root / "review"
    @property
    def premiere(self) -> Path: return self.data_root / "premiere"
    @property
    def reports(self) -> Path: return self.data_root / "reports"
    @property
    def episodes_csv(self) -> Path: return self.data_root / "episodes.csv"
    # 앱
    @property
    def games(self) -> Path: return self.app_root / "games"
    @property
    def models(self) -> Path: return self.app_root / "models"
    @property
    def fonts(self) -> Path: return self.app_root / "assets" / "fonts"
    @property
    def ui_dir(self) -> Path: return self.app_root / "ui"

    def health(self) -> dict:
        """첫 실행 진단: 도구·GPU·모델·폰트."""
        import subprocess
        out = {"schema": SCHEMA_VERSION, "app_root": str(self.app_root), "data_root": str(self.data_root),
               "ffmpeg": str(self.ffmpeg_dir) if self.ffmpeg_dir else None, "ffmpeg_ok": False, "nvenc": False,
               "gpu": None, "whisper_gpu": False, "fonts_ok": (self.fonts / "NanumPenScript-Regular.ttf").exists(),
               "rapidocr": False}
        try:
            r = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True, timeout=20)
            out["ffmpeg_ok"] = r.returncode == 0
            out["nvenc"] = "h264_nvenc" in r.stdout
        except Exception:
            pass
        try:
            r = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
                               capture_output=True, text=True, timeout=10)
            out["gpu"] = r.stdout.strip() or None
        except Exception:
            pass
        try:
            import ctranslate2
            out["whisper_gpu"] = ctranslate2.get_cuda_device_count() > 0
        except Exception:
            pass
        try:
            import rapidocr  # noqa: F401
            out["rapidocr"] = True
        except Exception:
            pass
        return out

    def episode_ids(self) -> list[str]:
        ids = {p.stem for p in self.videos.glob("*.mp4")} | {p.name for p in self.cache.iterdir() if p.is_dir() and (p / "meta.json").exists()}
        return sorted(ids)

    def episode_info(self, vid: str) -> dict:
        meta_p = self.cache / vid / "meta.json"
        meta = json.loads(meta_p.read_text(encoding="utf-8")) if meta_p.exists() else {}
        video = next((p for p in self.videos.glob(f"{vid}.*")), None)
        stages = {
            "prep": (self.cache / vid / "frames").exists(),
            "transcribe": (self.cache / vid / "transcript.json").exists(),
            "signals": (self.cache / vid / "item_banner.json").exists(),
            "shorts": (self.cache / vid / "shorts.json").exists(),
            "export": (self.review / vid / "shorts" / "index.json").exists(),
            "xml": (self.premiere / f"{vid}_shorts.xml").exists(),
        }
        title = ""
        if self.episodes_csv.exists():
            import csv
            with open(self.episodes_csv, encoding="utf-8", newline="") as f:
                for row in csv.DictReader(f):
                    if row.get("id") == vid:
                        title = row.get("title", ""); break
        return {"id": vid, "video": str(video) if video else meta.get("source"), "title": title,
                "duration": meta.get("duration"), "width": meta.get("width"), "height": meta.get("height"),
                "game": meta.get("game"), "stages": stages}
