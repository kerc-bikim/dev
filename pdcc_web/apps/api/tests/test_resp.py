from __future__ import annotations

import io
import zipfile
from io import BytesIO
from pathlib import Path

from obspy import read_inventory

from app.db import SessionLocal
from app.inventory.resp_convert import convert_resp_to_xml, convert_xml_to_resp, xml_to_resp_files
from app.inventory.xmlbuild import add_station, apply_response, empty_inventory
from app.inventory.xmlslice import slice_stationxml
from app.inventory.xmlutil import dumps, parse_root, qname, set_child
from app.jobs.runner import process_job
from app.models import Job
from tests.test_users import _enable_admin, _name

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "nrl" / "stationxml-resp.xml"


def _station_xml(*, channels: list[str] = ("BHZ", "BHN", "BHE"), sample_rate: float = 100.0) -> str:
    xml = empty_inventory("YZ", operator="KIGAM")
    xml = add_station(
        xml,
        network="YZ",
        station="TEST1",
        site_name="Test One",
        start="2009-04-10T00:00:00",
        latitude=76.35,
        longitude=-41.84,
        elevation=80,
        depth=0,
        channels=list(channels),
        sample_rate=sample_rate,
    )
    payload = FIXTURE.read_bytes()
    for code in channels:
        xml = apply_response(
            xml,
            network="YZ",
            station="TEST1",
            start="2009-04-10T00:00:00",
            location="00",
            channel=code,
            response_xml=payload,
            comments=[],
            sample_rate=sample_rate,
            replace_existing=True,
        )
    return xml


def _set_sensitivity(xml: str, channel: str, value: str) -> str:
    root = parse_root(xml)
    for cha in root.findall(f".//{qname('Channel')}"):
        if cha.get("code") != channel:
            continue
        ins = cha.find(f".//{qname('InstrumentSensitivity')}")
        assert ins is not None
        set_child(ins, "Value", value)
        break
    else:
        raise AssertionError(channel)
    return dumps(root)


def test_slice_does_not_change_source_string():
    xml = _station_xml()
    original = xml
    sliced = slice_stationxml(
        xml, network="YZ", station="TEST1", start="2009-04-10T00:00:00", nslc="00.BHZ"
    )
    assert original == xml
    assert sliced.count("<Channel") == 1
    assert 'code="BHZ"' in sliced
    assert sliced.count('code="BHE"') == 0


def test_resp_includes_edited_sensitivity_not_nrl_combine():
    xml = _set_sensitivity(_station_xml(channels=["BHE"]), "BHE", "42.5")
    original = xml
    files, engine, nchan = xml_to_resp_files(
        xml, network="YZ", station="TEST1", start="2009-04-10T00:00:00", nslc="00.BHE"
    )
    assert original == xml
    assert engine == "obspy"
    assert nchan == 1
    assert len(files) == 1
    name, body = files[0]
    assert name == "RESP.YZ.TEST1.00.BHE"
    text = body.decode("ascii")
    assert "B050F03" in text
    assert "TEST1" in text
    assert "BHE" in text
    assert "4.250000E+01" in text
    data, filename, media, _engine, count = convert_xml_to_resp(
        xml, network="YZ", station="TEST1", nslc="00.BHE"
    )
    assert filename == name
    assert media.startswith("text/plain")
    assert count == 1
    assert data == body


def test_resp_station_is_zip_of_channels():
    xml = _station_xml()
    data, filename, media, engine, nchan = convert_xml_to_resp(
        xml, network="YZ", station="TEST1", start="2009-04-10T00:00:00"
    )
    assert engine == "obspy"
    assert nchan == 3
    assert filename == "YZ.TEST1.resp.zip"
    assert media == "application/zip"
    with zipfile.ZipFile(BytesIO(data)) as zf:
        names = set(zf.namelist())
    assert names == {
        "RESP.YZ.TEST1.00.BHZ",
        "RESP.YZ.TEST1.00.BHN",
        "RESP.YZ.TEST1.00.BHE",
    }


def test_resp_import_fills_incomplete_metadata():
    xml = _set_sensitivity(_station_xml(channels=["BHE"]), "BHE", "42.5")
    files, _engine, _nchan = xml_to_resp_files(xml, network="YZ", nslc="00.BHE")
    imported, notes = convert_resp_to_xml(files[0][1])
    codes = {row["code"] for row in notes}
    assert "W_RESP_CONVERT" in codes
    assert "W_RESP_INCOMPLETE" in codes
    assert "W_RESP_COORDS" in codes
    assert any("네트워크 코드, 좌표, 기간을 채워 주세요" in row["message"] for row in notes)
    root = parse_root(imported)
    sta = root.find(f".//{qname('Station')}")
    assert sta is not None
    assert sta.get("code") == "TEST1"
    lat = sta.find(qname("Latitude"))
    assert lat is not None
    assert float(lat.text) == 0.0
    ins = root.find(f".//{qname('InstrumentSensitivity')}")
    assert ins is not None
    assert float(ins.find(qname("Value")).text) == 42.5


def test_resp_export_job_download_retry_and_import(client):
    client.post("/api/login", json={"username": "stub", "password": "stub"})
    xml = _station_xml(channels=["BHE"])
    imported = client.post(
        "/api/projects/import",
        json={
            "filename": "yz-test1.xml",
            "xml_text": xml,
            "name": "RESP 내보내기",
            "operator": "KIGAM",
        },
    )
    assert imported.status_code == 200, imported.text
    project_id = imported.json()["id"]
    queued = client.post(
        f"/api/projects/{project_id}/export/resp?station=TEST1&start=2009-04-10T00:00:00&nslc=00.BHE"
    )
    assert queued.status_code == 200, queued.text
    job = queued.json()
    assert job["kind"] == "resp"
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
        assert snapshot.count("<Channel") == 1
    finally:
        db.close()

    assert client.get(f"/api/jobs/{job_id}/download").status_code == 409
    process_job(job_id)
    done = client.get(f"/api/jobs/{job_id}")
    assert done.status_code == 200, done.text
    info = done.json()
    assert info["status"] == "succeeded"
    assert info["downloadable"] is True
    assert info["version_id"] == version_id
    assert info["filename"] == "RESP.YZ.TEST1.00.BHE"
    assert info["result"]["engine"] == "obspy"
    assert info["result"]["channel_count"] == 1

    downloaded = client.get(f"/api/jobs/{job_id}/download")
    assert downloaded.status_code == 200, downloaded.text
    assert downloaded.headers.get("x-pdcc-filename") == info["filename"]
    payload = downloaded.content
    text = payload.decode("ascii")
    assert "8.388600E+08" in text
    back = read_inventory(BytesIO(payload), format="RESP")
    assert back[0][0][0].code == "BHE"

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
    assert b"8.388600E+08" in again.content

    created = client.post(
        "/api/projects/import-file",
        files={"file": ("chan.resp", payload, "text/plain")},
        data={"name": "가져온 RESP"},
    )
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["name"] == "가져온 RESP"
    assert body["network_code"] == "YZ"
    assert body["station_count"] == 1
    assert body["original_kind"] == "resp"
    assert body["has_original"] is True
    pid = body["id"]
    original = client.get(f"/api/projects/{pid}/original")
    assert original.status_code == 200
    assert original.content == payload
    issues = client.get(f"/api/projects/{pid}/issues")
    assert issues.status_code == 200, issues.text
    codes = {row["code"] for row in issues.json()["issues"]}
    assert "W_RESP_CONVERT" in codes
    assert "W_RESP_INCOMPLETE" in codes
    drafted = client.put(
        f"/api/projects/{pid}/draft",
        json={
            "station": body["stations"][0]["code"],
            "start_time": body["stations"][0]["start"],
            "latitude": 10.5,
            "propagate": True,
        },
    )
    assert drafted.status_code == 200, drafted.text
    client.post(f"/api/projects/{pid}/draft/commit")
    xml_out = client.get(f"/api/projects/{pid}/xml")
    assert xml_out.status_code == 200
    assert ">10.5<" in xml_out.text
    assert client.get(f"/api/projects/{pid}/original").content == payload


def test_resp_station_zip_job(client):
    client.post("/api/login", json={"username": "stub", "password": "stub"})
    imported = client.post(
        "/api/projects/import",
        json={"filename": "yz.xml", "xml_text": _station_xml(), "name": "RESP zip"},
    )
    project_id = imported.json()["id"]
    queued = client.post(f"/api/projects/{project_id}/export/resp?station=TEST1")
    assert queued.status_code == 200, queued.text
    process_job(queued.json()["id"])
    done = client.get(f"/api/jobs/{queued.json()['id']}")
    assert done.json()["filename"] == "YZ.TEST1.resp.zip"
    downloaded = client.get(f"/api/jobs/{queued.json()['id']}/download")
    assert downloaded.status_code == 200
    with zipfile.ZipFile(io.BytesIO(downloaded.content)) as zf:
        assert len(zf.namelist()) == 3


def test_resp_blocked_when_validation_errors(client):
    client.post("/api/login", json={"username": "stub", "password": "stub"})
    xml = _set_sensitivity(_station_xml(channels=["BHE"]), "BHE", "1.0")
    imported = client.post(
        "/api/projects/import",
        json={"filename": "bad.xml", "xml_text": xml, "name": "오류 RESP"},
    )
    project_id = imported.json()["id"]
    blocked = client.post(f"/api/projects/{project_id}/export/resp")
    assert blocked.status_code == 409
    detail = blocked.json()["detail"]
    assert detail["code"] == "E_UNVALIDATED"


def test_viewer_cannot_export_or_download_resp(client):
    client.post("/api/login", json={"username": "stub", "password": "stub"})
    imported = client.post(
        "/api/projects/import",
        json={"filename": "yz.xml", "xml_text": _station_xml(channels=["BHE"]), "name": "조회 RESP"},
    )
    project_id = imported.json()["id"]
    queued = client.post(f"/api/projects/{project_id}/export/resp?nslc=00.BHE")
    job_id = queued.json()["id"]
    process_job(job_id)

    client.post("/api/logout")
    _enable_admin(client)
    viewer_name = _name("respv")
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
    denied_export = client.post(f"/api/projects/{project_id}/export/resp")
    assert denied_export.status_code == 403
    denied = client.get(f"/api/jobs/{job_id}/download")
    assert denied.status_code == 403
    client.post("/api/logout")
    client.post("/api/login", json={"username": "stub", "password": "stub"})
    ok = client.get(f"/api/jobs/{job_id}/download")
    assert ok.status_code == 200
