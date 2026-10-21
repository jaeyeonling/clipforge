"""캡처 소스. 모두 `next_frame() -> (t_wall, PIL.Image RGB) | None`.

ScreenSource(bbox|monitor)  : Windows 화면 캡처 (PIL.ImageGrab, CPU 복사 1장/초 수준). 게임 창이 있는 모니터/영역.
FramesDirSource(dir, fps)   : cache/<id>/frames/*.jpg 를 순서대로 (개발·테스트: 방송 없이 파이프라인을 돌려본다)
VideoFileSource(path, fps)  : 영상 파일을 ffmpeg 로 fps 간격 디코딩 (리플레이 테스트)
ObsSource                   : obs-websocket GetSourceScreenshot (후속 — OBS 가 보는 그대로, 창 가림 영향 없음)
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

from PIL import Image


class FrameSource:
    name = "base"

    def next_frame(self) -> tuple[float, Image.Image] | None:
        raise NotImplementedError

    def close(self) -> None:
        pass


class ScreenSource(FrameSource):
    name = "screen"

    def __init__(self, bbox: tuple[int, int, int, int] | None = None, monitor: int | None = None):
        """bbox = (left, top, right, bottom) 절대 좌표. 없으면 주 모니터 전체. all_screens=True 로 다중 모니터 좌표계."""
        self.bbox = bbox
        self.monitor = monitor

    def next_frame(self):
        from PIL import ImageGrab

        im = ImageGrab.grab(bbox=self.bbox, all_screens=True) if self.bbox else ImageGrab.grab()
        return time.time(), im.convert("RGB")


class FramesDirSource(FrameSource):
    name = "frames"

    def __init__(
        self, frames_dir: Path, fps: float = 1.0, start: int = 0, end: int | None = None, realtime: bool = False
    ):
        self.files = sorted(Path(frames_dir).glob("*.jpg"))[start:end]
        self.i = 0
        self.fps = fps
        self.realtime = realtime
        self.t0 = time.time()

    def next_frame(self):
        if self.i >= len(self.files):
            return None
        p = self.files[self.i]
        self.i += 1
        t = self.t0 + (self.i - 1) / self.fps
        if self.realtime:
            now = time.time()
            if t > now:
                time.sleep(t - now)
        return t, Image.open(p).convert("RGB")


class VideoFileSource(FrameSource):
    name = "video"

    def __init__(self, path: Path, fps: float = 1.0, width: int = 1920, start_s: float = 0.0):
        self.path = Path(path)
        self.fps = fps
        self.width = width
        self.start_s = start_s
        self.proc: subprocess.Popen[bytes] | None = None
        self.h = 0  # _open 에서 영상 비율로 정한다
        self.i = 0
        self.t0 = time.time()

    def _open(self):
        probe = (
            subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-select_streams",
                    "v:0",
                    "-show_entries",
                    "stream=width,height",
                    "-of",
                    "csv=p=0",
                    str(self.path),
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            .stdout.strip()
            .split(",")
        )
        w, h = int(probe[0]), int(probe[1])
        self.h = max(2, round(h * self.width / w / 2) * 2)
        self.proc = subprocess.Popen(
            [
                "ffmpeg",
                "-v",
                "error",
                "-ss",
                str(self.start_s),
                "-i",
                str(self.path),
                "-vf",
                f"fps={self.fps},scale={self.width}:{self.h}",
                "-f",
                "rawvideo",
                "-pix_fmt",
                "rgb24",
                "-",
            ],
            stdout=subprocess.PIPE,
        )

    def next_frame(self):
        if self.proc is None:
            self._open()
        assert self.proc is not None and self.proc.stdout is not None
        n = self.width * self.h * 3
        buf = self.proc.stdout.read(n)
        if len(buf) < n:
            return None
        t = self.t0 + self.i / self.fps
        self.i += 1
        return t, Image.frombytes("RGB", (self.width, self.h), buf)

    def close(self):
        if self.proc:
            self.proc.kill()
            self.proc = None


def make_source(cfg: dict, project=None) -> FrameSource:
    kind = cfg.get("source", "screen")
    if kind == "screen":
        bb = cfg.get("bbox")
        return ScreenSource(tuple(bb) if bb else None)
    if kind == "frames":
        d = Path(cfg["frames_dir"]) if cfg.get("frames_dir") else (project.cache / cfg["episode"] / "frames")
        return FramesDirSource(
            d,
            fps=float(cfg.get("fps", 1.0)),
            start=int(cfg.get("start", 0)),
            end=cfg.get("end"),
            realtime=bool(cfg.get("realtime", False)),
        )
    if kind == "video":
        return VideoFileSource(
            Path(cfg["path"]), fps=float(cfg.get("fps", 1.0)), start_s=float(cfg.get("start_s", 0.0))
        )
    raise ValueError(f"알 수 없는 소스: {kind}")
