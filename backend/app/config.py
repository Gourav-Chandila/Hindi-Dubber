"""Runtime configuration, all overridable through environment variables."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _bool(name: str, default: bool) -> bool:
    return _env(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(_env("HD_DATA_DIR", "/tmp/hindidub")))
    # Optional shared secret. When set, clients must send header X-API-Key.
    api_key: str = field(default_factory=lambda: _env("HD_API_KEY", ""))
    device: str = field(default_factory=lambda: _env("HD_DEVICE", "auto"))  # auto|cpu|cuda
    whisper_model: str = field(default_factory=lambda: _env("HD_WHISPER_MODEL", "auto"))
    translate_model: str = field(
        default_factory=lambda: _env("HD_TRANSLATE_MODEL", "facebook/nllb-200-distilled-600M")
    )
    tts_model: str = field(
        default_factory=lambda: _env("HD_TTS_MODEL", "tts_models/multilingual/multi-dataset/xtts_v2")
    )
    separate_music: bool = field(default_factory=lambda: _bool("HD_SEPARATE", True))
    chunk_seconds: int = field(default_factory=lambda: int(_env("HD_CHUNK_SECONDS", "600")))
    max_speakers: int = field(default_factory=lambda: int(_env("HD_MAX_SPEAKERS", "8")))
    speaker_threshold: float = field(
        default_factory=lambda: float(_env("HD_SPEAKER_THRESHOLD", "0.70"))
    )
    max_stretch: float = field(default_factory=lambda: float(_env("HD_MAX_STRETCH", "1.2")))
    # Ask for a shorter Hindi line as soon as it needs more than this speed-up.
    shorten_above: float = field(default_factory=lambda: float(_env("HD_SHORTEN_ABOVE", "1.08")))
    # "studio" = clean built-in voice per character; "clone" = imitate the actor.
    voice_mode: str = field(default_factory=lambda: _env("HD_VOICE_MODE", "studio"))
    max_upload_bytes: int = field(
        default_factory=lambda: int(_env("HD_MAX_UPLOAD_MB", "4096")) * 1024 * 1024
    )
    retention_hours: int = field(default_factory=lambda: int(_env("HD_RETENTION_HOURS", "24")))

    def resolved_device(self) -> str:
        if self.device != "auto":
            return self.device
        try:
            import torch

            return "cuda" if torch.cuda.is_available() else "cpu"
        except Exception:  # pragma: no cover - torch missing in light test env
            return "cpu"

    def resolved_whisper_model(self) -> str:
        if self.whisper_model != "auto":
            return self.whisper_model
        return "large-v3" if self.resolved_device() == "cuda" else "small"


settings = Settings()
