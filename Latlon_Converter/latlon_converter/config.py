"""환경변수 기반 설정."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = PROJECT_ROOT / "fixtures"


def load_dotenv(path: Path | None = None) -> None:
    """`.env`를 읽어 환경변수에 채운다. 이미 있는 값은 덮어쓰지 않는다."""
    env_path = path or (PROJECT_ROOT / ".env")
    if not env_path.is_file():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "").strip() or default)
    except ValueError:
        return default


@dataclass
class Settings:
    """실행 설정. CLI 인자가 환경변수보다 우선한다."""

    provider: str = "mock"
    api_key: str = ""
    domain: str = ""
    cache_db: str = ""
    cache_ttl_days: int = 30
    timeout: int = 10
    retries: int = 3

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        return cls(
            provider=(os.getenv("LATLON_PROVIDER", "") or "mock").strip().lower(),
            api_key=os.getenv("VWORLD_API_KEY", "").strip(),
            domain=os.getenv("VWORLD_DOMAIN", "").strip(),
            cache_db=os.getenv("LATLON_CACHE_DB", "").strip(),
            cache_ttl_days=_int_env("LATLON_CACHE_TTL_DAYS", 30),
            timeout=_int_env("LATLON_TIMEOUT", 10),
            retries=_int_env("LATLON_RETRIES", 3),
        )
