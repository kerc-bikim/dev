from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO

from obspy import read_inventory
from obspy.io.xseed import Parser

from app.db import SessionLocal
from app.inventory.seed_convert import classify_seed, convert_xml_to_dataless, dataless_filename
from app.jobs.runner import process_job
from app.models import Job
from tests.test_seed_loss import _loss_xml
from tests.test_users import _enable_admin, _name


def test_convert_xml_to_dataless_roundtrip_does_not_mutate_source():
    xml = _loss_xml()
    original = xml
    data, engine = convert_xml_to_dataless(xml, organization="KIGAM", label="YZ")
    assert original == xml
    assert engine == "obspy"
    assert classify_seed(data) == "dataless"
    back = read_inventory(BytesIO(data), format="SEED")
    assert back[0].code == "YZ"
    assert back[0][0].code == "TEST1"
    assert {ch.code for ch in back[0][0]} == {"BHE"}
    parser = Parser(BytesIO(data))
    vol = parser.volume[0]
    assert "KIGAM" in str(getattr(vol, "originating_organization", "") or "")
    assert dataless_filename(xml, "YZ", datetime(2026, 4, 10, tzinfo=timezone.utc)) == (
        "YZ.TEST1.20260410.dataless"
    )


def test_seed_export_job_download_and_retry(client):
    client.post("/api/login", json={"username": "stub", "password": "stub"})
    imported = client.post(
        "/api/projects/import",
        json={
            "filename": "yz-test1.xml",
            "xml_text": _loss_xml(),
            "name": "SEED 내보내기",
            "operator": "KIGAM",
        },
    )
    assert imported.status_code == 200, imported.text
    project_id = imported.json()["id"]
    ack = client.get(f"/api/projects/{project_id}/export/seed-loss").json()["ack"]
    queued = client.post(f"/api/projects/{project_id}/export/seed?loss_ack={ack}")
    assert queued.status_code == 200, queued.text
    job = queued.json()
    assert job["kind"] == "dataless"
    assert job["status"] == "queued"
    assert job["version_id"] is not None
    job_id = job["id"]
    version_id = job["version_id"]
    snapshot = None
    db = SessionLocal()
    try:
        row = db.get(Job, job_id)
        assert row is not None
        snapshot = row.xml_snapshot
    finally:
        db.close()

    too_soon = client.get(f"/api/jobs/{job_id}/download")
    assert too_soon.status_code == 409

    process_job(job_id)
    done = client.get(f"/api/jobs/{job_id}")
    assert done.status_code == 200, done.text
    info = done.json()
    assert info["status"] == "succeeded"
    assert info["downloadable"] is True
    assert info["version_id"] == version_id
    assert info["filename"].startswith("YZ.TEST1.")
    assert info["filename"].endswith(".dataless")
    assert info["result"]["engine"] == "obspy"
    assert info["result"]["bytes"] > 0

    downloaded = client.get(f"/api/jobs/{job_id}/download")
    assert downloaded.status_code == 200, downloaded.text
    assert downloaded.headers.get("x-pdcc-filename") == info["filename"]
    assert "filename=" in downloaded.headers.get("content-disposition", "")
    payload = downloaded.content
    assert classify_seed(payload) == "dataless"
    back = read_inventory(BytesIO(payload), format="SEED")
    assert back[0][0].code == "TEST1"
    assert {ch.code for ch in back[0][0]} == {"BHE"}

    db = SessionLocal()
    try:
        row = db.get(Job, job_id)
        assert row is not None
        row.status = "failed"
        row.error = "boom"
        db.commit()
    finally:
        db.close()
    retried = client.post(f"/api/jobs/{job_id}/retry")
    assert retried.status_code == 200, retried.text
    assert retried.json()["id"] == job_id
    assert retried.json()["version_id"] == version_id
    db = SessionLocal()
    try:
        row = db.get(Job, job_id)
        assert row is not None
        assert row.xml_snapshot == snapshot
    finally:
        db.close()
    process_job(job_id)
    again = client.get(f"/api/jobs/{job_id}/download")
    assert again.status_code == 200
    assert classify_seed(again.content) == "dataless"


def test_viewer_cannot_download_seed(client):
    client.post("/api/login", json={"username": "stub", "password": "stub"})
    imported = client.post(
        "/api/projects/import",
        json={"filename": "yz-test1.xml", "xml_text": _loss_xml(), "name": "조회 SEED"},
    )
    project_id = imported.json()["id"]
    ack = client.get(f"/api/projects/{project_id}/export/seed-loss").json()["ack"]
    queued = client.post(f"/api/projects/{project_id}/export/seed?loss_ack={ack}")
    job_id = queued.json()["id"]
    process_job(job_id)

    client.post("/api/logout")
    _enable_admin(client)
    viewer_name = _name("seedv")
    viewer = client.post(
        "/api/admin/users",
        json={"username": viewer_name, "password": "view1", "role": "viewer"},
    )
    client.put(
        f"/api/projects/{project_id}/members",
        json={"user_id": viewer.json()["id"], "role": "viewer"},
    )
    client.post("/api/logout")
    client.post("/api/login", json={"username": viewer_name, "password": "view1"})
    listed = client.get("/api/jobs")
    assert listed.status_code == 200
    assert any(row["id"] == job_id for row in listed.json()["jobs"])
    denied = client.get(f"/api/jobs/{job_id}/download")
    assert denied.status_code == 403
    outsider = client.post("/api/logout")
    assert outsider.status_code == 200
    client.post("/api/login", json={"username": "stub", "password": "stub"})
    ok = client.get(f"/api/jobs/{job_id}/download")
    assert ok.status_code == 200
