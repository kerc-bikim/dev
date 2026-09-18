"""Edge Heartbeat 감시와 하위 장애 억제.

Heartbeat 가 2회 빠지면 WARNING, 3회 빠지면 CRITICAL 이다. Edge 가 죽은 동안
하위 기록계 장애를 각각 올리면 알림이 폭주하고, 원인은 '지역 수집기가 멈춤' 한
가지인데 화면이 수십 건의 전압·시각 장애로 가득 찬다.

그래서 Edge Offline 때는
  * Edge 장애 1건만 연다
  * 하위 장비는 UNKNOWN / EDGE UNREACHABLE 로 표시한다
  * 이미 열린 장비 장애는 suppressed_by_edge 로 접어 함대 집계에서 뺀다
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config.settings import Settings, get_settings
from app.db.models import (
    CollectionMode,
    Device,
    DeviceRuntimeState,
    EdgeCollector,
    EdgeRuntimeState,
    EdgeStatus,
    Incident,
    IncidentEvent,
    IncidentStatus,
)
from app.domain.enums import Severity, SupportState
from app.health.incidents import OPEN_STATUSES
from app.observability.logging import get_logger
from app.repository.postgres import health_repo
from app.repository.postgres.collector_repo import as_utc

logger = get_logger("app.health.edge_watch", role="api")

EDGE_CATEGORY = "connectivity"
EDGE_METRIC = "edge.reachable"
EDGE_UNREACHABLE = "EDGE_UNREACHABLE"


@dataclass
class EdgeWatchReport:
    checked: int = 0
    warning: int = 0
    critical: int = 0
    recovered: int = 0
    suppressed: int = 0
    opened: list[str] = field(default_factory=list)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def last_seen_at(edge: EdgeCollector) -> datetime | None:
    moments = [
        as_utc(edge.last_heartbeat_at),
        as_utc(edge.last_upload_at),
        as_utc(edge.registered_at),
    ]
    present = [moment for moment in moments if moment is not None]
    return max(present) if present else None


def missed_intervals(edge: EdgeCollector, *, now: datetime, interval_seconds: int) -> float:
    seen = last_seen_at(edge)
    if seen is None or interval_seconds <= 0:
        return 0.0
    elapsed = (now - seen).total_seconds()
    if elapsed <= 0:
        return 0.0
    return elapsed / interval_seconds


def connectivity_for_misses(missed: float, *, warning: int, critical: int) -> Severity:
    if missed >= critical:
        return Severity.CRITICAL
    if missed >= warning:
        return Severity.WARNING
    return Severity.OK


def _open_edge_incident(session: Session, edge: EdgeCollector, severity: Severity, now: datetime) -> Incident:
    existing = session.scalar(
        select(Incident).where(
            Incident.edge_id == edge.id,
            Incident.metric_key == EDGE_METRIC,
            Incident.status.in_(OPEN_STATUSES),
        )
    )
    if existing is not None:
        existing.last_observed_at = now
        if severity is Severity.CRITICAL and existing.severity is not Severity.CRITICAL:
            session.add(
                IncidentEvent(
                    incident_id=existing.id,
                    occurred_at=now,
                    event_type="ESCALATED",
                    from_status=existing.status,
                    to_status=existing.status,
                    message=f"{existing.severity.value} → {severity.value}",
                )
            )
            existing.severity = severity
        return existing

    incident = Incident(
        device_id=None,
        station_id=None,
        edge_id=edge.id,
        category=EDGE_CATEGORY,
        metric_key=EDGE_METRIC,
        dimension_value=(edge.edge_code or "")[:32],
        severity=severity,
        status=IncidentStatus.OPEN,
        title=f"[{edge.edge_code}] Edge 연결 끊김",
        first_observed_at=now,
        last_observed_at=now,
        suppressed_by_edge=False,
        detail={"reason": "heartbeat missed", "edgeCode": edge.edge_code},
    )
    session.add(incident)
    session.flush()
    session.add(
        IncidentEvent(
            incident_id=incident.id,
            occurred_at=now,
            event_type="OPENED",
            to_status=IncidentStatus.OPEN,
            message="Heartbeat 가 빠졌다",
        )
    )
    return incident


def _resolve_edge_incident(session: Session, edge: EdgeCollector, now: datetime) -> int:
    resolved = 0
    for incident in session.scalars(
        select(Incident).where(
            Incident.edge_id == edge.id,
            Incident.metric_key == EDGE_METRIC,
            Incident.status.in_(OPEN_STATUSES),
        )
    ):
        previous = incident.status
        incident.status = IncidentStatus.RESOLVED
        incident.resolved_at = now
        incident.last_observed_at = now
        session.add(
            IncidentEvent(
                incident_id=incident.id,
                occurred_at=now,
                event_type="RESOLVED",
                from_status=previous,
                to_status=IncidentStatus.RESOLVED,
                message="Heartbeat 가 돌아왔다",
            )
        )
        resolved += 1
    return resolved


def suppress_child_devices(session: Session, edge: EdgeCollector, now: datetime) -> int:
    """하위 장비를 UNKNOWN / EDGE UNREACHABLE 로 접고 열린 장애를 억제한다."""
    devices = session.scalars(
        select(Device).where(
            Device.edge_id == edge.id,
            Device.collection_mode == CollectionMode.EDGE,
        )
    ).all()
    suppressed = 0
    for device in devices:
        states = health_repo.load_states(session, device.id)
        health_repo.upsert_state(
            session,
            device.id,
            category=EDGE_CATEGORY,
            metric_key="connectivity.reachable",
            dimension_value="",
            severity=Severity.UNKNOWN,
            support_state=SupportState.SUPPORTED_ENABLED,
            is_stale=True,
            observed_at=now,
            evaluated_at=now,
            value_text=EDGE_UNREACHABLE,
            detail={"reason": "EDGE UNREACHABLE", "edgeCode": edge.edge_code},
            existing=states.get((EDGE_CATEGORY, "connectivity.reachable", "")),
        )
        health_repo.upsert_state(
            session,
            device.id,
            category=EDGE_CATEGORY,
            metric_key="",
            dimension_value="",
            severity=Severity.UNKNOWN,
            support_state=SupportState.SUPPORTED_ENABLED,
            is_stale=True,
            observed_at=now,
            evaluated_at=now,
            value_text=EDGE_UNREACHABLE,
            detail={"reason": "EDGE UNREACHABLE", "edgeCode": edge.edge_code},
            existing=states.get((EDGE_CATEGORY, "", "")),
        )
        runtime = session.get(DeviceRuntimeState, device.id)
        if runtime is None:
            runtime = DeviceRuntimeState(device_id=device.id, overall_severity=Severity.UNKNOWN)
            session.add(runtime)
        else:
            runtime.overall_severity = Severity.UNKNOWN
        for incident in session.scalars(
            select(Incident).where(
                Incident.device_id == device.id,
                Incident.status.in_(OPEN_STATUSES),
            )
        ):
            if not incident.suppressed_by_edge:
                incident.suppressed_by_edge = True
                suppressed += 1
    return suppressed


def _runtime(session: Session, edge: EdgeCollector) -> EdgeRuntimeState:
    state = session.get(EdgeRuntimeState, edge.id)
    if state is None:
        state = EdgeRuntimeState(edge_id=edge.id)
        session.add(state)
        session.flush()
    return state


def evaluate_edge(
    session: Session,
    edge: EdgeCollector,
    *,
    now: datetime | None = None,
    settings: Settings | None = None,
) -> Severity:
    settings = settings or get_settings()
    now = now or utcnow()
    if edge.status in {EdgeStatus.ENROLLING, EdgeStatus.DISABLED} or edge.revoked_at is not None:
        return Severity.DISABLED if edge.status is EdgeStatus.DISABLED else Severity.UNKNOWN

    missed = missed_intervals(edge, now=now, interval_seconds=settings.edge_heartbeat_seconds)
    severity = connectivity_for_misses(
        missed,
        warning=settings.edge_heartbeat_miss_warning,
        critical=settings.edge_heartbeat_miss_critical,
    )
    state = _runtime(session, edge)
    state.connectivity_status = severity

    if severity is Severity.CRITICAL:
        edge.status = EdgeStatus.OFFLINE
        _open_edge_incident(session, edge, severity, now)
        suppress_child_devices(session, edge, now)
    elif severity is Severity.WARNING:
        if edge.status is not EdgeStatus.DISABLED:
            edge.status = EdgeStatus.DEGRADED
        _open_edge_incident(session, edge, severity, now)
        suppress_child_devices(session, edge, now)
    else:
        _resolve_edge_incident(session, edge, now)
        if edge.status is EdgeStatus.OFFLINE:
            edge.status = EdgeStatus.ONLINE
    return severity


def evaluate_all(
    session: Session,
    *,
    now: datetime | None = None,
    settings: Settings | None = None,
) -> EdgeWatchReport:
    settings = settings or get_settings()
    now = now or utcnow()
    report = EdgeWatchReport()
    edges = session.scalars(select(EdgeCollector)).all()
    for edge in edges:
        if edge.status in {EdgeStatus.ENROLLING, EdgeStatus.DISABLED} or edge.revoked_at is not None:
            continue
        report.checked += 1
        before = edge.status
        severity = evaluate_edge(session, edge, now=now, settings=settings)
        if severity is Severity.CRITICAL:
            report.critical += 1
            if before is not EdgeStatus.OFFLINE:
                report.opened.append(edge.edge_code)
        elif severity is Severity.WARNING:
            report.warning += 1
        elif before is EdgeStatus.OFFLINE:
            report.recovered += 1
    session.flush()
    return report
