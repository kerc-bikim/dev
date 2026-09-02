from __future__ import annotations

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

INSECURE_SECRET = "dev-insecure-change-me"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../../.env"), extra="ignore")

    app_secret: str = INSECURE_SECRET
    app_env: str = "development"
    database_url: str = "postgresql+psycopg://pdcc:pdcc@postgres:5432/pdcc"
    redis_url: str = "redis://redis:6379/0"
    dev_bootstrap_admin: bool = False
    allow_stub_login: bool = True
    session_cookie_name: str = "pdcc_session"
    session_ttl_sec: int = 86400
    session_cookie_secure: bool | None = None
    session_cookie_samesite: str = "lax"
    cors_origins: str = ""
    audit_retention_days: int = 365
    stub_username: str = "stub"
    stub_password: str = "stub"
    nrl_base_url: str = "https://service.earthscope.org/irisws/nrl/1"
    nrl_timeout_sec: float = 30.0
    nrl_cache_ttl_sec: int = 3600
    lock_ttl_sec: int = 300
    export_dir: str = "/tmp/pdcc-exports"
    job_poll_sec: int = 5

    @field_validator("session_cookie_secure", mode="before")
    @classmethod
    def _empty_secure(cls, value: object) -> object:
        if value in ("", None):
            return None
        return value


settings = Settings()
