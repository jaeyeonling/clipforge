"""포터블 엔진 런타임 `engine-dist/` 구성 (PRODUCT_ARCHITECTURE §9: 설치본의 몸통).

    python scripts/build_engine_dist.py [--out engine-dist] [--skip-packages] [--skip-ffmpeg] [--skip-models] [--smoke]

만드는 것 (전부 한 폴더, 상대 경로만 사용 → 어디에 놓아도 동작):
  engine-dist/
    python.exe, python312.dll, python312._pth(…)  ← python.org 임베더블 배포판 (관리자 권한·레지스트리 無)
    Lib/site-packages/                            ← requirements-runtime.txt 를 pip --target 으로 (개발 venv 의 pip 사용, 같은 3.12 x64)
    clipforge/ games/ data/ assets/ app/dist/     ← 엔진 코드·프로필·사전·폰트·화면 (APP_ROOT = engine-dist)
    bin/ffmpeg.exe ffprobe.exe                    ← find_ffmpeg() 1순위
    models/faster-whisper-large-v3-turbo/         ← HF 캐시 스냅샷 복사 (transcribe 가 이 폴더를 우선 사용 → 오프라인)
    THIRD_PARTY_NOTICES.md, VERSION.json
Electron 껍데기는 이 폴더를 resources/engine 으로 넣고 python.exe -m clipforge.app 을 띄운다. 데이터 폴더는 CLIPFORGE_DATA 로 분리.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY_VER = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"      # 개발 venv 와 같은 버전
EMBED_URL = f"https://www.python.org/ftp/python/{PY_VER}/python-{PY_VER}-embed-amd64.zip"
HF_REPO = "mobiuslabsgmbh/faster-whisper-large-v3-turbo"
MODEL_DIR_NAME = "faster-whisper-large-v3-turbo"
RUNTIME_EXCLUDE = {"pytest", "httpx"}        # 개발 전용


def log(msg: str) -> None:
    print(f"[dist] {msg}", flush=True)


def human(n: int) -> str:
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f}{u}"
        n /= 1024
    return f"{n:.1f}TB"


def du(p: Path) -> int:
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) if p.exists() else 0


# ---------- 1. 임베더블 파이썬 ----------
def step_python(out: Path) -> None:
    if (out / "python.exe").exists():
        log(f"python: 이미 있음 ({out / 'python.exe'})"); return
    zp = out.parent / f"python-{PY_VER}-embed-amd64.zip"
    if not zp.exists():
        log(f"python: 다운로드 {EMBED_URL}")
        urllib.request.urlretrieve(EMBED_URL, zp)
    out.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zp) as z:
        z.extractall(out)
    zp.unlink()
    pth = next(out.glob("python3*._pth"))
    pth.write_text(f"{pth.stem.replace('._pth', '')}.zip\n.\nLib\\site-packages\nimport site\n", encoding="utf-8")
    (out / "Lib" / "site-packages").mkdir(parents=True, exist_ok=True)
    log(f"python: {PY_VER} 임베더블 설치, {pth.name} = [zip, ., Lib\\site-packages, import site]")


# ---------- 2. 패키지 ----------
def step_packages(out: Path, force: bool) -> None:
    req_src = (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
    runtime = [l for l in req_src if l.strip() and not l.startswith("#") and l.split("[")[0].split("=")[0].strip() not in RUNTIME_EXCLUDE]
    req = ROOT / "requirements-runtime.txt"
    req.write_text("# 배포 런타임용 (requirements.txt 에서 개발 전용 제외). scripts/build_engine_dist.py 가 생성\n" + "\n".join(runtime) + "\n", encoding="utf-8")
    site = out / "Lib" / "site-packages"
    if force and site.exists():
        shutil.rmtree(site)
    site.mkdir(parents=True, exist_ok=True)
    if (site / "fastapi").exists() and not force:
        log("packages: 이미 있음 (--force-packages 로 다시)"); return
    log(f"packages: pip install --target {site} ({len(runtime)} 개)")
    subprocess.run([sys.executable, "-m", "pip", "install", "--target", str(site), "--only-binary=:all:", "--upgrade",
                    "--no-warn-script-location", "-r", str(req)], check=True)
    # 설치 스크립트(bin/)는 필요 없다
    shutil.rmtree(site / "bin", ignore_errors=True)
    log(f"packages: {human(du(site))}")


# ---------- 3. 엔진 코드·자산 ----------
def copytree(src: Path, dst: Path, ignore=None) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst, ignore=ignore)


def step_code(out: Path) -> None:
    ig = shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache")
    copytree(ROOT / "clipforge", out / "clipforge", ig)
    copytree(ROOT / "games", out / "games", ig)
    copytree(ROOT / "data", out / "data", ig)
    copytree(ROOT / "assets", out / "assets", ig)
    dist = ROOT / "app" / "dist"
    if not (dist / "index.html").exists():
        raise SystemExit("app/dist 가 없습니다 — 먼저 `cd app && npm run build`")
    copytree(dist, out / "app" / "dist")
    # 기본 episodes.csv 는 데이터 폴더의 것이므로 넣지 않는다. 비어 있는 데이터 폴더에서 시작한다.
    log("code: clipforge/ games/ data/ assets/ app/dist/ 복사")


# ---------- 4. ffmpeg ----------
def step_ffmpeg(out: Path) -> None:
    sys.path.insert(0, str(ROOT))
    from clipforge.project import find_ffmpeg
    src = find_ffmpeg()
    if not src:
        raise SystemExit("ffmpeg 를 찾지 못했습니다 (winget Gyan.FFmpeg 설치 또는 CLIPFORGE_FFMPEG)")
    b = out / "bin"; b.mkdir(exist_ok=True)
    for exe in ("ffmpeg.exe", "ffprobe.exe"):
        shutil.copy2(src / exe, b / exe)
    for lic in ("LICENSE", "LICENSE.txt", "COPYING.GPLv3"):
        p = src.parent / lic
        if p.exists():
            shutil.copy2(p, b / f"ffmpeg-{lic}")
    ver = subprocess.run([str(b / "ffmpeg.exe"), "-version"], capture_output=True, text=True).stdout.splitlines()[0]
    log(f"ffmpeg: {ver} ({human(du(b))}) ← {src}")


# ---------- 5. 모델 ----------
def step_models(out: Path) -> None:
    cache = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface")) / "hub" / ("models--" + HF_REPO.replace("/", "--"))
    snaps = sorted((cache / "snapshots").glob("*")) if cache.exists() else []
    if not snaps:
        raise SystemExit(f"HF 캐시에 {HF_REPO} 가 없습니다. 한 번 transcribe 를 돌려 받아 두거나 --skip-models")
    snap = snaps[-1]
    dst = out / "models" / MODEL_DIR_NAME
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True)
    for f in snap.iterdir():                       # HF 는 blobs 로 심볼릭/하드 링크 → 실제 파일로 복사
        if f.is_file() or f.is_symlink():
            shutil.copyfile(f.resolve(), dst / f.name)
    (out / "models" / "README.md").write_text(
        f"# models\n- {MODEL_DIR_NAME}/ : {HF_REPO} (CTranslate2 변환, faster-whisper 용). transcribe 가 이 폴더를 우선 사용한다 (오프라인).\n", encoding="utf-8")
    log(f"models: {MODEL_DIR_NAME} {human(du(dst))} ← {snap}")


# ---------- 6. 고지·버전 ----------
def step_meta(out: Path) -> None:
    sys.path.insert(0, str(ROOT))
    from clipforge import __version__
    (out / "VERSION.json").write_text(json.dumps({"engine_version": __version__, "python": PY_VER, "built": time.strftime("%Y-%m-%dT%H:%M:%S"),
                                                  "components": {k: human(du(out / k)) for k in ("Lib/site-packages", "bin", "models", "app/dist", "clipforge")}},
                                                 ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "THIRD_PARTY_NOTICES.md").write_text("""# 제3자 구성요소 고지 (engine-dist)

| 구성요소 | 라이선스 | 비고 |
|---|---|---|
| Python (임베더블 배포판) | PSF | python.org |
| FFmpeg (Gyan.dev full build, bin/) | **GPL v3** (full build 는 GPL 구성요소 포함) | 소스: ffmpeg.org · 빌드: gyan.dev. 실행 파일을 그대로 동봉하며 수정하지 않음. 라이선스 원문 bin/ffmpeg-LICENSE |
| faster-whisper / CTranslate2 | MIT | |
| Whisper large-v3-turbo (CTranslate2 변환, models/) | MIT (OpenAI Whisper) | 변환본: mobiuslabsgmbh/faster-whisper-large-v3-turbo |
| NVIDIA cuBLAS / cuDNN (pip 휠) | NVIDIA 라이선스 | 재배포 허용 조건은 각 휠의 License 참고 |
| RapidOCR / ONNX Runtime | Apache-2.0 / MIT | PP-OCR 모델 포함 (Apache-2.0) |
| FastAPI, uvicorn, Pillow, numpy, PyYAML, rapidfuzz, fonttools, OpenTimelineIO | MIT/BSD/HPND/Apache | |
| 나눔펜스크립트, 검은고딕(Black Han Sans) | SIL OFL 1.1 | assets/fonts |
| React, Vite 산출물 (app/dist) | MIT | |

설치본 배포 전 확인: GPL ffmpeg 를 동봉하므로 고지와 소스 입수 방법(ffmpeg.org)을 제품 정보 화면에 표기한다.
""", encoding="utf-8")
    log("meta: VERSION.json, THIRD_PARTY_NOTICES.md")


# ---------- 7. 스모크 ----------
def step_smoke(out: Path) -> dict:
    import tempfile
    import urllib.error
    data = Path(tempfile.mkdtemp(prefix="cf-dist-"))
    port = 8799
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")} | {"CLIPFORGE_DATA": str(data), "PYTHONIOENCODING": "utf-8"}
    env.pop("PATH", None); env["PATH"] = str(out / "bin")            # PATH 에서 개발 ffmpeg 를 숨긴다 → 번들 bin/ 만으로 돼야 한다
    env["SYSTEMROOT"] = os.environ.get("SYSTEMROOT", r"C:\Windows"); env["PATH"] += os.pathsep + env["SYSTEMROOT"] + r"\System32"
    log(f"smoke: {out / 'python.exe'} -m clipforge.app --port {port}  (CLIPFORGE_DATA={data}, PATH=bin 만)")
    proc = subprocess.Popen([str(out / "python.exe"), "-m", "clipforge.app", "--no-browser", "--port", str(port)], cwd=str(out), env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
    health = None
    try:
        t0 = time.time()
        while time.time() - t0 < 90:
            if proc.poll() is not None:
                break
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=3) as r:
                    health = json.loads(r.read().decode("utf-8")); break
            except (urllib.error.URLError, ConnectionError, TimeoutError, OSError):
                time.sleep(0.5)
    finally:
        if proc.poll() is None:
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
        tail = (proc.stdout.read() if proc.stdout else "")[-1500:]
    shutil.rmtree(data, ignore_errors=True)
    if not health:
        print(tail); raise SystemExit("smoke: 엔진이 뜨지 않았습니다")
    keys = ("engine_version", "ffmpeg_ok", "nvenc", "gpu", "whisper_gpu", "rapidocr", "fonts_ok")
    log("smoke: " + "  ".join(f"{k}={health.get(k)}" for k in keys))
    log(f"smoke: ffmpeg={health.get('ffmpeg')}  problems={[p['code'] for p in health.get('problems', [])]}")
    bad = [k for k in ("ffmpeg_ok", "rapidocr", "fonts_ok") if not health.get(k)]
    if bad or not str(health.get("ffmpeg", "")).startswith(str(out)):
        raise SystemExit(f"smoke: 실패 {bad or 'ffmpeg 가 번들 bin/ 이 아님'}")
    return health


# ---------- 8. 릴리스 아티팩트 (앱 내 업데이트용, PRODUCT_ARCHITECTURE §9.2) ----------
CODE_PATHS = ["clipforge", "games", "data", "assets", "app"]       # 층 A
DATA_DIRS = {"cache", "labels", "review", "premiere", "reports", "videos", "project.json", "episodes.csv"}   # 번들에 들어가면 안 되는 것
NOTICE_FILES = {"VERSION.json", "THIRD_PARTY_NOTICES.md"}


def component_paths(out: Path, name: str) -> list[str]:
    """층 B 구성요소의 상대 경로 (zip 안 경로 = 런타임 루트 기준).
    python-base = 루트의 파일 전부(고지 제외) + Lib (단, Lib/site-packages/nvidia 제외)  ·  cuda = Lib/site-packages/nvidia (선택: GPU 가속)
    ffmpeg = bin  ·  whisper = models"""
    if name == "python-base":
        return sorted(p.name for p in out.iterdir() if p.is_file() and p.name not in NOTICE_FILES and p.name not in DATA_DIRS) + ["Lib"]
    return {"cuda": ["Lib/site-packages/nvidia"], "ffmpeg": ["bin"], "whisper": ["models"]}[name]


COMPONENTS = ("python-base", "cuda", "ffmpeg", "whisper")
COMPONENT_INFO = {   # 첫 실행 화면에 보여줄 설명. optional 은 사용자가 끌 수 있다.
    "python-base": {"label": "파이썬 런타임 + 분석 패키지", "optional": False},
    "cuda": {"label": "GPU 가속 (NVIDIA cuBLAS/cuDNN) — 전사 20배 빠름", "optional": True},
    "ffmpeg": {"label": "FFmpeg (영상 디코딩·렌더)", "optional": False},
    "whisper": {"label": "음성 인식 모델 (Whisper large-v3-turbo)", "optional": False},
}
EXCLUDE_IN = {"python-base": ["Lib/site-packages/nvidia"]}


def sha256_of(p: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def zip_paths(out: Path, rel_paths: list[str], dst: Path, exclude: list[str] | None = None) -> None:
    ex = [out / e for e in (exclude or [])]
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as z:      # 속도 우선 (DLL·모델은 거의 안 줄어든다)
        for rel in rel_paths:
            p = out / rel
            if p.is_file():
                z.write(p, rel)
            elif p.is_dir():
                for f in sorted(p.rglob("*")):
                    if f.is_file() and "__pycache__" not in f.parts and not any(e in f.parents or e == f for e in ex):
                        z.write(f, f.relative_to(out).as_posix())


def step_release(out: Path, rel_dir: Path, with_components: bool, base_url: str, components_url: str | None = None) -> None:
    """engine-code-<ver>.zip (+ 구성요소 zip) 과 latest.json.
    base_url       = 앱 릴리스 자산 주소 (engine-code zip·latest.json. GitHub: .../releases/latest/download)
    components_url = 구성요소 zip 주소 (드물게 갱신되는 런타임 릴리스. GitHub: .../releases/download/runtime-YYYY.MM). 없으면 base_url"""
    sys.path.insert(0, str(ROOT))
    from clipforge import __version__
    rel_dir.mkdir(parents=True, exist_ok=True)
    ver = json.loads((out / "VERSION.json").read_text(encoding="utf-8"))
    comp_ver = ver.get("component_versions") or {"python-base": f"{PY_VER}+pkg{time.strftime('%Y.%m')}", "cuda": "12.9+cudnn9.27",
                                                  "ffmpeg": "9.0.2", "whisper": "large-v3-turbo-ct2-1"}
    comp_base = (components_url or base_url).rstrip("/")
    entry = lambda p, v, base=base_url.rstrip("/"): {"version": v, "url": f"{base}/{p.name}", "sha256": sha256_of(p), "size": p.stat().st_size}
    code_zip = rel_dir / f"engine-code-{__version__}.zip"
    zip_paths(out, CODE_PATHS, code_zip)
    manifest = {"published": time.strftime("%Y-%m-%dT%H:%M:%S"), "shell": {"version": __version__, "min_engine_code": __version__},
                "engine_code": entry(code_zip, __version__), "components": {}, "compat": {}}
    log(f"release: {code_zip.name} {human(code_zip.stat().st_size)}")
    for name in COMPONENTS:
        zp = rel_dir / f"{name}-{comp_ver[name].replace('+', '_')}.zip"
        if with_components:
            zip_paths(out, component_paths(out, name), zp, EXCLUDE_IN.get(name))
            log(f"release: {zp.name} {human(zp.stat().st_size)}")
        info = {**COMPONENT_INFO[name], "paths": component_paths(out, name) if name != "python-base" else ["<root files>", "Lib"]}
        if zp.exists():
            manifest["components"][name] = {**entry(zp, comp_ver[name], comp_base), **info}
        else:
            manifest["components"][name] = {"version": comp_ver[name], **info}          # zip 없이 버전만 (서버에 이미 있는 경우)
    (rel_dir / "latest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    ver["component_versions"] = comp_ver
    (out / "VERSION.json").write_text(json.dumps(ver, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"release: latest.json → {rel_dir}  (base_url={base_url}, components={comp_base})")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "engine-dist"))
    ap.add_argument("--release", metavar="DIR", help="앱 내 업데이트용 아티팩트(engine-code zip + latest.json)를 DIR 에 생성")
    ap.add_argument("--release-components", action="store_true", help="--release 에 구성요소 zip(python/ffmpeg/whisper, 4GB)도 포함")
    ap.add_argument("--base-url", default="https://github.com/jaeyeonling/clipforge/releases/latest/download", help="engine-code zip·latest.json 의 url 접두 (앱 릴리스)")
    ap.add_argument("--components-url", default=None, help="구성요소 zip 의 url 접두 (런타임 릴리스, 예: .../releases/download/runtime-2026.10). 없으면 --base-url")
    ap.add_argument("--skip-packages", action="store_true"); ap.add_argument("--force-packages", action="store_true")
    ap.add_argument("--skip-ffmpeg", action="store_true"); ap.add_argument("--skip-models", action="store_true")
    ap.add_argument("--smoke", action="store_true", help="구성 뒤 번들 파이썬으로 엔진을 띄워 health 확인")
    a = ap.parse_args()
    out = Path(a.out).resolve()
    t0 = time.time()
    step_python(out)
    if not a.skip_packages:
        step_packages(out, a.force_packages)
    step_code(out)
    if not a.skip_ffmpeg:
        step_ffmpeg(out)
    if not a.skip_models:
        step_models(out)
    step_meta(out)
    log(f"총 {human(du(out))}  ({time.time() - t0:.0f}s)  → {out}")
    for k in ("Lib/site-packages", "Lib/site-packages/nvidia", "bin", "models", "app/dist", "clipforge", "assets"):
        log(f"  {k:<28} {human(du(out / k))}")
    if a.smoke:
        step_smoke(out)
    if a.release:
        step_release(out, Path(a.release).resolve(), a.release_components, a.base_url, a.components_url)


if __name__ == "__main__":
    main()
