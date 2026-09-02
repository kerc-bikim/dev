from __future__ import annotations

from app.nrl.client import set_nrl_client

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


def test_equipment_set_stale_when_catalog_changes(stub, fake_nrl):
    created = stub.post(
        "/api/equipment-sets",
        json={
            "name": "광대역 표준세트",
            "sensor_instconfig": WIZARD["sensor_instconfig"],
            "datalogger_instconfig": WIZARD["datalogger_instconfig"],
            "channels": ["BHZ", "BHN", "BHE"],
        },
    )
    assert created.status_code == 200, created.text
    assert created.json()["stale"] is False
    fake_nrl.elements = {"NRLCatalog": {"element": [{"name": "other"}]}}
    listed = stub.get("/api/equipment-sets")
    assert listed.status_code == 200
    row = listed.json()["sets"][0]
    assert row["stale"] is True
    assert row["name"] == "광대역 표준세트"


def test_draft_recover_and_commit(stub):
    project = _project(stub)
    later = dict(WIZARD, nrl_later=True, sensor_instconfig=None, datalogger_instconfig=None)
    created = stub.post(f"/api/projects/{project['id']}/wizard", json=later)
    assert created.status_code == 200
    drafted = stub.put(
        f"/api/projects/{project['id']}/draft",
        json={
            "station": "TEST1",
            "start_time": "2009-04-10T00:00:00",
            "latitude": 10.5,
        },
    )
    assert drafted.status_code == 200
    got = stub.get(f"/api/projects/{project['id']}")
    assert got.json()["draft"]["conflict"] is False
    preview = stub.get(f"/api/projects/{project['id']}/draft")
    assert preview.json()["draft"]["stations"][0]["latitude"] == 10.5
    xml_before = stub.get(f"/api/projects/{project['id']}/xml").text
    assert ">10.5<" not in xml_before
    saved = stub.post(f"/api/projects/{project['id']}/draft/commit")
    assert saved.status_code == 200, saved.text
    xml = stub.get(f"/api/projects/{project['id']}/xml").text
    assert ">10.5<" in xml
    assert saved.json()["project"]["draft"] is None


def test_undo_restores_previous_response(stub):
    project = _project(stub)
    later = dict(WIZARD, nrl_later=True, sensor_instconfig=None, datalogger_instconfig=None)
    stub.post(f"/api/projects/{project['id']}/wizard", json=later)
    applied = stub.post(
        f"/api/projects/{project['id']}/apply-nrl",
        json={
            "station": "TEST1",
            "start_time": "2009-04-10T00:00:00",
            "channels": ["00.BHZ"],
            "sensor_instconfig": WIZARD["sensor_instconfig"],
            "datalogger_instconfig": WIZARD["datalogger_instconfig"],
        },
    )
    assert applied.status_code == 200
    assert applied.json()["project"]["stations"][0]["channels"][0]["has_response"] is True
    undone = stub.post(f"/api/projects/{project['id']}/undo")
    assert undone.status_code == 200, undone.text
    chans = {c["code"]: c for c in undone.json()["project"]["stations"][0]["channels"]}
    assert chans["BHZ"]["has_response"] is False


def test_restore_creates_new_version_and_diff(stub):
    project = _project(stub)
    later = dict(WIZARD, nrl_later=True, sensor_instconfig=None, datalogger_instconfig=None)
    stub.post(f"/api/projects/{project['id']}/wizard", json=later)
    stub.post(
        f"/api/projects/{project['id']}/apply-nrl",
        json={
            "station": "TEST1",
            "start_time": "2009-04-10T00:00:00",
            "channels": ["00.BHZ"],
            "sensor_instconfig": WIZARD["sensor_instconfig"],
            "datalogger_instconfig": WIZARD["datalogger_instconfig"],
        },
    )
    versions = stub.get(f"/api/projects/{project['id']}/versions").json()["versions"]
    assert len(versions) >= 2
    first = versions[-1]
    latest = versions[0]
    restored = stub.post(f"/api/projects/{project['id']}/versions/{first['id']}/restore")
    assert restored.status_code == 200
    after = stub.get(f"/api/projects/{project['id']}/versions").json()["versions"]
    assert after[0]["action"] == "restore"
    assert after[0]["number"] == latest["number"] + 1
    diff = stub.get(
        f"/api/projects/{project['id']}/versions/{latest['id']}/diff/{after[0]['id']}"
    )
    assert diff.status_code == 200
    paths = [row["path"] for row in diff.json()["fields"]]
    assert any("has_response" in path for path in paths)
    chans = {c["code"]: c for c in restored.json()["project"]["stations"][0]["channels"]}
    assert chans["BHZ"]["has_response"] is False


def test_draft_conflict_merge(stub):
    project = _project(stub)
    later = dict(WIZARD, nrl_later=True, sensor_instconfig=None, datalogger_instconfig=None)
    stub.post(f"/api/projects/{project['id']}/wizard", json=later)
    stub.put(
        f"/api/projects/{project['id']}/draft",
        json={"station": "TEST1", "start_time": "2009-04-10T00:00:00", "latitude": 11},
    )
    stub.post(
        f"/api/projects/{project['id']}/apply-nrl",
        json={
            "station": "TEST1",
            "start_time": "2009-04-10T00:00:00",
            "channels": ["00.BHE"],
            "sensor_instconfig": WIZARD["sensor_instconfig"],
            "datalogger_instconfig": WIZARD["datalogger_instconfig"],
        },
    )
    conflicted = stub.post(f"/api/projects/{project['id']}/draft/commit")
    assert conflicted.status_code == 409
    fields = conflicted.json()["detail"]["fields"]
    assert any("latitude" in row["path"] for row in fields)
    merged = stub.post(
        f"/api/projects/{project['id']}/draft/merge",
        json={"choices": {row["path"]: "mine" for row in fields}},
    )
    assert merged.status_code == 200, merged.text
    xml = stub.get(f"/api/projects/{project['id']}/xml").text
    assert ">11.0<" in xml or ">11<" in xml
