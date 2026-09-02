from __future__ import annotations

from app.inventory.importers import inspect_stationxml
from app.inventory.xmlbuild import InventoryError, add_station, empty_inventory


def _valid_xml() -> str:
    xml = empty_inventory("YZ", operator="KIGAM")
    return add_station(
        xml,
        network="YZ",
        station="TEST1",
        site_name="Test One",
        start="2009-04-10T00:00:00",
        latitude=76.35,
        longitude=-41.84,
        elevation=80,
        depth=0,
        channels=["BHZ", "BHN", "BHE"],
        sample_rate=20,
    )


def test_inspect_accepts_stationxml():
    info = inspect_stationxml(_valid_xml().encode("utf-8"))
    assert info["network_code"] == "YZ"
    assert info["station_count"] == 1
    assert info["channel_count"] == 3


def test_inspect_rejects_broken_xml():
    try:
        inspect_stationxml(b"<not-xml")
        assert False
    except InventoryError as exc:
        assert exc.code == "XSD"


def test_inspect_rejects_non_stationxml_and_zip():
    try:
        inspect_stationxml(b"SEED volume")
        assert False
    except InventoryError as exc:
        assert exc.code == "E_IMPORT"
    try:
        inspect_stationxml(b"PK\x03\x04not-a-zip")
        assert False
    except InventoryError as exc:
        assert "zip" in str(exc)


def test_inspect_rejects_wrong_schema_version():
    xml = empty_inventory("YZ").replace('schemaVersion="1.2"', 'schemaVersion="1.1"')
    try:
        inspect_stationxml(xml.encode("utf-8"))
        assert False
    except InventoryError as exc:
        assert exc.code == "XSD"


def test_import_api_stores_original(client):
    client.post("/api/login", json={"username": "stub", "password": "stub"})
    xml = _valid_xml()
    created = client.post(
        "/api/projects/import",
        json={"filename": "yz-test1.xml", "xml_text": xml, "name": "가져온 YZ"},
    )
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["name"] == "가져온 YZ"
    assert body["network_code"] == "YZ"
    assert body["station_count"] == 1
    assert body["has_original"] is True
    assert body["stations"][0]["code"] == "TEST1"
    pid = body["id"]
    original = client.get(f"/api/projects/{pid}/original")
    assert original.status_code == 200
    assert original.headers.get("content-disposition", "").endswith('filename="yz-test1.xml"')
    assert original.content == xml.encode("utf-8")
    listed = client.get("/api/projects")
    assert any(row["id"] == pid and row["has_original"] for row in listed.json()["projects"])


def test_import_api_rejects_garbage(client):
    client.post("/api/login", json={"username": "stub", "password": "stub"})
    bad = client.post(
        "/api/projects/import",
        json={"filename": "bad.xml", "xml_text": "<FDSNStationXML>"},
    )
    assert bad.status_code == 400
    assert "XML" in bad.json()["detail"] or "표준" in bad.json()["detail"]


def test_import_then_edit_latitude(client):
    client.post("/api/login", json={"username": "stub", "password": "stub"})
    xml = _valid_xml()
    created = client.post(
        "/api/projects/import",
        json={"filename": "yz-test1.xml", "xml_text": xml},
    )
    pid = created.json()["id"]
    drafted = client.put(
        f"/api/projects/{pid}/draft",
        json={
            "station": "TEST1",
            "start_time": "2009-04-10T00:00:00",
            "latitude": 10.5,
            "propagate": True,
        },
    )
    assert drafted.status_code == 200, drafted.text
    preview = client.get(f"/api/projects/{pid}/draft")
    assert preview.json()["draft"]["stations"][0]["latitude"] == 10.5
    committed = client.post(f"/api/projects/{pid}/draft/commit")
    assert committed.status_code == 200, committed.text
    xml_out = client.get(f"/api/projects/{pid}/xml")
    assert xml_out.status_code == 200
    assert ">10.5<" in xml_out.text
    original = client.get(f"/api/projects/{pid}/original")
    assert b">76.35<" in original.content
