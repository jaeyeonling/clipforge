"""데스크톱 앱 진입점 (로컬 웹 UI): 엔진 서버를 127.0.0.1 에 띄우고 브라우저를 연다.

    python -m clipforge.app [--port 8765] [--no-browser]
"""
from __future__ import annotations

import argparse
import threading
import webbrowser

import uvicorn

from .api.server import create_app


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args()
    app = create_app()
    url = f"http://127.0.0.1:{a.port}/"
    if not a.no_browser:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    print(f"clipforge engine: {url}  (Ctrl+C 로 종료)")
    uvicorn.run(app, host="127.0.0.1", port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
