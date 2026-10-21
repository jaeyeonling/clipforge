"""릴리스 노트: CHANGELOG.md 에서 그 버전의 절을 꺼내고, 설치 안내를 붙인다.

python scripts/release_notes.py 0.2.0 runtime-2026.10 > notes.md
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def section(changelog: str, version: str) -> str:
    """'## [version]' 부터 다음 '## [' 앞까지 (제목 줄 제외)."""
    m = re.search(rf"^## \[{re.escape(version)}\][^\n]*\n(.*?)(?=^## \[|\Z)", changelog, re.M | re.S)
    if not m:
        raise SystemExit(f"CHANGELOG.md 에 [{version}] 절이 없어요")
    return m.group(1).strip()


def notes(version: str, runtime_tag: str, changelog: str) -> str:
    return "\n".join(
        [
            "## 설치",
            "",
            f"`clipforge-Setup-{version}.exe` 를 받아 실행하세요. 관리자 권한은 필요 없어요.",
            f"처음 켜면 분석 엔진 구성요소를 받아요 (런타임 릴리스 `{runtime_tag}`, GPU 가속은 NVIDIA 가 PyPI 에 올린 라이브러리).",
            "이미 쓰고 있다면 앱이 새 버전을 알려 주고, 바뀐 부분만 받아요.",
            "",
            section(changelog, version),
            "",
        ]
    )


if __name__ == "__main__":
    ver, rt = sys.argv[1], sys.argv[2]
    sys.stdout.reconfigure(encoding="utf-8")
    print(notes(ver, rt, (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")))
