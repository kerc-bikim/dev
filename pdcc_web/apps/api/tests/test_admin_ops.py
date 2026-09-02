from __future__ import annotations

from app.config import settings
from app.db import SessionLocal
from app.inventory.collab import get_draft
from app.models import User
from app.nrl.client import set_nrl_client
from app.seed import seed_users
from sqlalchemy import select
from tests.test_nrl_api import FakeNrl
from tests.test_nrl_cache import ScriptedNrl
from tests.test_wizard import WIZARD, _project

import pytest


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
    ok = client.post("/api/login", json={"username": "admin", "password": "admin"})
    assert ok.status_code == 200, ok.text


def _login(client, username: str, password: str) -> None:
    ok = client.post("/api/login", json={"username": username, "password": password})
    assert ok.status_code == 200, ok.text


def test_editor_cannot_use_admin_ops(client, fake_nrl):
    _login(client, "stub", "stub")
    assert client.get("/api/admin/jobs").status_code == 403
    assert client.get("/api/admin/system").status_code == 403
    assert client.post("/api/nrl/catalog/refresh").status_code == 403
    denied = client.post(
        "/api/admin/locks/unlock",
        json={"station_path": "sta:1:YZ.TEST1#2009", "reason": "테스트"},
    )
    assert denied.status_code == 403


def test_admin_catalog_refresh_and_cache_first(client, monkeypatch):
    nrl = ScriptedNrl()
    set_nrl_client(nrl)
    try:
        _login_admin(client)
        first = client.get("/api/nrl/elements")
        assert first.status_code == 200
        live_after_first = nrl.live_gets
        assert live_after_first >= 1

        refreshed = client.post("/api/nrl/catalog/refresh")
        assert refreshed.status_code == 200, refreshed.text
        assert "sensor" in refreshed.json()["elements"]
        assert refreshed.json()["prefix_count"] >= 1
        assert nrl.live_gets > live_after_first

        switched = client.post("/api/nrl/mode", json={"mode": "cache-first"})
        assert switched.status_code == 200, switched.text
        assert switched.json()["mode"] == "cache-first"

        after_mode = nrl.live_gets
        nrl.down = True
        cached = client.get("/api/nrl/elements")
        assert cached.status_code == 200, cached.text
        assert "sensor" in cached.json()["elements"]
        assert nrl.live_gets == after_mode
    finally:
        set_nrl_client(None)
        settings.dev_bootstrap_admin = False
        settings.nrl_mode = "online"


def test_force_unlock_requires_reason_notifies_and_keeps_draft(client, fake_nrl):
    _login(client, "stub", "stub")
    project = _project(client)
    created = client.post(f"/api/projects/{project['id']}/wizard", json=WIZARD)
    assert created.status_code == 200, created.text
    path = created.json()["station_path"]
    locked = client.post(
        f"/api/projects/{project['id']}/lock", params={"station_path": path}
    )
    assert locked.status_code == 200, locked.text
    drafted = client.put(
        f"/api/projects/{project['id']}/draft",
        json={"station": "TEST1", "start_time": "2009-04-10T00:00:00", "latitude": 10.5},
    )
    assert drafted.status_code == 200, drafted.text

    _login_admin(client)
    blank = client.post(
        "/api/admin/locks/unlock", json={"station_path": path, "reason": " "}
    )
    assert blank.status_code == 400
    missing = client.post("/api/admin/locks/unlock", json={"station_path": path})
    assert missing.status_code == 422
    unlocked = client.post(
        "/api/admin/locks/unlock",
        json={"station_path": path, "reason": "편집자 부재"},
    )
    assert unlocked.status_code == 200, unlocked.text
    assert unlocked.json()["draft_kept"] is True

    db = SessionLocal()
    try:
        stub = db.scalar(select(User).where(User.username == "stub"))
        assert stub is not None
        draft = get_draft(db, project["id"], stub.id)
        assert draft is not None
        assert ">10.5<" in draft.xml_text or "10.5" in draft.xml_text
    finally:
        db.close()

    _login(client, "stub", "stub")
    notices = client.get("/api/notices")
    assert notices.status_code == 200, notices.text
    messages = [row["message"] for row in notices.json()["notices"]]
    assert "관리자가 잠금을 해제했습니다" in messages
    notice_id = notices.json()["notices"][0]["id"]
    acked = client.post(f"/api/notices/{notice_id}/ack")
    assert acked.status_code == 200
    assert acked.json()["notices"] == []


def test_admin_jobs_filter_log_and_cancel(client, fake_nrl):
    _login(client, "stub", "stub")
    project = _project(client)
    client.post(f"/api/projects/{project['id']}/wizard", json=WIZARD)
    queued = client.post(f"/api/projects/{project['id']}/validate")
    assert queued.status_code == 200, queued.text
    job_id = queued.json()["id"]

    _login_admin(client)
    listed = client.get("/api/admin/jobs", params={"kind": "validate", "status": "queued"})
    assert listed.status_code == 200, listed.text
    ids = {row["id"] for row in listed.json()["jobs"]}
    assert job_id in ids
    log = client.get(f"/api/admin/jobs/{job_id}/log")
    assert log.status_code == 200
    assert b"kind=validate" in log.content
    cancelled = client.post(f"/api/admin/jobs/{job_id}/cancel")
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "cancelled"
    again = client.post(f"/api/admin/jobs/{job_id}/cancel")
    assert again.status_code == 409


def test_admin_system_shows_limits_and_citations(client):
    _login_admin(client)
    try:
        response = client.get("/api/admin/system")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["session_ttl_sec"] == settings.session_ttl_sec
        assert body["upload"]["max_upload_bytes"] == settings.max_upload_bytes
        dois = {row["doi"] for row in body["citations"]}
        assert "10.17611/S7159Q" in dois
    finally:
        settings.dev_bootstrap_admin = False
