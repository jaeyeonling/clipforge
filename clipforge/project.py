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

from . import __version__ as ENGINE_VERSION
from .errors import EngineError
from .schema import SCHEMA, load_json, load_project_file

APP_ROOT = Path(__file__).resolve().parent.parent


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
        # 데이터 폴더 스키마 (project.json). 엔진보다 새 버전이면 읽기 전용으로 열고 health/job.run 에서 막는다.
        self.project_info: dict = {}
        self.schema_error: dict | None = None
        try:
            self.project_info = load_project_file(self.data_root)
        except EngineError as e:
            self.schema_error = e.to_dict()
        self.log_path = self.reports / "engine.log"
        _setup_logging(self.log_path)

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
    def ui_dir(self) -> Path:
        """React 빌드(app/dist)가 있으면 그것을, 없으면 예전 바닐라 ui/ 를 서빙한다."""
        dist = self.app_root / "app" / "dist"
        return dist if (dist / "index.html").exists() else self.app_root / "ui"

    def health(self) -> dict:
        """첫 실행 진단: 도구·GPU·모델·폰트."""
        import subprocess
        out = {"engine_version": ENGINE_VERSION, "schema": dict(SCHEMA), "project": self.project_info,
               "schema_error": self.schema_error, "log_path": str(self.log_path),
               "app_root": str(self.app_root), "data_root": str(self.data_root),
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
        try:
            out["disk_free_gb"] = round(shutil.disk_usage(self.data_root).free / 1e9, 1)
        except Exception:
            out["disk_free_gb"] = None
        out["problems"] = health_problems(out)
        return out

    def episode_ids(self) -> list[str]:
        ids = {p.stem for p in self.videos.glob("*.mp4")} | {p.name for p in self.cache.iterdir() if p.is_dir() and (p / "meta.json").exists()}
        return sorted(ids)

    def episode_info(self, vid: str) -> dict:
        meta_p = self.cache / vid / "meta.json"
        try:
            meta = load_json(meta_p, "meta") if meta_p.exists() else {}
        except EngineError:
            meta = {}
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


def health_problems(h: dict) -> list[dict]:
    """health 결과 → 사용자에게 보여줄 문제 목록 [{level: error|warn, code, message, hint}]. UI 상단 배너의 입력."""
    out = []
    if h.get("schema_error"):
        e = h["schema_error"]; out.append({"level": "error", "code": e["code"], "message": e["message"], "hint": e["hint"]})
    if not h.get("ffmpeg_ok"):
        out.append({"level": "error", "code": "E_FFMPEG_MISSING", "message": "ffmpeg 를 실행할 수 없습니다",
                    "hint": "설치 폴더 bin/ 에 ffmpeg.exe·ffprobe.exe 를 두거나 CLIPFORGE_FFMPEG 환경변수로 폴더를 지정하세요."})
    if not h.get("fonts_ok"):
        out.append({"level": "error", "code": "E_FONTS_MISSING", "message": "제목 폰트(NanumPenScript)가 없습니다",
                    "hint": "assets/fonts/ 폴더를 확인하세요. 없으면 쇼츠 제목 띠가 깨집니다."})
    if not h.get("rapidocr"):
        out.append({"level": "error", "code": "E_OCR_MISSING", "message": "RapidOCR 이 설치되지 않았습니다",
                    "hint": "pip install -r requirements.txt 를 실행하세요. 배너·채팅 신호가 동작하지 않습니다."})
    if h.get("ffmpeg_ok") and not h.get("nvenc"):
        out.append({"level": "warn", "code": "W_NO_NVENC", "message": "NVENC 인코더가 없어 CPU 로 렌더합니다 (느림)",
                    "hint": "NVIDIA GPU 와 최신 드라이버가 있으면 자동으로 NVENC 를 씁니다."})
    if not h.get("whisper_gpu"):
        out.append({"level": "warn", "code": "W_NO_GPU_WHISPER", "message": "전사가 CPU 로 돌아갑니다 (12분 영상 약 20분)",
                    "hint": "CUDA 런타임(nvidia-cublas-cu12, nvidia-cudnn-cu12)을 확인하세요."})
    if h.get("disk_free_gb") is not None and h["disk_free_gb"] < 10:
        out.append({"level": "warn", "code": "W_DISK_LOW", "message": f"디스크 여유 {h['disk_free_gb']}GB",
                    "hint": "4K 회차 하나의 캐시가 수 GB 입니다. cache/<회차>/frames 는 지워도 됩니다."})
    return out


def _setup_logging(path: Path) -> None:
    """엔진 전역 로그(reports/engine.log, 회전 2MB×3). 작업별 JSONL 로그와 별개로, 전송층 예외·경고가 여기 쌓인다."""
    import logging
    from logging.handlers import RotatingFileHandler
    log = logging.getLogger("clipforge")
    if any(getattr(h, "baseFilename", None) == str(path) for h in log.handlers):
        return
    try:
        h = RotatingFileHandler(path, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        log.addHandler(h)
        log.setLevel(logging.INFO)
    except OSError:
        pass
