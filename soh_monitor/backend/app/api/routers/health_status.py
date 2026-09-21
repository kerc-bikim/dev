"""현재 상태와 장애 조회.

화면은 InfluxDB 를 조회하지 않고 이 API 로 현재 상태를 받는다. 시계열은 추세를 보는
용도이고, "지금 어떤가" 는 판정 결과 표에서 읽는 편이 빠르고 정확하다.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import desc, func, select

from app.api.deps import RequireOperate, RequireRead
from app.db.models import (
    CollectionMode,
    Device,
    DeviceRuntimeState,
    EdgeCollector,
    HealthState,
    Incident,
    IncidentEvent,
    IncidentStatus,
    Region,
    Station,
    User,
)
from app.db.session import session_scope
from app.domain.enums import Severity
from app.health import incidents as incident_ops
from app.health.collection import collected_severity
from app.health.state_machine import rollup
from app.repository.postgres.collector_repo import as_utc

router = APIRouter(prefix="/api/v1", tags=["health"])


def _parse_uuid(value: str, label: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"{label} 형식이 잘못됐다") from exc


@router.get("/fleet/summary", summary="전체 현황")
def fleet_summary(actor: RequireRead) -> dict[str, object]:
    with session_scope() as session:
        from app.health.edge_watch import evaluate_all

        evaluate_all(session)
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
                .where(
                    Incident.status.in_(incident_ops.OPEN_STATUSES),
                    Incident.suppressed_by_edge.is_(False),
                )
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
def device_health(device_id: str, actor: RequireRead) -> dict[str, object]:
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
        if not device.enabled:
            categories = {
                key: {**value, "severity": Severity.DISABLED.value} for key, value in categories.items()
            }
            if not categories:
                categories["connectivity"] = {
                    "severity": Severity.DISABLED.value,
                    "isStale": False,
                    "evaluatedAt": None,
                    "detail": {"reason": "수집 비활성"},
                }
            metrics = [{**item, "severity": Severity.DISABLED.value} for item in metrics]

        return {
            "deviceId": device_id,
            "stationCode": station.station_code if station else None,
            "overall": collected_severity(device.enabled, overall),
            "lastSuccessAt": as_utc(runtime.last_success_at) if runtime else None,
            "lastPollAt": as_utc(runtime.last_poll_at) if runtime else None,
            "consecutiveFailures": runtime.consecutive_failures if runtime else 0,
            "categories": categories,
            "metrics": sorted(metrics, key=lambda item: item["metricKey"]),
        }


@router.get("/incidents", summary="장애 목록")
def list_incidents(
    actor: RequireRead,
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
        actor_ids = {incident.acknowledged_by for incident in incidents if incident.acknowledged_by}
        actor_names = (
            {
                user.id: user.display_name
                for user in session.scalars(select(User).where(User.id.in_(actor_ids)))
            }
            if actor_ids
            else {}
        )

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
                    "acknowledgedBy": actor_names.get(incident.acknowledged_by) if incident.acknowledged_by else None,
                    "worstValue": incident.worst_value,
                    "thresholdValue": incident.threshold_value,
                    "maintenanceRelated": incident.maintenance_related,
                    "suppressedByEdge": incident.suppressed_by_edge,
                    "edgeId": str(incident.edge_id) if incident.edge_id else None,
                    "detail": incident.detail or {},
                }
                for incident in incidents
            ]
        }


@router.post("/incidents/{incident_id}/acknowledge", summary="장애 확인")
def acknowledge_incident(incident_id: str, actor: RequireOperate, message: str = "") -> dict[str, object]:
    identifier = _parse_uuid(incident_id, "장애 식별자")

    with session_scope() as session:
        incident = incident_ops.acknowledge(
            session,
            identifier,
            actor_id=actor.id,
            occurred_at=datetime.now(timezone.utc),
            message=message,
        )
        if incident is None:
            raise HTTPException(status_code=404, detail="확인할 수 있는 장애가 아니다")

        return {
            "incidentId": incident_id,
            "status": incident.status.value,
            "acknowledgedAt": as_utc(incident.acknowledged_at),
            "acknowledgedBy": actor.display_name,
        }


@router.get("/incidents/{incident_id}/events", summary="장애 이력")
def incident_events(incident_id: str, actor: RequireRead) -> dict[str, object]:
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

        actor_ids = {event.actor_id for event in events if event.actor_id}
        actor_names = (
            {
                user.id: user.display_name
                for user in session.scalars(select(User).where(User.id.in_(actor_ids)))
            }
            if actor_ids
            else {}
        )

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
                    "actorName": actor_names.get(event.actor_id) if event.actor_id else None,
                }
                for event in events
            ],
        }


@router.get("/fleet/topology", summary="지역 → Edge → 관측소 계층")
def fleet_topology(actor: RequireRead) -> dict[str, object]:
    with session_scope() as session:
        from app.health.edge_watch import EDGE_UNREACHABLE, evaluate_all

        evaluate_all(session)
        regions = session.scalars(select(Region).order_by(Region.region_code)).all()
        edges = session.scalars(select(EdgeCollector).order_by(EdgeCollector.edge_code)).all()
        stations = session.scalars(select(Station).order_by(Station.network_code, Station.station_code)).all()
        devices = session.scalars(select(Device)).all()
        category_states = session.scalars(select(HealthState).where(HealthState.metric_key == "")).all()
        by_device: dict = {}
        for state in category_states:
            by_device.setdefault(state.device_id, {})[state.category] = state.severity
        unreachable_devices = {
            state.device_id
            for state in session.scalars(
                select(HealthState).where(
                    HealthState.metric_key == "connectivity.reachable",
                    HealthState.value_text == EDGE_UNREACHABLE,
                )
            )
        }
        devices_by_station: dict = {}
        for device in devices:
            devices_by_station.setdefault(device.station_id, []).append(device)

        def station_node(station: Station) -> dict:
            members = devices_by_station.get(station.id, [])
            cats = []
            edge_unreachable = False
            modes: set[str] = set()
            for device in members:
                cats.extend(by_device.get(device.id, {}).values())
                modes.add(device.collection_mode.value)
                if device.id in unreachable_devices:
                    edge_unreachable = True
            return {
                "id": str(station.id),
                "stationCode": station.station_code,
                "networkCode": station.network_code,
                "name": station.name,
                "worstSeverity": rollup(cats).value if cats else None,
                "edgeUnreachable": edge_unreachable,
                "collectionMode": next(iter(modes)) if len(modes) == 1 else ("MIXED" if modes else None),
            }

        stations_by_edge: dict = {}
        for station in stations:
            members = devices_by_station.get(station.id, [])
            edge_ids = {
                device.edge_id
                for device in members
                if device.collection_mode is CollectionMode.EDGE and device.edge_id
            }
            for edge_id in edge_ids:
                stations_by_edge.setdefault(edge_id, []).append(station)

        def edge_node(edge: EdgeCollector) -> dict:
            return {
                "id": str(edge.id),
                "edgeCode": edge.edge_code,
                "name": edge.name,
                "status": edge.status.value,
                "softwareVersion": edge.software_version,
                "lastHeartbeatAt": as_utc(edge.last_heartbeat_at),
                "stations": [station_node(station) for station in stations_by_edge.get(edge.id, [])],
            }

        edges_by_region: dict = {}
        unregioned_edges = []
        for edge in edges:
            payload = edge_node(edge)
            if edge.region_id:
                edges_by_region.setdefault(edge.region_id, []).append(payload)
            else:
                unregioned_edges.append(payload)

        covered: set[str] = set()
        region_payloads = []
        for region in regions:
            region_edges = edges_by_region.get(region.id, [])
            covered_here = {node["id"] for item in region_edges for node in item["stations"]}
            covered.update(covered_here)
            region_payloads.append(
                {
                    "id": str(region.id),
                    "regionCode": region.region_code,
                    "name": region.name,
                    "edges": region_edges,
                    "stationsWithoutEdge": [
                        station_node(station)
                        for station in stations
                        if station.region_id == region.id and str(station.id) not in covered_here
                    ],
                }
            )
        unregioned_stations = [
            station_node(station)
            for station in stations
            if station.region_id is None and str(station.id) not in covered
        ]
        return {
            "regions": region_payloads,
            "unassigned": {"edges": unregioned_edges, "stations": unregioned_stations},
        }
