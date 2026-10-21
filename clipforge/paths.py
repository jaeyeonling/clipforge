"""앱 폴더와 데이터 폴더 — 경로의 기준은 여기 한 곳.

- 앱 폴더(APP_ROOT): 코드 · 게임 프로필(games/) · 사전(data/) · 글꼴(assets/) · 모델(models/) · 화면 빌드(app/dist).
  설치본에서는 런타임 폴더이고, 앱 코드 업데이트가 통째로 교체하는 곳이라 사용자 데이터를 두면 안 된다.
- 데이터 폴더(data_root()): 영상 · 캐시 · 판정 · 회차 목록 · 사용자 화면 영역. 환경변수 CLIPFORGE_DATA,
  없으면(개발) 저장소. 업데이트가 건드리지 않는다.
"""

from __future__ import annotations

import os
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent


def data_root() -> Path:
    return Path(os.environ.get("CLIPFORGE_DATA", str(APP_ROOT)))
