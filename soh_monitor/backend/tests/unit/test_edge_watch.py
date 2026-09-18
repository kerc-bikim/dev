"""Edge Heartbeat 감시·하위 장애 억제·토폴로지."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.auth.passwords import hash_password
from app.db.base import Base
from app.db.models import Device, EdgeCollector, Incident, IncidentStatus, User, UserRole
from app.db.seed import seed_default_profiles, seed_metric_definitions
from app.db.session import get_engine, reset_engine_cache, session_scope
from app.domain.enums import Severity

ADMIN_PASSWORD = "admin-pass-123"


def _client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("SOH_DATABASE_URL_OVERRIDE", f"sqlite:///{tmp_path}/watch.db")
    monkeypatch.setenv("SOH_SESSION_SECRET", "unit-test-session-secret")
    monkeypatch.setenv("SOH_APP_ENV", "development")
    monkeypatch.setenv("SOH_EDGE_HEARTBEAT_SECONDS", "30")
    from app.config.settings import get_settings

    get_settings.cache_clear()
    reset_engine_cache()
    engine = get_engine()
    Base.metadata.create_all(engine)
    with session_scope() as session:
        seed_metric_definitions(session)
        seed_default_profiles(session)
        session.add(
            User(
                username="admin",
                display_name="관리자",
                password_hash=hash_password(ADMIN_PASSWORD, n=2**10),
                role=UserRole.ADMIN,
                enabled=True,
            )
        )
    from app.api.app import create_app

    return TestClient(create_app())


def _setup_edge(client: TestClient) -> tuple[str, str]:
    assert client.post("/api/v1/auth/login", json={"username": "admin", "password": ADMIN_PASSWORD}).status_code == 200
    created = client.post("/api/v1/edges", json={"edgeCode": "edge-region-a-01", "name": "지역 A"}).json()["edge"]
    client.post(
        "/api/v1/edge/enroll",
        json={
            "edgeId": "edge-region-a-01",
            "enrollmentToken": created["enrollmentToken"],
            "agentVersion": "0.7.0",
            "installedAdapters": ["nanometrics.centaur.ctr"],
        },
    )
    station = client.post(
        "/api/v1/stations",
        json={"networkCode": "KS", "stationCode": "A01", "name": "시험", "latitude": 37.5, "longitude": 127.0},
    ).json()["station"]
    client.post(
        f"/api/v1/stations/{station['id']}/devices",
        json={
            "adapterKey": "nanometrics.centaur.ctr",
            "collectionMode": "EDGE",
            "edgeId": created["id"],
            "endpoint": {"hostname": "10.10.1.20", "scheme": "http"},
        },
    )
    return created["id"], station["id"]


def _age_heartbeat(edge_id: str, seconds: int) -> None:
    now = datetime.now(timezone.utc)
    with session_scope() as session:
        edge = session.get(EdgeCollector, uuid.UUID(edge_id))
        assert edge is not None
        seen = now - timedelta(seconds=seconds)
        edge.last_heartbeat_at = seen
        edge.last_upload_at = seen
        edge.registered_at = now - timedelta(hours=1)


def test_Heartbeat_2회_누락은_WARNING_3회는_CRITICAL(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    edge_id, station_id = _setup_edge(client)

    _age_heartbeat(edge_id, 60)
    listed = client.get("/api/v1/edges")
    assert listed.json()["edges"][0]["health"]["connectivityStatus"] == "WARNING"

    _age_heartbeat(edge_id, 90)
    listed = client.get("/api/v1/edges")
    body = listed.json()["edges"][0]
    assert body["status"] == "OFFLINE"
    assert body["health"]["connectivityStatus"] == "CRITICAL"

    stations = client.get("/api/v1/stations").json()["stations"]
    target = next(item for item in stations if item["id"] == station_id)
    assert target["edgeUnreachable"] is True
    assert target["categories"].get("connectivity") == "UNKNOWN"

    fleet = client.get("/api/v1/fleet/summary").json()
    assert fleet["openIncidents"] == 1
    incidents = client.get("/api/v1/incidents?status=open").json()["incidents"]
    assert any(item["metricKey"] == "edge.reachable" for item in incidents)

    topology = client.get("/api/v1/fleet/topology").json()
    found = False
    for region in topology["regions"]:
        for edge in region["edges"]:
            if edge["id"] == edge_id:
                found = True
                assert edge["status"] == "OFFLINE"
                assert any(station["edgeUnreachable"] for station in edge["stations"])
    if not found:
        match = next(item for item in topology["unassigned"]["edges"] if item["id"] == edge_id)
        assert match["status"] == "OFFLINE"


def test_미지원_Adapter_할당은_거부한다(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    assert client.post("/api/v1/auth/login", json={"username": "admin", "password": ADMIN_PASSWORD}).status_code == 200
    created = client.post("/api/v1/edges", json={"edgeCode": "edge-region-b-01", "name": "지역 B"}).json()["edge"]
    client.post(
        "/api/v1/edge/enroll",
        json={
            "edgeId": "edge-region-b-01",
            "enrollmentToken": created["enrollmentToken"],
            "agentVersion": "0.0.1",
            "installedAdapters": ["other.adapter"],
        },
    )
    station = client.post(
        "/api/v1/stations",
        json={"networkCode": "KS", "stationCode": "B01", "name": "시험B", "latitude": 36.0, "longitude": 128.0},
    ).json()["station"]
    denied = client.post(
        f"/api/v1/stations/{station['id']}/devices",
        json={
            "adapterKey": "nanometrics.centaur.ctr",
            "collectionMode": "EDGE",
            "edgeId": created["id"],
            "endpoint": {"hostname": "10.10.1.21", "scheme": "http"},
        },
    )
    assert denied.status_code == 409

    from app.config.settings import get_settings

    get_settings.cache_clear()
    reset_engine_cache()


def test_열린_장비_장애는_Edge_Offline_때_억제된다(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    edge_id, _station_id = _setup_edge(client)
    now = datetime.now(timezone.utc)
    with session_scope() as session:
        device = session.scalars(select(Device)).first()
        assert device is not None
        session.add(
            Incident(
                device_id=device.id,
                station_id=device.station_id,
                category="power",
                metric_key="power.system_voltage_v",
                dimension_value="",
                severity=Severity.CRITICAL,
                status=IncidentStatus.OPEN,
                title="전압 장애",
                first_observed_at=now,
                last_observed_at=now,
                suppressed_by_edge=False,
            )
        )
    _age_heartbeat(edge_id, 90)
    client.get("/api/v1/edges")
    fleet = client.get("/api/v1/fleet/summary").json()
    assert fleet["openIncidents"] == 1
    incidents = client.get("/api/v1/incidents?status=open").json()["incidents"]
    device_ones = [item for item in incidents if item["metricKey"] == "power.system_voltage_v"]
    assert device_ones and device_ones[0]["suppressedByEdge"] is True
    edge_ones = [item for item in incidents if item["metricKey"] == "edge.reachable"]
    assert edge_ones and edge_ones[0]["suppressedByEdge"] is False
