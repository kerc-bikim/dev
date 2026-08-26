from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../../.env"), extra="ignore")

    app_secret: str = "dev-insecure-change-me"
    database_url: str = "postgresql+psycopg://pdcc:pdcc@postgres:5432/pdcc"
    redis_url: str = "redis://redis:6379/0"
    dev_bootstrap_admin: bool = False
    session_cookie_name: str = "pdcc_session"
    session_ttl_sec: int = 86400
    stub_username: str = "stub"
    stub_password: str = "stub"
    nrl_base_url: str = "https://service.earthscope.org/irisws/nrl/1"
    nrl_timeout_sec: float = 30.0
    nrl_cache_ttl_sec: int = 3600


settings = Settings()
