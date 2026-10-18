"""신호 플러그인 패키지. 여기서 import된 모듈만 REGISTRY에 등록된다."""
from . import audio_loudness, frame_motion, item_banner  # noqa: F401
from .base import REGISTRY, run_signal, signal  # noqa: F401
