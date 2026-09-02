"""Incident 생명주기.

    PENDING → OPEN → ACKNOWLEDGED → RESOLVED

같은 대상에 열려 있는 장애는 하나뿐이다. DB 의 부분 유일 인덱스가 이를 보장하고,
이 모듈은 그 하나를 찾아 갱신한다. 상태가 더 나빠지면 새 장애를 만들지 않고 승격한다.
같은 원인으로 장애가 계속 새로 생기면 이력이 쓸모없어진다.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Incident, IncidentEvent, IncidentStatus
from app.domain.enums import Severity
from app.health.notifier import Notification, Notifier

OPEN_STATUSES = (IncidentStatus.PENDING, IncidentStatus.OPEN, IncidentStatus.ACKNOWLEDGED)


@dataclass(frozen=True)
class IncidentTarget:
    device_id: uuid.UUID
    station_id: uuid.UUID
    station_code: str
    category: str
    metric_key: str
    dimension_value: str


def find_open(session: Session, target: IncidentTarget) -> Incident | None:
    return session.scalar(
        select(Incident).where(
            Incident.device_id == target.device_id,
            Incident.category == target.category,
            Incident.metric_key == (target.metric_key or None),
            Incident.dimension_value == target.dimension_value,
            Incident.status.in_(OPEN_STATUSES),
        )
    )


def _record_event(
    session: Session,
    incident: Incident,
    *,
    event_type: str,
    occurred_at: datetime,
    from_status: IncidentStatus | None = None,
    to_status: IncidentStatus | None = None,
    message: str | None = None,
    actor_id: uuid.UUID | None = None,
) -> IncidentEvent:
    event = IncidentEvent(
        incident_id=incident.id,
        occurred_at=occurred_at,
        event_type=event_type,
        from_status=from_status,
        to_status=to_status,
        message=message,
        actor_id=actor_id,
    )
    session.add(event)
    return event


def _notify(
    notifier: Notifier | None,
    kind: str,
    incident: Incident,
    target: IncidentTarget,
    occurred_at: datetime,
    reason: str,
) -> None:
    if notifier is None:
        return
    notifier.send(
        Notification(
            kind=kind,
            incident_id=str(incident.id),
            device_id=str(target.device_id),
            station_code=target.station_code,
            category=target.category,
            metric_key=target.metric_key or None,
            dimension_value=target.dimension_value,
            severity=incident.severity,
            title=incident.title,
            occurred_at=occurred_at,
            detail={"reason": reason},
        )
    )


def open_or_escalate(
    session: Session,
    target: IncidentTarget,
    *,
    severity: Severity,
    title: str,
    observed_at: datetime,
    value: float | None = None,
    threshold: float | None = None,
    reason: str = "",
    maintenance_related: bool = False,
    suppressed_by_edge: bool = False,
    notifier: Notifier | None = None,
) -> tuple[Incident, str | None]:
    """장애를 열거나 승격한다. (장애, 알림 종류) 를 돌려준다."""
    incident = find_open(session, target)

    if incident is None:
        incident = Incident(
            device_id=target.device_id,
            station_id=target.station_id,
            category=target.category,
            metric_key=target.metric_key or None,
            dimension_value=target.dimension_value,
            severity=severity,
            status=IncidentStatus.OPEN,
            title=title,
            first_observed_at=observed_at,
            last_observed_at=observed_at,
            worst_value=value,
            threshold_value=threshold,
            maintenance_related=maintenance_related,
            suppressed_by_edge=suppressed_by_edge,
            detail={"reason": reason},
        )
        session.add(incident)
        session.flush()
        _record_event(
            session,
            incident,
            event_type="OPENED",
            occurred_at=observed_at,
            to_status=IncidentStatus.OPEN,
            message=reason,
        )
        kind = "OPENED"
    else:
        incident.last_observed_at = observed_at
        if value is not None:
            previous = incident.worst_value
            if previous is None or abs(value) > abs(previous):
                incident.worst_value = value

        if severity is not incident.severity and severity is Severity.CRITICAL:
            _record_event(
                session,
                incident,
                event_type="ESCALATED",
                occurred_at=observed_at,
                from_status=incident.status,
                to_status=incident.status,
                message=f"{incident.severity.value} → {severity.value}: {reason}",
            )
            incident.severity = severity
            kind = "ESCALATED"
        else:
            # 같은 상태가 이어지는 동안에는 알림을 다시 보내지 않는다.
            kind = None

    session.flush()

    if kind:
        _notify(notifier, kind, incident, target, observed_at, reason)

    return incident, kind


def resolve(
    session: Session,
    target: IncidentTarget,
    *,
    observed_at: datetime,
    reason: str = "",
    notifier: Notifier | None = None,
) -> Incident | None:
    """열려 있는 장애를 복구 처리한다. 없으면 아무 일도 하지 않는다."""
    incident = find_open(session, target)
    if incident is None:
        return None

    previous = incident.status
    incident.status = IncidentStatus.RESOLVED
    incident.resolved_at = observed_at
    incident.last_observed_at = observed_at
    _record_event(
        session,
        incident,
        event_type="RESOLVED",
        occurred_at=observed_at,
        from_status=previous,
        to_status=IncidentStatus.RESOLVED,
        message=reason,
    )
    session.flush()
    _notify(notifier, "RESOLVED", incident, target, observed_at, reason)
    return incident


def acknowledge(
    session: Session,
    incident_id: uuid.UUID,
    *,
    actor_id: uuid.UUID | None,
    occurred_at: datetime,
    message: str = "",
) -> Incident | None:
    """운영자가 장애를 확인했다. 복구가 아니라 '보고 있다' 는 표시다."""
    incident = session.get(Incident, incident_id)
    if incident is None or incident.status is IncidentStatus.RESOLVED:
        return None

    previous = incident.status
    incident.status = IncidentStatus.ACKNOWLEDGED
    incident.acknowledged_at = occurred_at
    incident.acknowledged_by = actor_id
    _record_event(
        session,
        incident,
        event_type="ACKNOWLEDGED",
        occurred_at=occurred_at,
        from_status=previous,
        to_status=IncidentStatus.ACKNOWLEDGED,
        message=message,
        actor_id=actor_id,
    )
    session.flush()
    return incident
