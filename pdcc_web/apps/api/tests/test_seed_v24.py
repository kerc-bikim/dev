"""SEED Manual V2.4 dataless 메타데이터 입·출력."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

from obspy import read_inventory
from obspy.io.xseed import Parser

from app.inventory.importers import inspect_upload
from app.inventory.seed_convert import classify_seed, convert_dataless_to_xml, convert_xml_to_dataless
from app.inventory.seed_loss import scan_seed_loss
from app.inventory.xmlbuild import InventoryError, add_station, apply_response, empty_inventory
from app.inventory.xmlutil import dumps, el, parse_root, qname

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "nrl" / "stationxml-resp.xml"
RECORD = 4096


def _xml(*, network: str = "YZ", depth: float = 1.2, site: str = "Test One", comment: str | None = None) -> str:
    xml = add_station(
        empty_inventory(network, operator="KIGAM"),
        network=network,
        station="TEST1",
        site_name=site,
        start="2009-04-10T00:00:00",
        latitude=76.35,
        longitude=-41.84,
        elevation=80.4,
        depth=depth,
        channels=["BHZ", "BHN", "BHE"],
        sample_rate=20,
        comments=[comment] if comment else None,
    )
    raw = FIXTURE.read_bytes()
    for channel in ("BHZ", "BHN", "BHE"):
        xml = apply_response(
            xml,
            network=network,
            station="TEST1",
            start="2009-04-10T00:00:00",
            location="00",
            channel=channel,
            response_xml=raw,
            comments=[],
            sample_rate=20.0,
            replace_existing=True,
        )
    return xml


def _as_list(value) -> list:
    if value is None:
        return []
    if isinstance(value, (int, float)):
        return [float(value)]
    return [float(item) for item in value]


def test_v24_dataless_volume_has_required_control_headers():
    data, engine = convert_xml_to_dataless(_xml(), organization="KIGAM", label="YZ")
    assert engine == "obspy"
    assert classify_seed(data) == "dataless"
    assert len(data) % RECORD == 0
    types = [data[off + 6 : off + 7].decode() for off in range(0, len(data), RECORD)]
    assert set(types) <= {"V", "A", "S"}
    assert types[0] == "V"
    assert "A" in types and "S" in types
    assert types.count("V") == 1
    body = data[8:RECORD]
    assert body.startswith(b"010")
    assert b"011" in data[:RECORD]
    parser = Parser(BytesIO(data), strict=False)
    assert parser.volume[0].version_of_format == 2.4
    assert parser.volume[0].logical_record_length == 12
    assert b"KIGAM" in bytes(parser.volume[0].originating_organization)
    abbr = {blkt.id for blkt in parser.abbreviations}
    assert {30, 33, 34} <= abbr
    station = parser.stations[0]
    ids = [blkt.id for blkt in station]
    assert ids[0] == 50
    assert ids.count(52) == 3
    assert any(blkt.id == 53 for blkt in station)
    assert any(blkt.id == 54 for blkt in station)
    assert any(blkt.id == 57 for blkt in station)
    stage0 = [
        blkt
        for blkt in station
        if blkt.id == 58 and blkt.stage_sequence_number == 0
    ]
    assert len(stage0) == 3
    b50 = station[0]
    assert b50.station_call_letters.strip() == "TEST1"
    assert b50.network_code.strip() == "YZ"
    assert float(b50.latitude) == 76.35
    assert float(b50.longitude) == -41.84


def test_v24_metadata_roundtrip_preserves_station_channel_response():
    xml = _xml(comment="vault door facing north")
    data, _ = convert_xml_to_dataless(xml, organization="KIGAM", label="YZ")
    back, notes = convert_dataless_to_xml(data)
    assert any(row["code"] == "W_SEED_CONVERT" for row in notes)
    uploaded = inspect_upload(data, "YZ.TEST1.dataless")
    assert uploaded["kind"] == "dataless"
    assert uploaded["network_code"] == "YZ"
    assert uploaded["station_count"] == 1
    assert uploaded["channel_count"] == 3

    src = read_inventory(BytesIO(xml.encode()), format="STATIONXML")
    dst = read_inventory(BytesIO(back.encode()), format="STATIONXML")
    s0, s1 = src[0][0], dst[0][0]
    assert src[0].code == dst[0].code == "YZ"
    assert s0.code == s1.code == "TEST1"
    assert s0.latitude == s1.latitude
    assert s0.longitude == s1.longitude
    assert s0.elevation == s1.elevation
    assert s0.site.name == s1.site.name == "Test One"
    assert s0.start_date == s1.start_date
    assert s0.end_date is None and s1.end_date is None
    for cha0 in s0:
        cha1 = s1.select(channel=cha0.code, location=cha0.location_code)[0]
        assert cha0.azimuth == cha1.azimuth
        assert cha0.dip == cha1.dip
        assert cha0.sample_rate == cha1.sample_rate
        assert cha0.depth == cha1.depth == 1.2
        assert cha0.latitude == cha1.latitude
        assert cha0.response.instrument_sensitivity.value == (
            cha1.response.instrument_sensitivity.value
        )
        def unit_name(value) -> str:
            return str(getattr(value, "name", None) or value or "").upper()

        assert unit_name(cha0.response.instrument_sensitivity.input_units) == unit_name(
            cha1.response.instrument_sensitivity.input_units
        )
        assert len(cha0.response.response_stages) == len(cha1.response.response_stages) == 2
    parser = Parser(BytesIO(data), strict=False)
    pz = next(blkt for blkt in parser.stations[0] if blkt.id == 53)
    assert pz.transfer_function_types == "A"
    assert _as_list(pz.real_zero) == [0.0]
    assert _as_list(pz.real_pole) == [-4.39823, -4.39823]
    comments = [blkt for blkt in parser.abbreviations if blkt.id == 31]
    assert comments
    assert any("vault door facing north" in str(getattr(blkt, "description_of_comment", "")) for blkt in comments)


def test_v24_refuses_network_longer_than_two_and_lists_loss():
    xml = _xml(network="ABCD")
    rows = scan_seed_loss(xml)
    assert any(row["code"] == "E_SEED_NET" for row in rows)
    try:
        convert_xml_to_dataless(xml)
        assert False
    except InventoryError as exc:
        assert exc.code == "E_EXPORT"
        assert "2자" in str(exc)


def test_v24_korean_site_and_depth_precision_in_loss():
    xml = _xml(depth=1.25, site="테스트 관측소")
    rows = {row["code"]: row for row in scan_seed_loss(xml)}
    assert rows["W_SEED_SITE"]["seed_value"] == "TEST1"
    assert rows["W_SEED_PREC"]["seed_value"] == "1.2"
    data, _ = convert_xml_to_dataless(xml)
    back = read_inventory(BytesIO(convert_dataless_to_xml(data)[0].encode()), format="STATIONXML")
    assert back[0][0].site.name == "TEST1"
    assert back[0][0][0].depth == 1.2


def test_v24_requires_stage_gain_zero_and_digital_decimation():
    xml = _xml()
    root = parse_root(xml)
    for sens in root.findall(f".//{qname('InstrumentSensitivity')}"):
        parent = sens.getparent()
        if parent is not None:
            parent.remove(sens)
    try:
        convert_xml_to_dataless(dumps(root))
        assert False
    except InventoryError as exc:
        assert "058" in str(exc) or "감도" in str(exc)

    xml = _xml()
    root = parse_root(xml)
    for decim in root.findall(f".//{qname('Decimation')}"):
        parent = decim.getparent()
        if parent is not None:
            parent.remove(decim)
    stripped = dumps(root)
    assert any(row["code"] == "E_SEED_DECIM" for row in scan_seed_loss(stripped))
    try:
        convert_xml_to_dataless(stripped)
        assert False
    except InventoryError as exc:
        assert "057" in str(exc) or "데시메이션" in str(exc)
