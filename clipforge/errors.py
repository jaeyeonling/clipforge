"""오류 분류: 예외 → {code, message, hint, kind} (docs/ARCHITECTURE.md · 오류).

- kind="user": 사용자가 조치할 수 있는 문제(파일 없음, ffmpeg 없음, 디스크 부족, 선행 단계 미실행). hint 문장 필수.
- kind="internal": 코드 결함. 메시지는 짧게, 트레이스백은 로그 파일로만.
엔진 안에서 의도적으로 던질 때는 EngineError(code, message, hint) 를 쓴다. 전송층(API)도 같은 타입을 그대로 쓴다.
"""

from __future__ import annotations

import errno
import subprocess


class EngineError(Exception):
    def __init__(self, code: str, message: str, hint: str = "", kind: str = "user"):
        super().__init__(message)
        self.code, self.message, self.hint, self.kind = code, message, hint, kind

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "hint": self.hint, "kind": self.kind}


LOG_HINT = "내부 오류입니다. 작업 로그(reports/jobs/)와 reports/engine.log 를 확인하세요."


def classify(e: BaseException) -> dict:
    """어떤 예외든 {code, message, hint, kind} 로. EngineError 는 그대로, 나머지는 패턴으로 추정."""
    if isinstance(e, EngineError):
        return e.to_dict()
    s = str(e)
    low = s.lower()
    msg = f"{type(e).__name__}: {s}"[:400]
    if isinstance(e, FileNotFoundError):
        if "ffmpeg" in low or "ffprobe" in low:
            return _d(
                "E_FFMPEG_MISSING",
                msg,
                "ffmpeg 를 찾지 못했습니다. 설치 폴더의 bin/ 또는 PATH, CLIPFORGE_FFMPEG 를 확인하세요.",
            )
        if "transcript.json" in s:
            return _d("E_NO_TRANSCRIPT", msg, "전사가 없습니다. transcribe 단계를 먼저 실행하세요.")
        if "meta.json" in s or "frames" in low or "audio.wav" in s:
            return _d("E_NO_PREP", msg, "prep 결과가 없습니다. prep 단계를 먼저 실행하세요.")
        if "shorts.json" in s:
            return _d("E_NO_SHORTS", msg, "후보가 없습니다. shorts 단계를 먼저 실행하세요.")
        if "프로필" in s or "games" in low:
            return _d("E_PROFILE_MISSING", msg, "games/<game>.yaml 이 없습니다. 게임 이름을 확인하세요.")
        return _d(
            "E_FILE_MISSING", msg, "파일 경로를 확인하세요. 영상은 videos/ 에, 캐시는 cache/<회차>/ 에 있어야 합니다."
        )
    if isinstance(e, subprocess.CalledProcessError):
        cmd = e.cmd[0] if isinstance(e.cmd, (list, tuple)) and e.cmd else str(e.cmd)
        tail = (e.stderr.decode(errors="ignore") if isinstance(e.stderr, bytes) else str(e.stderr or ""))[-300:].strip()
        if "ffmpeg" in str(cmd).lower() or "ffprobe" in str(cmd).lower():
            return _d(
                "E_FFMPEG_FAILED",
                f"ffmpeg 실패 (exit {e.returncode}): {tail or '출력 없음'}"[:400],
                "영상 파일이 손상됐거나 코덱을 지원하지 않을 수 있습니다. 다른 플레이어로 재생되는지 확인하고, GPU 디코딩 문제면 --proxy 로 CPU 경로를 시도하세요.",
            )
        return _d("E_SUBPROCESS", f"{cmd} 실패 (exit {e.returncode}): {tail}"[:400], LOG_HINT, "internal")
    if isinstance(e, OSError) and getattr(e, "errno", None) == errno.ENOSPC:
        return _d("E_DISK_FULL", msg, "디스크 공간이 부족합니다. cache/<회차>/frames 는 지워도 다시 만들 수 있습니다.")
    if isinstance(e, PermissionError):
        return _d("E_PERMISSION", msg, "파일이 다른 프로그램(플레이어·Premiere)에 열려 있거나 폴더 권한이 없습니다.")
    if isinstance(e, MemoryError) or "out of memory" in low:
        return _d(
            "E_OOM", msg, "메모리 부족입니다. 다른 GPU/메모리 사용 프로그램을 닫거나 전사 모델을 작은 것으로 바꾸세요."
        )
    if "cuda" in low or "cudnn" in low or "cublas" in low:
        return _d(
            "E_GPU",
            msg,
            "GPU 런타임 문제입니다. nvidia-cublas-cu12 / nvidia-cudnn-cu12 설치와 드라이버를 확인하세요. 전사는 CPU 로 폴백됩니다.",
        )
    if "ffmpeg" in low or "ffprobe" in low:
        return _d("E_FFMPEG_FAILED", msg, "ffmpeg 호출이 실패했습니다. 설치와 영상 파일을 확인하세요.")
    if isinstance(e, (KeyError, TypeError, ValueError, AttributeError, IndexError, AssertionError)):
        return _d("E_INTERNAL", msg, LOG_HINT, "internal")
    return _d("E_INTERNAL", msg, LOG_HINT, "internal")


def _d(code: str, message: str, hint: str, kind: str = "user") -> dict:
    return {"code": code, "message": message, "hint": hint, "kind": kind}
