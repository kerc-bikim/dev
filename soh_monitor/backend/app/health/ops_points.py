"""Edge·수집기 자체 상태를 Grafana 가 볼 수 있게 recorder_health 로 옮긴다.

기록계 판정은 HealthService 가 만든다. 여기는 수집 경로 자체다.
임계값은 이미 백엔드가 정한 severity 만 나간다. Grafana 는 그 숫자만 감시한다.

scope
  * device    — 기록계 (HealthService)
  * edge      — Edge Collector
  * collector — 중앙 수집기 / Influx 쓰기
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import EdgeCollector, EdgeRuntimeState
from app.domain.enums import Severity
from app.health.service import HEALTH_MEASUREMENT
from app.repository.influx.points import PointSpec
from app.repository.influx.sink import MetricSink
from app.repository.postgres.collector_repo import as_utc

SCOPE_DEVICE = "device"
SCOPE_EDGE = "edge"
SCOPE_COLLECTOR = "collector"


def health_point(
    *,
    scope: str,
    category: str,
    severity: Severity,
    now: datetime,
    extra_tags: dict[str, str] | None = None,
    extra_fields: dict[str, Any] | None = None,
    is_stale: bool = False,
) -> PointSpec:
    tags = {"scope": scope, "category": category}
    if extra_tags:
        tags.update({key: value for key, value in extra_tags.items() if value})
    fields: dict[str, Any] = {"severity": severity.code, "is_stale": is_stale}
    if extra_fields:
        fields.update(extra_fields)
    return PointSpec(
        measurement=HEALTH_MEASUREMENT,
        tags=tags,
        fields=fields,
        timestamp=now,
    )


def certificate_days_remaining(edge: EdgeCollector, now: datetime) -> float | None:
    expires = as_utc(edge.certificate_expires_at)
    if expires is None:
        return None
    return (expires - now).total_seconds() / 86400.0


def certificate_severity(edge: EdgeCollector, now: datetime) -> Severity:
    if edge.revoked_at is not None:
        return Severity.CRITICAL
    days = certificate_days_remaining(edge, now)
    if days is None:
        return Severity.UNKNOWN
    if days < 0:
        return Severity.CRITICAL
    if days < 14:
        return Severity.WARNING
    return Severity.OK


def _spool_percent(edge: EdgeCollector) -> float | None:
    used = edge.spool_used_bytes
    limit = edge.spool_limit_bytes
    if used is None or not limit:
        return None
    return min(100.0, max(0.0, (used / limit) * 100.0))


def edge_tags(edge: EdgeCollector) -> dict[str, str]:
    tags = {"edge_id": str(edge.id), "edge_code": edge.edge_code}
    if edge.region_id is not None:
        tags["region"] = str(edge.region_id)
    if edge.software_version:
        tags["software_version"] = edge.software_version
    return tags


def edge_points(edge: EdgeCollector, state: EdgeRuntimeState, now: datetime) -> list[PointSpec]:
    """Heartbeat·평가 결과를 Grafana 알림이 읽는 형태로 만든다."""
    tags = edge_tags(edge)
    spool_fields: dict[str, Any] = {}
    percent = _spool_percent(edge)
    if percent is not None:
        spool_fields["spool_used_percent"] = percent
    if state.pending_batches is not None:
        spool_fields["pending_batches"] = int(state.pending_batches)
    if state.oldest_pending_age_seconds is not None:
        spool_fields["oldest_pending_age_seconds"] = float(state.oldest_pending_age_seconds)

    cert_fields: dict[str, Any] = {}
    days = certificate_days_remaining(edge, now)
    if days is not None:
        cert_fields["certificate_days_remaining"] = days

    return [
        health_point(
            scope=SCOPE_EDGE,
            category="connectivity",
            severity=state.connectivity_status,
            now=now,
            extra_tags=tags,
        ),
        health_point(
            scope=SCOPE_EDGE,
            category="storage",
            severity=state.spool_status,
            now=now,
            extra_tags=tags,
            extra_fields=spool_fields or None,
        ),
        health_point(
            scope=SCOPE_EDGE,
            category="device",
            severity=state.collector_status,
            now=now,
            extra_tags=tags,
            extra_fields=cert_fields or None,
        ),
        health_point(
            scope=SCOPE_EDGE,
            category="timing",
            severity=certificate_severity(edge, now),
            now=now,
            extra_tags=tags,
            extra_fields=cert_fields or None,
        ),
    ]


def collector_point(
    now: datetime,
    *,
    success: bool,
    failed_writes: int = 0,
    dropped_points: int = 0,
) -> PointSpec:
    severity = Severity.OK if success else Severity.CRITICAL
    return health_point(
        scope=SCOPE_COLLECTOR,
        category="connectivity",
        severity=severity,
        now=now,
        extra_tags={"collector": "central"},
        extra_fields={
            "failed_writes": int(failed_writes),
            "dropped_points": int(dropped_points),
        },
    )


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def points_for_edges(session: Session, now: datetime) -> list[PointSpec]:
    points: list[PointSpec] = []
    for edge in session.scalars(select(EdgeCollector)):
        state = session.get(EdgeRuntimeState, edge.id)
        if state is None:
            continue
        points.extend(edge_points(edge, state, now))
    return points


def write_ops_health(
    session: Session,
    sink: MetricSink,
    now: datetime,
    *,
    write_success: bool,
    failed_writes: int = 0,
    dropped_points: int = 0,
    evaluate_edges: bool = True,
) -> list[PointSpec]:
    """Edge 평가 결과와 수집기 쓰기 상태를 한 번에 적재한다."""
    if evaluate_edges:
        from app.health.edge_watch import evaluate_all

        evaluate_all(session, now=now)
    points = points_for_edges(session, now)
    points.append(
        collector_point(
            now,
            success=write_success,
            failed_writes=failed_writes,
            dropped_points=dropped_points,
        )
    )
    sink.write(points)
    return points
