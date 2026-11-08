from functools import lru_cache

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Values come from the environment, so one image runs as API, worker and CLI."""

    model_config = SettingsConfigDict(env_prefix="PLANNY_", extra="ignore")

    database_url: str
    # Only the API needs it: create_app refuses to start without the secret.
    bff_shared_secret: SecretStr | None = Field(default=None, min_length=32)
    log_level: str = "INFO"
    default_timezone: str = "Europe/Moscow"
    session_ttl_days: int = 30
    # OpenAI-compatible bases ending in /v1. Empty means the assistant (or only its voice) is off.
    llm_url: str = ""
    llm_model: str = ""
    stt_url: str = ""
    stt_model: str = "Systran/faster-whisper-medium"
    assistant_timeout_seconds: float = 60

    @field_validator("llm_url", "stt_url")
    @classmethod
    def strip_slash(cls, value: str) -> str:
        return value.strip().rstrip("/")

    @property
    def assistant_enabled(self) -> bool:
        return bool(self.llm_url)

    @property
    def voice_enabled(self) -> bool:
        return bool(self.llm_url and self.stt_url)


@lru_cache
def get_settings() -> Settings:
    return Settings()
