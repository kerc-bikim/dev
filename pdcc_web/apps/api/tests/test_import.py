from __future__ import annotations

from obspy import UTCDateTime
from obspy.io.xseed import Parser
from obspy.io.xseed.blockette import (
    Blockette010,
    Blockette030,
    Blockette033,
    Blockette034,
    Blockette050,
    Blockette052,
    Blockette058,
)

from app.inventory.importers import inspect_stationxml, inspect_upload
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


def _dataless_seed() -> bytes:
    start = UTCDateTime("2009-04-10")
    b10 = Blockette010()
    b10.version_of_format = 2.4
    b10.logical_record_length = 12
    b10.beginning_time = start
    b10.end_time = UTCDateTime("2038-01-01")
    b10.volume_time = UTCDateTime("2009-04-10")
    b10.originating_organization = "PDCC Web"
    b10.label = "dataless"
    b30 = Blockette030()
    b30.short_descriptive_name = "Steim-2 Integer Compression Format"
    b30.data_format_identifier_code = 1
    b30.data_family_type = 50
    b30.number_of_decoder_keys = 1
    b30.decoder_keys = ["M0"]
    b33 = Blockette033()
    b33.abbreviation_lookup_code = 1
    b33.abbreviation_description = "YZ"
    b34 = Blockette034()
    b34.unit_lookup_code = 1
    b34.unit_name = "M/S"
    b34.unit_description = "Velocity"
    b50 = Blockette050()
    b50.station_call_letters = "TEST1"
    b50.latitude = 76.35
    b50.longitude = -41.84
    b50.elevation = 80.0
    b50.number_of_channels = 1
    b50.number_of_station_comments = 0
    b50.site_name = "Test One"
    b50.network_identifier_code = 1
    b50.word_order_32bit = 3210
    b50.word_order_16bit = 10
    b50.start_effective_date = start
    b50.end_effective_date = ""
    b50.update_flag = "N"
    b50.network_code = "YZ"
    b52 = Blockette052()
    b52.location_identifier = "00"
    b52.channel_identifier = "BHE"
    b52.subchannel_identifier = 0
    b52.instrument_identifier = 1
    b52.optional_comment = ""
    b52.units_of_signal_response = 1
    b52.units_of_calibration_input = 1
    b52.latitude = 76.35
    b52.longitude = -41.84
    b52.elevation = 80.0
    b52.local_depth = 0.0
    b52.azimuth = 90.0
    b52.dip = 0.0
    b52.data_format_identifier_code = 1
    b52.data_record_length = 12
    b52.sample_rate = 20.0
    b52.max_clock_drift = 0.0
    b52.number_of_comments = 0
    b52.channel_flags = "CG"
    b52.start_date = start
    b52.end_date = ""
    b52.update_flag = "N"
    b58 = Blockette058()
    b58.stage_sequence_number = 0
    b58.sensitivity_gain = 1.0
    b58.frequency = 1.0
    b58.number_of_history_values = 0
    parser = Parser()
    parser.volume = [b10]
    parser.abbreviations = [b30, b33, b34]
    parser.stations = [[b50, b52, b58]]
    return parser.get_seed()


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


def test_inspect_upload_converts_dataless():
    seed = _dataless_seed()
    info = inspect_upload(seed, "yz-test1.dataless")
    assert info["kind"] == "dataless"
    assert info["network_code"] == "YZ"
    assert info["station_count"] == 1
    assert info["channel_count"] == 1
    assert info["media_type"] == "application/vnd.fdsn.seed"
    codes = {row["code"] for row in info["warnings"]}
    assert "W_SEED_CONVERT" in codes
    assert "<FDSNStationXML" in info["xml_text"]


def test_inspect_upload_rejects_miniseed_and_zip():
    miniseed = b"000001D " + b"\x00" * (4096 - 8)
    try:
        inspect_upload(miniseed, "wave.mseed")
        assert False
    except InventoryError as exc:
        assert "MiniSEED" in str(exc)
    try:
        inspect_upload(b"PK\x03\x04not-a-zip", "bundle.zip")
        assert False
    except InventoryError as exc:
        assert "zip" in str(exc)


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
    assert body["original_kind"] == "stationxml"
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


def test_import_dataless_keeps_bytes_and_warnings(client):
    client.post("/api/login", json={"username": "stub", "password": "stub"})
    seed = _dataless_seed()
    created = client.post(
        "/api/projects/import-file",
        files={"file": ("yz-test1.dataless", seed, "application/vnd.fdsn.seed")},
        data={"name": "가져온 SEED"},
    )
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["name"] == "가져온 SEED"
    assert body["network_code"] == "YZ"
    assert body["station_count"] == 1
    assert body["stations"][0]["code"] == "TEST1"
    assert body["has_original"] is True
    assert body["original_kind"] == "dataless"
    pid = body["id"]
    original = client.get(f"/api/projects/{pid}/original")
    assert original.status_code == 200
    assert original.content == seed
    assert "yz-test1.dataless" in original.headers.get("content-disposition", "")
    issues = client.get(f"/api/projects/{pid}/issues")
    assert issues.status_code == 200, issues.text
    codes = {row["code"] for row in issues.json()["issues"]}
    assert "W_SEED_CONVERT" in codes
    start = body["stations"][0]["start"]
    drafted = client.put(
        f"/api/projects/{pid}/draft",
        json={"station": "TEST1", "start_time": start, "latitude": 10.5, "propagate": True},
    )
    assert drafted.status_code == 200, drafted.text
    client.post(f"/api/projects/{pid}/draft/commit")
    xml_out = client.get(f"/api/projects/{pid}/xml")
    assert xml_out.status_code == 200
    assert ">10.5<" in xml_out.text
    assert client.get(f"/api/projects/{pid}/original").content == seed


def test_import_file_xml_still_works(client):
    client.post("/api/login", json={"username": "stub", "password": "stub"})
    xml = _valid_xml().encode("utf-8")
    created = client.post(
        "/api/projects/import-file",
        files={"file": ("yz-test1.xml", xml, "application/xml")},
        data={"name": "XML 업로드"},
    )
    assert created.status_code == 200, created.text
    assert created.json()["original_kind"] == "stationxml"
    pid = created.json()["id"]
    assert client.get(f"/api/projects/{pid}/original").content == xml


def test_viewer_cannot_import_seed(client):
    import uuid

    from app.config import settings
    from app.db import SessionLocal
    from app.seed import seed_users

    settings.dev_bootstrap_admin = True
    db = SessionLocal()
    try:
        seed_users(db)
    finally:
        db.close()
    client.post("/api/login", json={"username": "admin", "password": "admin"})
    username = f"seedview{uuid.uuid4().hex[:8]}"
    viewer = client.post(
        "/api/admin/users",
        json={"username": username, "password": "view-pass", "role": "viewer"},
    )
    assert viewer.status_code == 200, viewer.text
    client.post("/api/logout")
    client.post("/api/login", json={"username": username, "password": "view-pass"})
    denied = client.post(
        "/api/projects/import-file",
        files={"file": ("yz-test1.dataless", _dataless_seed(), "application/vnd.fdsn.seed")},
    )
    assert denied.status_code == 403
