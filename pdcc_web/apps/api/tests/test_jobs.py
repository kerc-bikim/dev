from __future__ import annotations

from app.db import SessionLocal
from app.jobs.runner import process_job
from app.models import Job, User, hash_password
from app.nrl.client import set_nrl_client
from sqlalchemy import select
from tests.test_nrl_api import FakeNrl
from tests.test_wizard import WIZARD, _project

import pytest


@pytest.fixture
def fake_nrl():
    fake = FakeNrl()
    set_nrl_client(fake)
    yield fake
    set_nrl_client(None)


@pytest.fixture
def stub(client, fake_nrl):
    client.post("/api/login", json={"username": "stub", "password": "stub"})
    return client


def _ensure_user(username: str, password: str, role: str = "editor") -> None:
    db = SessionLocal()
    try:
        if db.scalar(select(User).where(User.username == username)) is None:
            db.add(
                User(
                    username=username,
                    password_hash=hash_password(password),
                    role=role,
                )
            )
            db.commit()
    finally:
        db.close()


def _station(stub):
    project = _project(stub)
    created = stub.post(f"/api/projects/{project['id']}/wizard", json=WIZARD)
    assert created.status_code == 200, created.text
    return project


def test_validate_job_keeps_snapshot_while_editing(stub):
    project = _station(stub)
    drafted = stub.put(
        f"/api/projects/{project['id']}/draft",
        json={
            "station": "TEST1",
            "start_time": "2009-04-10T00:00:00",
            "channel": "BHE",
            "location": "00",
            "sensitivity": 1.0,
        },
    )
    assert drafted.status_code == 200, drafted.text
    queued = stub.post(f"/api/projects/{project['id']}/validate")
    assert queued.status_code == 200, queued.text
    body = queued.json()
    assert body["status"] == "queued"
    assert body["kind"] == "validate"
    assert body["progress"] == 0
    assert body["result"] is None
    assert body["version_id"] is not None
    listed = stub.get("/api/jobs")
    assert listed.status_code == 200
    assert listed.json()["jobs"][0]["id"] == body["id"]

    edited = stub.put(
        f"/api/projects/{project['id']}/draft",
        json={
            "station": "TEST1",
            "start_time": "2009-04-10T00:00:00",
            "channel": "BHE",
            "location": "00",
            "sensitivity": 838860000.0,
        },
    )
    assert edited.status_code == 200, edited.text

    process_job(body["id"])
    done = stub.get(f"/api/jobs/{body['id']}")
    assert done.status_code == 200
    info = done.json()
    assert info["status"] == "succeeded"
    assert info["progress"] == 100
    assert info["version_id"] == body["version_id"]
    result = info["result"]
    assert result["mode"] == "full"
    codes = {row["code"] for row in result["issues"]}
    assert "412" in codes
    assert result["can_export_seed"] is False
    assert result["filename"] == "YZ_unvalidated.xml"

    live = stub.get(f"/api/projects/{project['id']}/issues?mode=full")
    assert live.status_code == 200
    live_codes = {row["code"] for row in live.json()["issues"]}
    assert "412" not in live_codes


def test_retry_failed_validate_same_version(stub):
    project = _station(stub)
    queued = stub.post(f"/api/projects/{project['id']}/validate")
    job_id = queued.json()["id"]
    version_id = queued.json()["version_id"]
    snapshot = None
    db = SessionLocal()
    try:
        row = db.get(Job, job_id)
        assert row is not None
        snapshot = row.xml_snapshot
        row.status = "failed"
        row.error = "boom"
        db.commit()
    finally:
        db.close()
    retried = stub.post(f"/api/jobs/{job_id}/retry")
    assert retried.status_code == 200, retried.text
    assert retried.json()["status"] == "queued"
    assert retried.json()["id"] == job_id
    assert retried.json()["version_id"] == version_id
    db = SessionLocal()
    try:
        row = db.get(Job, job_id)
        assert row is not None
        assert row.xml_snapshot == snapshot
        assert row.version_id == version_id
    finally:
        db.close()
    process_job(job_id)
    done = stub.get(f"/api/jobs/{job_id}")
    assert done.json()["status"] == "succeeded"
    assert done.json()["id"] == job_id
    assert done.json()["version_id"] == version_id


def test_job_hidden_from_other_user(stub, client):
    project = _station(stub)
    queued = stub.post(f"/api/projects/{project['id']}/validate")
    job_id = queued.json()["id"]
    _ensure_user("outsider", "outsider")
    client.post("/api/logout")
    login = client.post("/api/login", json={"username": "outsider", "password": "outsider"})
    assert login.status_code == 200
    missing = client.get(f"/api/jobs/{job_id}")
    assert missing.status_code == 404
    assert "작업이 없습니다" in missing.text
    listed = client.get("/api/jobs")
    assert listed.status_code == 200
    assert listed.json()["jobs"] == []
