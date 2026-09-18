"""관리 API 공통 변환."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException

from app.db.models import (
    CollectionProfile,
    Device,
    DeviceEndpoint,
    DeviceMetricOverride,
    ExternalSohChannel,
    LifecycleStatus,
    MetricProfile,
    ProfileMetric,
    Sensor,
    SensorAxis,
    Station,
    User,
)
from app.repository.postgres.collector_repo import as_utc


def parse_uuid(value: str, label: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"{label} 형식이 잘못됐다") from exc


def iso(moment: datetime | None) -> str | None:
    converted = as_utc(moment)
    return converted.isoformat() if converted else None


def reject_secret_fields(payload: dict[str, Any]) -> None:
    """요청 본문에 비밀번호 평문이 있으면 거절한다."""
    forbidden = []
    for key in payload:
        lowered = str(key).lower().replace("-", "_")
        if lowered in {"password", "secret", "credential", "credential_value", "token"}:
            forbidden.append(key)
    if forbidden:
        raise HTTPException(
            status_code=400,
            detail="비밀번호 평문은 저장하지 않는다. credentialReference(env: 또는 file:) 를 쓴다",
        )


def station_payload(
    station: Station,
    *,
    device_count: int = 0,
    worst_severity: str | None = None,
    categories: dict[str, str] | None = None,
    last_success_at: datetime | None = None,
    collection_mode: str | None = None,
) -> dict[str, Any]:
    return {
        "id": str(station.id),
        "networkCode": station.network_code,
        "stationCode": station.station_code,
        "name": station.name,
        "regionId": str(station.region_id) if station.region_id else None,
        "latitude": station.latitude,
        "longitude": station.longitude,
        "elevationM": station.elevation_m,
        "address": station.address,
        "timezone": station.timezone,
        "operatorName": station.operator_name,
        "operatorContact": station.operator_contact,
        "powerProfile": station.power_profile,
        "status": station.status.value,
        "installedAt": iso(station.installed_at),
        "notes": station.notes,
        "deviceCount": device_count,
        "worstSeverity": worst_severity,
        "categories": categories or {},
        "lastSuccessAt": iso(last_success_at),
        "collectionMode": collection_mode,
        "createdAt": iso(station.created_at),
        "updatedAt": iso(station.updated_at),
    }


def endpoint_payload(endpoint: DeviceEndpoint | None) -> dict[str, Any] | None:
    if endpoint is None:
        return None
    return {
        "scheme": endpoint.scheme,
        "hostname": endpoint.hostname,
        "port": endpoint.port,
        "basePath": endpoint.base_path,
        "tlsVerify": endpoint.tls_verify,
        "credentialReference": endpoint.credential_reference,
        "connectTimeoutMs": endpoint.connect_timeout_ms,
        "requestTimeoutMs": endpoint.request_timeout_ms,
        "connectionOptions": endpoint.connection_options or {},
    }


def device_payload(device: Device, *, include_children: bool = False) -> dict[str, Any]:
    body: dict[str, Any] = {
        "id": str(device.id),
        "stationId": str(device.station_id),
        "label": device.label,
        "serialNumber": device.serial_number,
        "instrumentId": device.instrument_id,
        "firmwareVersion": device.firmware_version,
        "adapterKey": device.adapter_key,
        "adapterVersion": device.adapter_version,
        "collectionMode": device.collection_mode.value,
        "edgeId": str(device.edge_id) if device.edge_id else None,
        "collectionProfileId": str(device.collection_profile_id) if device.collection_profile_id else None,
        "metricProfileId": str(device.metric_profile_id) if device.metric_profile_id else None,
        "dataSourceUri": device.data_source_uri,
        "enabled": device.enabled,
        "status": device.status.value,
        "nextPollAt": iso(device.next_poll_at),
        "notes": device.notes,
        "endpoint": endpoint_payload(device.endpoint),
    }
    if include_children:
        body["sensors"] = [sensor_payload(sensor) for sensor in device.sensors]
        body["externalSohChannels"] = [
            external_soh_payload(channel) for channel in getattr(device, "external_channels", [])
        ]
    return body


def sensor_payload(sensor: Sensor) -> dict[str, Any]:
    return {
        "id": str(sensor.id),
        "port": sensor.port,
        "manufacturer": sensor.manufacturer,
        "model": sensor.model,
        "serialNumber": sensor.serial_number,
        "axisCount": sensor.axis_count,
        "enabled": sensor.enabled,
        "axes": [axis_payload(axis) for axis in sensor.axes],
    }


def axis_payload(axis: SensorAxis) -> dict[str, Any]:
    return {
        "id": str(axis.id),
        "axisCode": axis.axis_code,
        "sohChannel": axis.soh_channel,
        "warningThreshold": axis.warning_threshold,
        "criticalThreshold": axis.critical_threshold,
        "unit": axis.unit,
    }


def external_soh_payload(channel: ExternalSohChannel) -> dict[str, Any]:
    return {
        "id": str(channel.id),
        "channelNumber": channel.channel_number,
        "name": channel.name,
        "measurementType": channel.measurement_type,
        "rawUnit": channel.raw_unit,
        "outputUnit": channel.output_unit,
        "scale": channel.scale,
        "offset": channel.offset,
        "warningLow": channel.warning_low,
        "warningHigh": channel.warning_high,
        "criticalLow": channel.critical_low,
        "criticalHigh": channel.critical_high,
        "enabled": channel.enabled,
        "formula": "value = raw × scale + offset",
    }


def collection_profile_payload(profile: CollectionProfile, *, affected: int = 0) -> dict[str, Any]:
    return {
        "id": str(profile.id),
        "name": profile.name,
        "description": profile.description,
        "pollIntervalMinutes": profile.poll_interval_minutes,
        "retryCount": profile.retry_count,
        "retryDelaySeconds": profile.retry_delay_seconds,
        "dataCheckIntervalMinutes": profile.data_check_interval_minutes,
        "connectTimeoutMs": profile.connect_timeout_ms,
        "requestTimeoutMs": profile.request_timeout_ms,
        "isDefault": profile.is_default,
        "affectedDeviceCount": affected,
    }


def profile_metric_payload(entry: ProfileMetric) -> dict[str, Any]:
    return {
        "metricKey": entry.metric_key,
        "enabled": entry.enabled,
        "alertingEnabled": entry.alerting_enabled,
        "warningCondition": entry.warning_condition or {},
        "criticalCondition": entry.critical_condition or {},
        "holdSeconds": entry.hold_seconds,
        "recoverySeconds": entry.recovery_seconds,
        "consecutiveViolations": entry.consecutive_violations,
    }


def metric_profile_payload(
    profile: MetricProfile, *, affected: int = 0, entries: list[ProfileMetric] | None = None
) -> dict[str, Any]:
    return {
        "id": str(profile.id),
        "name": profile.name,
        "description": profile.description,
        "isDefault": profile.is_default,
        "affectedDeviceCount": affected,
        "entries": [profile_metric_payload(entry) for entry in (entries if entries is not None else profile.entries)],
    }


def override_payload(row: DeviceMetricOverride) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "metricKey": row.metric_key,
        "dimensionValue": row.dimension_value or None,
        "enabled": row.enabled,
        "alertingEnabled": row.alerting_enabled,
        "warningCondition": row.warning_condition,
        "criticalCondition": row.critical_condition,
        "holdSeconds": row.hold_seconds,
        "recoverySeconds": row.recovery_seconds,
        "reason": row.reason,
    }


def user_payload(user: User) -> dict[str, Any]:
    return {
        "id": str(user.id),
        "username": user.username,
        "displayName": user.display_name,
        "email": user.email,
        "role": user.role.value,
        "enabled": user.enabled,
        "mustChangePassword": user.must_change_password,
        "lastLoginAt": iso(user.last_login_at),
    }


def lifecycle_or_400(value: str) -> LifecycleStatus:
    try:
        return LifecycleStatus(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"알 수 없는 상태값: {value}") from exc


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
