"""시스템 전역에서 쓰는 표준 열거형.

제조사 고유 문자열은 이 파일에 들어오지 않는다. Adapter 가 변환한 뒤의 값만 다룬다.
"""
from __future__ import annotations

from enum import Enum


class Severity(str, Enum):
    """표준 상태. 숫자 값은 InfluxDB `recorder_health.severity` 로 나간다."""

    OK = "OK"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"
    UNKNOWN = "UNKNOWN"
    DISABLED = "DISABLED"
    MAINTENANCE = "MAINTENANCE"

    @property
    def code(self) -> int:
        return _SEVERITY_CODES[self]

    @classmethod
    def from_code(cls, code: int) -> "Severity":
        for severity, value in _SEVERITY_CODES.items():
            if value == code:
                return severity
        raise ValueError(f"알 수 없는 severity 코드: {code}")

    @classmethod
    def worst(cls, severities: "list[Severity] | tuple[Severity, ...]") -> "Severity":
        """집계용. 판정 대상이 없으면 UNKNOWN 이다. OK 로 접지 않는다."""
        actionable = [s for s in severities if s in _ACTIONABLE_ORDER]
        if not actionable:
            return cls.UNKNOWN if not severities else severities[0]
        return max(actionable, key=lambda s: _ACTIONABLE_ORDER[s])


_SEVERITY_CODES: dict[Severity, int] = {
    Severity.OK: 0,
    Severity.WARNING: 1,
    Severity.CRITICAL: 2,
    Severity.UNKNOWN: 3,
    Severity.DISABLED: 4,
    Severity.MAINTENANCE: 5,
}

# 심각도 비교 순서. DISABLED/MAINTENANCE 는 "판정 대상 아님"이므로 비교에서 빠진다.
_ACTIONABLE_ORDER: dict[Severity, int] = {
    Severity.OK: 0,
    Severity.UNKNOWN: 1,
    Severity.WARNING: 2,
    Severity.CRITICAL: 3,
}


class SupportState(str, Enum):
    """장비 기능 지원 상태. UNSUPPORTED 와 UNKNOWN 을 OK 로 접지 않기 위한 장치."""

    SUPPORTED_ENABLED = "SUPPORTED_ENABLED"
    SUPPORTED_DISABLED = "SUPPORTED_DISABLED"
    UNSUPPORTED = "UNSUPPORTED"
    UNKNOWN = "UNKNOWN"
    ERROR = "ERROR"

    @property
    def expects_value(self) -> bool:
        """값이 와야 하는 상태인지. 아니면 값 없음이 정상이다."""
        return self is SupportState.SUPPORTED_ENABLED

    @property
    def evaluable(self) -> bool:
        """장애 판정 대상인지."""
        return self is SupportState.SUPPORTED_ENABLED


class ValueType(str, Enum):
    BOOLEAN = "boolean"
    INTEGER = "integer"
    FLOAT = "float"
    STATUS = "status"
    TEXT = "text"
    TIMESTAMP = "timestamp"


class MetricSource(str, Enum):
    ADAPTER = "adapter"
    COLLECTOR = "collector"
    DATA_AVAILABILITY = "data_availability"
    HEALTH_ENGINE = "health_engine"


class Aggregation(str, Enum):
    LAST = "last"
    MEAN = "mean"
    MIN = "min"
    MAX = "max"
    SUM = "sum"


class CollectionMode(str, Enum):
    DIRECT = "DIRECT"
    EDGE = "EDGE"


class PollErrorCode(str, Enum):
    """수집 실패 분류. 회선 문제와 장비 문제를 구분해야 조치가 갈린다."""

    DNS_FAILURE = "DNS_FAILURE"
    CONNECTION_REFUSED = "CONNECTION_REFUSED"
    CONNECT_TIMEOUT = "CONNECT_TIMEOUT"
    REQUEST_TIMEOUT = "REQUEST_TIMEOUT"
    TLS_ERROR = "TLS_ERROR"
    HTTP_ERROR = "HTTP_ERROR"
    AUTH_ERROR = "AUTH_ERROR"
    INVALID_PAYLOAD = "INVALID_PAYLOAD"
    IDENTITY_MISMATCH = "IDENTITY_MISMATCH"
    ADAPTER_ERROR = "ADAPTER_ERROR"
    STORAGE_ERROR = "STORAGE_ERROR"
    UNKNOWN = "UNKNOWN"


class ProcessRole(str, Enum):
    API = "api"
    COLLECTOR = "collector"
    EDGE = "edge"
