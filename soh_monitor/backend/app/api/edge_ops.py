"""Edge 등록·할당·설정 문서 조립.

관리 API 와 Edge 프로토콜이 같이 쓴다. 장비의 collection_mode 가 EDGE 로 바뀌면
활성 할당 행을 맞춰 두어 설정 동기화가 빈 목록을 내려주지 않게 한다.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException, Request, status
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.api import audit
from app.api.deps import Actor
from app.api.presenters import endpoint_payload, iso, parse_uuid
from app.config.settings import get_settings
from app.db.models import (
    AdapterVersion,
    CollectionMode,
    Device,
    DeviceEndpoint,
    EdgeAssignment,
    EdgeCollector,
    EdgeRuntimeState,
    EdgeStatus,
    EdgeTask,
    EdgeTaskStatus,
    LifecycleStatus,
    Station,
)
from app.domain.enums import Severity
from app.edgeagent.codec import iso_z
from app.edgeagent.enroll import generate_enrollment_token, hash_enrollment_token, verify_edge_token


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def load_edge(session: Session, edge_id: str) -> EdgeCollector:
    identifier = parse_uuid(edge_id, "Edge 식별자")
    edge = session.get(EdgeCollector, identifier)
    if edge is None:
        raise HTTPException(status_code=404, detail="등록되지 않은 Edge 다")
    return edge


def load_edge_by_code(session: Session, edge_code: str) -> EdgeCollector | None:
    return session.scalar(select(EdgeCollector).where(EdgeCollector.edge_code == edge_code))


def bump_config_version(session: Session, edge_id: uuid.UUID) -> int:
    edge = session.get(EdgeCollector, edge_id)
    if edge is None:
        return 0
    edge.last_config_version = int(edge.last_config_version or 0) + 1
    if edge.last_config_version < 1:
        edge.last_config_version = 1
    return edge.last_config_version


def parse_version(value: str) -> tuple[int, ...]:
    parts: list[int] = []
    for token in (value or "0").split("."):
        digits = "".join(ch for ch in token if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts or (0,))


def installed_adapter_keys(edge: EdgeCollector) -> set[str] | None:
    raw = edge.installed_adapters or {}
    if not raw:
        return None
    if isinstance(raw, dict):
        return {str(key) for key, enabled in raw.items() if enabled}
    if isinstance(raw, list):
        return {str(key) for key in raw}
    return None


def assert_assignment_compatible(session: Session, edge: EdgeCollector, device: Device) -> None:
    """Adapter 가 Edge 에 없거나 프로그램 버전이 모자라면 할당을 막는다."""
    if edge.status is EdgeStatus.DISABLED or edge.revoked_at is not None:
        raise HTTPException(status_code=409, detail="폐기된 Edge 에는 장비를 할당할 수 없다")
    keys = installed_adapter_keys(edge)
    if keys is not None and device.adapter_key not in keys:
        raise HTTPException(
            status_code=409,
            detail=f"이 Edge 에 {device.adapter_key} Adapter 가 설치되어 있지 않다",
        )
    min_version = None
    try:
        from app.adapters.registry import get_registry

        min_version = get_registry().get(device.adapter_key).manifest.minimum_edge_version
    except Exception:  # noqa: BLE001 - 레지스트리에 없으면 DB 버전 표를 본다
        row = session.scalar(
            select(AdapterVersion)
            .where(AdapterVersion.adapter_key == device.adapter_key)
            .order_by(AdapterVersion.released_at.desc())
        )
        if row is not None:
            min_version = row.minimum_edge_version
    if min_version and edge.software_version:
        if parse_version(edge.software_version) < parse_version(min_version):
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Edge 프로그램 {edge.software_version} 은 "
                    f"{device.adapter_key} 최소 버전 {min_version} 보다 낮다"
                ),
            )


def sync_device_assignment(session: Session, device: Device) -> None:
    """장비의 Edge 지정과 활성 할당 행을 맞춘다."""
    now = utcnow()
    actives = list(
        session.scalars(
            select(EdgeAssignment).where(
                EdgeAssignment.device_id == device.id,
                EdgeAssignment.enabled.is_(True),
            )
        )
    )
    if device.collection_mode is CollectionMode.EDGE and device.edge_id:
        edge = session.get(EdgeCollector, device.edge_id)
        if edge is None:
            raise HTTPException(status_code=404, detail="없는 Edge 다")
        assert_assignment_compatible(session, edge, device)
        keep = None
        for row in actives:
            if row.edge_id == device.edge_id:
                keep = row
            else:
                row.enabled = False
                bump_config_version(session, row.edge_id)
        if keep is None:
            last_epoch = session.scalar(
                select(func.max(EdgeAssignment.assignment_epoch)).where(
                    EdgeAssignment.device_id == device.id,
                    EdgeAssignment.edge_id == device.edge_id,
                )
            ) or 0
            session.add(
                EdgeAssignment(
                    edge_id=device.edge_id,
                    device_id=device.id,
                    assignment_epoch=int(last_epoch) + 1,
                    enabled=True,
                    assigned_at=now,
                )
            )
        bump_config_version(session, device.edge_id)
        return

    for row in actives:
        row.enabled = False
        bump_config_version(session, row.edge_id)


def assign_device(
    session: Session,
    edge: EdgeCollector,
    device: Device,
    *,
    role: str = "primary",
) -> EdgeAssignment:
    now = utcnow()
    assert_assignment_compatible(session, edge, device)
    for row in session.scalars(
        select(EdgeAssignment).where(
            EdgeAssignment.device_id == device.id,
            EdgeAssignment.enabled.is_(True),
        )
    ):
        if row.edge_id != edge.id:
            row.enabled = False
            bump_config_version(session, row.edge_id)
        elif row.edge_id == edge.id:
            device.collection_mode = CollectionMode.EDGE
            device.edge_id = edge.id
            bump_config_version(session, edge.id)
            return row

    last_epoch = session.scalar(
        select(func.max(EdgeAssignment.assignment_epoch)).where(
            EdgeAssignment.device_id == device.id,
            EdgeAssignment.edge_id == edge.id,
        )
    ) or 0
    assignment = EdgeAssignment(
        edge_id=edge.id,
        device_id=device.id,
        assignment_epoch=int(last_epoch) + 1,
        role=role or "primary",
        enabled=True,
        assigned_at=now,
    )
    session.add(assignment)
    device.collection_mode = CollectionMode.EDGE
    device.edge_id = edge.id
    bump_config_version(session, edge.id)
    return assignment


def unassign_device(session: Session, edge: EdgeCollector, device: Device) -> None:
    changed = False
    for row in session.scalars(
        select(EdgeAssignment).where(
            EdgeAssignment.edge_id == edge.id,
            EdgeAssignment.device_id == device.id,
            EdgeAssignment.enabled.is_(True),
        )
    ):
        row.enabled = False
        changed = True
    if device.edge_id == edge.id:
        device.edge_id = None
        device.collection_mode = CollectionMode.DIRECT
        changed = True
    if changed:
        bump_config_version(session, edge.id)


def issue_enrollment(session: Session, edge: EdgeCollector, *, hours: int = 24) -> str:
    token = generate_enrollment_token()
    edge.enrollment_token_hash = hash_enrollment_token(token)
    edge.enrollment_token_expires_at = utcnow() + timedelta(hours=hours)
    edge.status = EdgeStatus.ENROLLING
    return token


def build_config_document(session: Session, edge: EdgeCollector) -> dict[str, Any]:
    version = int(edge.last_config_version or 0)
    if version < 1:
        version = 1
        edge.last_config_version = 1
    rows = session.execute(
        select(Device, DeviceEndpoint, Station, EdgeAssignment)
        .join(Station, Station.id == Device.station_id)
        .outerjoin(DeviceEndpoint, DeviceEndpoint.device_id == Device.id)
        .outerjoin(
            EdgeAssignment,
            and_(
                EdgeAssignment.device_id == Device.id,
                EdgeAssignment.edge_id == edge.id,
                EdgeAssignment.enabled.is_(True),
            ),
        )
        .where(
            Device.edge_id == edge.id,
            Device.collection_mode == CollectionMode.EDGE,
            Device.status != LifecycleStatus.RETIRED,
        )
    ).all()
    devices: list[dict[str, Any]] = []
    for device, endpoint, station, assignment in rows:
        profile = device.collection_profile
        interval = profile.poll_interval_minutes if profile else 5
        retry = profile.retry_count if profile else 1
        connect_timeout = endpoint.connect_timeout_ms if endpoint else 5000
        request_timeout = endpoint.request_timeout_ms if endpoint else 15000
        connection: dict[str, Any] = {}
        if endpoint is not None:
            connection = {
                "scheme": endpoint.scheme,
                "hostname": endpoint.hostname,
                "basePath": endpoint.base_path,
                "tlsVerify": endpoint.tls_verify,
            }
            if endpoint.port:
                connection["port"] = endpoint.port
            if device.instrument_id:
                connection["instrumentId"] = device.instrument_id
            if endpoint.connection_options:
                connection.update(endpoint.connection_options)
        credential = None
        if endpoint is not None and endpoint.credential_reference:
            credential = {"reference": endpoint.credential_reference}
        devices.append(
            {
                "deviceId": str(device.id),
                "stationId": str(station.id),
                "stationCode": station.station_code,
                "adapterKey": device.adapter_key,
                "adapterVersion": device.adapter_version or "1.0",
                "assignmentEpoch": assignment.assignment_epoch if assignment else 1,
                "enabled": bool(device.enabled and (assignment.enabled if assignment else True)),
                "pollIntervalMinutes": interval,
                "connectTimeoutMs": connect_timeout,
                "requestTimeoutMs": request_timeout,
                "retryCount": retry,
                "connection": connection,
                "credential": credential,
            }
        )
    return {
        "configVersion": version,
        "edgeId": edge.edge_code,
        "issuedAt": iso_z(utcnow()),
        "heartbeatIntervalSeconds": get_settings().edge_heartbeat_seconds,
        "uploadBatchMaxPolls": 1000,
        "uploadBatchMaxBytes": 5 * 1024 * 1024,
        "spoolLimitBytes": edge.spool_limit_bytes or get_settings().edge_spool_limit_bytes,
        "devices": devices,
    }


def runtime_of(session: Session, edge: EdgeCollector) -> EdgeRuntimeState:
    state = session.get(EdgeRuntimeState, edge.id)
    if state is None:
        state = EdgeRuntimeState(edge_id=edge.id)
        session.add(state)
        session.flush()
    return state


def enqueue_task(
    session: Session,
    edge: EdgeCollector,
    *,
    task_type: str,
    payload: dict[str, Any],
    device_id: uuid.UUID | None = None,
) -> EdgeTask:
    task = EdgeTask(
        edge_id=edge.id,
        device_id=device_id,
        task_type=task_type,
        payload=payload,
        status=EdgeTaskStatus.PENDING,
        requested_at=utcnow(),
    )
    session.add(task)
    session.flush()
    return task


def pending_tasks(session: Session, edge: EdgeCollector) -> list[dict[str, Any]]:
    rows = session.scalars(
        select(EdgeTask)
        .where(EdgeTask.edge_id == edge.id, EdgeTask.status == EdgeTaskStatus.PENDING)
        .order_by(EdgeTask.requested_at)
    ).all()
    return [
        {
            "id": str(row.id),
            "type": row.task_type,
            "deviceId": str(row.device_id) if row.device_id else None,
            "payload": row.payload or {},
            "requestedAt": iso(row.requested_at),
        }
        for row in rows
    ]


def edge_payload(edge: EdgeCollector, *, health: EdgeRuntimeState | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {
        "id": str(edge.id),
        "edgeCode": edge.edge_code,
        "name": edge.name,
        "regionId": str(edge.region_id) if edge.region_id else None,
        "status": edge.status.value,
        "softwareVersion": edge.software_version,
        "installedAdapters": edge.installed_adapters or {},
        "certificateExpiresAt": iso(edge.certificate_expires_at),
        "lastHeartbeatAt": iso(edge.last_heartbeat_at),
        "lastUploadAt": iso(edge.last_upload_at),
        "lastConfigVersion": edge.last_config_version,
        "lastConfigAppliedVersion": edge.last_config_applied_version,
        "spoolUsedBytes": edge.spool_used_bytes,
        "spoolLimitBytes": edge.spool_limit_bytes,
        "ipAddress": edge.ip_address,
        "registeredAt": iso(edge.registered_at),
        "revokedAt": iso(edge.revoked_at),
        "certificateSerial": edge.certificate_serial,
        "notes": edge.notes,
        "hasEnrollmentToken": bool(edge.enrollment_token_hash),
    }
    if health is not None:
        body["health"] = {
            "connectivityStatus": health.connectivity_status.value,
            "configStatus": health.config_status.value,
            "collectorStatus": health.collector_status.value,
            "spoolStatus": health.spool_status.value,
            "certificateStatus": health.certificate_status.value,
            "clockStatus": health.clock_status.value,
            "pendingBatches": health.pending_batches,
            "oldestPendingAgeSeconds": health.oldest_pending_age_seconds,
            "clockOffsetMs": health.clock_offset_ms,
            "detail": health.detail or {},
        }
    return body


def current_edge_from_request(request: Request, session: Session) -> EdgeCollector:
    header = request.headers.get("authorization") or ""
    token = header[7:].strip() if header.lower().startswith("bearer ") else header.strip()
    secret = get_settings().session_signing_key()
    try:
        edge_code = verify_edge_token(token, secret)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    edge = load_edge_by_code(session, edge_code)
    if edge is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="등록되지 않은 Edge 다")
    if edge.status is EdgeStatus.DISABLED or edge.revoked_at is not None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="폐기된 Edge 다")
    verify = (request.headers.get("x-edge-certificate-verify") or "").strip().upper()
    serial = (request.headers.get("x-edge-certificate-serial") or "").strip()
    if verify == "FAILED":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="클라이언트 인증서가 유효하지 않다")
    if verify == "SUCCESS" or serial:
        expected = (edge.certificate_serial or "").strip()
        if verify == "SUCCESS" and not serial:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="인증서 일련번호가 없다")
        if expected and serial and serial.lower() != expected.lower():
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="인증서 일련번호가 등록된 Edge 와 다르다",
            )
    return edge


def revoke_edge(session: Session, edge: EdgeCollector) -> None:
    now = utcnow()
    edge.status = EdgeStatus.DISABLED
    edge.revoked_at = now
    edge.enrollment_token_hash = None
    edge.enrollment_token_expires_at = None
    health = runtime_of(session, edge)
    health.certificate_status = Severity.CRITICAL
    health.connectivity_status = Severity.DISABLED


def record_edge_audit(
    session: Session,
    *,
    actor: Actor | None,
    action: str,
    edge: EdgeCollector,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    request: Request | None = None,
) -> None:
    audit.record(
        session,
        actor=actor,
        action=action,
        entity_type="edge",
        entity_id=str(edge.id),
        before=before,
        after=after,
        request=request,
    )


def spool_status(used: int | None, limit: int | None) -> Severity:
    if used is None or not limit:
        return Severity.UNKNOWN
    ratio = used / limit
    if ratio >= 0.9:
        return Severity.CRITICAL
    if ratio >= 0.8:
        return Severity.WARNING
    return Severity.OK
