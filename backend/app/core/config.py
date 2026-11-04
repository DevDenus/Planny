from functools import lru_cache

from pydantic import Field, SecretStr
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


@lru_cache
def get_settings() -> Settings:
    return Settings()
