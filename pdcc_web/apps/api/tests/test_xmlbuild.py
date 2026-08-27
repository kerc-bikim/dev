from __future__ import annotations

from app.inventory.xmlbuild import (
    InventoryError,
    add_station,
    apply_response,
    empty_inventory,
    list_inventory,
    orientation,
    station_path,
)

FIXTURE = (
    __import__("pathlib").Path(__file__).resolve().parent / "fixtures" / "nrl" / "stationxml-resp.xml"
)


def test_orientation_from_channel_suffix():
    assert orientation("BHZ") == (0.0, -90.0)
    assert orientation("BHN") == (0.0, 0.0)
    assert orientation("BHE") == (90.0, 0.0)


def test_add_station_three_components():
    xml = empty_inventory("YZ", operator="KIGAM")
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
        channels=["BHZ", "BHN", "BHE"],
        sample_rate=20,
    )
    stations = list_inventory(xml, "YZ")
    assert len(stations) == 1
    chans = {c["code"]: c for c in stations[0]["channels"]}
    assert chans["BHZ"]["azimuth"] == 0
    assert chans["BHZ"]["dip"] == -90
    assert chans["BHE"]["azimuth"] == 90
    assert chans["BHN"]["dip"] == 0
    assert stations[0]["station_path"] == station_path("YZ", "TEST1", "2009-04-10T00:00:00")


def test_rejects_bad_station_and_overlap():
    xml = empty_inventory("YZ")
    try:
        add_station(
            xml,
            network="YZ",
            station="TOOLONG",
            site_name="x",
            start="2009-04-10T00:00:00",
            latitude=0,
            longitude=0,
            elevation=0,
            depth=0,
            channels=["BHZ"],
        )
        assert False
    except InventoryError as exc:
        assert exc.code == "E_CODE_STA"
    xml = add_station(
        xml,
        network="YZ",
        station="TEST1",
        site_name="x",
        start="2009-04-10T00:00:00",
        latitude=0,
        longitude=0,
        elevation=0,
        depth=0,
        channels=["BHZ"],
    )
    try:
        add_station(
            xml,
            network="YZ",
            station="TEST1",
            site_name="x",
            start="2009-04-10T00:00:00",
            latitude=0,
            longitude=0,
            elevation=0,
            depth=0,
            channels=["BHN"],
        )
        assert False
    except InventoryError as exc:
        assert exc.code == "E_EPOCH_OVERLAP"


def test_apply_keeps_azimuth():
    xml = empty_inventory("YZ")
    xml = add_station(
        xml,
        network="YZ",
        station="TEST1",
        site_name="x",
        start="2009-04-10T00:00:00",
        latitude=1,
        longitude=2,
        elevation=3,
        depth=0,
        channels=["BHE", "BHZ"],
        sample_rate=20,
    )
    resp = FIXTURE.read_bytes()
    xml = apply_response(
        xml,
        network="YZ",
        station="TEST1",
        start="2009-04-10T00:00:00",
        location="00",
        channel="BHE",
        response_xml=resp,
        comments=["NRL v2 sensor_x"],
        sample_rate=20,
        replace_existing=True,
    )
    stations = list_inventory(xml, "YZ")
    chans = {c["code"]: c for c in stations[0]["channels"]}
    assert chans["BHE"]["azimuth"] == 90
    assert chans["BHE"]["has_response"] is True
    assert chans["BHZ"]["has_response"] is False
    assert "NRL v2 sensor_x" in xml
