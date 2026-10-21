"""USB/오프라인 배포 폴더 만들기 — 서버 없이 친구 PC 에 설치.

    python scripts/make_usb_release.py --out E:/clipforge-release [--skip-installer] [--skip-components]

만드는 것:
  <out>/1-clipforge-Setup-<ver>.exe           설치본 (desktop/release 에서 복사; 없으면 npm run dist 실행)
  <out>/2-구성요소-위치-등록.cmd                더블클릭하면 %LOCALAPPDATA%\\clipforge\\update-url.txt 에 이 폴더 주소(file://)를 적는다
  <out>/latest.json, engine-code-*.zip, python-base-*.zip, cuda-*.zip, ffmpeg-*.zip, whisper-*.zip
  <out>/설치안내.txt
친구는 1 → 2 → 앱 실행 순서. 앱은 첫 실행 때 이 폴더에서 구성요소를 읽는다 (네트워크 불필요).
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
def _node_dir() -> Path:
    """npm/node 가 있는 폴더: CLIPFORGE_NODE_DIR → PATH 의 node → 포터블 Node 기본 위치(~/tools/node)."""
    if os.environ.get("CLIPFORGE_NODE_DIR"):
        return Path(os.environ["CLIPFORGE_NODE_DIR"])
    found = shutil.which("node")
    return Path(found).parent if found else Path.home() / "tools" / "node"


NODE = _node_dir()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--skip-installer", action="store_true"); ap.add_argument("--skip-components", action="store_true")
    a = ap.parse_args()
    out = Path(a.out).resolve(); out.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(ROOT))
    from clipforge import __version__ as ver

    # 1) 릴리스 아티팩트 (앱 코드 zip + 구성요소 zip + latest.json, URL 은 이 폴더 자체)
    # URL 은 상대(파일 이름만): 앱이 update-url.txt 의 폴더 기준으로 해석하므로 USB 드라이브 문자가 바뀌어도 된다
    cmd = [sys.executable, str(ROOT / "scripts" / "build_engine_dist.py"), "--skip-packages", "--skip-ffmpeg", "--skip-models",
           "--release", str(out), "--base-url", "rel"]
    if not a.skip_components:
        cmd.append("--release-components")
    subprocess.run(cmd, check=True)

    # 2) 설치본
    if not a.skip_installer:
        rel = ROOT / "desktop" / "release"
        exe = next(iter(sorted(rel.glob("clipforge-Setup-*.exe"))), None) if rel.exists() else None
        if exe is None:
            subprocess.run([str(NODE / "npm.cmd"), "run", "dist"], cwd=str(ROOT / "desktop"), check=True,
                           env={**os.environ, "PATH": f"{NODE}{os.pathsep}{os.environ.get('PATH', '')}"})
            exe = next(iter(sorted(rel.glob("clipforge-Setup-*.exe"))))
        shutil.copy2(exe, out / f"1-{exe.name}")

    # 3) 주소 등록 cmd + 안내
    (out / "2-구성요소-위치-등록.cmd").write_text(
        "@echo off\r\nchcp 65001 >nul\r\n"
        "set D=%LOCALAPPDATA%\\clipforge\r\nif not exist \"%D%\" mkdir \"%D%\"\r\n"
        "rem 이 cmd 가 있는 폴더를 file:// 주소로 적는다 (USB 드라이브 문자가 달라도 됨)\r\n"
        "set P=%~dp0\r\nset P=%P:~0,-1%\r\nset P=%P:\\=/%\r\n"
        "echo file:///%P%> \"%D%\\update-url.txt\"\r\n"
        "echo 등록 완료: file:///%P%\r\necho 이제 clipforge 를 실행하세요. 구성요소를 이 폴더에서 읽어요.\r\npause\r\n",
        encoding="utf-8")
    (out / "설치안내.txt").write_text(
        f"clipforge {ver} 오프라인 설치\r\n\r\n"
        "1) 1-clipforge-Setup-*.exe 실행 → 'Windows의 PC 보호' 창이 뜨면 [추가 정보] → [실행]\r\n"
        "2) 2-구성요소-위치-등록.cmd 더블클릭 (이 폴더 위치를 앱에 알려줘요)\r\n"
        "3) clipforge 실행 → 첫 화면에서 [설치 시작] → 이 폴더에서 구성요소를 복사해요 (3~4분)\r\n\r\n"
        "USB 를 다른 드라이브 문자로 꽂았으면 2) 를 다시 실행해 주세요.\r\n"
        "나중에 온라인 업데이트로 바꾸려면 %LOCALAPPDATA%\\clipforge\\update-url.txt 를 지우면 돼요.\r\n"
        "막히면 앱의 [도움말] 탭이나 docs/USER_GUIDE.md 를 보세요.\r\n",
        encoding="utf-8")
    total = sum(f.stat().st_size for f in out.iterdir() if f.is_file())
    print(f"[usb] {out}  {total / 1e9:.2f}GB  " + ", ".join(f.name for f in sorted(out.iterdir())))


if __name__ == "__main__":
    main()
