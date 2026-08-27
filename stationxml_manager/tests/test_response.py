from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.crud import list_channels, list_history
from app.errors import ValidationError
from app.response import (
    eval_response_curve,
    overlay_response_curves,
    parse_ids,
    recompute_a0,
    unpaired_conjugates,
    update_pz_stage,
)
from tests.inventories import (
    import_inventory,
    inventory_with_fir,
    inventory_with_pz,
    make_channel,
    make_inventory,
    pz_response,
)
from tests.test_core import _sample_hierarchy
from app.crud import import_hierarchy


def test_png_filename_convention():
    text = Path("frontend/src/charts/pngFilename.ts").read_text(encoding="utf-8")
    assert "${nslc}_${unit}_response.png" in text
    assert "response_compare_${series.length}ch_${unit}.png" in text


def test_parse_ids_and_conjugates():
    assert parse_ids("1,2,2,3") == [1, 2, 3]
    with pytest.raises(ValidationError, match="최대 8"):
        parse_ids("1,2,3,4,5,6,7,8,9")
    with pytest.raises(ValidationError, match="숫자"):
        parse_ids("a,b")
    assert unpaired_conjugates([-0.1 + 0.2j, -0.1 - 0.2j]) is False
    assert unpaired_conjugates([-0.1 + 0.2j]) is True
    assert unpaired_conjugates([-1 + 0j]) is False
    a0 = recompute_a0([-6.28 + 0j], [0j], 1.0, "LAPLACE (RADIANS/SECOND)")
    assert a0 > 0


def test_single_curve_requires_response(session):
    import_hierarchy(
        session, _sample_hierarchy(), replace_all=False, source="ui", actor=None
    )
    ch = list_channels(session)[0]
    with pytest.raises(ValidationError, match="계측기 응답이 없습니다"):
        eval_response_curve(ch)


def test_single_curve_and_nyquist(api_client):
    client, SessionLocal = api_client
    session = SessionLocal()
    try:
        import_inventory(session, inventory_with_pz())
        ch = list_channels(session)[0]
        cid = ch.id
    finally:
        session.close()

    ok = client.get(f"/api/channels/{cid}/response-curve")
    assert ok.status_code == 200
    body = ok.json()
    assert body["output"] == "VEL"
    assert body["npts"] == 200
    assert body["max_freq"] == pytest.approx(50.0)
    assert len(body["frequencies"]) == 200
    assert len(body["amplitude"]) == 200

    bad_nyq = client.get(f"/api/channels/{cid}/response-curve?max_freq=80")
    assert bad_nyq.status_code == 400
    assert "Nyquist" in bad_nyq.json()["detail"]

    bad_out = client.get(f"/api/channels/{cid}/response-curve?output=FOO")
    assert bad_out.status_code == 400

    missing = client.get("/api/channels/9999/response-curve")
    assert missing.status_code == 404


def test_overlay_partial_success_and_limits(api_client):
    client, SessionLocal = api_client
    session = SessionLocal()
    try:
        import_inventory(
            session,
            make_inventory(
                [
                    make_channel("HHZ", 100.0, pz_response()),
                    make_channel("HHN", 40.0, None, start="2020-01-02"),
                ]
            ),
        )
        rows = list_channels(session)
        with_resp = next(ch.id for ch in rows if ch.response_xml)
        without = next(ch.id for ch in rows if not ch.response_xml)
    finally:
        session.close()

    overlay = client.get(f"/api/response-curves?ids={with_resp},{without}")
    assert overlay.status_code == 200
    body = overlay.json()
    assert body["max_freq"] == pytest.approx(20.0)
    assert len(body["series"]) == 1
    assert len(body["errors"]) == 1
    assert "계측기 응답이 없습니다" in body["errors"][0]["reason"]

    empty = client.get(f"/api/response-curves?ids={without}")
    assert empty.status_code == 200
    assert empty.json()["series"] == []
    assert empty.json()["errors"]

    too_many = client.get("/api/response-curves?ids=1,2,3,4,5,6,7,8,9")
    assert too_many.status_code == 400
    assert "최대 8" in too_many.json()["detail"]


def test_pz_edit_success_and_guards(api_client):
    client, SessionLocal = api_client
    session = SessionLocal()
    try:
        import_inventory(session, inventory_with_pz())
        ch = list_channels(session)[0]
        cid = ch.id
        original = ch.response_xml
    finally:
        session.close()

    stages = client.get(f"/api/channels/{cid}/response-stages")
    assert stages.status_code == 200
    pz = next(s for s in stages.json()["stages"] if s["editable"])
    assert pz["type"] == "PolesZeros"

    forbidden = client.put(
        f"/api/channels/{cid}/response-stages/{pz['stage_sequence_number']}",
        json={"normalization_factor": 2.0},
    )
    assert forbidden.status_code == 400
    assert "normalization_factor" in forbidden.json()["detail"]

    saved = client.put(
        f"/api/channels/{cid}/response-stages/{pz['stage_sequence_number']}",
        json={
            "poles": [
                {"real": -0.037, "imag": 0.037},
                {"real": -0.037, "imag": -0.037},
            ],
            "zeros": [{"real": 0.0, "imag": 0.0}],
            "stage_gain": 1500.0,
            "normalization_frequency": 1.0,
        },
        params={"actor": "편집자"},
    )
    assert saved.status_code == 200
    body = saved.json()
    assert "warnings" not in body
    edited = next(s for s in body["stages"] if s["editable"])
    assert edited["normalization_factor"] != pz["normalization_factor"]
    assert edited["stage_gain"] == 1500.0

    session = SessionLocal()
    try:
        ch = list_channels(session)[0]
        assert ch.response_source == "edited"
        assert ch.response_xml != original
        hist = list_history(session, nslc="XX.AAA.--.HHZ")
        pz_logs = [h for h in hist if h.summary and "Poles/Zeros" in h.summary]
        assert pz_logs
        after = json.loads(pz_logs[0].after_json)
        assert after["response_source"] == "edited"
        assert "poles" in after
        assert "response_xml" not in after
    finally:
        session.close()


def test_pz_conjugate_warning_and_fir_rejected(api_client):
    client, SessionLocal = api_client
    session = SessionLocal()
    try:
        import_inventory(session, inventory_with_pz())
        pz_id = list_channels(session)[0].id
        import_inventory(session, inventory_with_fir())
        fir_id = [ch.id for ch in list_channels(session) if ch.id != pz_id][0]
    finally:
        session.close()

    warn = client.put(
        f"/api/channels/{pz_id}/response-stages/1",
        json={
            "poles": [{"real": -0.1, "imag": 0.2}],
            "zeros": [{"real": 0.0, "imag": 0.0}],
        },
    )
    assert warn.status_code == 200
    assert warn.json()["warnings"] == ["켤레가 아닌 극이 있습니다"]

    fir = client.put(
        f"/api/channels/{fir_id}/response-stages/1",
        json={"poles": [{"real": -1.0, "imag": 0.0}]},
    )
    assert fir.status_code == 400
    assert "Poles/Zeros가 아닙니다" in fir.json()["detail"]


def test_pz_evalresp_failure_keeps_blob(session, monkeypatch):
    import_inventory(session, inventory_with_pz())
    ch = list_channels(session)[0]
    original = ch.response_xml

    def boom(*_args, **_kwargs):
        raise ValidationError(f"{ch.channel}: 응답 곡선을 계산하지 못했습니다: boom")

    monkeypatch.setattr("app.response.eval_response_curve", boom)
    with pytest.raises(ValidationError, match="저장하지 않았습니다"):
        update_pz_stage(
            session,
            ch.id,
            1,
            {"poles": [{"real": -1.0, "imag": 0.0}], "zeros": []},
            None,
        )
    session.rollback()
    session.refresh(ch)
    assert ch.response_xml == original
    assert ch.response_source != "edited"


def test_overlay_uses_shared_grid(session):
    import_inventory(
        session,
        make_inventory(
            [
                make_channel("HHZ", 100.0, pz_response()),
                make_channel("HHE", 50.0, pz_response(), start="2020-01-03"),
            ]
        ),
    )
    ids = [ch.id for ch in list_channels(session)]
    result = overlay_response_curves(session, ids)
    assert result["max_freq"] == pytest.approx(25.0)
    assert len(result["series"]) == 2
    assert result["errors"] == []
    assert result["series"][0]["amplitude"]
