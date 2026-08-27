from __future__ import annotations

from io import BytesIO

from obspy import read_inventory

from app.export.convert import classify_seed, preview_export, render_export
from app.export.slice import slice_stationxml
from app.inventory.xmlbuild import add_station, apply_response, empty_inventory

FIXTURE = (
    __import__("pathlib").Path(__file__).resolve().parent
    / "fixtures"
    / "nrl"
    / "stationxml-resp.xml"
)


def _station_xml(*, site_name: str = "Test One", comments: list[str] | None = None) -> str:
    xml = empty_inventory("YZ", operator="KIGAM")
    xml = add_station(
        xml,
        network="YZ",
        station="TEST1",
        site_name=site_name,
        start="2009-04-10T00:00:00",
        latitude=76.35,
        longitude=-41.84,
        elevation=80,
        depth=0,
        channels=["BHZ", "BHN", "BHE"],
        sample_rate=20,
        comments=comments or ["NRL v2 fixture"],
    )
    payload = FIXTURE.read_bytes()
    for code in ("BHZ", "BHN", "BHE"):
        xml = apply_response(
            xml,
            network="YZ",
            station="TEST1",
            start="2009-04-10T00:00:00",
            location="00",
            channel=code,
            response_xml=payload,
            comments=[],
            sample_rate=20,
            replace_existing=True,
        )
    return xml


def test_slice_does_not_change_source_string():
    xml = _station_xml()
    original = xml
    sliced = slice_stationxml(
        xml, network="YZ", station="TEST1", start="2009-04-10T00:00:00", nslc="00.BHZ"
    )
    assert original == xml
    assert sliced.count("<Channel") == 1
    assert "BHZ" in sliced
    assert "BHE" not in sliced or sliced.count('code="BHE"') == 0


def test_resp_single_channel_is_evalresp_text():
    xml = _station_xml()
    result = render_export(
        xml,
        kind="resp",
        network="YZ",
        station="TEST1",
        start="2009-04-10T00:00:00",
        nslc="00.BHZ",
    )
    assert result.filename.startswith("RESP.")
    text = result.data.decode("ascii")
    assert "B050F03" in text
    assert "TEST1" in text
    assert "BHZ" in text
    inv = read_inventory(BytesIO(result.data), format="RESP")
    assert inv[0][0][0].code == "BHZ"


def test_resp_station_is_zip():
    xml = _station_xml()
    result = render_export(xml, kind="resp", network="YZ", station="TEST1")
    assert result.filename.endswith(".zip")
    assert result.media_type == "application/zip"
    assert result.channel_count == 3


def test_dataless_roundtrip():
    xml = _station_xml()
    before = xml
    result = render_export(xml, kind="dataless", network="YZ", station="TEST1")
    assert before == xml
    assert classify_seed(result.data) == "dataless"
    back = read_inventory(BytesIO(result.data), format="SEED")
    assert back[0].code == "YZ"
    assert back[0][0].code == "TEST1"
    codes = {ch.code for ch in back[0][0]}
    assert codes == {"BHZ", "BHN", "BHE"}


def test_missing_response_blocks_dataless():
    xml = empty_inventory("YZ")
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
    preview = preview_export(xml, kind="dataless", network="YZ")
    assert preview["blocked"] is True
    assert any(item["field"] == "response" for item in preview["errors"])


def test_long_comment_requires_confirm():
    xml = _station_xml(comments=["NRL v2 " + ("comment-check-" * 8)])
    preview = preview_export(xml, kind="dataless", network="YZ")
    assert preview["needs_confirm"] is True
    assert any(item["field"] == "comment" for item in preview["losses"])
    try:
        render_export(xml, kind="dataless", network="YZ", accept_losses=False)
        assert False, "expected ExportError"
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 409
    result = render_export(xml, kind="dataless", network="YZ", accept_losses=True)
    assert classify_seed(result.data) == "dataless"


def test_korean_site_name_is_loss():
    xml = _station_xml(site_name="테스트관측소")
    preview = preview_export(xml, kind="dataless", network="YZ")
    assert any(item["kind"] == "replace" for item in preview["losses"])
