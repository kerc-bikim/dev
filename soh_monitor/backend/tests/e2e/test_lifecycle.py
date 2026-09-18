"""등록 → 수집 → 장애 → 복구. 관리 API 와 수집기가 같은 DB 를 본다."""
from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

from fastapi.testclient import TestClient
from httpx import ASGITransport
from sqlalchemy import select

from app.adapters.centaur_ctr.adapter import MANIFEST_PATH, CentaurCtrAdapter
from app.adapters.registry import AdapterRegistry
from app.auth.passwords import hash_password
from app.collector.scheduler import CollectorScheduler
from app.config.settings import Settings, get_settings
from app.db.base import Base
from app.db.models import Device, User, UserRole
from app.db.seed import seed_default_profiles, seed_metric_definitions
from app.db.session import get_engine, reset_engine_cache, session_scope
from app.domain.models import utcnow
from app.health.notifier import CollectingNotifier
from app.health.service import HealthService
from app.repository.influx.sink import InMemoryMetricSink

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from mock.centaur_mock.devices import DeviceRegistry, VirtualDevice  # noqa: E402
from mock.centaur_mock.scenarios import PayloadScenario, TransportScenario  # noqa: E402
from mock.centaur_mock.server import create_app as create_mock  # noqa: E402

ADMIN_PASSWORD = "admin-pass-123"
INSTRUMENT = "centaur-6__0901"


def _client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("SOH_DATABASE_URL_OVERRIDE", f"sqlite:///{tmp_path}/e2e.db")
    monkeypatch.setenv("SOH_SESSION_SECRET", "unit-test-session-secret")
    monkeypatch.setenv("SOH_APP_ENV", "development")
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


async def test_화면경로_등록_수집_장애_복구(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    assert client.post("/api/v1/auth/login", json={"username": "admin", "password": ADMIN_PASSWORD}).status_code == 200

    station = client.post(
        "/api/v1/stations",
        json={"networkCode": "KS", "stationCode": "E01", "name": "수명주기", "latitude": 37.5, "longitude": 127.0},
    )
    assert station.status_code == 201, station.text
    station_id = station.json()["station"]["id"]

    profile = client.post(
        "/api/v1/metric-profiles",
        json={
            "name": "수명주기 감시",
            "entries": [
                {
                    "metricKey": "storage.used_percent",
                    "warningCondition": {"op": ">=", "value": 80},
                    "criticalCondition": {"op": ">=", "value": 90},
                    "holdSeconds": 0,
                    "recoverySeconds": 0,
                }
            ],
        },
    )
    assert profile.status_code == 201, profile.text
    profile_id = profile.json()["profile"]["id"]

    device = client.post(
        f"/api/v1/stations/{station_id}/devices",
        json={
            "adapterKey": "nanometrics.centaur.ctr",
            "instrumentId": INSTRUMENT,
            "metricProfileId": profile_id,
            "endpoint": {"hostname": "10.10.9.1", "scheme": "http"},
        },
    )
    assert device.status_code == 201, device.text
    device_id = device.json()["device"]["id"]

    queued = client.post(f"/api/v1/devices/{device_id}/poll-now")
    assert queued.status_code == 202

    virtual = VirtualDevice(
        instrument_id=INSTRUMENT,
        station_code="E01",
        model="CTR4-6S",
        firmware_version="3.2.8",
        serial_number="0901",
        payload_scenario=PayloadScenario.NORMAL,
        transport_scenario=TransportScenario.OK,
    )
    mock = DeviceRegistry([virtual])
    registry = AdapterRegistry()
    registry.register(
        CentaurCtrAdapter(transport=ASGITransport(app=create_mock(mock))),
        manifest_path=MANIFEST_PATH,
    )
    scheduler = CollectorScheduler(
        session_scope,
        InMemoryMetricSink(),
        settings=Settings(app_env="test", max_concurrent_polls=2, poll_jitter_percent=0),
        registry=registry,
        owner="e2e",
        health=HealthService(notifier=CollectingNotifier()),
    )

    first = await scheduler.tick()
    assert first.succeeded == 1
    health = client.get(f"/api/v1/stations/{station_id}/current-health").json()
    assert health["overall"] in {"OK", "WARNING"}

    mock.update(INSTRUMENT, payload_scenario=PayloadScenario.STORE_FULL)
    with session_scope() as session:
        row = session.get(Device, __import__("uuid").UUID(device_id))
        assert row is not None
        row.next_poll_at = utcnow() - timedelta(seconds=1)
        session.commit()
    second = await scheduler.tick()
    assert second.succeeded == 1

    incidents = client.get("/api/v1/incidents?status=open").json()["incidents"]
    assert any(item["stationCode"] == "E01" and item["category"] == "storage" for item in incidents)

    mock.update(INSTRUMENT, payload_scenario=PayloadScenario.NORMAL)
    with session_scope() as session:
        session.get(Device, __import__("uuid").UUID(device_id)).next_poll_at = utcnow() - timedelta(seconds=1)
        session.commit()
    third = await scheduler.tick()
    assert third.succeeded == 1

    opened = client.get("/api/v1/incidents?status=open").json()["incidents"]
    storage = [item for item in opened if item["category"] == "storage" and item["stationCode"] == "E01"]
    assert storage == []

    reset_engine_cache()
    get_settings.cache_clear()
