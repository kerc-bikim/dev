from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    API_KEY: str = "dev"
    CORS_ORIGINS: list[str] = [
        "http://localhost:5174",
        "http://127.0.0.1:5174",
        "http://localhost:4173",
        "http://127.0.0.1:4173",
    ]
    LOG_LEVEL: str = "INFO"
    APP_JSON: Path = Path(__file__).resolve().parent.parent / "data" / "app.json"
    FIXTURES_DIR: Path = ROOT / "fixtures"
    DEFAULT_EW_HOME: Path = ROOT / ".ew_home"
    BASH_PATH: Path | None = None
    AUTO_SEED: bool = True
    STATUS_INTERVAL_SEC: float = 2.0
    SNIFF_MAX_SESSIONS: int = 2
    SNIFF_LINE_LIMIT: int = 2000
    CONTROL_TIMEOUT_SEC: float = 20.0
    KILL_DELAY_SEC: float = 10.0

    model_config = SettingsConfigDict(
        env_prefix="EW_WEB_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
settings.APP_JSON.parent.mkdir(parents=True, exist_ok=True)
