"""릴리스 매니페스트(latest.json)의 구성요소 항목: 앱이 받을 주소가 빠지지 않는다.

- GPU 가속은 PyPI 의 NVIDIA 휠을 그대로 가리킨다 (독점 바이너리를 우리 릴리스에 올리지 않는다).
- 앱 릴리스는 구성요소 zip 을 만들지 않으므로 런타임 릴리스의 항목을 그대로 가져온다.
- 어디에도 주소가 없으면 만들지 않고 멈춘다.
"""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("build_engine_dist", ROOT / "scripts" / "build_engine_dist.py")
B = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(B)


def fake_pypi(url: str) -> dict:
    name = url.split("/pypi/")[1].split("/")[0]
    return {
        "urls": [
            {"packagetype": "sdist", "filename": f"{name}.tar.gz", "url": "x", "digests": {"sha256": "s"}, "size": 1},
            {
                "packagetype": "bdist_wheel",
                "filename": f"{name}-1-py3-none-manylinux_x86_64.whl",
                "url": "linux",
                "digests": {"sha256": "l"},
                "size": 2,
            },
            {
                "packagetype": "bdist_wheel",
                "filename": f"{name}-1-py3-none-win_amd64.whl",
                "url": f"https://files.pythonhosted.org/{name}.whl",
                "digests": {"sha256": f"sha-{name}"},
                "size": 10,
            },
        ]
    }


def test_cuda_comes_from_the_pinned_pypi_wheels(tmp_path):
    c = tmp_path / "constraints.txt"
    c.write_text(
        "# 머리말\nnvidia-cublas-cu12==12.9.2.10\nnvidia-cudnn-cu12==9.27.0.42\nnvidia-cuda-nvrtc-cu12==12.9.86\n",
        encoding="utf-8",
    )
    e = B.cuda_entry(fetch=fake_pypi, constraints=c)
    assert e["version"] == "12.9.2.10+cudnn9.27.0.42"
    assert [p["url"] for p in e["parts"]] == [f"https://files.pythonhosted.org/{n}.whl" for n in B.CUDA_WHEELS]
    assert e["size"] == 30 and e["prefix"] == "Lib/site-packages"


def test_pinned_versions_exist_for_every_cuda_wheel():
    for name in B.CUDA_WHEELS:
        assert B.pinned(name)  # 실제 constraints.txt 에 고정돼 있어야 릴리스를 만들 수 있다


def test_app_release_reuses_runtime_entries_and_refuses_gaps(tmp_path):
    info = {n: {"label": n} for n in B.COMPONENTS}
    runtime = {
        "components": {
            "python-base": {"version": "3.12", "url": "https://r/python.zip", "sha256": "a", "size": 1},
            "ffmpeg": {"version": "9", "url": "https://r/ffmpeg.zip", "sha256": "b", "size": 2},
            "whisper": {"version": "w", "url": "https://r/whisper.zip", "sha256": "c", "size": 3},
            "cuda": {"version": "old", "url": "https://r/cuda.zip"},  # 예전 런타임 릴리스의 cuda 는 쓰지 않는다
        }
    }
    cuda = {"version": "12+9", "parts": [{"url": "https://files.pythonhosted.org/x.whl"}], "size": 1}
    out = B.component_entries(B.COMPONENTS, {}, info, runtime, lambda n, zp: {}, cuda)
    assert out["ffmpeg"]["url"] == "https://r/ffmpeg.zip" and out["ffmpeg"]["label"] == "ffmpeg"
    assert out["cuda"]["parts"] == cuda["parts"] and "url" not in out["cuda"]

    del runtime["components"]["whisper"]
    with pytest.raises(SystemExit, match="whisper"):
        B.component_entries(B.COMPONENTS, {}, info, runtime, lambda n, zp: {}, cuda)
