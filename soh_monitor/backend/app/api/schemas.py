"""관리 API 요청 본문."""
from __future__ import annotations

from datetime import datetime
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator

ALLOWED_DATA_SOURCE_SCHEMES = frozenset({"http", "https", "fdsnws", "seedlink"})


def normalize_data_source_uri(value: str | None) -> str | None:
    """빈 값은 미지원(None). 스킴은 수집기가 아는 것만 받는다."""
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    scheme = urlparse(stripped).scheme.lower()
    if scheme not in ALLOWED_DATA_SOURCE_SCHEMES:
        allowed = ", ".join(sorted(ALLOWED_DATA_SOURCE_SCHEMES))
        raise ValueError(f"dataSourceUri 스킴은 {allowed} 만 허용한다")
    return stripped


def _to_camel(name: str) -> str:
    parts = name.split("_")
    return parts[0] + "".join(part.title() for part in parts[1:])


class ApiModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, alias_generator=_to_camel, extra="forbid")


class LoginRequest(ApiModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class PasswordChangeRequest(ApiModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=10, max_length=128)


class UserCreateRequest(ApiModel):
    username: str = Field(min_length=2, max_length=64)
    display_name: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=10, max_length=128)
    role: str = "VIEWER"
    email: str | None = Field(default=None, max_length=128)


class UserUpdateRequest(ApiModel):
    display_name: str | None = Field(default=None, max_length=64)
    role: str | None = None
    email: str | None = Field(default=None, max_length=128)
    enabled: bool | None = None
    password: str | None = Field(default=None, min_length=10, max_length=128)


class StationWriteRequest(ApiModel):
    station_code: str | None = Field(default=None, min_length=1, max_length=16)
    network_code: str | None = Field(default=None, min_length=1, max_length=8)
    name: str | None = Field(default=None, min_length=1, max_length=128)
    region_id: str | None = None
    region_code: str | None = Field(default=None, max_length=32)
    latitude: float | None = None
    longitude: float | None = None
    elevation_m: float | None = None
    address: str | None = Field(default=None, max_length=256)
    timezone: str | None = Field(default=None, max_length=64)
    operator_name: str | None = Field(default=None, max_length=64)
    operator_contact: str | None = Field(default=None, max_length=128)
    power_profile: str | None = Field(default=None, max_length=32)
    status: str | None = None
    notes: str | None = None


class EndpointWrite(ApiModel):
    scheme: str = "http"
    hostname: str = Field(min_length=1, max_length=256)
    port: int | None = Field(default=None, ge=1, le=65535)
    base_path: str = "/"
    tls_verify: bool = True
    credential_reference: str | None = Field(default=None, max_length=256)
    connect_timeout_ms: int = Field(default=5000, ge=100, le=60000)
    request_timeout_ms: int = Field(default=15000, ge=100, le=120000)
    connection_options: dict[str, Any] = Field(default_factory=dict)

    @field_validator("scheme")
    @classmethod
    def _scheme(cls, value: str) -> str:
        lowered = value.lower()
        if lowered not in {"http", "https"}:
            raise ValueError("scheme 은 http 또는 https 여야 한다")
        return lowered

    @field_validator("credential_reference")
    @classmethod
    def _credential(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return None
        scheme, _, target = value.partition(":")
        if scheme not in {"env", "file"} or not target:
            raise ValueError("credentialReference 는 env: 또는 file: 형식이어야 한다")
        return value


class DeviceWriteRequest(ApiModel):
    label: str | None = Field(default=None, max_length=64)
    serial_number: str | None = Field(default=None, max_length=64)
    instrument_id: str | None = Field(default=None, max_length=64)
    firmware_version: str | None = Field(default=None, max_length=64)
    adapter_key: str | None = Field(default=None, max_length=128)
    adapter_version: str | None = Field(default=None, max_length=32)
    collection_mode: str | None = None
    edge_id: str | None = None
    collection_profile_id: str | None = None
    metric_profile_id: str | None = None
    data_source_uri: str | None = Field(default=None, max_length=256)
    enabled: bool | None = None
    status: str | None = None
    notes: str | None = None
    endpoint: EndpointWrite | None = None

    @field_validator("data_source_uri")
    @classmethod
    def _data_source_uri(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class AxisWrite(ApiModel):
    axis_code: str = Field(min_length=1, max_length=8)
    soh_channel: str | None = Field(default=None, max_length=32)
    warning_threshold: float | None = None
    critical_threshold: float | None = None
    unit: str = Field(default="V", max_length=16)


class SensorWrite(ApiModel):
    port: str = Field(min_length=1, max_length=8)
    manufacturer: str | None = Field(default=None, max_length=64)
    model: str | None = Field(default=None, max_length=64)
    serial_number: str | None = Field(default=None, max_length=64)
    axis_count: int = Field(default=3, ge=1, le=6)
    enabled: bool = True
    axes: list[AxisWrite] = Field(default_factory=list)


class ExternalSohWrite(ApiModel):
    channel_number: int = Field(ge=1, le=16)
    name: str = Field(min_length=1, max_length=64)
    measurement_type: str = Field(default="voltage", max_length=32)
    raw_unit: str = Field(default="uV", max_length=16)
    output_unit: str = Field(default="V", max_length=16)
    scale: float = 1.0
    offset: float = 0.0
    warning_low: float | None = None
    warning_high: float | None = None
    critical_low: float | None = None
    critical_high: float | None = None
    enabled: bool = True


class ConnectionProbeRequest(ApiModel):
    adapter_key: str = Field(default="nanometrics.centaur.ctr", max_length=128)
    hostname: str = Field(min_length=1, max_length=256)
    scheme: str = "http"
    port: int | None = Field(default=None, ge=1, le=65535)
    base_path: str = ""
    tls_verify: bool = True
    credential_reference: str | None = None
    instrument_id: str | None = None
    connect_timeout_ms: int = Field(default=5000, ge=100, le=30000)
    request_timeout_ms: int = Field(default=10000, ge=100, le=30000)

    @field_validator("scheme")
    @classmethod
    def _scheme(cls, value: str) -> str:
        lowered = value.lower()
        if lowered not in {"http", "https"}:
            raise ValueError("scheme 은 http 또는 https 여야 한다")
        return lowered


class CollectionProfileWrite(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    description: str | None = None
    poll_interval_minutes: int | None = Field(default=None, ge=1, le=1440)
    retry_count: int | None = Field(default=None, ge=0, le=5)
    retry_delay_seconds: int | None = Field(default=None, ge=0, le=120)
    data_check_interval_minutes: int | None = Field(default=None, ge=1, le=1440)
    connect_timeout_ms: int | None = Field(default=None, ge=100, le=60000)
    request_timeout_ms: int | None = Field(default=None, ge=100, le=120000)
    is_default: bool | None = None


class ProfileMetricWrite(ApiModel):
    metric_key: str = Field(min_length=1, max_length=128)
    enabled: bool = True
    alerting_enabled: bool = True
    warning_condition: dict[str, Any] = Field(default_factory=dict)
    critical_condition: dict[str, Any] = Field(default_factory=dict)
    hold_seconds: int = Field(default=0, ge=0, le=86400)
    recovery_seconds: int = Field(default=0, ge=0, le=86400)
    consecutive_violations: int = Field(default=1, ge=1, le=20)


class MetricProfileWrite(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    description: str | None = None
    is_default: bool | None = None
    entries: list[ProfileMetricWrite] | None = None


class OverrideWrite(ApiModel):
    metric_key: str = Field(min_length=1, max_length=128)
    dimension_value: str = Field(default="", max_length=32)
    enabled: bool | None = None
    alerting_enabled: bool | None = None
    warning_condition: dict[str, Any] | None = None
    critical_condition: dict[str, Any] | None = None
    hold_seconds: int | None = Field(default=None, ge=0, le=86400)
    recovery_seconds: int | None = Field(default=None, ge=0, le=86400)
    reason: str | None = None


class MaintenanceWrite(ApiModel):
    scope: str = Field(default="device", pattern="^(device|station|edge|region|global)$")
    scope_id: str | None = None
    starts_at: datetime
    ends_at: datetime
    reason: str | None = None
    suppress_alerts: bool = True


class EdgeCreateRequest(ApiModel):
    edge_code: str = Field(min_length=2, max_length=64)
    name: str = Field(min_length=1, max_length=128)
    region_id: str | None = None
    notes: str | None = None


class EdgeAssignmentRequest(ApiModel):
    device_id: str = Field(min_length=1)
    role: str = Field(default="primary", max_length=16)


class EdgeEnrollRequest(ApiModel):
    edge_id: str = Field(min_length=1, max_length=64)
    enrollment_token: str = Field(min_length=8, max_length=256)
    agent_version: str | None = Field(default=None, max_length=32)
    installed_adapters: list[str] = Field(default_factory=list)
