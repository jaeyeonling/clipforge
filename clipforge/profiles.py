"""게임 프로필 로더. games/<game>.yaml 을 읽고 ROI 비율을 실제 해상도 픽셀로 변환한다.

공통 설정(games/common.yaml: 리액션·채팅 어휘, 전사, 회차 종류별 신호 묶음, 정답 범주)은 모든 게임이 같이 쓰고,
게임 프로필에 같은 키가 있으면 그 게임에서는 그 값이 이긴다 (load_settings).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
GAMES = ROOT / "games"

# 게임 프로필이 덮어쓸 수 있는 공통 설정 키
SHARED_KEYS = ("speech_keywords", "chat_keywords", "speech_kernel", "transcribe", "pipelines", "label_categories")


def _read_yaml(p: Path) -> dict:
    return (yaml.safe_load(p.read_text(encoding="utf-8")) or {}) if p.exists() else {}


def _merge(base, over):
    """사전은 한 단계씩 합치고, 목록·값은 통째로 바꾼다."""
    if isinstance(base, dict) and isinstance(over, dict):
        out = dict(base)
        for k, v in over.items():
            out[k] = _merge(base.get(k), v)
        return out
    return over


def load_settings(game: str | None = None, games_dir: Path | None = None) -> dict:
    """공통 설정에 게임 프로필의 같은 키(SHARED_KEYS)를 덮어쓴 결과. game 이 없거나 프로필이 없으면 공통 설정 그대로."""
    gd = games_dir or GAMES
    common = _read_yaml(gd / "common.yaml")
    if not game:
        return common
    prof = _read_yaml(gd / f"{game}.yaml")
    out = dict(common)
    for k in SHARED_KEYS:
        if k in prof:
            out[k] = _merge(common.get(k), prof[k])
    return out


def episode_game(cache: Path) -> str | None:
    """전처리한 회차의 게임 (cache/<id>/meta.json). 아직 전처리 전이면 None."""
    try:
        return json.loads((cache / "meta.json").read_text(encoding="utf-8")).get("game")
    except (FileNotFoundError, json.JSONDecodeError):
        return None


# 사용자가 화면 영역 탭에서 고친 값. 데이터 폴더에 두어 앱 업데이트(games/ 교체)가 지우지 않게 한다.
USER_KEYS = ("rois", "panel_bands")


def user_profiles_dir() -> Path:
    return Path(os.environ.get("CLIPFORGE_DATA", str(ROOT))) / "profiles"


def load_user_overrides(game: str, user_dir: Path | None = None) -> dict:
    return _read_yaml((user_dir or user_profiles_dir()) / f"{game}.yaml")


def save_user_overrides(game: str, values: dict, user_dir: Path | None = None) -> Path:
    """사용자 값(USER_KEYS)만 저장한다. 기존 사용자 값과 합친다."""
    d = user_dir or user_profiles_dir()
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{game}.yaml"
    cur = _read_yaml(p)
    cur.update({k: v for k, v in values.items() if k in USER_KEYS})
    cur["schema_version"] = 1
    p.write_text(yaml.safe_dump(cur, allow_unicode=True, sort_keys=False, width=200), encoding="utf-8")
    return p


def load_profile(game: str, user_dir: Path | None = None) -> dict:
    """앱의 기본 프로필(games/<game>.yaml) 위에 사용자 값(데이터 폴더 profiles/<game>.yaml)을 겹친다."""
    p = GAMES / f"{game}.yaml"
    if not p.exists():
        raise FileNotFoundError(f"게임 프로필 없음: {p}  (games/ 에 {game}.yaml 추가)")
    prof = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    from .schema import migrate

    prof = migrate("profile", prof, p)
    over = load_user_overrides(game, user_dir)
    if isinstance(over.get("rois"), dict):
        prof["rois"] = {**(prof.get("rois") or {}), **over["rois"]}  # 기본에 새로 생긴 영역은 살린다
    if over.get("panel_bands"):
        prof["panel_bands"] = over["panel_bands"]
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


def guess_game(video: Path, default: str = "d2r", games_dir: Path | None = None) -> str:
    """파일명 접두어(<게임>_ 또는 <게임>-)로 게임 추정. games/ 에 있는 프로필 이름이면 무엇이든. 없으면 default."""
    stem = video.stem.lower()
    names = sorted((p.stem for p in (games_dir or GAMES).glob("*.yaml") if p.stem != "common"), key=len, reverse=True)
    for g in names:
        if stem.startswith(g.lower() + "_") or stem.startswith(g.lower() + "-"):
            return g
    return default
