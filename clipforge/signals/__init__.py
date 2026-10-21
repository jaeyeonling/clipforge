"""신호 플러그인 패키지. 여기서 import된 모듈만 REGISTRY에 등록된다."""

from . import (
    audio_loudness,
    chat_burst,
    chat_text,
    cut_density,
    edit_emphasis,
    frame_motion,
    item_banner,
    speech_keyword,
    ui_state,
)
from .base import REGISTRY, run_signal, signal
