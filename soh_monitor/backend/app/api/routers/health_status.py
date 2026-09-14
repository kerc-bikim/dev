"""현재 상태와 장애 조회.

화면은 InfluxDB 를 조회하지 않고 이 API 로 현재 상태를 받는다. 시계열은 추세를 보는
용도이고, "지금 어떤가" 는 판정 결과 표에서 읽는 편이 빠르고 정확하다.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import desc, func, select

from app.db.models import (
    Device,
    DeviceRuntimeState,
    HealthState,
    Incident,
    IncidentEvent,
    IncidentStatus,
    Station,
)
from app.db.session import session_scope
from app.health import incidents as incident_ops
from app.health.state_machine import rollup
from app.repository.postgres.collector_repo import as_utc

router = APIRouter(prefix="/api/v1", tags=["health"])


def _parse_uuid(value: str, label: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"{label} 형식이 잘못됐다") from exc


@router.get("/fleet/summary", summary="전체 현황")
def fleet_summary() -> dict[str, object]:
    with session_scope() as session:
        total = session.scalar(select(func.count()).select_from(Device)) or 0

        connectivity: dict[str, int] = {}
        for row in session.execute(
            select(HealthState.severity, func.count())
            .where(HealthState.metric_key == "", HealthState.category == "connectivity")
            .group_by(HealthState.severity)
        ):
            connectivity[row[0].value] = row[1]

        open_incidents = (
            session.scalar(
                select(func.count())
                .select_from(Incident)
                .where(Incident.status.in_(incident_ops.OPEN_STATUSES))
            )
            or 0
        )

        stale = (
            session.scalar(
                select(func.count())
                .select_from(HealthState)
                .where(HealthState.metric_key == "", HealthState.is_stale.is_(True))
            )
            or 0
        )

        by_category: dict[str, dict[str, int]] = {}
        for row in session.execute(
            select(HealthState.category, HealthState.severity, func.count())
            .where(HealthState.metric_key == "")
            .group_by(HealthState.category, HealthState.severity)
        ):
            by_category.setdefault(row[0], {})[row[1].value] = row[2]

        return {
            "deviceCount": total,
            "connectivity": connectivity,
            "openIncidents": open_incidents,
            "staleStates": stale,
            "byCategory": by_category,
        }


@router.get("/devices/{device_id}/current-health", summary="장비 현재 상태")
def device_health(device_id: str) -> dict[str, object]:
    identifier = _parse_uuid(device_id, "장비 식별자")

    with session_scope() as session:
        device = session.get(Device, identifier)
        if device is None:
            raise HTTPException(status_code=404, detail="등록되지 않은 장비다")
        station = session.get(Station, device.station_id)
        runtime = session.get(DeviceRuntimeState, identifier)

        states = session.scalars(
            select(HealthState).where(HealthState.device_id == identifier)
        ).all()

        categories = {
            state.category: {
                "severity": state.severity.value,
                "isStale": state.is_stale,
                "evaluatedAt": as_utc(state.evaluated_at),
                "detail": state.detail or {},
            }
            for state in states
            if not state.metric_key
        }

        metrics = [
            {
                "metricKey": state.metric_key,
                "category": state.category,
                "dimension": state.dimension_value or None,
                "severity": state.severity.value,
                "supportState": state.support_state.value,
                "value": state.value_text,
                "isStale": state.is_stale,
                "observedAt": as_utc(state.observed_at),
                "detail": state.detail or {},
            }
            for state in states
            if state.metric_key
        ]

        overall = rollup([state.severity for state in states if not state.metric_key])

        return {
            "deviceId": device_id,
            "stationCode": station.station_code if station else None,
            "overall": overall.value,
            "lastSuccessAt": as_utc(runtime.last_success_at) if runtime else None,
            "lastPollAt": as_utc(runtime.last_poll_at) if runtime else None,
            "consecutiveFailures": runtime.consecutive_failures if runtime else 0,
            "categories": categories,
            "metrics": sorted(metrics, key=lambda item: item["metricKey"]),
        }


@router.get("/incidents", summary="장애 목록")
def list_incidents(
    status: str | None = Query(default="open", description="open | resolved | all"),
    limit: int = Query(default=50, ge=1, le=500),
) -> dict[str, object]:
    with session_scope() as session:
        query = select(Incident).order_by(desc(Incident.first_observed_at)).limit(limit)
        if status == "open":
            query = query.where(Incident.status.in_(incident_ops.OPEN_STATUSES))
        elif status == "resolved":
            query = query.where(Incident.status == IncidentStatus.RESOLVED)

        incidents = session.scalars(query).all()
        station_codes = {
            station.id: station.station_code for station in session.scalars(select(Station))
        }

        return {
            "incidents": [
                {
                    "incidentId": str(incident.id),
                    "deviceId": str(incident.device_id) if incident.device_id else None,
                    "stationCode": station_codes.get(incident.station_id),
                    "category": incident.category,
                    "metricKey": incident.metric_key,
                    "dimension": incident.dimension_value or None,
                    "severity": incident.severity.value,
                    "status": incident.status.value,
                    "title": incident.title,
                    "firstObservedAt": as_utc(incident.first_observed_at),
                    "lastObservedAt": as_utc(incident.last_observed_at),
                    "resolvedAt": as_utc(incident.resolved_at),
                    "acknowledgedAt": as_utc(incident.acknowledged_at),
                    "worstValue": incident.worst_value,
                    "thresholdValue": incident.threshold_value,
                    "maintenanceRelated": incident.maintenance_related,
                    "suppressedByEdge": incident.suppressed_by_edge,
                    "detail": incident.detail or {},
                }
                for incident in incidents
            ]
        }


@router.post("/incidents/{incident_id}/acknowledge", summary="장애 확인")
def acknowledge_incident(incident_id: str, message: str = "") -> dict[str, object]:
    identifier = _parse_uuid(incident_id, "장애 식별자")

    with session_scope() as session:
        incident = incident_ops.acknowledge(
            session,
            identifier,
            actor_id=None,  # M5 에서 인증 사용자로 바뀐다
            occurred_at=datetime.now(timezone.utc),
            message=message,
        )
        if incident is None:
            raise HTTPException(status_code=404, detail="확인할 수 있는 장애가 아니다")

        return {
            "incidentId": incident_id,
            "status": incident.status.value,
            "acknowledgedAt": as_utc(incident.acknowledged_at),
        }


@router.get("/incidents/{incident_id}/events", summary="장애 이력")
def incident_events(incident_id: str) -> dict[str, object]:
    identifier = _parse_uuid(incident_id, "장애 식별자")

    with session_scope() as session:
        incident = session.get(Incident, identifier)
        if incident is None:
            raise HTTPException(status_code=404, detail="등록되지 않은 장애다")

        events = session.scalars(
            select(IncidentEvent)
            .where(IncidentEvent.incident_id == identifier)
            .order_by(IncidentEvent.occurred_at)
        ).all()

        return {
            "incidentId": incident_id,
            "title": incident.title,
            "events": [
                {
                    "occurredAt": as_utc(event.occurred_at),
                    "eventType": event.event_type,
                    "fromStatus": event.from_status.value if event.from_status else None,
                    "toStatus": event.to_status.value if event.to_status else None,
                    "message": event.message,
                }
                for event in events
            ],
        }
