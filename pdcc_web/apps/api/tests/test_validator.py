from __future__ import annotations

from pathlib import Path

from app.jobs.runner import process_job
from app.inventory.validator import (
    official_validate,
    parse_sidecar_output,
    validate_project,
    xml_filename,
)
from app.inventory.xmlbuild import add_station, apply_response, empty_inventory
from app.inventory.xmlutil import dumps, parse_root, qname, set_child
from tests.test_nrl_api import FakeNrl
from tests.test_wizard import WIZARD, _project

from app.nrl.client import set_nrl_client

import pytest

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "nrl" / "stationxml-resp.xml"


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


def _with_response(sample_rate: float = 100.0, channels: list[str] | None = None) -> str:
    xml = empty_inventory("YZ")
    xml = add_station(
        xml,
        network="YZ",
        station="TEST1",
        site_name="Test",
        start="2009-04-10T00:00:00",
        latitude=76.35,
        longitude=-41.84,
        elevation=80,
        depth=0,
        channels=channels or ["BHE"],
        sample_rate=sample_rate,
    )
    for code in channels or ["BHE"]:
        xml = apply_response(
            xml,
            network="YZ",
            station="TEST1",
            start="2009-04-10T00:00:00",
            location="00",
            channel=code,
            response_xml=FIXTURE.read_bytes(),
            comments=[],
            sample_rate=sample_rate,
            replace_existing=True,
        )
    return xml


def _set_sensitivity(xml: str, value: str) -> str:
    root = parse_root(xml)
    ins = root.find(f".//{qname('InstrumentSensitivity')}")
    assert ins is not None
    set_child(ins, "Value", value)
    return dumps(root)


def test_xml_filename_unvalidated_only_on_errors():
    assert xml_filename("YZ", []) == "YZ.xml"
    assert xml_filename("YZ", [{"level": "warning"}]) == "YZ.xml"
    assert xml_filename("YZ", [{"level": "error"}]) == "YZ_unvalidated.xml"


def test_412_when_sensitivity_does_not_match_stage_gains():
    xml = _set_sensitivity(_with_response(), "1.0")
    codes = {row["code"] for row in official_validate(xml, "YZ", 1)}
    assert "412" in codes
    assert "410" not in codes


def test_matching_sensitivity_is_clean_at_100hz():
    xml = _with_response(100.0)
    issues = official_validate(xml, "YZ", 1)
    assert [row["code"] for row in issues if row["level"] == "error"] == []


def test_410_when_sensitivity_is_zero():
    xml = _set_sensitivity(_with_response(), "0")
    codes = {row["code"] for row in official_validate(xml, "YZ", 1)}
    assert "410" in codes


def test_401_when_stage_numbers_skip():
    xml = _with_response()
    root = parse_root(xml)
    stages = root.findall(f".//{qname('Stage')}")
    stages[1].set("number", "4")
    codes = {row["code"] for row in official_validate(dumps(root), "YZ", 1)}
    assert "401" in codes


def test_413_when_stage_gain_missing():
    xml = _with_response()
    root = parse_root(xml)
    gain = root.find(f".//{qname('StageGain')}")
    assert gain is not None
    set_child(gain, "Value", "0")
    codes = {row["code"] for row in official_validate(dumps(root), "YZ", 1)}
    assert "413" in codes


def test_305_and_421_when_sample_rate_mismatches_decimation():
    xml = _with_response(sample_rate=20.0)
    codes = {row["code"] for row in official_validate(xml, "YZ", 1)}
    assert "421" in codes
    root = parse_root(xml)
    rate = root.find(f".//{qname('SampleRate')}")
    assert rate is not None
    rate.text = "0"
    codes = {row["code"] for row in official_validate(dumps(root), "YZ", 1)}
    assert "305" in codes


def test_411_when_sensitivity_frequency_at_nyquist():
    xml = _with_response(100.0)
    root = parse_root(xml)
    ins = root.find(f".//{qname('InstrumentSensitivity')}")
    assert ins is not None
    set_child(ins, "Frequency", "50")
    issues = official_validate(dumps(root), "YZ", 1)
    warn = [row for row in issues if row["code"] == "411"]
    assert warn and warn[0]["level"] == "warning"


def test_111_station_overlap_uses_official_number_in_full_mode():
    xml = empty_inventory("YZ")
    xml = add_station(
        xml,
        network="YZ",
        station="TEST1",
        site_name="a",
        start="2009-04-10T00:00:00",
        latitude=0,
        longitude=0,
        elevation=0,
        depth=0,
        channels=["BHZ"],
        end="2010-01-01T00:00:00",
    )
    root = parse_root(xml)
    net = root.find(qname("Network"))
    assert net is not None
    from app.inventory.xmlutil import el

    sta = el("Station", code="TEST1", startDate="2009-06-01T00:00:00")
    sta.append(el("Latitude", "1"))
    sta.append(el("Longitude", "1"))
    sta.append(el("Elevation", "0"))
    net.append(sta)
    full = validate_project(dumps(root), "YZ", 1, mode="full")
    codes = {row["code"] for row in full}
    assert "111" in codes
    assert "E_EPOCH_OVERLAP" not in codes


def test_sidecar_parser_reads_rule_numbers():
    text = "\n".join(
        [
            "[ERROR] [412] 00.BHE The product of the stage gains does not equal the sensitivity",
            "[WARNING] [411] sensitivity frequency",
            "noise",
        ]
    )
    parsed = parse_sidecar_output(text)
    codes = {row["code"]: row["level"] for row in parsed}
    assert codes["412"] == "error"
    assert codes["411"] == "warning"


def test_validate_and_unvalidated_xml_api(stub):
    project = _project(stub)
    created = stub.post(f"/api/projects/{project['id']}/wizard", json=WIZARD)
    assert created.status_code == 200, created.text
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
    result = stub.post(f"/api/projects/{project['id']}/validate")
    assert result.status_code == 200, result.text
    job = result.json()
    assert job["status"] == "queued"
    process_job(job["id"])
    done = stub.get(f"/api/jobs/{job['id']}")
    assert done.status_code == 200, done.text
    body = done.json()["result"]
    codes = {row["code"] for row in body["issues"]}
    assert "412" in codes
    assert body["mode"] == "full"
    assert body["can_export_seed"] is False
    assert body["filename"] == "YZ_unvalidated.xml"
    xml = stub.get(f"/api/projects/{project['id']}/xml?source=draft")
    assert xml.status_code == 200
    assert 'filename="YZ_unvalidated.xml"' in xml.headers.get("content-disposition", "")
    assert xml.headers.get("x-pdcc-filename") == "YZ_unvalidated.xml"
    assert ">1.0<" in xml.text or ">1<" in xml.text
    blocked = stub.post(f"/api/projects/{project['id']}/export/seed")
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "E_UNVALIDATED"


def test_clean_xml_filename_when_only_warnings(stub):
    project = _project(stub)
    later = dict(WIZARD, nrl_later=True, sensor_instconfig=None, datalogger_instconfig=None)
    created = stub.post(f"/api/projects/{project['id']}/wizard", json=later)
    assert created.status_code == 200, created.text
    xml = stub.get(f"/api/projects/{project['id']}/xml")
    assert xml.status_code == 200
    assert 'filename="YZ.xml"' in xml.headers.get("content-disposition", "")
    blocked = stub.post(f"/api/projects/{project['id']}/export/seed")
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "E_LOSS_ACK"
    ack = stub.get(f"/api/projects/{project['id']}/export/seed-loss").json()["ack"]
    seed = stub.post(f"/api/projects/{project['id']}/export/seed?loss_ack={ack}")
    assert seed.status_code == 200, seed.text
    assert seed.json()["kind"] == "dataless"
    assert seed.json()["status"] == "queued"


def test_sensitivity_listed_and_drafted(stub):
    project = _project(stub)
    created = stub.post(f"/api/projects/{project['id']}/wizard", json=WIZARD)
    assert created.status_code == 200, created.text
    chans = {c["code"]: c for c in created.json()["project"]["stations"][0]["channels"]}
    assert chans["BHE"]["sensitivity"] == pytest.approx(838860000.0)
    drafted = stub.put(
        f"/api/projects/{project['id']}/draft",
        json={
            "station": "TEST1",
            "start_time": "2009-04-10T00:00:00",
            "channel": "BHE",
            "location": "00",
            "sensitivity": 42.5,
        },
    )
    assert drafted.status_code == 200, drafted.text
    preview = stub.get(f"/api/projects/{project['id']}/draft")
    chans = {c["code"]: c for c in preview.json()["draft"]["stations"][0]["channels"]}
    assert chans["BHE"]["sensitivity"] == pytest.approx(42.5)
    assert chans["BHZ"]["sensitivity"] == pytest.approx(838860000.0)
