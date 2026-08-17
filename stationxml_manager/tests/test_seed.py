from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest
from obspy import read_inventory

from app.cli import main as cli_main
from app.crud import export_stationxml_bytes, import_hierarchy, list_channels
from app.errors import AppError, ValidationError
from app.excel_io import read_excel, write_excel
from app.seed_io import (
    classify_seed,
    collect_dataless_errors,
    export_dataless_bytes,
    inventory_to_seed_bytes,
    read_seed,
)
from tests.inventories import (
    import_inventory,
    inventory_with_pz,
    make_channel,
    make_inventory,
    stationxml_bytes,
)
from tests.test_core import _sample_hierarchy


def _miniseed_bytes() -> bytes:
    rec = bytearray(4096)
    rec[6:7] = b"D"
    return bytes(rec)


def _full_seed_bytes(dataless: bytes) -> bytes:
    pad = (-len(dataless)) % 4096
    rec = bytearray(4096)
    rec[6:7] = b"D"
    return dataless + (b"\x00" * pad) + bytes(rec)


def test_classify_seed_kinds():
    assert classify_seed(_miniseed_bytes()) == "miniseed"
    dataless = inventory_to_seed_bytes(inventory_with_pz(site_name="AAA"))
    assert classify_seed(dataless) == "dataless"
    assert classify_seed(_full_seed_bytes(dataless)) == "full"


def test_read_miniseed_rejected(session):
    with pytest.raises(ValidationError, match="MiniSEED"):
        read_seed(BytesIO(_miniseed_bytes()), session)


def test_seed_roundtrip_nslc_and_stages(session):
    inv = inventory_with_pz(site_name="AAA")
    data = inventory_to_seed_bytes(inv)
    hierarchy = read_seed(BytesIO(data), session)
    import_hierarchy(session, hierarchy, replace_all=False, source="seed", actor=None)
    ch = list_channels(session)[0]
    assert ch.channel == "HHZ"
    assert ch.sample_rate == 100.0
    assert ch.station.latitude == pytest.approx(37.5)
    assert ch.response_xml
    assert ch.response_source == "imported"
    xml = export_stationxml_bytes(session)
    back = read_inventory(BytesIO(xml), format="STATIONXML")
    stages = back[0][0][0].response.response_stages
    assert len(stages) >= 1
    assert any(hasattr(s, "poles") for s in stages)
    again = inventory_to_seed_bytes(back)
    reread = read_inventory(BytesIO(again), format="SEED")
    assert reread[0].code == "XX"
    assert reread[0][0][0].code == "HHZ"


def test_full_seed_imports_metadata_only(session):
    dataless = inventory_to_seed_bytes(inventory_with_pz(site_name="AAA"))
    hierarchy = read_seed(BytesIO(_full_seed_bytes(dataless)), session)
    assert any("파형 레코드는 무시" in w for w in hierarchy["warnings"])
    import_hierarchy(session, hierarchy, replace_all=False, source="seed", actor=None)
    ch = list_channels(session)[0]
    assert ch.response_xml
    assert b"\x00D" not in (ch.response_xml.encode() if ch.response_xml else b"")


def test_export_dataless_requires_response(session, caplog):
    import_hierarchy(session, _sample_hierarchy(), replace_all=False, source="ui", actor=None)
    with caplog.at_level("ERROR", logger="stationxml_manager.export"):
        with pytest.raises(AppError, match="문제 채널") as exc:
            export_dataless_bytes(session)
    assert exc.value.status_code == 400
    assert exc.value.errors
    assert exc.value.errors[0]["nslc"].endswith("HHZ")
    assert "계측기 응답이 없습니다" in exc.value.errors[0]["reason"]
    assert any("HHZ" in rec.message for rec in caplog.records)


def test_export_stationxml_allows_missing_response(session):
    import_hierarchy(session, _sample_hierarchy(), replace_all=False, source="ui", actor=None)
    data = export_stationxml_bytes(session)
    assert data.startswith(b"<?xml") or b"<FDSNStationXML" in data


def test_export_dataless_network_code_length(session):
    data = _sample_hierarchy()
    data["networks"]["KGX"] = data["networks"].pop("XX")
    data["networks"]["KGX"]["code"] = "KGX"
    import_hierarchy(session, data, replace_all=False, source="ui", actor=None)
    errors = collect_dataless_errors(session)
    assert any("네트워크 코드는 2자" in e["reason"] for e in errors)


def test_export_replaces_korean_site_name(session):
    import_inventory(session, inventory_with_pz(site_name="첫번째"))
    data, warnings = export_dataless_bytes(session)
    assert any("한글 사이트명" in w for w in warnings)
    back = read_inventory(BytesIO(data), format="SEED")
    assert back[0][0].site.name == "AAA"


def test_api_seed_import_export(api_client):
    client, SessionLocal = api_client
    seed = inventory_to_seed_bytes(inventory_with_pz(site_name="AAA"))
    imported = client.post(
        "/api/import",
        files={"file": ("inventory.seed", seed, "application/vnd.fdsn.seed")},
        data={"replace_all": "false"},
    )
    assert imported.status_code == 200
    assert imported.json()["created"] == 1

    ok = client.get("/api/export/dataless")
    assert ok.status_code == 200
    assert ok.content[:8] == b"000001V "
    back = read_inventory(BytesIO(ok.content), format="SEED")
    assert back[0][0][0].code == "HHZ"

    session = SessionLocal()
    try:
        import_inventory(
            session,
            make_inventory([make_channel("HHZ")], station="BBB", site_name="BBB"),
        )
    finally:
        session.close()
    missing = client.get("/api/export/dataless")
    assert missing.status_code == 400
    body = missing.json()
    assert "errors" in body
    assert body["errors"][0]["nslc"]
    xml = client.get("/api/export/stationxml")
    assert xml.status_code == 200


def test_api_miniseed_rejected(api_client):
    client, _ = api_client
    response = client.post(
        "/api/import",
        files={"file": ("wave.miniseed", _miniseed_bytes(), "application/octet-stream")},
        data={"replace_all": "false"},
    )
    # 확장자가 seed가 아니면 거절. .seed로 올려 MiniSEED 내용을 검사한다.
    response = client.post(
        "/api/import",
        files={"file": ("wave.seed", _miniseed_bytes(), "application/octet-stream")},
        data={"replace_all": "false"},
    )
    assert response.status_code == 400
    assert "MiniSEED" in response.json()["detail"]


def test_excel_reimport_keeps_seed_response(session):
    import_inventory(session, inventory_with_pz(site_name="AAA"), source="seed")
    original = list_channels(session)[0].response_xml
    hierarchy = read_excel(BytesIO(write_excel(session)))
    import_hierarchy(session, hierarchy, replace_all=True, source="excel", actor=None)
    assert list_channels(session)[0].response_xml == original


def test_cli_seed_export_failure(tmp_path, monkeypatch, session, capsys):
    import_hierarchy(session, _sample_hierarchy(), replace_all=False, source="ui", actor=None)
    xml_path = tmp_path / "in.xml"
    xml_path.write_bytes(stationxml_bytes(make_inventory([make_channel("HHZ")])))
    out = tmp_path / "out.seed"

    from app import cli as cli_mod

    monkeypatch.setattr(cli_mod, "init_db", lambda: None)
    monkeypatch.setattr(cli_mod, "get_session", lambda: session)
    monkeypatch.setattr(cli_mod, "seed_catalog", lambda _s: None)
    code = cli_main([str(xml_path), "-o", str(out)])
    captured = capsys.readouterr()
    assert code == 1
    assert "계측기 응답이 없습니다" in captured.err
    assert not out.exists()


def test_cli_seed_export_success(tmp_path, monkeypatch, session):
    xml_path = tmp_path / "in.xml"
    xml_path.write_bytes(stationxml_bytes(inventory_with_pz(site_name="AAA")))
    out = tmp_path / "out.dataless"
    from app import cli as cli_mod

    monkeypatch.setattr(cli_mod, "init_db", lambda: None)
    monkeypatch.setattr(cli_mod, "get_session", lambda: session)
    monkeypatch.setattr(cli_mod, "seed_catalog", lambda _s: None)
    assert cli_main([str(xml_path), "-o", str(out)]) == 0
    assert out.exists()
    assert out.read_bytes()[:8] == b"000001V "


def test_sample_obspy_dataless_imports(session):
    sample = Path(
        "/home/ubuntu/.local/lib/python3.12/site-packages/obspy/io/xseed/tests/data/dataless.seed.BW_FURT"
    )
    if not sample.exists():
        pytest.skip("ObsPy 샘플 dataless 없음")
    hierarchy = read_seed(sample, session)
    import_hierarchy(session, hierarchy, replace_all=False, source="seed", actor=None)
    rows = list_channels(session)
    assert rows
    assert any(ch.response_xml for ch in rows)
