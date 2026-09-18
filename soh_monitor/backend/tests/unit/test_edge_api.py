"""Edge 관리·프로토콜 API 시험."""
from __future__ import annotations

import gzip
import json
import uuid

from fastapi.testclient import TestClient

from app.auth.passwords import hash_password
from app.db.base import Base
from app.db.models import User, UserRole
from app.db.seed import seed_default_profiles, seed_metric_definitions
from app.db.session import get_engine, reset_engine_cache, session_scope

ADMIN_PASSWORD = "admin-pass-123"
VIEWER_PASSWORD = "viewer-pass-123"


def _client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("SOH_DATABASE_URL_OVERRIDE", f"sqlite:///{tmp_path}/edge.db")
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
        session.add(
            User(
                username="viewer",
                display_name="조회자",
                password_hash=hash_password(VIEWER_PASSWORD, n=2**10),
                role=UserRole.VIEWER,
                enabled=True,
            )
        )
    from app.api.app import create_app

    return TestClient(create_app())


def login(client: TestClient, username: str = "admin", password: str = ADMIN_PASSWORD) -> None:
    response = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text


def test_VIEWER는_Edge를_만들_수_없다(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    login(client, "viewer", VIEWER_PASSWORD)
    response = client.post("/api/v1/edges", json={"edgeCode": "edge-a", "name": "지역 A"})
    assert response.status_code == 403


def test_등록_Token은_한_번만_유효하다(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    login(client)
    created = client.post("/api/v1/edges", json={"edgeCode": "edge-region-a-01", "name": "지역 A"})
    assert created.status_code == 201, created.text
    token = created.json()["edge"]["enrollmentToken"]
    assert token
    listed = client.get("/api/v1/edges")
    assert listed.status_code == 200
    assert listed.json()["edges"][0]["hasEnrollmentToken"] is True

    enrolled = client.post(
        "/api/v1/edge/enroll",
        json={
            "edgeId": "edge-region-a-01",
            "enrollmentToken": token,
            "agentVersion": "0.7.0",
            "installedAdapters": ["nanometrics.centaur.ctr"],
        },
    )
    assert enrolled.status_code == 200, enrolled.text
    body = enrolled.json()
    assert body["clientToken"]
    assert "BEGIN CERTIFICATE" in body["certificate"]

    reused = client.post(
        "/api/v1/edge/enroll",
        json={"edgeId": "edge-region-a-01", "enrollmentToken": token, "agentVersion": "0.7.0"},
    )
    assert reused.status_code == 409

    listed = client.get("/api/v1/edges")
    assert listed.json()["edges"][0]["hasEnrollmentToken"] is False

    from app.config.settings import get_settings

    get_settings.cache_clear()
    reset_engine_cache()


def test_설정_동기와_Batch_멱등_ACK(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    login(client)
    created = client.post("/api/v1/edges", json={"edgeCode": "edge-region-a-01", "name": "지역 A"}).json()["edge"]
    token = created["enrollmentToken"]
    edge_id = created["id"]
    enrolled = client.post(
        "/api/v1/edge/enroll",
        json={"edgeId": "edge-region-a-01", "enrollmentToken": token, "agentVersion": "0.7.0"},
    ).json()
    bearer = {"Authorization": f"Bearer {enrolled['clientToken']}"}

    station = client.post(
        "/api/v1/stations",
        json={"networkCode": "KS", "stationCode": "A01", "name": "시험", "latitude": 37.5, "longitude": 127.0},
    ).json()["station"]
    device = client.post(
        f"/api/v1/stations/{station['id']}/devices",
        json={
            "adapterKey": "nanometrics.centaur.ctr",
            "collectionMode": "EDGE",
            "edgeId": edge_id,
            "endpoint": {"hostname": "10.10.1.20", "scheme": "http"},
        },
    )
    assert device.status_code == 201, device.text

    config = client.get("/api/v1/edge/config", headers=bearer, params={"currentVersion": 0})
    assert config.status_code == 200, config.text
    document = config.json()["config"]
    assert document["edgeId"] == "edge-region-a-01"
    assert document["devices"][0]["stationCode"] == "A01"

    unchanged = client.get("/api/v1/edge/config", headers=bearer, params={"currentVersion": document["configVersion"]})
    assert unchanged.json()["unchanged"] is True

    device_id = document["devices"][0]["deviceId"]
    batch = {
        "edgeId": "edge-region-a-01",
        "batchId": str(uuid.uuid4()),
        "configVersion": document["configVersion"],
        "firstSequence": 1,
        "lastSequence": 1,
        "polls": [
            {
                "pollId": str(uuid.uuid4()),
                "sequence": 1,
                "deviceId": device_id,
                "observedAt": "2026-09-18T00:05:00Z",
                "success": True,
                "samples": [{"metricKey": "connectivity.reachable", "valueBool": True}],
            }
        ],
    }
    raw = gzip.compress(json.dumps(batch).encode("utf-8"))
    first = client.post(
        "/api/v1/edge/ingest/batches",
        content=raw,
        headers={**bearer, "Content-Type": "application/gzip"},
    )
    assert first.status_code == 200, first.text
    assert first.json()["accepted"] is True
    assert first.json()["duplicate"] is False

    second = client.post(
        "/api/v1/edge/ingest/batches",
        content=raw,
        headers={**bearer, "Content-Type": "application/gzip"},
    )
    assert second.status_code == 200, second.text
    assert second.json()["duplicate"] is True

    from app.config.settings import get_settings

    get_settings.cache_clear()
    reset_engine_cache()


def test_연결_시험은_EDGE_장비에서_원격_작업으로_넘어간다(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    login(client)
    created = client.post("/api/v1/edges", json={"edgeCode": "edge-region-a-01", "name": "지역 A"}).json()["edge"]
    token = created["enrollmentToken"]
    edge_id = created["id"]
    enrolled = client.post(
        "/api/v1/edge/enroll",
        json={"edgeId": "edge-region-a-01", "enrollmentToken": token},
    ).json()
    bearer = {"Authorization": f"Bearer {enrolled['clientToken']}"}

    station = client.post(
        "/api/v1/stations",
        json={"networkCode": "KS", "stationCode": "B01", "name": "시험2", "latitude": 36.0, "longitude": 128.0},
    ).json()["station"]
    device = client.post(
        f"/api/v1/stations/{station['id']}/devices",
        json={
            "adapterKey": "nanometrics.centaur.ctr",
            "collectionMode": "EDGE",
            "edgeId": edge_id,
            "endpoint": {"hostname": "10.10.1.21", "scheme": "http"},
        },
    ).json()["device"]

    probed = client.post(f"/api/v1/devices/{device['id']}/test-connection")
    assert probed.status_code == 200, probed.text
    assert probed.json()["queued"] is True
    task_id = probed.json()["taskId"]

    beat = client.post(
        "/api/v1/edge/heartbeat",
        headers=bearer,
        json={
            "edgeId": "edge-region-a-01",
            "agentVersion": "0.7.0",
            "configVersion": 1,
            "spool": {"usedBytes": 12, "limitBytes": 1000, "pending": 1},
            "health": {"cpuPercent": 3.0, "memoryPercent": 20.0, "diskPercent": 11.0},
        },
    )
    assert beat.status_code == 200, beat.text
    tasks = beat.json()["tasks"]
    assert tasks and tasks[0]["id"] == task_id
    assert tasks[0]["type"] == "test_connection"

    done = client.post(
        f"/api/v1/edge/tasks/{task_id}/result",
        headers=bearer,
        json={"ok": True, "reachable": True, "message": "연결됐다"},
    )
    assert done.status_code == 200, done.text
    health = client.get(f"/api/v1/edges/{edge_id}/health")
    assert health.status_code == 200
    assert health.json()["edge"]["lastHeartbeatAt"] is not None

    from app.config.settings import get_settings

    get_settings.cache_clear()
    reset_engine_cache()
