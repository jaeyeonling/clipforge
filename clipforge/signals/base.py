"""신호 플러그인 인터페이스.

신호 = 캐시 디렉터리를 읽어서 Curve 또는 Segments를 내놓는 함수.
새 신호를 추가하려면 이 모듈의 `@signal` 데코레이터로 등록만 하면
`python -m clipforge.run signals <cache_dir>`에서 자동으로 실행된다.

    @signal("my_signal")
    def my_signal(cache: Path) -> Curve | Segments: ...
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from ..timeline import Curve, Segments

SignalFn = Callable[[Path], Curve | Segments]
REGISTRY: dict[str, SignalFn] = {}


def signal(name: str):
    def deco(fn: SignalFn) -> SignalFn:
        REGISTRY[name] = fn
        return fn
    return deco


def run_signal(name: str, cache: Path, force: bool = False) -> Curve | Segments:
    out = cache / f"{name}.json"
    if out.exists() and not force:
        try:
            return Curve.load(out)
        except TypeError:
            return Segments.load(out)
    result = REGISTRY[name](cache)
    result.save(out)
    return result
