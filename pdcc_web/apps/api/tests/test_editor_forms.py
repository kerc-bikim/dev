from __future__ import annotations

from app.inventory.xmlutil import dumps, el, parse_root, qname
from app.inventory.xmlbuild import (
    add_station,
    empty_inventory,
    list_inventory,
    update_channel,
    update_station,
    validate_inventory,
)
from tests.test_nrl_api import FakeNrl
from tests.test_wizard import WIZARD, _project

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


def _xml():
    xml = empty_inventory("YZ")
    return add_station(
        xml,
        network="YZ",
        station="TEST1",
        site_name="Test",
        start="2009-04-10T00:00:00",
        latitude=76.35,
        longitude=-41.84,
        elevation=80,
        depth=0,
        channels=["BHZ", "BHN", "BHE"],
        sample_rate=20,
    )


def test_update_channel_orientation_and_depth():
    xml = update_channel(
        _xml(),
        network="YZ",
        station="TEST1",
        start="2009-04-10T00:00:00",
        location="00",
        channel="BHZ",
        azimuth=12,
        dip=-80,
        depth=1.5,
        sample_rate=40,
    )
    chans = {c["code"]: c for c in list_inventory(xml, "YZ", 1)[0]["channels"]}
    assert chans["BHZ"]["azimuth"] == 12
    assert chans["BHZ"]["dip"] == -80
    assert chans["BHZ"]["depth"] == 1.5
    assert chans["BHZ"]["sample_rate"] == 40
    assert chans["BHN"]["azimuth"] == 0


def test_propagate_false_leaves_channel_latitude():
    xml = update_station(
        _xml(),
        network="YZ",
        station="TEST1",
        start="2009-04-10T00:00:00",
        latitude=10.5,
        propagate=False,
    )
    sta = list_inventory(xml, "YZ", 1)[0]
    assert sta["latitude"] == 10.5
    assert sta["channels"][0]["latitude"] == 76.35


def test_propagate_true_updates_channel_end():
    xml = update_station(
        _xml(),
        network="YZ",
        station="TEST1",
        start="2009-04-10T00:00:00",
        end="2010-01-01T00:00:00",
        set_end=True,
        propagate=True,
    )
    sta = list_inventory(xml, "YZ", 1)[0]
    assert sta["end"] == "2010-01-01T00:00:00"
    assert all(ch["end"] == "2010-01-01T00:00:00" for ch in sta["channels"])


def test_validate_lat_and_overlap():
    xml = _xml()
    root = parse_root(xml)
    net = root.find(qname("Network"))
    assert net is not None
    sta = el("Station", code="TEST1", startDate="2009-06-01T00:00:00")
    sta.append(el("Latitude", "91"))
    sta.append(el("Longitude", "0"))
    sta.append(el("Elevation", "0"))
    net.append(sta)
    issues = validate_inventory(dumps(root), "YZ", 1)
    codes = {row["code"] for row in issues}
    assert "E_LAT" in codes
    assert "E_EPOCH_OVERLAP" in codes


def test_draft_channel_and_issues_api(stub):
    project = _project(stub)
    later = dict(WIZARD, nrl_later=True, sensor_instconfig=None, datalogger_instconfig=None)
    created = stub.post(f"/api/projects/{project['id']}/wizard", json=later)
    assert created.status_code == 200, created.text
    drafted = stub.put(
        f"/api/projects/{project['id']}/draft",
        json={
            "station": "TEST1",
            "start_time": "2009-04-10T00:00:00",
            "channel": "BHZ",
            "location": "00",
            "azimuth": 33,
            "depth": 2,
        },
    )
    assert drafted.status_code == 200, drafted.text
    preview = stub.get(f"/api/projects/{project['id']}/draft")
    chans = {c["code"]: c for c in preview.json()["draft"]["stations"][0]["channels"]}
    assert chans["BHZ"]["azimuth"] == 33
    assert chans["BHZ"]["depth"] == 2
    assert chans["BHN"]["azimuth"] == 0
    geo = stub.put(
        f"/api/projects/{project['id']}/draft",
        json={
            "station": "TEST1",
            "start_time": "2009-04-10T00:00:00",
            "latitude": 11.1,
            "propagate": False,
        },
    )
    assert geo.status_code == 200, geo.text
    preview = stub.get(f"/api/projects/{project['id']}/draft")
    sta = preview.json()["draft"]["stations"][0]
    assert sta["latitude"] == 11.1
    assert sta["channels"][0]["latitude"] == 76.35
    bad = stub.put(
        f"/api/projects/{project['id']}/draft",
        json={
            "station": "TEST1",
            "start_time": "2009-04-10T00:00:00",
            "latitude": 91,
        },
    )
    assert bad.status_code == 400
    assert "위도" in bad.json()["detail"]
    issues = stub.get(f"/api/projects/{project['id']}/issues")
    assert issues.status_code == 200
    assert issues.json()["source"] == "draft"
    assert issues.json()["issues"] == []
