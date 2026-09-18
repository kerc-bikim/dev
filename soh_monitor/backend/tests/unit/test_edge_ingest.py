"""M8 Ingest 멱등·크기 제한·지연 도달."""
from __future__ import annotations

import gzip
import json
import uuid
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.auth.passwords import hash_password
from app.db.base import Base
from app.db.models import DeviceRuntimeState, User, UserRole
from app.db.seed import seed_default_profiles, seed_metric_definitions
from app.db.session import get_engine, reset_engine_cache, session_scope
from app.repository.influx.sink import InMemoryMetricSink

ADMIN_PASSWORD = "admin-pass-123"


def _client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("SOH_DATABASE_URL_OVERRIDE", f"sqlite:///{tmp_path}/ingest.db")
    monkeypatch.setenv("SOH_SESSION_SECRET", "unit-test-session-secret")
    monkeypatch.setenv("SOH_APP_ENV", "development")
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

    app = create_app()
    app.state.ingest_sink = InMemoryMetricSink()
    return TestClient(app)


def _login(client: TestClient) -> None:
    assert client.post("/api/v1/auth/login", json={"username": "admin", "password": ADMIN_PASSWORD}).status_code == 200


def _enrolled_edge(client: TestClient) -> tuple[str, dict, str]:
    created = client.post("/api/v1/edges", json={"edgeCode": "edge-region-a-01", "name": "지역 A"}).json()["edge"]
    enrolled = client.post(
        "/api/v1/edge/enroll",
        json={
            "edgeId": "edge-region-a-01",
            "enrollmentToken": created["enrollmentToken"],
            "agentVersion": "0.7.0",
            "installedAdapters": ["nanometrics.centaur.ctr"],
        },
    ).json()
    station = client.post(
        "/api/v1/stations",
        json={"networkCode": "KS", "stationCode": "A01", "name": "시험", "latitude": 37.5, "longitude": 127.0},
    ).json()["station"]
    device = client.post(
        f"/api/v1/stations/{station['id']}/devices",
        json={
            "adapterKey": "nanometrics.centaur.ctr",
            "collectionMode": "EDGE",
            "edgeId": created["id"],
            "endpoint": {"hostname": "10.10.1.20", "scheme": "http"},
        },
    ).json()["device"]
    bearer = {"Authorization": f"Bearer {enrolled['clientToken']}"}
    return device["id"], bearer, created["id"]


def _post_batch(client: TestClient, bearer: dict, batch: dict) -> object:
    raw = gzip.compress(json.dumps(batch).encode("utf-8"))
    return client.post(
        "/api/v1/edge/ingest/batches",
        content=raw,
        headers={**bearer, "Content-Type": "application/gzip"},
    )


def _poll(device_id: str, sequence: int, observed_at: str, *, success: bool = True, extra: dict | None = None) -> dict:
    body = {
        "pollId": str(uuid.uuid4()),
        "sequence": sequence,
        "deviceId": device_id,
        "adapterKey": "nanometrics.centaur.ctr",
        "observedAt": observed_at,
        "success": success,
        "samples": [{"metricKey": "connectivity.reachable", "valueBool": success}],
    }
    if extra:
        body.update(extra)
    return body


def test_과대_Batch는_413(tmp_path, monkeypatch):
    monkeypatch.setenv("SOH_EDGE_INGEST_MAX_BYTES", "64")
    client = _client(tmp_path, monkeypatch)
    _login(client)
    _, bearer, _ = _enrolled_edge(client)
    huge = b"x" * 200
    response = client.post(
        "/api/v1/edge/ingest/batches",
        content=huge,
        headers={**bearer, "Content-Type": "application/gzip"},
    )
    assert response.status_code == 413


def test_같은_Batch_세_번은_Point_수가_변하지_않는다(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    _login(client)
    device_id, bearer, _ = _enrolled_edge(client)
    batch = {
        "edgeId": "edge-region-a-01",
        "batchId": str(uuid.uuid4()),
        "configVersion": 1,
        "firstSequence": 1,
        "lastSequence": 1,
        "polls": [_poll(device_id, 1, "2026-09-18T00:05:00Z")],
    }
    first = _post_batch(client, bearer, batch)
    assert first.status_code == 200, first.text
    assert first.json()["duplicate"] is False
    sink: InMemoryMetricSink = client.app.state.ingest_sink
    count = len(sink.points)
    assert count > 0
    for _ in range(2):
        again = _post_batch(client, bearer, batch)
        assert again.status_code == 200
        assert again.json()["duplicate"] is True
    assert len(sink.points) == count


def test_다른_batch_같은_sequence는_건너뛴다(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    _login(client)
    device_id, bearer, _ = _enrolled_edge(client)
    first = {
        "edgeId": "edge-region-a-01",
        "batchId": str(uuid.uuid4()),
        "firstSequence": 1,
        "lastSequence": 1,
        "polls": [_poll(device_id, 1, "2026-09-18T00:05:00Z")],
    }
    assert _post_batch(client, bearer, first).status_code == 200
    sink: InMemoryMetricSink = client.app.state.ingest_sink
    after_first = len(sink.points)
    second = {
        "edgeId": "edge-region-a-01",
        "batchId": str(uuid.uuid4()),
        "firstSequence": 1,
        "lastSequence": 2,
        "polls": [
            _poll(device_id, 1, "2026-09-18T00:06:00Z"),
            _poll(device_id, 2, "2026-09-18T00:07:00Z"),
        ],
    }
    body = _post_batch(client, bearer, second).json()
    assert body["written"] == 1
    assert body["skippedDuplicate"] == 1
    assert len(sink.points) > after_first


def test_늦은_데이터는_시계열만_채우고_현재_상태를_되돌리지_않는다(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    _login(client)
    device_id, bearer, _ = _enrolled_edge(client)
    newer = {
        "edgeId": "edge-region-a-01",
        "batchId": str(uuid.uuid4()),
        "firstSequence": 2,
        "lastSequence": 2,
        "polls": [_poll(device_id, 2, "2026-09-18T12:00:00Z")],
    }
    older = {
        "edgeId": "edge-region-a-01",
        "batchId": str(uuid.uuid4()),
        "firstSequence": 1,
        "lastSequence": 1,
        "polls": [_poll(device_id, 1, "2026-09-17T12:00:00Z")],
    }
    assert _post_batch(client, bearer, newer).json()["delayed"] == 0
    delayed = _post_batch(client, bearer, older).json()
    assert delayed["written"] == 1
    assert delayed["delayed"] == 1
    sink: InMemoryMetricSink = client.app.state.ingest_sink
    times = [point.timestamp for point in sink.points if point.timestamp is not None]
    assert datetime(2026, 9, 17, 12, tzinfo=timezone.utc) in times
    with session_scope() as session:
        runtime = session.get(DeviceRuntimeState, uuid.UUID(device_id))
        assert runtime is not None
        observed = runtime.last_observed_at
        if observed.tzinfo is None:
            observed = observed.replace(tzinfo=timezone.utc)
        assert observed == datetime(2026, 9, 18, 12, tzinfo=timezone.utc)


def test_폐기된_Edge_와_틀린_인증서는_403(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    _login(client)
    device_id, bearer, edge_id = _enrolled_edge(client)
    wrong = client.post(
        "/api/v1/edge/heartbeat",
        headers={**bearer, "X-Edge-Certificate-Serial": "other-serial"},
        json={"edgeId": "edge-region-a-01", "agentVersion": "0.7.0", "health": {}},
    )
    assert wrong.status_code == 403
    revoked = client.post(f"/api/v1/edges/{edge_id}/revoke")
    assert revoked.status_code == 200
    assert revoked.json()["edge"]["status"] == "DISABLED"
    blocked = _post_batch(
        client,
        bearer,
        {
            "edgeId": "edge-region-a-01",
            "batchId": str(uuid.uuid4()),
            "firstSequence": 1,
            "lastSequence": 1,
            "polls": [_poll(device_id, 1, "2026-09-18T00:05:00Z")],
        },
    )
    assert blocked.status_code == 403

    from app.config.settings import get_settings

    get_settings.cache_clear()
    reset_engine_cache()
