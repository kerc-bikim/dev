from __future__ import annotations

import pytest
from app.nrl.client import set_nrl_client

from tests.test_nrl_api import FakeNrl
from tests.test_wizard import WIZARD, _project
from app.inventory.xmlbuild import parse_clone_paste


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


S7_PASTE = """TST2	Site Two	76.36	-41.85	81
		76.40
TST3	Site Three	76.37	-41.86	82
TST4	Site Four	76.38	-41.87	83
TST5	Site Five	76.39	-41.88	84
"""


def test_parse_clone_paste_skips_blank_and_empty_code():
    rows = parse_clone_paste(S7_PASTE)
    assert [row["code"] for row in rows] == ["TST2", "", "TST3", "TST4", "TST5"]
    assert rows[1]["latitude"] == "76.40"
    headed = parse_clone_paste("코드\t위도\nAA\t1\n\t\nBB\t2\n")
    assert [row["code"] for row in headed] == ["AA", "BB"]
    assert headed[0]["latitude"] == "1"


def test_s7_clone_ignores_empty_code_and_copies_response(stub):
    project = _project(stub)
    created = stub.post(f"/api/projects/{project['id']}/wizard", json=WIZARD)
    assert created.status_code == 200, created.text
    source = created.json()["project"]["stations"][0]
    assert all(ch["has_response"] for ch in source["channels"])

    cloned = stub.post(
        f"/api/projects/{project['id']}/clone-stations",
        json={
            "source_station": "TEST1",
            "source_start": "2009-04-10T00:00:00",
            "paste": S7_PASTE,
        },
    )
    assert cloned.status_code == 200, cloned.text
    body = cloned.json()
    assert [row["code"] for row in body["created"]] == ["TST2", "TST3", "TST4", "TST5"]
    assert any(row["reason"] == "empty_code" for row in body["skipped"])
    project_body = body["project"]
    assert project_body["station_count"] == 5
    codes = {sta["code"] for sta in project_body["stations"]}
    assert codes == {"TEST1", "TST2", "TST3", "TST4", "TST5"}
    copies = [sta for sta in project_body["stations"] if sta["code"] != "TEST1"]
    assert len(copies) == 4
    assert all(len(sta["channels"]) == 3 for sta in copies)
    assert all(ch["has_response"] for sta in copies for ch in sta["channels"])
    tst2 = next(sta for sta in copies if sta["code"] == "TST2")
    assert tst2["latitude"] == 76.36
    assert tst2["site_name"] == "Site Two"
    xml = stub.get(f"/api/projects/{project['id']}/xml")
    assert xml.status_code == 200
    assert xml.text.count("<Response") == 15


def test_clone_empty_cells_inherit_source(stub):
    project = _project(stub)
    assert stub.post(f"/api/projects/{project['id']}/wizard", json=WIZARD).status_code == 200
    cloned = stub.post(
        f"/api/projects/{project['id']}/clone-stations",
        json={
            "source_station": "TEST1",
            "source_start": "2009-04-10T00:00:00",
            "rows": [{"code": "AA1", "comment": "copy", "serial": "SN-01"}],
        },
    )
    assert cloned.status_code == 200, cloned.text
    sta = next(row for row in cloned.json()["project"]["stations"] if row["code"] == "AA1")
    assert sta["latitude"] == 76.35
    assert sta["longitude"] == -41.84
    assert sta["elevation"] == 80
    assert sta["site_name"] == "Test One"
    xml = stub.get(f"/api/projects/{project['id']}/xml").text
    assert "copy" in xml
    assert "SN-01" in xml


def test_clone_rejects_empty_batch_and_overlap(stub):
    project = _project(stub)
    stub.post(f"/api/projects/{project['id']}/wizard", json=WIZARD)
    empty = stub.post(
        f"/api/projects/{project['id']}/clone-stations",
        json={
            "source_station": "TEST1",
            "source_start": "2009-04-10T00:00:00",
            "rows": [{"code": ""}, {"code": "   "}],
        },
    )
    assert empty.status_code == 400
    clash = stub.post(
        f"/api/projects/{project['id']}/clone-stations",
        json={
            "source_station": "TEST1",
            "source_start": "2009-04-10T00:00:00",
            "rows": [{"code": "TEST1"}],
        },
    )
    assert clash.status_code == 400
    long_serial = stub.post(
        f"/api/projects/{project['id']}/clone-stations",
        json={
            "source_station": "TEST1",
            "source_start": "2009-04-10T00:00:00",
            "rows": [{"code": "BB1", "serial": "x" * 31}],
        },
    )
    assert long_serial.status_code == 400
