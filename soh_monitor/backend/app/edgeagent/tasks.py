"""중앙이 맡긴 원격 작업.

연결 시험은 지역망에 있는 Edge 가 대행한다. 중앙 API 프로세스는 관측소망으로
나가지 않는다.
"""
from __future__ import annotations

from typing import Any

from app.adapters.contract import DeviceContext
from app.adapters.registry import AdapterRegistrationError, AdapterRegistry
from app.auth.credentials import CredentialResolver
from app.config.settings import get_settings
from app.net.ssrf import SsrfError, resolve_safe_host
from app.observability.logging import get_logger

logger = get_logger("app.edgeagent.tasks", role="edge")


async def execute_task(
    task: dict[str, Any],
    registry: AdapterRegistry,
    resolver: CredentialResolver,
) -> dict[str, Any]:
    task_type = str(task.get("type") or "")
    if task_type == "test_connection":
        return await _test_connection(task.get("payload") or {}, registry, resolver)
    if task_type == "poll_now":
        return {
            "ok": True,
            "type": task_type,
            "deviceId": (task.get("payload") or {}).get("deviceId"),
            "forced": True,
        }
    return {"ok": False, "type": task_type, "error": f"모르는 작업이다: {task_type}"}


async def _test_connection(
    payload: dict[str, Any],
    registry: AdapterRegistry,
    resolver: CredentialResolver,
) -> dict[str, Any]:
    hostname = str(payload.get("hostname") or "")
    adapter_key = str(payload.get("adapterKey") or "")
    if not hostname or not adapter_key:
        return {"ok": False, "type": "test_connection", "error": "hostname 과 adapterKey 가 필요하다"}

    settings = get_settings()
    try:
        resolve_safe_host(hostname, settings.allowed_device_networks)
    except SsrfError as exc:
        return {"ok": False, "type": "test_connection", "error": str(exc), "reachable": False}

    try:
        adapter = registry.get(adapter_key)
    except AdapterRegistrationError as exc:
        return {"ok": False, "type": "test_connection", "error": str(exc), "reachable": False}

    connection = {
        "scheme": payload.get("scheme") or "http",
        "hostname": hostname,
        "basePath": payload.get("basePath") or "",
        "tlsVerify": payload.get("tlsVerify", True),
    }
    if payload.get("port"):
        connection["port"] = payload["port"]
    if payload.get("instrumentId"):
        connection["instrumentId"] = payload["instrumentId"]

    context = DeviceContext(
        device_id=str(payload.get("deviceId") or "probe"),
        station_code=str(payload.get("stationCode") or "PROBE"),
        connection=connection,
        credential=resolver.resolve(payload.get("credentialReference")),
        connect_timeout_ms=int(payload.get("connectTimeoutMs") or 5000),
        request_timeout_ms=int(payload.get("requestTimeoutMs") or 10000),
    )
    result = await adapter.test_connection(context)
    identity = None
    if result.identity is not None:
        identity = {
            "manufacturer": result.identity.manufacturer,
            "model": result.identity.model,
            "serialNumber": result.identity.serial_number,
            "instrumentId": result.identity.instrument_id,
            "firmwareVersion": result.identity.firmware_version,
            "channelCount": result.identity.channel_count,
        }
    return {
        "ok": result.reachable,
        "type": "test_connection",
        "reachable": result.reachable,
        "latencyMs": result.latency_ms,
        "httpStatus": result.http_status,
        "message": result.message,
        "identity": identity,
    }
