from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables or defaults."""

    FDSNWS_URL: str = "http://172.31.100.100"
    CACHE_DIR: Path = Path(__file__).resolve().parent.parent / "cache"
    # SeisComP SDS-style root for persisted daily PPSD npz results
    PPSD_SDS_DIR: Path = Path(__file__).resolve().parent.parent / "sds"
    CORS_ORIGINS: List[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:4173",
    ]
    PPSD_TIMEOUT_SECONDS: int = 180
    FDSN_TIMEOUT_SECONDS: int = 120
    MAX_WORKERS: int = 4
    MAX_TARGETS: int = 20
    LOG_LEVEL: str = "INFO"
    # Optional default axis limits (X in period[s] or frequency[Hz] per request xaxis)
    PPSD_X_MIN: Optional[float] = None
    PPSD_X_MAX: Optional[float] = None
    PPSD_Y_MIN: Optional[float] = None
    PPSD_Y_MAX: Optional[float] = None
    PPSD_YAXIS_TYPE: str = "acceleration"
    # Additive dB shift for pressure PSD display (sensor-specific calibration)
    PPSD_PRESSURE_DB_OFFSET: float = 0.0

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
    )


settings = Settings()
settings.CACHE_DIR.mkdir(parents=True, exist_ok=True)
settings.PPSD_SDS_DIR.mkdir(parents=True, exist_ok=True)
