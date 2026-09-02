from __future__ import annotations

import pytest
from app.db import SessionLocal
from app.models import User, hash_password
from app.nrl.client import set_nrl_client
from sqlalchemy import select

from tests.test_nrl_api import FakeNrl


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


def _ensure_stub2() -> None:
    db = SessionLocal()
    try:
        if db.scalar(select(User).where(User.username == "stub2")) is None:
            db.add(
                User(
                    username="stub2",
                    password_hash=hash_password("stub2"),
                    role="editor",
                )
            )
            db.commit()
    finally:
        db.close()


def _add_member(project_id: int, username: str, role: str = "editor") -> None:
    from app.models import ProjectMember

    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.username == username))
        assert user is not None
        exists = db.scalar(
            select(ProjectMember).where(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id == user.id,
            )
        )
        if exists is None:
            db.add(ProjectMember(project_id=project_id, user_id=user.id, role=role))
            db.commit()
    finally:
        db.close()


def _login(client, username: str, password: str) -> None:
    ok = client.post("/api/login", json={"username": username, "password": password})
    assert ok.status_code == 200


def _project(client):
    created = client.post(
        "/api/projects",
        json={"name": "YZ 상시망", "network_code": "YZ", "operator": "KIGAM"},
    )
    assert created.status_code == 200
    return created.json()


WIZARD = {
    "station": "TEST1",
    "site_name": "Test One",
    "start_time": "2009-04-10T00:00:00",
    "current_operation": True,
    "latitude": 76.35,
    "longitude": -41.84,
    "elevation": 80,
    "depth": 0,
    "location": "00",
    "channels": ["BHZ", "BHN", "BHE"],
    "sensor_instconfig": "sensor_Guralp_CMG-3T_LP120_HF50_SG1500_STgroundVel",
    "datalogger_instconfig": "datalogger_Quanterra_Q330HR_PG20_FR20_ADSR_LRbelow100_DENone",
}


def test_wizard_creates_three_component_station(stub):
    project = _project(stub)
    result = stub.post(f"/api/projects/{project['id']}/wizard", json=WIZARD)
    assert result.status_code == 200, result.text
    body = result.json()["project"]
    assert body["station_count"] == 1
    assert body["channel_count"] == 3
    chans = {c["code"]: c for c in body["stations"][0]["channels"]}
    assert chans["BHE"]["azimuth"] == 90
    assert chans["BHN"]["azimuth"] == 0
    assert chans["BHZ"]["dip"] == -90
    assert all(c["has_response"] for c in chans.values())
    assert all(c["sample_rate"] == 20 for c in chans.values())
    xml = stub.get(f"/api/projects/{project['id']}/xml")
    assert xml.status_code == 200
    text = xml.text
    assert "NRL v2 sensor_Guralp_CMG-3T" in text
    assert text.count("<Response") == 3
    assert body["lock"]["mine"] is True


def test_wizard_validation(stub):
    project = _project(stub)
    bad = dict(WIZARD, station="TOOLONG")
    assert stub.post(f"/api/projects/{project['id']}/wizard", json=bad).status_code == 422
    bad_lat = dict(WIZARD, latitude=100)
    assert stub.post(f"/api/projects/{project['id']}/wizard", json=bad_lat).status_code == 400


def test_apply_skips_unchecked_channel(stub):
    project = _project(stub)
    later = dict(WIZARD)
    later["nrl_later"] = True
    later["sensor_instconfig"] = None
    later["datalogger_instconfig"] = None
    created = stub.post(f"/api/projects/{project['id']}/wizard", json=later)
    assert created.status_code == 200
    assert all(not c["has_response"] for c in created.json()["project"]["stations"][0]["channels"])
    applied = stub.post(
        f"/api/projects/{project['id']}/apply-nrl",
        json={
            "station": "TEST1",
            "start_time": "2009-04-10T00:00:00",
            "channels": ["00.BHE", "00.BHN"],
            "sensor_instconfig": WIZARD["sensor_instconfig"],
            "datalogger_instconfig": WIZARD["datalogger_instconfig"],
        },
    )
    assert applied.status_code == 200, applied.text
    chans = {c["code"]: c for c in applied.json()["project"]["stations"][0]["channels"]}
    assert chans["BHE"]["has_response"] is True
    assert chans["BHN"]["has_response"] is True
    assert chans["BHZ"]["has_response"] is False
    assert applied.json()["applied"] == ["00.BHE", "00.BHN"]


def test_second_user_is_read_only_while_locked(stub, redis_client):
    project = _project(stub)
    created = stub.post(f"/api/projects/{project['id']}/wizard", json=WIZARD)
    assert created.status_code == 200
    path = created.json()["station_path"]
    _ensure_stub2()
    _add_member(project["id"], "stub2")
    _login(stub, "stub2", "stub2")
    blocked = stub.post(
        f"/api/projects/{project['id']}/lock",
        params={"station_path": path},
    )
    assert blocked.status_code == 409
    assert "수정 중" in blocked.json()["detail"]
    apply_blocked = stub.post(
        f"/api/projects/{project['id']}/apply-nrl",
        json={
            "station": "TEST1",
            "start_time": "2009-04-10T00:00:00",
            "channels": ["00.BHZ"],
            "sensor_instconfig": WIZARD["sensor_instconfig"],
        },
    )
    assert apply_blocked.status_code == 409
    redis_client.delete(f"pdcc:lock:{path}")
    after = stub.post(
        f"/api/projects/{project['id']}/lock",
        params={"station_path": path},
    )
    assert after.status_code == 200
    assert after.json()["username"] == "stub2"


def test_locks_are_per_project(stub):
    later = dict(WIZARD)
    later["nrl_later"] = True
    later["sensor_instconfig"] = None
    later["datalogger_instconfig"] = None
    p1 = _project(stub)
    first = stub.post(f"/api/projects/{p1['id']}/wizard", json=later)
    assert first.status_code == 200
    _ensure_stub2()
    _add_member(p1["id"], "stub2")
    _login(stub, "stub2", "stub2")
    p2 = _project(stub)
    second = stub.post(f"/api/projects/{p2['id']}/wizard", json=later)
    assert second.status_code == 200, second.text
    assert first.json()["station_path"] != second.json()["station_path"]
    blocked = stub.post(
        f"/api/projects/{p1['id']}/lock",
        params={"station_path": first.json()["station_path"]},
    )
    assert blocked.status_code == 409
    own = stub.post(
        f"/api/projects/{p2['id']}/lock",
        params={"station_path": second.json()["station_path"]},
    )
    assert own.status_code == 200
    assert own.json()["username"] == "stub2"
