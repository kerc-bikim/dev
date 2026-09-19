"""Edge·수집기 운영 Point 가 Grafana 알림이 기대하는 태그를 갖는지."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.domain.enums import Severity
from app.health.ops_points import (
    SCOPE_COLLECTOR,
    SCOPE_EDGE,
    certificate_severity,
    collector_point,
    edge_points,
    health_point,
)
from app.health.service import HEALTH_MEASUREMENT

NOW = datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc)


def test_health_point_는_scope와_severity만_필수다():
    point = health_point(
        scope=SCOPE_EDGE,
        category="connectivity",
        severity=Severity.CRITICAL,
        now=NOW,
        extra_tags={"edge_code": "edge-a"},
    )
    assert point.measurement == HEALTH_MEASUREMENT
    assert point.tags["scope"] == "edge"
    assert point.tags["category"] == "connectivity"
    assert point.fields["severity"] == Severity.CRITICAL.code
    assert point.fields["is_stale"] is False


def test_collector_point_실패는_CRITICAL이다():
    ok = collector_point(NOW, success=True)
    bad = collector_point(NOW, success=False, failed_writes=3)
    assert ok.tags["scope"] == SCOPE_COLLECTOR
    assert ok.fields["severity"] == Severity.OK.code
    assert bad.fields["severity"] == Severity.CRITICAL.code
    assert bad.fields["failed_writes"] == 3


def test_edge_points_는_기록계_태그를_넣지_않는다():
    edge = SimpleNamespace(
        id=uuid.uuid4(),
        edge_code="edge-region-a-01",
        region_id=None,
        software_version="0.8.0",
        revoked_at=None,
        certificate_expires_at=NOW + timedelta(days=90),
        spool_used_bytes=4_500_000_000,
        spool_limit_bytes=5_000_000_000,
    )
    state = SimpleNamespace(
        connectivity_status=Severity.WARNING,
        spool_status=Severity.CRITICAL,
        collector_status=Severity.OK,
        pending_batches=12,
        oldest_pending_age_seconds=90.0,
    )
    points = edge_points(edge, state, NOW)
    assert {p.tags["category"] for p in points} >= {"connectivity", "storage", "device"}
    for point in points:
        assert point.tags["scope"] == SCOPE_EDGE
        assert "device_id" not in point.tags
        assert "station_code" not in point.tags
        assert point.tags["edge_code"] == "edge-region-a-01"
    storage = next(p for p in points if p.tags["category"] == "storage")
    assert storage.fields["severity"] == Severity.CRITICAL.code
    assert storage.fields["spool_used_percent"] == 90.0


def test_폐기된_인증서는_CRITICAL이다():
    edge = SimpleNamespace(
        revoked_at=NOW,
        certificate_expires_at=NOW + timedelta(days=30),
    )
    assert certificate_severity(edge, NOW) is Severity.CRITICAL
