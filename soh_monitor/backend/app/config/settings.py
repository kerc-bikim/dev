"""환경 설정.

비민감 설정은 환경변수로, 비밀값은 Docker Secret 또는 외부 Secret Manager 로 주입한다.
`*_FILE` 로 끝나는 환경변수가 있으면 그 파일 내용을 값으로 읽는다. Compose Secret 을
쓰기 위한 관례다.
"""
from __future__ import annotations

import functools
import os
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _read_secret_file(env_name: str) -> str | None:
    path = os.environ.get(f"{env_name}_FILE")
    if not path:
        return None
    file_path = Path(path)
    if not file_path.exists():
        return None
    return file_path.read_text(encoding="utf-8").strip()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SOH_", extra="ignore")

    app_env: str = "development"
    log_level: str = "INFO"
    http_port: int = 8000

    # --- PostgreSQL ---
    postgres_host: str = "postgres"
    postgres_port: int = 5432
    postgres_db: str = "soh_monitor"
    postgres_user: str = "soh"
    postgres_password: str = ""
    database_url_override: str | None = None

    # --- InfluxDB ---
    influx_url: str = "http://influxdb:8086"
    influx_org: str = "observatory"
    influx_bucket: str = "soh"
    influx_token: str = ""

    # --- Grafana ---
    grafana_url: str = "http://localhost:3000"

    # --- 수집 기본값 ---
    default_poll_interval_minutes: int = 5
    scheduler_tick_seconds: int = 10
    poll_jitter_percent: int = 15
    max_concurrent_polls: int = 20
    failure_warning_threshold: int = 2
    failure_critical_threshold: int = 3

    # --- Edge ---
    edge_id: str | None = None
    central_url: str = "https://localhost"
    edge_spool_path: Path = Path("/var/lib/soh-edge")
    edge_spool_limit_bytes: int = 5 * 1024 * 1024 * 1024
    edge_heartbeat_seconds: int = 30
    edge_upload_timeout_seconds: int = 30
    edge_enrollment_token: str | None = None
    edge_cert_dir: Path = Path("/var/lib/soh-edge/certs")
    edge_ingest_max_bytes: int = 6 * 1024 * 1024
    edge_heartbeat_miss_warning: int = 2
    edge_heartbeat_miss_critical: int = 3

    # --- 보안 ---
    session_secret: str = ""
    device_credential_key: str = ""
    allowed_device_networks: list[str] = Field(
        default_factory=lambda: ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"],
        description="기록계 접속을 허용할 대역. 접속 저장·연결 시험 SSRF 차단에 쓴다.",
    )

    @field_validator("poll_jitter_percent")
    @classmethod
    def _jitter_range(cls, value: int) -> int:
        if not 0 <= value <= 50:
            raise ValueError("poll_jitter_percent 는 0~50 사이여야 한다")
        return value

    @field_validator("allowed_device_networks", mode="before")
    @classmethod
    def _split_networks(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @property
    def database_url(self) -> str:
        if self.database_url_override:
            return self.database_url_override
        password = self.postgres_password or _read_secret_file("SOH_POSTGRES_PASSWORD") or ""
        return (
            f"postgresql+psycopg://{self.postgres_user}:{password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() in {"production", "prod"}

    def resolved_secret(self, name: str) -> str:
        """비밀값을 환경변수 또는 `*_FILE` 에서 읽는다."""
        direct = getattr(self, name, "") or ""
        if direct:
            return direct
        return _read_secret_file(f"SOH_{name.upper()}") or ""

    def session_signing_key(self) -> str:
        """쿠키 서명 키.

        개발 환경에서 비어 있으면 고정값을 쓴다. 운영에서는 비어 있으면 안 되며
        `startup_problems` 가 기동을 막는다.
        """
        key = self.resolved_secret("session_secret")
        if key:
            return key
        if self.is_production:
            return ""
        return "dev-only-session-secret-not-for-production"

    def startup_problems(self) -> list[str]:
        """운영 환경에서 비어 있으면 안 되는 값을 점검한다."""
        problems: list[str] = []
        if not self.is_production:
            return problems
        for name, label in (
            ("session_secret", "세션 서명 키"),
            ("device_credential_key", "기록계 인증정보 암호화 키"),
            ("influx_token", "InfluxDB 토큰"),
        ):
            if not self.resolved_secret(name):
                problems.append(f"{label}({name}) 가 비어 있다")
        if not self.postgres_password and not _read_secret_file("SOH_POSTGRES_PASSWORD"):
            problems.append("PostgreSQL 비밀번호가 비어 있다")
        return problems


@functools.lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
