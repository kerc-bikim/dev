"""ADR 0002: 화이트리스트 왕복 테스트."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.stationxml.compare import diff_whitelist, extract_whitelist, values_equal
from app.stationxml.patch import (
    identity_roundtrip,
    replace_channel_response,
    roundtrip_via_obspy_write,
    set_station_latitude,
)
from app.stationxml.whitelist import SCHEMA_VERSION

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "stationxml"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_decimal_normalization():
    assert values_equal("1.5E3", "1500")
    assert values_equal("1.2e9", "1200000000")
    assert not values_equal("76.35", "76.40")


def test_identity_roundtrip_keeps_whitelist():
    original = _read("YZ.TEST1.bhe-bhn-bhz.xml")
    patched = identity_roundtrip(original)
    diffs = diff_whitelist(original, patched)
    assert diffs == [], diffs
    snap = extract_whitelist(patched)
    assert snap["schemaVersion"] == SCHEMA_VERSION
    assert snap["Source"] == "unit-test"
    assert snap["Module"] == "stationxml_manager"
    assert "keep-me-document-comment" in snap["xml_comments"]


def test_latitude_only_change_leaves_comments_identifiers_response():
    original = _read("YZ.TEST1.bhe-bhn-bhz.xml")
    patched = set_station_latitude(
        original, "YZ", "TEST1", "76.40", start_date="2009-04-10T00:00:00Z"
    )
    diffs = diff_whitelist(original, patched)
    assert len(diffs) == 1, diffs
    assert diffs[0].path.endswith("Latitude/value")
    assert diffs[0].before == "76.35"
    assert diffs[0].after == "76.40"

    before = extract_whitelist(original)
    after = extract_whitelist(patched)
    sta_b = before["networks"]["YZ#2009-04-10T00:00:00Z"]["stations"][
        "TEST1#2009-04-10T00:00:00Z"
    ]
    sta_a = after["networks"]["YZ#2009-04-10T00:00:00Z"]["stations"][
        "TEST1#2009-04-10T00:00:00Z"
    ]
    assert sta_b["Comment"] == sta_a["Comment"]
    assert sta_b["Identifier"] == sta_a["Identifier"]
    ch_key = "00.BHE#2009-04-10T00:00:00Z"
    assert sta_b["channels"][ch_key]["Response"] == sta_a["channels"][ch_key]["Response"]
    assert sta_b["channels"][ch_key]["Latitude"] == sta_a["channels"][ch_key]["Latitude"]


def test_replace_response_keeps_sensor_extra():
    original = _read("YZ.TEST1.bhe-bhn-bhz.xml")
    new_resp = _read("replacement-response.xml")
    patched = replace_channel_response(
        original,
        "YZ",
        "TEST1",
        "00",
        "BHE",
        new_resp,
        start_date="2009-04-10T00:00:00Z",
    )
    before = extract_whitelist(original)
    after = extract_whitelist(patched)
    sta_b = before["networks"]["YZ#2009-04-10T00:00:00Z"]["stations"][
        "TEST1#2009-04-10T00:00:00Z"
    ]
    sta_a = after["networks"]["YZ#2009-04-10T00:00:00Z"]["stations"][
        "TEST1#2009-04-10T00:00:00Z"
    ]
    ch_b = sta_b["channels"]["00.BHE#2009-04-10T00:00:00Z"]
    ch_a = sta_a["channels"]["00.BHE#2009-04-10T00:00:00Z"]
    assert ch_b["Response"] != ch_a["Response"]
    assert "9.9e8" in ch_a["Response"] or "9.9E8" in ch_a["Response"]
    assert ch_b["Sensor"][0]["extra"] == ch_a["Sensor"][0]["extra"]
    assert ch_a["Sensor"][0]["extra"], "gfz Identifier extra 가 유지되어야 합니다"
    assert sta_b["channels"]["00.BHN#2009-04-10T00:00:00Z"]["Response"] == (
        sta_a["channels"]["00.BHN#2009-04-10T00:00:00Z"]["Response"]
    )


def test_patch_keeps_two_agencies_obspy_write_does_not():
    original = _read("two-agencies.xml")
    patched = identity_roundtrip(original)
    snap = extract_whitelist(patched)
    agencies = snap["networks"]["YZ#2009-04-10T00:00:00Z"]["Operator"][0]["agencies"]
    assert agencies == ["First Agency", "Second Agency"]
    assert "keep-two-agencies" in snap["xml_comments"]

    via_obspy = roundtrip_via_obspy_write(original)
    obspy_snap = extract_whitelist(via_obspy)
    obspy_agencies = obspy_snap["networks"]["YZ#2009-04-10T00:00:00Z"]["Operator"][0][
        "agencies"
    ]
    assert obspy_agencies == ["First Agency"]
    assert "keep-two-agencies" not in obspy_snap["xml_comments"]
    diffs = diff_whitelist(original, via_obspy)
    paths = [d.path for d in diffs]
    assert any("Operator" in p and "agencies" in p for p in paths)


def test_extract_rejects_non_stationxml():
    with pytest.raises(ValueError):
        extract_whitelist("<root/>")
