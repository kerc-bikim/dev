from __future__ import annotations

from app.db import SessionLocal
from app.jobs.runner import process_job
from app.models import Project
from tests.test_nrl_api import FakeNrl
from app.nrl.client import set_nrl_client

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


def _project_with_station(client):
    created = client.post(
        "/api/projects",
        json={"name": "YZ 상시망", "network_code": "YZ", "operator": "KIGAM"},
    )
    assert created.status_code == 200
    project = created.json()
    wiz = client.post(f"/api/projects/{project['id']}/wizard", json=WIZARD)
    assert wiz.status_code == 200, wiz.text
    return project


def test_export_returns_queued_then_worker_completes(stub, tmp_path, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "export_dir", str(tmp_path))
    project = _project_with_station(stub)
    xml_before = stub.get(f"/api/projects/{project['id']}/xml").text
    queued = stub.post(
        f"/api/projects/{project['id']}/export",
        json={"kind": "resp", "scope": "channel", "station": "TEST1", "nslc": "00.BHZ"},
    )
    assert queued.status_code == 200, queued.text
    body = queued.json()
    assert body["status"] == "queued"
    assert body["downloadable"] is False
    listed = stub.get("/api/jobs")
    assert listed.status_code == 200
    assert listed.json()["jobs"][0]["id"] == body["id"]
    process_job(body["id"])
    done = stub.get(f"/api/jobs/{body['id']}")
    assert done.status_code == 200
    info = done.json()
    assert info["status"] == "completed"
    assert info["progress"] == 100
    assert info["downloadable"] is True
    download = stub.get(f"/api/jobs/{body['id']}/download")
    assert download.status_code == 200
    text = download.content.decode("ascii")
    assert "B050F03" in text
    assert "BHZ" in text
    xml_after = stub.get(f"/api/projects/{project['id']}/xml").text
    assert xml_after == xml_before


def test_dataless_job_download(stub, tmp_path, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "export_dir", str(tmp_path))
    project = _project_with_station(stub)
    queued = stub.post(
        f"/api/projects/{project['id']}/export",
        json={
            "kind": "dataless",
            "scope": "station",
            "station": "TEST1",
            "start_time": "2009-04-10T00:00:00",
            "accept_losses": True,
        },
    )
    assert queued.status_code == 200, queued.text
    process_job(queued.json()["id"])
    done = stub.get(f"/api/jobs/{queued.json()['id']}")
    assert done.json()["status"] == "completed"
    download = stub.get(f"/api/jobs/{queued.json()['id']}/download")
    assert download.status_code == 200
    assert download.content[:8] == b"000001V "


def test_preview_and_loss_confirm(stub, tmp_path, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "export_dir", str(tmp_path))
    project = _project_with_station(stub)
    db = SessionLocal()
    try:
        row = db.get(Project, project["id"])
        assert row is not None
        row.xml_text = row.xml_text.replace(
            "NRL v2 sensor",
            "NRL v2 " + ("truncate-me-" * 10) + " sensor",
            1,
        )
        db.commit()
    finally:
        db.close()
    preview = stub.post(
        f"/api/projects/{project['id']}/export",
        json={
            "kind": "dataless",
            "scope": "station",
            "station": "TEST1",
            "preview": True,
        },
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["needs_confirm"] is True
    blocked = stub.post(
        f"/api/projects/{project['id']}/export",
        json={"kind": "dataless", "scope": "station", "station": "TEST1"},
    )
    assert blocked.status_code == 409
    detail = blocked.json()["detail"]
    assert isinstance(detail, dict)
    assert detail["losses"]
    queued = stub.post(
        f"/api/projects/{project['id']}/export",
        json={
            "kind": "dataless",
            "scope": "station",
            "station": "TEST1",
            "accept_losses": True,
        },
    )
    assert queued.status_code == 200
    process_job(queued.json()["id"])
    assert stub.get(f"/api/jobs/{queued.json()['id']}").json()["status"] == "completed"


def test_retry_failed_job(stub, tmp_path, monkeypatch):
    from app.config import settings
    from app.db import SessionLocal as SL
    from app.models import ExportJob

    monkeypatch.setattr(settings, "export_dir", str(tmp_path))
    project = _project_with_station(stub)
    queued = stub.post(
        f"/api/projects/{project['id']}/export",
        json={"kind": "resp", "scope": "channel", "station": "TEST1", "nslc": "00.BHZ"},
    )
    job_id = queued.json()["id"]
    db = SL()
    try:
        row = db.get(ExportJob, job_id)
        assert row is not None
        row.status = "failed"
        row.error = "boom"
        db.commit()
    finally:
        db.close()
    retried = stub.post(f"/api/jobs/{job_id}/retry")
    assert retried.status_code == 200
    assert retried.json()["status"] == "queued"
    process_job(job_id)
    assert stub.get(f"/api/jobs/{job_id}").json()["status"] == "completed"


def test_missing_response_export_400(stub):
    later = dict(WIZARD)
    later["nrl_later"] = True
    later["sensor_instconfig"] = None
    later["datalogger_instconfig"] = None
    created = stub.post(
        "/api/projects",
        json={"name": "empty", "network_code": "YZ"},
    )
    project = created.json()
    wiz = stub.post(f"/api/projects/{project['id']}/wizard", json=later)
    assert wiz.status_code == 200
    resp = stub.post(
        f"/api/projects/{project['id']}/export",
        json={"kind": "dataless", "scope": "project"},
    )
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert "errors" in detail
