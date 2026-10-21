"""스키마 버전과 마이그레이션 (docs/ARCHITECTURE.md · 데이터와 폴더).

버전이 붙는 파일 = 사람이 만든 것이거나 다른 프로그램이 읽는 것:
  project.json(데이터 폴더 루트) · cache/<id>/meta.json · cache/<id>/shorts.json · review/<id>/shorts/index.json · games/<game>.yaml
labels/*.csv 는 열 구조가 곧 스키마(start,end,label,note)라 파일 안에 버전을 두지 않고 project.json 의 labels_schema 로 관리한다.
신호 캐시(cache/<id>/*.json 중 Curve/Segments)는 재생성 가능하므로 버전 대상이 아니다 — 형식이 바뀌면 prep/signals 를 강제 재계산한다.

규칙
- 쓰기: write_json(path, kind, payload) — dict 는 schema_version 키를 붙이고, 리스트형(shorts·index)은 {"schema_version", "<items>": [...]} 로 감싼다.
- 읽기: load_json(path, kind) — 버전 0(키 없음·맨 리스트)부터 현재까지 MIGRATIONS 를 순서대로 적용해 payload 를 돌려준다.
  엔진보다 새 버전이면 E_SCHEMA_NEWER (덮어쓰지 않는다).
- 새 버전을 올릴 때: SCHEMA[kind] += 1, MIGRATIONS[kind][old] = fn(old_data) -> new_data 를 추가한다. 마이그레이션은 메모리에서만 하고,
  rewrite=True 를 준 호출자만 파일을 새 형식으로 다시 쓴다.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import __version__ as ENGINE_VERSION
from .errors import EngineError

KEY = "schema_version"
SCHEMA: dict[str, int] = {"project": 1, "meta": 1, "shorts": 1, "index": 1, "profile": 1, "labels": 1}
LIST_KEY: dict[str, str] = {"shorts": "candidates", "index": "items"}  # v0 가 맨 리스트였던 종류의 v1 래퍼 키

Migration = Callable[[Any], Any]
MIGRATIONS: dict[str, dict[int, Migration]] = {k: {} for k in SCHEMA}


def _v0_to_v1(kind: str) -> Migration:
    def fn(data: Any) -> Any:
        if kind in LIST_KEY and isinstance(data, list):
            return {KEY: 1, LIST_KEY[kind]: data}
        if isinstance(data, dict):
            return {KEY: 1, **{k: v for k, v in data.items() if k != KEY}}
        raise EngineError(
            "E_SCHEMA_BAD",
            f"{kind}: 알 수 없는 파일 형식 ({type(data).__name__})",
            "파일이 손상됐을 수 있습니다. 캐시라면 지우고 다시 실행하세요.",
        )

    return fn


for _k in SCHEMA:
    MIGRATIONS[_k][0] = _v0_to_v1(_k)


def version_of(data: Any) -> int:
    if isinstance(data, dict):
        try:
            return int(data.get(KEY, 0))
        except (TypeError, ValueError):
            return 0
    return 0


def migrate(kind: str, data: Any, where: str | Path | None = None) -> Any:
    """메모리 내 마이그레이션. 반환은 현재 버전 형식(dict, 리스트형은 래퍼 dict)."""
    cur = SCHEMA[kind]
    v = version_of(data)
    name = str(where or kind)
    if v > cur:
        raise EngineError(
            "E_SCHEMA_NEWER",
            f"{name}: schema v{v} 는 이 엔진(v{cur})보다 새 버전입니다",
            "엔진을 최신으로 업데이트하세요. 파일은 변경하지 않았습니다.",
        )
    while v < cur:
        fn = MIGRATIONS[kind].get(v)
        if fn is None:
            raise EngineError(
                "E_SCHEMA_GAP",
                f"{name}: v{v} → v{v + 1} 마이그레이션이 없습니다",
                "엔진 결함입니다. 로그를 첨부해 알려주세요.",
                kind="internal",
            )
        data = fn(data)
        nv = version_of(data)
        if nv <= v:
            raise EngineError(
                "E_SCHEMA_GAP",
                f"{name}: 마이그레이션 v{v} 가 버전을 올리지 않았습니다",
                "엔진 결함입니다.",
                kind="internal",
            )
        v = nv
    return data


def stamp(kind: str, payload: Any) -> Any:
    """파일에 쓸 객체: 리스트형은 래핑, dict 는 버전 키를 맨 앞에."""
    if kind in LIST_KEY:
        return {KEY: SCHEMA[kind], LIST_KEY[kind]: list(payload)}
    return {KEY: SCHEMA[kind], **{k: v for k, v in dict(payload).items() if k != KEY}}


def unwrap(kind: str, data: Any) -> Any:
    return data[LIST_KEY[kind]] if kind in LIST_KEY else data


def write_json(path: Path, kind: str, payload: Any, indent: int = 1) -> None:
    Path(path).write_text(json.dumps(stamp(kind, payload), ensure_ascii=False, indent=indent), encoding="utf-8")


def load_json(path: Path, kind: str, rewrite: bool = False) -> Any:
    """읽기 + 마이그레이션. 반환은 payload(리스트형은 리스트, dict 형은 schema_version 을 포함한 dict)."""
    path = Path(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise EngineError(
            "E_SCHEMA_BAD",
            f"{path.name}: JSON 파싱 실패 ({e.msg} line {e.lineno})",
            "파일이 손상됐습니다. 캐시라면 지우고 해당 단계를 다시 실행하세요.",
        ) from e
    v0 = version_of(raw) if isinstance(raw, dict) else 0
    data = migrate(kind, raw, path)
    if rewrite and v0 != SCHEMA[kind]:
        write_json(path, kind, unwrap(kind, data))
    return unwrap(kind, data)


# ---------- project.json (데이터 폴더 루트) ----------
def load_project_file(data_root: Path) -> dict:
    """없으면 만든다. 있으면 마이그레이션(엔진보다 새 버전이면 E_SCHEMA_NEWER)."""
    p = Path(data_root) / "project.json"
    if p.exists():
        d = load_json(p, "project")
        if d.get("labels_schema", 0) > SCHEMA["labels"]:
            raise EngineError(
                "E_SCHEMA_NEWER",
                f"labels 스키마 v{d['labels_schema']} 는 이 엔진(v{SCHEMA['labels']})보다 새 버전입니다",
                "엔진을 업데이트하세요.",
            )
        changed = False
        if d.get("engine_version") != ENGINE_VERSION:
            d["engine_version"], d["last_opened_by"] = ENGINE_VERSION, d.get("engine_version")
            changed = True
        if d.get("labels_schema") != SCHEMA["labels"]:
            d["labels_schema"] = SCHEMA["labels"]
            changed = True
        if changed:
            write_json(p, "project", d)
        return d
    d = {
        "engine_version": ENGINE_VERSION,
        "labels_schema": SCHEMA["labels"],
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "schemas": dict(SCHEMA),
    }
    write_json(p, "project", d)
    return {KEY: SCHEMA["project"], **d}
