from __future__ import annotations

import pytest
from app.config import settings
from app.db import SessionLocal
from app.models import AuditLog
from app.nrl.client import set_nrl_client
from app.seed import seed_users
from tests.test_nrl_api import FakeNrl
from tests.test_wizard import WIZARD, _project


@pytest.fixture
def fake_nrl():
    fake = FakeNrl()
    set_nrl_client(fake)
    yield fake
    set_nrl_client(None)


def _login_admin(client) -> None:
    settings.dev_bootstrap_admin = True
    db = SessionLocal()
    try:
        seed_users(db)
    finally:
        db.close()
    response = client.post("/api/login", json={"username": "admin", "password": "admin"})
    assert response.status_code == 200, response.text


def test_editor_cannot_read_audit_logs(client):
    assert client.post("/api/login", json={"username": "stub", "password": "stub"}).status_code == 200
    response = client.get("/api/admin/audit-logs")
    assert response.status_code == 403
    assert "관리자" in response.json()["detail"]


def test_admin_filters_audit_logs_and_sees_nrl_instconfig(client, fake_nrl):
    assert client.post("/api/login", json={"username": "stub", "password": "stub"}).status_code == 200
    first = _project(client)
    later = {
        **WIZARD,
        "nrl_later": True,
        "sensor_instconfig": None,
        "datalogger_instconfig": None,
    }
    created = client.post(f"/api/projects/{first['id']}/wizard", json=later)
    assert created.status_code == 200, created.text
    applied = client.post(
        f"/api/projects/{first['id']}/apply-nrl",
        json={
            "station": WIZARD["station"],
            "start_time": WIZARD["start_time"],
            "channels": ["00.BHZ"],
            "sensor_instconfig": WIZARD["sensor_instconfig"],
            "datalogger_instconfig": WIZARD["datalogger_instconfig"],
        },
    )
    assert applied.status_code == 200, applied.text
    second = _project(client)

    db = SessionLocal()
    try:
        db.add(
            AuditLog(
                project_id=None,
                actor="system",
                action="maintenance",
                target="database",
                summary="시스템 기록",
            )
        )
        db.commit()
    finally:
        db.close()

    _login_admin(client)
    response = client.get("/api/admin/audit-logs", params={"limit": 500})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] >= 5
    assert body["audit_logs"][0]["summary"] == "시스템 기록"
    assert body["audit_logs"][0]["project_id"] is None
    assert body["audit_logs"][0]["project_name"] is None

    filtered = client.get(
        "/api/admin/audit-logs", params={"project_id": first["id"], "limit": 500}
    )
    assert filtered.status_code == 200, filtered.text
    logs = filtered.json()["audit_logs"]
    assert filtered.json()["total"] == len(logs)
    assert logs
    assert {row["project_id"] for row in logs} == {first["id"]}
    assert {row["project_name"] for row in logs} == {first["name"]}
    nrl = next(row for row in logs if row["action"] == "nrl")
    assert nrl["details"] == (
        f"instconfig={WIZARD['sensor_instconfig']}:{WIZARD['datalogger_instconfig']}"
    )

    other = client.get("/api/admin/audit-logs", params={"project_id": second["id"]}).json()
    assert other["total"] == 1
    assert other["audit_logs"][0]["action"] == "create"

    limited = client.get("/api/admin/audit-logs", params={"limit": 1}).json()
    assert limited["total"] == body["total"]
    assert len(limited["audit_logs"]) == 1
