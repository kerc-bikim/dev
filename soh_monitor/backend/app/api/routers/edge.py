"""Edge 관리와 Edge Agent 프로토콜.

관리자 경로(`/api/v1/edges`)와 Agent 경로(`/api/v1/edge`)를 한곳에 둔다.
Agent 경로는 쿠키 세션이 아니라 등록 때 받은 HMAC 토큰으로 식별한다.
"""
from __future__ import annotations

import gzip
import json
import re
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, status
from jsonschema import Draft202012Validator
from sqlalchemy import select

from app.api import edge_ops
from app.api.deps import RequireAdmin, RequireOperate, RequireRead
from app.api.presenters import parse_uuid
from app.api.schemas import EdgeAssignmentRequest, EdgeCreateRequest, EdgeEnrollRequest
from app.config.settings import get_settings
from app.db.models import (
    Device,
    EdgeAssignment,
    EdgeCollector,
    EdgeStatus,
    EdgeTask,
    EdgeTaskStatus,
    Region,
    Station,
)
from app.db.session import session_scope
from app.domain.enums import Severity
from app.edgeagent.codec import iso_z
from app.edgeagent.enroll import (
    hash_enrollment_token,
    issue_edge_token,
    write_placeholder_certificate,
)
from app.metrics.catalog import CONTRACTS_DIR
from app.repository.postgres.collector_repo import as_utc

manager = APIRouter(prefix="/api/v1/edges", tags=["edges"])
agent = APIRouter(prefix="/api/v1/edge", tags=["edge-agent"])

EDGE_CODE_RE = re.compile(r"^[A-Za-z0-9._-]{2,64}$")
INGEST_SCHEMA = json.loads((CONTRACTS_DIR / "edge" / "ingest.schema.json").read_text("utf-8"))
_INGEST_VALIDATOR = Draft202012Validator(INGEST_SCHEMA)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _decode_batch(raw: bytes, *, max_bytes: int) -> dict:
    if not raw:
        raise HTTPException(status_code=400, detail="빈 Batch 다")
    if len(raw) > max_bytes:
        raise HTTPException(status_code=413, detail="Batch 가 크기 한도를 넘었다")
    if raw.startswith(b"\x1f\x8b"):
        try:
            raw = gzip.decompress(raw)
        except OSError as exc:
            raise HTTPException(status_code=400, detail="gzip 을 풀 수 없다") from exc
    if len(raw) > max_bytes:
        raise HTTPException(status_code=413, detail="Batch 가 크기 한도를 넘었다")
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail="Batch JSON 이 깨졌다") from exc


@manager.get("", summary="Edge 목록")
def list_edges(actor: RequireRead) -> dict:
    with session_scope() as session:
        from app.health.edge_watch import evaluate_all

        evaluate_all(session)
        edges = session.scalars(select(EdgeCollector).order_by(EdgeCollector.edge_code)).all()
        items = []
        for edge in edges:
            health = edge_ops.runtime_of(session, edge)
            items.append(edge_ops.edge_payload(edge, health=health))
        return {"edges": items}


@manager.post("", status_code=status.HTTP_201_CREATED, summary="Edge 등록")
def create_edge(body: EdgeCreateRequest, request: Request, actor: RequireAdmin) -> dict:
    if not EDGE_CODE_RE.match(body.edge_code):
        raise HTTPException(status_code=400, detail="edgeCode 형식이 잘못됐다")
    with session_scope() as session:
        if session.scalar(select(EdgeCollector).where(EdgeCollector.edge_code == body.edge_code)):
            raise HTTPException(status_code=409, detail="이미 있는 Edge 코드다")
        region_id = parse_uuid(body.region_id, "지역 식별자") if body.region_id else None
        if region_id is not None and session.get(Region, region_id) is None:
            raise HTTPException(status_code=404, detail="없는 지역이다")
        edge = EdgeCollector(
            edge_code=body.edge_code,
            name=body.name,
            region_id=region_id,
            status=EdgeStatus.ENROLLING,
            notes=body.notes,
            last_config_version=1,
            spool_limit_bytes=get_settings().edge_spool_limit_bytes,
        )
        session.add(edge)
        session.flush()
        token = edge_ops.issue_enrollment(session, edge)
        edge_ops.runtime_of(session, edge)
        edge_ops.record_edge_audit(
            session,
            actor=actor,
            action="create",
            edge=edge,
            after={"edgeCode": edge.edge_code, "name": edge.name},
            request=request,
        )
        payload = edge_ops.edge_payload(edge)
        payload["enrollmentToken"] = token
        payload["enrollmentTokenExpiresAt"] = edge.enrollment_token_expires_at.isoformat() if edge.enrollment_token_expires_at else None
        return {"edge": payload}


@manager.get("/{edge_id}", summary="Edge 상세")
def get_edge(edge_id: str, actor: RequireRead) -> dict:
    with session_scope() as session:
        from app.health.edge_watch import evaluate_all

        evaluate_all(session)
        edge = edge_ops.load_edge(session, edge_id)
        health = edge_ops.runtime_of(session, edge)
        from app.db.models import EdgeAssignment

        assignments = session.scalars(
            select(EdgeAssignment).where(EdgeAssignment.edge_id == edge.id, EdgeAssignment.enabled.is_(True))
        ).all()
        device_ids = [row.device_id for row in assignments]
        devices = {
            device.id: device
            for device in session.scalars(select(Device).where(Device.id.in_(device_ids))).all()
        } if device_ids else {}
        stations = {
            station.id: station
            for station in session.scalars(
                select(Station).where(Station.id.in_({device.station_id for device in devices.values()}))
            ).all()
        } if devices else {}
        body = edge_ops.edge_payload(edge, health=health)
        body["assignments"] = [
            {
                "id": str(row.id),
                "deviceId": str(row.device_id),
                "assignmentEpoch": row.assignment_epoch,
                "role": row.role,
                "enabled": row.enabled,
                "assignedAt": row.assigned_at.isoformat() if row.assigned_at else None,
                "adapterKey": devices[row.device_id].adapter_key if row.device_id in devices else None,
                "label": devices[row.device_id].label if row.device_id in devices else None,
                "stationId": str(devices[row.device_id].station_id) if row.device_id in devices else None,
                "stationCode": (
                    stations[devices[row.device_id].station_id].station_code
                    if row.device_id in devices and devices[row.device_id].station_id in stations
                    else None
                ),
            }
            for row in assignments
        ]
        return {"edge": body}


@manager.post("/{edge_id}/enrollment-token", summary="등록 Token 재발급")
def reissue_token(edge_id: str, request: Request, actor: RequireAdmin) -> dict:
    with session_scope() as session:
        edge = edge_ops.load_edge(session, edge_id)
        token = edge_ops.issue_enrollment(session, edge)
        edge_ops.record_edge_audit(
            session, actor=actor, action="enrollment-token", edge=edge, request=request
        )
        return {
            "edgeId": str(edge.id),
            "edgeCode": edge.edge_code,
            "enrollmentToken": token,
            "enrollmentTokenExpiresAt": edge.enrollment_token_expires_at.isoformat()
            if edge.enrollment_token_expires_at
            else None,
        }


@manager.post("/{edge_id}/assignments", status_code=status.HTTP_201_CREATED, summary="장비 할당")
def assign_device(edge_id: str, body: EdgeAssignmentRequest, request: Request, actor: RequireAdmin) -> dict:
    with session_scope() as session:
        edge = edge_ops.load_edge(session, edge_id)
        device = session.get(Device, parse_uuid(body.device_id, "장비 식별자"))
        if device is None:
            raise HTTPException(status_code=404, detail="등록되지 않은 장비다")
        assignment = edge_ops.assign_device(session, edge, device, role=body.role)
        session.flush()
        edge_ops.record_edge_audit(
            session,
            actor=actor,
            action="assign",
            edge=edge,
            after={"deviceId": str(device.id), "epoch": assignment.assignment_epoch},
            request=request,
        )
        return {
            "assignment": {
                "id": str(assignment.id),
                "edgeId": str(edge.id),
                "deviceId": str(device.id),
                "assignmentEpoch": assignment.assignment_epoch,
                "role": assignment.role,
                "configVersion": edge.last_config_version,
            }
        }


@manager.delete("/{edge_id}/assignments/{device_id}", summary="장비 할당 해제")
def unassign_device(edge_id: str, device_id: str, request: Request, actor: RequireAdmin) -> dict:
    with session_scope() as session:
        edge = edge_ops.load_edge(session, edge_id)
        device = session.get(Device, parse_uuid(device_id, "장비 식별자"))
        if device is None:
            raise HTTPException(status_code=404, detail="등록되지 않은 장비다")
        edge_ops.unassign_device(session, edge, device)
        edge_ops.record_edge_audit(
            session,
            actor=actor,
            action="unassign",
            edge=edge,
            after={"deviceId": str(device.id)},
            request=request,
        )
        return {"ok": True, "configVersion": edge.last_config_version}


@manager.post("/{edge_id}/revoke", summary="인증서 폐기")
def revoke_edge(edge_id: str, request: Request, actor: RequireAdmin) -> dict:
    with session_scope() as session:
        edge = edge_ops.load_edge(session, edge_id)
        edge_ops.revoke_edge(session, edge)
        edge_ops.record_edge_audit(
            session,
            actor=actor,
            action="revoke",
            edge=edge,
            after={"status": edge.status.value, "revokedAt": edge.revoked_at.isoformat() if edge.revoked_at else None},
            request=request,
        )
        return {"edge": edge_ops.edge_payload(edge, health=edge_ops.runtime_of(session, edge))}


@manager.get("/{edge_id}/health", summary="Edge 상태")
def edge_health(edge_id: str, actor: RequireRead) -> dict:
    with session_scope() as session:
        edge = edge_ops.load_edge(session, edge_id)
        health = edge_ops.runtime_of(session, edge)
        return {"edge": edge_ops.edge_payload(edge, health=health)}


@manager.post("/{edge_id}/tasks", status_code=status.HTTP_202_ACCEPTED, summary="원격 작업 요청")
def enqueue_task(edge_id: str, body: dict[str, Any], actor: RequireOperate) -> dict:
    task_type = str(body.get("type") or "")
    if task_type not in {"test_connection", "poll_now"}:
        raise HTTPException(status_code=400, detail="지원하지 않는 작업이다")
    with session_scope() as session:
        edge = edge_ops.load_edge(session, edge_id)
        device_id = parse_uuid(body["deviceId"], "장비 식별자") if body.get("deviceId") else None
        task = edge_ops.enqueue_task(
            session,
            edge,
            task_type=task_type,
            payload=body.get("payload") or {k: v for k, v in body.items() if k not in {"type"}},
            device_id=device_id,
        )
        return {"taskId": str(task.id), "queued": True, "type": task.task_type}


@agent.post("/enroll", summary="일회용 Token 으로 등록")
def enroll(body: EdgeEnrollRequest) -> dict:
    now = _utcnow()
    with session_scope() as session:
        edge = edge_ops.load_edge_by_code(session, body.edge_id)
        if edge is None:
            raise HTTPException(status_code=404, detail="등록되지 않은 Edge 다")
        if not edge.enrollment_token_hash:
            raise HTTPException(status_code=409, detail="등록 Token 이 없다. 관리자가 다시 발급해야 한다")
        expires = as_utc(edge.enrollment_token_expires_at)
        if expires and expires < now:
            edge.enrollment_token_hash = None
            raise HTTPException(status_code=401, detail="등록 Token 이 만료됐다")
        incoming = hash_enrollment_token(body.enrollment_token)
        if incoming != edge.enrollment_token_hash:
            raise HTTPException(status_code=401, detail="등록 Token 이 맞지 않는다")

        secret = get_settings().session_signing_key()
        client_token = issue_edge_token(edge.edge_code, secret)
        issued_at = iso_z(now)
        certificate, private_key, ca_certificate = write_placeholder_certificate(edge.edge_code, issued_at)
        edge.enrollment_token_hash = None
        edge.enrollment_token_expires_at = None
        edge.status = EdgeStatus.ONLINE
        edge.registered_at = now
        edge.software_version = body.agent_version
        edge.installed_adapters = {key: True for key in body.installed_adapters}
        edge.certificate_serial = edge.edge_code
        edge.certificate_expires_at = now.replace(year=now.year + 1) if now.year < 9999 else now
        health = edge_ops.runtime_of(session, edge)
        health.certificate_status = Severity.OK
        health.connectivity_status = Severity.OK
        return {
            "edgeId": edge.edge_code,
            "certificate": certificate,
            "privateKey": private_key,
            "caCertificate": ca_certificate,
            "clientToken": client_token,
            "expiresAt": iso_z(edge.certificate_expires_at) if edge.certificate_expires_at else None,
        }


@agent.get("/config", summary="설정 동기화")
def get_config(request: Request, current_version: int = Query(0, alias="currentVersion")) -> dict:
    with session_scope() as session:
        edge = edge_ops.current_edge_from_request(request, session)
        if current_version >= int(edge.last_config_version or 0) and current_version > 0:
            edge.last_config_applied_version = current_version
            return {"unchanged": True, "configVersion": edge.last_config_version}
        document = edge_ops.build_config_document(session, edge)
        return {"unchanged": False, "config": document}


@agent.post("/heartbeat", summary="상태 보고")
def heartbeat(request: Request, body: dict[str, Any]) -> dict:
    now = _utcnow()
    with session_scope() as session:
        edge = edge_ops.current_edge_from_request(request, session)
        edge.last_heartbeat_at = now
        edge.software_version = body.get("agentVersion") or edge.software_version
        if body.get("installedAdapters"):
            adapters = body["installedAdapters"]
            if isinstance(adapters, list):
                edge.installed_adapters = {key: True for key in adapters}
            elif isinstance(adapters, dict):
                edge.installed_adapters = adapters
        applied = body.get("configVersion")
        if isinstance(applied, int):
            edge.last_config_applied_version = applied
            edge.last_config_applied_at = now
        spool = body.get("spool") or {}
        if spool.get("usedBytes") is not None:
            edge.spool_used_bytes = int(spool["usedBytes"])
        if spool.get("limitBytes") is not None:
            edge.spool_limit_bytes = int(spool["limitBytes"])
        health_body = body.get("health") or {}
        state = edge_ops.runtime_of(session, edge)
        state.connectivity_status = Severity.OK
        state.pending_batches = spool.get("pending")
        state.oldest_pending_age_seconds = spool.get("oldestPendingAgeSeconds")
        state.clock_offset_ms = health_body.get("clockOffsetMs")
        state.spool_status = edge_ops.spool_status(edge.spool_used_bytes, edge.spool_limit_bytes)
        state.detail = {"health": health_body, "spool": spool}
        cpu = health_body.get("cpuPercent")
        mem = health_body.get("memoryPercent")
        disk = health_body.get("diskPercent")
        collector = Severity.OK
        if any(value is not None and value >= 90 for value in (cpu, mem, disk)):
            collector = Severity.CRITICAL
        elif any(value is not None and value >= 80 for value in (cpu, mem, disk)):
            collector = Severity.WARNING
        state.collector_status = collector
        if edge.status is not EdgeStatus.DISABLED:
            edge.status = EdgeStatus.DEGRADED if collector is not Severity.OK else EdgeStatus.ONLINE
        from app.health.edge_watch import evaluate_edge

        evaluate_edge(session, edge)
        tasks = edge_ops.pending_tasks(session, edge)
        return {
            "serverTime": iso_z(now),
            "configVersion": edge.last_config_version,
            "tasks": tasks,
        }


@agent.post("/ingest/batches", summary="수집 Batch 업로드")
async def ingest_batches(request: Request) -> dict:
    settings = get_settings()
    raw = await request.body()
    if len(raw) > settings.edge_ingest_max_bytes:
        raise HTTPException(status_code=413, detail="Batch 가 크기 한도를 넘었다")
    document = _decode_batch(raw, max_bytes=settings.edge_ingest_max_bytes)
    errors = sorted(_INGEST_VALIDATOR.iter_errors(document), key=lambda item: list(item.path))
    if errors:
        details = "; ".join(
            f"{'/'.join(str(part) for part in error.path) or '(root)'}: {error.message}"
            for error in errors[:8]
        )
        raise HTTPException(status_code=400, detail=f"Batch Schema 위반: {details}")

    now = _utcnow()
    with session_scope() as session:
        edge = edge_ops.current_edge_from_request(request, session)
        if document.get("edgeId") != edge.edge_code:
            raise HTTPException(status_code=400, detail="Batch 의 edgeId 가 인증된 Edge 와 다르다")
        from app.ingest import writer

        report = writer.process_batch(
            session,
            edge,
            document,
            sink=writer.sink_for(request.app),
            settings=settings,
            received_at=now,
        )
        from app.health.edge_watch import evaluate_edge

        evaluate_edge(session, edge, now=now, settings=settings)
        return {
            "accepted": report.accepted,
            "duplicate": report.duplicate,
            "batchId": report.batch_id,
            "firstSequence": report.first_sequence,
            "lastSequence": report.last_sequence,
            "pollCount": report.poll_count,
            "written": report.written,
            "skippedDuplicate": report.skipped_duplicate,
            "delayed": report.delayed,
            "pointsWritten": report.points_written,
        }


@agent.post("/tasks/{task_id}/result", summary="원격 작업 결과")
def task_result(task_id: str, request: Request, body: dict[str, Any]) -> dict:
    with session_scope() as session:
        edge = edge_ops.current_edge_from_request(request, session)
        task = session.get(EdgeTask, parse_uuid(task_id, "작업 식별자"))
        if task is None or task.edge_id != edge.id:
            raise HTTPException(status_code=404, detail="없는 작업이다")
        task.result = body
        task.completed_at = _utcnow()
        task.status = EdgeTaskStatus.SUCCEEDED if body.get("ok") else EdgeTaskStatus.FAILED
        return {"ok": True, "taskId": str(task.id), "status": task.status.value}
