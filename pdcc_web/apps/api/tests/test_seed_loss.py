from __future__ import annotations

from pathlib import Path

from lxml import etree

from app.inventory.seed_convert import COMMENT_MAX, FIR_NAME_MAX
from app.inventory.seed_loss import NOTICES, scan_seed_loss
from app.inventory.xmlbuild import add_station, apply_response, empty_inventory
from app.inventory.xmlutil import dumps, el, parse_root, qname
from tests.test_users import _enable_admin, _name
from tests.test_wizard import WIZARD, _project

LONG_COMMENT = "YZ.TEST1 CMG-3T+Q330HR 설치 메모 " + ("가" * 50)
LONG_FIR = "Q330HR_FIR_STAGE_DECIMATION_FILTER"
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "nrl" / "stationxml-resp.xml"


def _loss_xml(*, comment: str = LONG_COMMENT, fir: str = LONG_FIR) -> str:
    xml = add_station(
        empty_inventory("YZ", operator="KIGAM"),
        network="YZ",
        station="TEST1",
        site_name="Test One",
        start="2009-04-10T00:00:00",
        latitude=76.35,
        longitude=-41.84,
        elevation=80,
        depth=0,
        channels=["BHE"],
        sample_rate=100,
        comments=[comment] if comment else None,
    )
    xml = apply_response(
        xml,
        network="YZ",
        station="TEST1",
        start="2009-04-10T00:00:00",
        location="00",
        channel="BHE",
        response_xml=FIXTURE.read_bytes(),
        comments=[],
        sample_rate=100.0,
        replace_existing=True,
    )
    root = parse_root(xml)
    sta = root.find(f".//{qname('Station')}")
    assert sta is not None
    sta.insert(0, el("Identifier", "10.17611/S7159Q", type="DOI"))
    eq = el("Equipment")
    eq.append(el("Manufacturer", "Guralp"))
    eq.append(el("Model", "CMG-3T"))
    sta.append(eq)
    note = etree.Element("{http://example.org/pdcc-ext}Note")
    note.text = "custom"
    sta.append(note)
    coef = root.find(f".//{qname('Coefficients')}")
    assert coef is not None
    coef.insert(0, el("Name", fir))
    return dumps(root)


def test_scan_truncates_comment_and_fir_and_drops_extensions():
    rows = scan_seed_loss(_loss_xml())
    by_code = {row["code"]: row for row in rows}
    trunc = [row for row in rows if row["code"] == "W_SEED_TRUNC"]
    fir = [row for row in rows if row["code"] == "W_SEED_FIR"]
    ident = [row for row in rows if row["field"] == "identifier"]
    equip = [row for row in rows if row["field"] == "equipment"]
    ext = [row for row in rows if row["field"] == "extension"]
    assert trunc
    assert len(trunc[0]["original"]) > COMMENT_MAX
    assert trunc[0]["seed_value"] == trunc[0]["original"][:COMMENT_MAX]
    assert trunc[0]["limit"] == COMMENT_MAX
    assert "YZ / TEST1 / 00.BHE" in trunc[0]["path"]
    assert fir
    assert len(fir[0]["original"]) > FIR_NAME_MAX
    assert fir[0]["seed_value"] == LONG_FIR[:FIR_NAME_MAX]
    assert ident and "10.17611/S7159Q" in ident[0]["original"]
    assert equip and "Guralp" in equip[0]["original"]
    assert ext and ext[0]["original"] == "Note"
    assert "W_SEED_DROP" in by_code


def test_short_comment_and_fir_are_omitted():
    rows = scan_seed_loss(_loss_xml(comment="short", fir="CMG3T"))
    codes = {row["code"] for row in rows}
    assert "W_SEED_TRUNC" not in codes
    assert "W_SEED_FIR" not in codes
    assert "W_SEED_DROP" in codes


def test_seed_loss_api_and_ack_gate(client):
    client.post("/api/login", json={"username": "stub", "password": "stub"})
    imported = client.post(
        "/api/projects/import",
        json={
            "filename": "yz-test1.xml",
            "xml_text": _loss_xml(),
            "name": "손실 표",
        },
    )
    assert imported.status_code == 200, imported.text
    project_id = imported.json()["id"]
    loss = client.get(f"/api/projects/{project_id}/export/seed-loss")
    assert loss.status_code == 200, loss.text
    body = loss.json()
    assert body["notices"] == list(NOTICES)
    assert body["comment_max"] == 70
    assert body["fir_name_max"] == 25
    assert body["trunc_count"] >= 2
    assert body["drop_count"] >= 3
    assert body["can_export_seed"] is True
    codes = {row["code"] for row in body["rows"]}
    assert {"W_SEED_TRUNC", "W_SEED_FIR", "W_SEED_DROP"} <= codes
    paths = {row["path"] for row in body["rows"]}
    assert any("00.BHE" in path for path in paths)
    ack = body["ack"]
    assert len(ack) == 24
    blocked = client.post(f"/api/projects/{project_id}/export/seed")
    assert blocked.status_code == 409
    detail = blocked.json()["detail"]
    assert detail["code"] == "E_LOSS_ACK"
    assert "손실 목록" in detail["message"]
    assert detail["rows"]
    wrong = client.post(f"/api/projects/{project_id}/export/seed?loss_ack=deadbeef")
    assert wrong.status_code == 409
    assert wrong.json()["detail"]["code"] == "E_LOSS_ACK"
    ok = client.post(f"/api/projects/{project_id}/export/seed?loss_ack={ack}")
    assert ok.status_code == 501
    assert "변환기" in ok.json()["detail"]


def test_unvalidated_still_blocks_before_ack(client):
    client.post("/api/login", json={"username": "stub", "password": "stub"})
    project = _project(client)
    created = client.post(f"/api/projects/{project['id']}/wizard", json=WIZARD)
    assert created.status_code == 200, created.text
    drafted = client.put(
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
    blocked = client.post(f"/api/projects/{project['id']}/export/seed")
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "E_UNVALIDATED"


def test_viewer_can_see_loss_table_not_export(client):
    client.post("/api/login", json={"username": "stub", "password": "stub"})
    imported = client.post(
        "/api/projects/import",
        json={"filename": "yz-test1.xml", "xml_text": _loss_xml(), "name": "조회 손실"},
    )
    project_id = imported.json()["id"]
    client.post("/api/logout")
    _enable_admin(client)
    viewer_name = _name("lossv")
    viewer = client.post(
        "/api/admin/users",
        json={"username": viewer_name, "password": "view1", "role": "viewer"},
    )
    client.put(
        f"/api/projects/{project_id}/members",
        json={"user_id": viewer.json()["id"], "role": "viewer"},
    )
    client.post("/api/logout")
    client.post("/api/login", json={"username": viewer_name, "password": "view1"})
    loss = client.get(f"/api/projects/{project_id}/export/seed-loss")
    assert loss.status_code == 200
    seed = client.post(
        f"/api/projects/{project_id}/export/seed?loss_ack={loss.json()['ack']}"
    )
    assert seed.status_code == 403
    outsider = client.get("/api/projects/999999/export/seed-loss")
    assert outsider.status_code in {403, 404}
