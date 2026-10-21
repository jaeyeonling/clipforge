"""게임 프로필 로더. games/<game>.yaml 을 읽고 ROI 비율을 실제 해상도 픽셀로 변환한다."""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
GAMES = ROOT / "games"


def load_profile(game: str) -> dict:
    p = GAMES / f"{game}.yaml"
    if not p.exists():
        raise FileNotFoundError(f"게임 프로필 없음: {p}  (games/ 에 {game}.yaml 추가)")
    prof = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    from .schema import migrate

    prof = migrate("profile", prof, p)
    prof.setdefault("rois", {})
    prof.setdefault("roi_crops", [])
    prof.setdefault("frames", {})
    return prof


def roi_pixels(prof: dict, width: int, height: int) -> dict[str, list[int]]:
    """비율 ROI → [x, y, w, h] 픽셀. ffmpeg crop 은 짝수 크기를 선호하므로 2의 배수로 맞춘다."""
    out = {}
    for name, (fx, fy, fw, fh) in prof["rois"].items():
        x, y = int(fx * width) // 2 * 2, int(fy * height) // 2 * 2
        w, h = max(2, int(fw * width) // 2 * 2), max(2, int(fh * height) // 2 * 2)
        w, h = min(w, width - x), min(h, height - y)
        out[name] = [x, y, w, h]
    return out


def guess_game(video: Path, default: str = "d2r") -> str:
    """파일명 접두어(d2r_, dnf_)로 게임 추정. 없으면 default."""
    stem = video.stem.lower()
    for g in ("d2r", "dnf"):
        if stem.startswith(g + "_") or stem.startswith(g + "-"):
            return g
    return default
