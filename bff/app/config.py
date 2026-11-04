from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PLANNY_", extra="ignore")

    bff_shared_secret: SecretStr = Field(min_length=32)
    # A Fernet key, see deploy/.env.example for how to generate one.
    cookie_key: SecretStr
    api_url: str = "http://api:8000"
    # False only on the dev machine, where browsers treat Secure on localhost differently.
    cookie_secure: bool = True
    # True only behind Caddy. Otherwise a client could pick its own IP for the login limit.
    trust_forwarded_for: bool = False
    static_dir: Path = Path("/app/static")
    session_ttl_days: int = 30
    login_rate_limit: int = 20
    login_rate_window_seconds: int = 300
    log_level: str = "INFO"
