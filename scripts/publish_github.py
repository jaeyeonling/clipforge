"""GitHub Releases 배포 (gh CLI). desktop/release.config.js 의 owner/repo 를 쓴다.

    python scripts/publish_github.py runtime            # 런타임 릴리스 runtime-YYYY.MM: 구성요소 zip 4개 (처음 한 번, 이후 런타임이 바뀔 때만)
    python scripts/publish_github.py app [--notes "…"]   # 앱 릴리스 v<version>: Setup.exe + blockmap + latest.yml + engine-code zip + latest.json
    옵션: --dry-run (업로드 없이 만들 것만 출력)  --runtime-tag runtime-2026.10 (앱 릴리스의 매니페스트가 가리킬 런타임 태그; 기본 = 가장 최근 runtime-* 릴리스)

전제: gh auth login 완료, engine-dist 구성 완료(build_engine_dist.py), app/dist 빌드 완료.
순서: runtime 을 먼저 올린다 → app 을 올린다 (latest.json 의 구성요소 URL 이 runtime 릴리스를 가리켜야 하므로).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DESKTOP = ROOT / "desktop"
def _node_dir() -> Path:
    """npm/node 가 있는 폴더: CLIPFORGE_NODE_DIR → PATH 의 node → 포터블 Node 기본 위치(~/tools/node)."""
    if os.environ.get("CLIPFORGE_NODE_DIR"):
        return Path(os.environ["CLIPFORGE_NODE_DIR"])
    found = shutil.which("node")
    return Path(found).parent if found else Path.home() / "tools" / "node"


NODE = _node_dir()
GH = shutil.which("gh") or str(Path(os.environ.get("CLIPFORGE_GH_DIR", str(Path.home() / "tools" / "gh" / "bin"))) / "gh.exe")


def sh(cmd: list[str], cwd: Path | None = None, capture: bool = False) -> str:
    print("$", " ".join(str(c) for c in cmd), flush=True)
    r = subprocess.run(cmd, cwd=str(cwd or ROOT), check=True, text=True, encoding="utf-8", errors="replace",
                       capture_output=capture, env={**os.environ, "PATH": f"{NODE}{os.pathsep}{os.environ.get('PATH', '')}"})
    return r.stdout if capture else ""


def release_cfg() -> dict:
    out = subprocess.run([str(NODE / "node.exe"), "-e", "const c=require('./release.config');console.log(JSON.stringify({owner:c.owner,repo:c.repo,isPrivate:c.isPrivate}))"],
                         cwd=str(DESKTOP), capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def engine_version() -> str:
    sys.path.insert(0, str(ROOT))
    from clipforge import __version__
    return __version__


def gh_json(args: list[str]) -> list | dict:
    out = sh([GH, *args], capture=True)
    return json.loads(out) if out.strip() else []


def latest_runtime_tag(slug: str) -> str | None:
    rels = gh_json(["release", "list", "--repo", slug, "--json", "tagName", "--limit", "50"])
    tags = sorted(r["tagName"] for r in rels if str(r["tagName"]).startswith("runtime-"))
    return tags[-1] if tags else None


def cmd_runtime(a, cfg) -> None:
    slug = f"{cfg['owner']}/{cfg['repo']}"
    tag = a.runtime_tag or f"runtime-{time.strftime('%Y.%m')}"
    rel = ROOT / "release-runtime"
    sh([sys.executable, str(ROOT / "scripts" / "build_engine_dist.py"), "--skip-packages", "--skip-ffmpeg", "--skip-models",
        "--release", str(rel), "--release-components", "--base-url", f"https://github.com/{slug}/releases/download/{tag}"])
    zips = sorted(p for p in rel.glob("*.zip") if not p.name.startswith("engine-code"))
    print(f"[publish] {tag}: " + ", ".join(f"{z.name} ({z.stat().st_size / 1e6:.0f}MB)" for z in zips))
    if a.dry_run:
        return
    existing = [r["tagName"] for r in gh_json(["release", "list", "--repo", slug, "--json", "tagName", "--limit", "50"])]
    if tag in existing:
        sh([GH, "release", "upload", "--repo", slug, tag, "--clobber", *map(str, zips)])
    else:
        sh([GH, "release", "create", "--repo", slug, tag, "--title", f"런타임 {tag}", "--notes",
            "파이썬 런타임·GPU 가속(선택)·FFmpeg·Whisper 모델. 앱이 첫 실행 때 내려받는 구성요소.", *map(str, zips)])


def cmd_app(a, cfg) -> None:
    slug = f"{cfg['owner']}/{cfg['repo']}"
    ver = engine_version()
    tag = f"v{ver}"
    rt = a.runtime_tag or latest_runtime_tag(slug)
    if not rt:
        raise SystemExit("런타임 릴리스가 없습니다 — 먼저 `publish_github.py runtime`")
    rel = ROOT / "release-app"
    if rel.exists():
        shutil.rmtree(rel)
    # 1) 화면 → 엔진 코드 번들(engine-dist 의 코드 경로 갱신) → 릴리스 아티팩트
    sh([str(NODE / "npm.cmd"), "run", "build"], cwd=ROOT / "app")
    sh([sys.executable, str(ROOT / "scripts" / "build_engine_dist.py"), "--skip-packages", "--skip-ffmpeg", "--skip-models",
        "--release", str(rel), "--base-url", f"https://github.com/{slug}/releases/latest/download",
        "--components-url", f"https://github.com/{slug}/releases/download/{rt}"])
    # 2) 설치본 (app-update.yml 에 publish 설정이 들어간다)
    sh([str(NODE / "npm.cmd"), "run", "dist"], cwd=DESKTOP)
    out = DESKTOP / "release"
    assets = [rel / f"engine-code-{ver}.zip", rel / "latest.json",
              *sorted(out.glob("clipforge-Setup-*.exe")), *sorted(out.glob("clipforge-Setup-*.exe.blockmap")), out / "latest.yml"]
    missing = [str(p) for p in assets if not p.exists()]
    if missing:
        raise SystemExit(f"빠진 아티팩트: {missing}")
    print(f"[publish] {tag}: " + ", ".join(f"{p.name} ({p.stat().st_size / 1e6:.1f}MB)" for p in assets))
    if a.dry_run:
        return
    notes = a.notes or f"clipforge {ver}. 런타임 {rt}."
    sh([GH, "release", "create", "--repo", slug, tag, "--title", f"clipforge {ver}", "--notes", notes, "--latest", *map(str, assets)])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("what", choices=["runtime", "app"])
    ap.add_argument("--runtime-tag"); ap.add_argument("--notes"); ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if not Path(GH).exists() and not shutil.which("gh"):
        raise SystemExit("gh CLI 가 없어요. PATH 에 gh 를 두거나 CLIPFORGE_GH_DIR 로 폴더를 알려 주세요")
    cfg = release_cfg()
    print(f"[publish] 대상 {cfg['owner']}/{cfg['repo']} (private={cfg['isPrivate']})")
    (cmd_runtime if a.what == "runtime" else cmd_app)(a, cfg)


if __name__ == "__main__":
    main()
