from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from sentinel.privacy.sequence_tagger import DEFAULT_SEQUENCE_MODEL_PATH


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_list(name: str, default: list[str]) -> list[str]:
    raw = os.getenv(name)
    if not raw:
        return default
    return [item.strip() for item in raw.split(",") if item.strip()]


@dataclass(frozen=True)
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(os.getenv("SENTINEL_DATA_DIR", "data/local")))
    db_path: Path = field(default_factory=lambda: Path(os.getenv("SENTINEL_DB_PATH", "data/local/sentinel.sqlite")))
    external_ai_enabled: bool = field(default_factory=lambda: _env_bool("EXTERNAL_AI_ENABLED", False))
    local_ml_enabled: bool = field(default_factory=lambda: _env_bool("SENTINEL_LOCAL_ML_ENABLED", True))
    local_ml_model_path: Path = field(default_factory=lambda: Path(os.getenv("SENTINEL_LOCAL_ML_MODEL_PATH", str(DEFAULT_SEQUENCE_MODEL_PATH))))
    openai_api_key: str | None = field(default_factory=lambda: os.getenv("OPENAI_API_KEY") or None)
    openai_model: str = field(default_factory=lambda: os.getenv("OPENAI_MODEL", "gpt-4o-mini"))
    elevenlabs_api_key: str | None = field(default_factory=lambda: os.getenv("ELEVENLABS_API_KEY") or None)
    elevenlabs_stt_model: str = field(default_factory=lambda: os.getenv("ELEVENLABS_STT_MODEL", "scribe_v2"))
    elevenlabs_enable_logging: bool = field(default_factory=lambda: _env_bool("ELEVENLABS_ENABLE_LOGGING", True))
    elevenlabs_timeout_seconds: int = field(default_factory=lambda: int(os.getenv("ELEVENLABS_TIMEOUT_SECONDS", "90")))
    cors_origins: list[str] = field(
        default_factory=lambda: _env_list(
            "SENTINEL_CORS_ORIGINS",
            ["http://localhost:5173", "http://127.0.0.1:5173"],
        )
    )

    @classmethod
    def from_env(cls) -> "Settings":
        settings = cls()
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        settings.db_path.parent.mkdir(parents=True, exist_ok=True)
        return settings


def load_settings() -> Settings:
    return Settings.from_env()
