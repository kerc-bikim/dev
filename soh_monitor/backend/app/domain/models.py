"""수집 결과의 표준 표현.

Adapter 는 제조사 응답을 이 형태로만 내놓는다. Collector·Edge·Health Engine·InfluxDB
Writer 는 이 형태만 안다. 이 경계가 Gen5·타 제조사 확장 범위를 Adapter 로 묶어 둔다.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.enums import PollErrorCode, Severity, SupportState


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class MetricSample(BaseModel):
    """표준 Metric 한 개의 관측값.

    값은 타입별 필드에 하나만 담는다. 값이 없을 수도 있다. 예를 들어 기능이
    UNSUPPORTED 면 값 없이 support_state 만 실려 온다. 값 없음을 0 으로 채우지 않는다.
    """

    model_config = ConfigDict(frozen=True)

    metric_key: str
    dimensions: dict[str, str] = Field(default_factory=dict)

    value_float: float | None = None
    value_int: int | None = None
    value_bool: bool | None = None
    value_text: str | None = None
    value_status: Severity | None = None
    value_timestamp: datetime | None = None

    support_state: SupportState = SupportState.SUPPORTED_ENABLED
    raw_value: str | None = Field(
        default=None,
        description="표준화 이전 원값의 문자열 표현. UNKNOWN 원인 추적용이며 판정에는 쓰지 않는다.",
    )

    @field_validator("dimensions")
    @classmethod
    def _no_empty_dimension(cls, value: dict[str, str]) -> dict[str, str]:
        for key, dim in value.items():
            if not key or not dim:
                raise ValueError("dimensions 의 키와 값은 비어 있을 수 없다")
        return value

    @property
    def has_value(self) -> bool:
        return any(
            v is not None
            for v in (
                self.value_float,
                self.value_int,
                self.value_bool,
                self.value_text,
                self.value_status,
                self.value_timestamp,
            )
        )

    @property
    def value(self) -> Any:
        for candidate in (
            self.value_float,
            self.value_int,
            self.value_bool,
            self.value_text,
            self.value_status,
            self.value_timestamp,
        ):
            if candidate is not None:
                return candidate
        return None


class DeviceIdentity(BaseModel):
    """Probe 로 확인한 장비 실제 신원. 등록값과 비교해 불일치를 사용자에게 보인다."""

    model_config = ConfigDict(frozen=True)

    manufacturer: str | None = None
    model: str | None = None
    serial_number: str | None = None
    instrument_id: str | None = None
    firmware_version: str | None = None
    channel_count: int | None = None
    sensor_ports: tuple[str, ...] = ()
    external_soh_channels: int | None = None

    def differences(self, expected: "DeviceIdentity") -> dict[str, tuple[Any, Any]]:
        """등록값과 다른 항목만 (등록값, 실제값) 으로 돌려준다."""
        diffs: dict[str, tuple[Any, Any]] = {}
        for field in ("manufacturer", "model", "serial_number", "instrument_id", "firmware_version", "channel_count"):
            want = getattr(expected, field)
            got = getattr(self, field)
            if want is None or got is None:
                continue
            if str(want).strip().lower() != str(got).strip().lower():
                diffs[field] = (want, got)
        return diffs


class CapabilityReport(BaseModel):
    """장비 기능 탐지 결과. 키는 capabilities.yaml 의 capability 키."""

    model_config = ConfigDict(frozen=True)

    states: dict[str, SupportState] = Field(default_factory=dict)

    def state_of(self, capability_key: str) -> SupportState:
        return self.states.get(capability_key, SupportState.UNKNOWN)

    def evaluable(self, capability_key: str | None) -> bool:
        if capability_key is None:
            return True
        return self.state_of(capability_key).evaluable


class PollResult(BaseModel):
    """한 번의 수집 시도 결과. 성공이든 실패든 항상 만들어진다.

    실패한 Poll 도 기록해야 통신 장애를 시계열로 볼 수 있다. 실패를 버리면
    '데이터가 없는 것'과 '장비가 죽은 것'을 구분할 수 없게 된다.
    """

    poll_id: str
    device_id: str
    adapter_key: str
    adapter_version: str
    observed_at: datetime = Field(default_factory=utcnow)
    success: bool
    samples: tuple[MetricSample, ...] = ()
    capabilities: CapabilityReport = Field(default_factory=CapabilityReport)
    identity: DeviceIdentity | None = None

    latency_ms: float | None = None
    http_status: int | None = None
    payload_bytes: int | None = None
    error_code: PollErrorCode | None = None
    error_message: str | None = None
    unmapped_values: dict[str, str] = Field(
        default_factory=dict,
        description="표준 상태로 해석하지 못한 원문. Mapping 보강 대상이며 UNKNOWN 으로 적재된다.",
    )

    @field_validator("observed_at")
    @classmethod
    def _require_tz(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("observed_at 은 시간대를 포함해야 한다. 내부 표준은 UTC 다")
        return value.astimezone(timezone.utc)

    def sample_of(self, metric_key: str, **dimensions: str) -> MetricSample | None:
        for sample in self.samples:
            if sample.metric_key != metric_key:
                continue
            if dimensions and sample.dimensions != dimensions:
                continue
            return sample
        return None
