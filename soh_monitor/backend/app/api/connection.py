"""등록 전·후 연결 시험.

API 프로세스가 관측소망으로 나가는 유일한 경로를 여기로 묶는다. 수집(poll-now)은
여전히 collector 가 담당하고, 여기서는 등록 화면이 필요로 하는 읽기 동작만 한다.
나가기 전에 SSRF 화이트리스트를 통과해야 한다.
"""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from app.adapters.contract import DeviceContext
from app.adapters.registry import AdapterRegistrationError, get_registry
from app.auth.credentials import CredentialResolver
from app.config.settings import get_settings
from app.domain.models import DeviceIdentity
from app.net.ssrf import SsrfError, resolve_safe_host


def _connection_dict(
    *,
    hostname: str,
    scheme: str = "http",
    port: int | None = None,
    base_path: str = "",
    tls_verify: bool = True,
    instrument_id: str | None = None,
) -> dict[str, Any]:
    connection: dict[str, Any] = {
        "scheme": scheme,
        "hostname": hostname,
        "basePath": base_path or "",
        "tlsVerify": tls_verify,
    }
    if port:
        connection["port"] = port
    if instrument_id:
        connection["instrumentId"] = instrument_id
    return connection


def assert_safe_target(hostname: str) -> None:
    settings = get_settings()
    try:
        resolve_safe_host(hostname, settings.allowed_device_networks)
    except SsrfError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def build_context(
    *,
    hostname: str,
    adapter_key: str,
    station_code: str = "PROBE",
    scheme: str = "http",
    port: int | None = None,
    base_path: str = "",
    tls_verify: bool = True,
    instrument_id: str | None = None,
    credential_reference: str | None = None,
    connect_timeout_ms: int = 5000,
    request_timeout_ms: int = 10000,
    resolver: CredentialResolver | None = None,
) -> tuple[Any, DeviceContext]:
    assert_safe_target(hostname)
    try:
        adapter = get_registry().get(adapter_key)
    except AdapterRegistrationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    connection = _connection_dict(
        hostname=hostname,
        scheme=scheme,
        port=port,
        base_path=base_path,
        tls_verify=tls_verify,
        instrument_id=instrument_id,
    )
    problems = [p for p in adapter.validate_configuration(connection) if "낯설다" not in p]
    if problems:
        raise HTTPException(status_code=400, detail="; ".join(problems))

    credential = (resolver or CredentialResolver()).resolve(credential_reference)
    context = DeviceContext(
        device_id="probe",
        station_code=station_code,
        connection=connection,
        credential=credential,
        connect_timeout_ms=connect_timeout_ms,
        request_timeout_ms=request_timeout_ms,
    )
    return adapter, context


def identity_payload(identity: DeviceIdentity | None) -> dict[str, Any] | None:
    if identity is None:
        return None
    return {
        "manufacturer": identity.manufacturer,
        "model": identity.model,
        "serialNumber": identity.serial_number,
        "instrumentId": identity.instrument_id,
        "firmwareVersion": identity.firmware_version,
        "channelCount": identity.channel_count,
        "sensorPorts": list(identity.sensor_ports),
        "externalSohChannels": identity.external_soh_channels,
    }
