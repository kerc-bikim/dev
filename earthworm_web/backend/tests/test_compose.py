from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.services.clone import CloneError
from app.services.env import parsed_core
from app.services.startstop_file import parse_startstop

HEADERS = {"X-API-Key": "test-key"}


def _complete(client: TestClient, ew_home: Path) -> None:
    client.put(
        "/api/setup/directories",
        headers=HEADERS,
        json={
            "EW_HOME": str(ew_home),
            "EW_VERSION": "earthworm_8.0",
            "EW_RUN_DIR": str(ew_home / "run_working"),
            "retention_days": 14,
        },
    )
    client.put("/api/setup/installation", headers=HEADERS, json={"EW_INSTALLATION": "INST_UNKNOWN"})
    rings = client.get("/api/setup/defaults", headers=HEADERS).json()["rings"]
    client.put("/api/setup/rings", headers=HEADERS, json={"rings": rings})
    done = client.post("/api/setup/complete", headers=HEADERS)
    assert done.status_code == 200, done.text


def _q330(iid: str, control: int, data: int) -> dict:
    return {
        "family": "q3302ew",
        "id": iid,
        "enabled": True,
        "values": {
            "IPAddress": "10.1.2.3",
            "BasePort": 5330,
            "SerialNumber": "1",
            "AuthCode": "secret-auth",
            "SourcePortControl": control,
            "SourcePortData": data,
            "LC": "0 BHZ 100",
            "RingName": "WAVE_RING",
            "HeartbeatInt": "30",
        },
    }


def test_compose_apply_two_q330_and_audit(ew_home):
    with TestClient(app) as client:
        _complete(client, ew_home)
        board = client.get("/api/compose", headers=HEADERS).json()
        keep = [i for i in board["instances"] if i["id"] != "q3302ew"]
        keep.extend([_q330("q3302ew_sta1", 16030, 16031), _q330("q3302ew_sta2", 16032, 16033)])
        body = {"site": board["site"], "instances": keep, "reconfigure": False}
        r = client.post("/api/compose/apply", headers=HEADERS, json=body)
        assert r.status_code == 200, r.text
        params = Path(parsed_core()["EW_PARAMS"])
        ss = parse_startstop((params / "startstop_unix.d").read_text(encoding="utf-8"))
        assert ss.process_named("q3302ew_sta1") is not None
        assert "q3302ew_sta1 q3302ew_sta1.d" in ss.process_named("q3302ew_sta1").command
        ew = (params / "earthworm.d").read_text(encoding="utf-8")
        assert "MOD_Q3302EW_STA1" in ew
        assert "MOD_Q3302EW_STA2" in ew
        audit = client.get("/api/audit", headers=HEADERS).json()["events"]
        rows = [e for e in audit if e["action"] == "compose_apply" and e["result"] == "ok"]
        assert rows
        assert rows[0]["actor_username"] == "service"
        blob = str(rows[0].get("detail"))
        assert "secret-auth" not in blob


def test_dup_listen_validate_no_write(ew_home):
    with TestClient(app) as client:
        _complete(client, ew_home)
        board = client.get("/api/compose", headers=HEADERS).json()
        inst = [
            {
                "family": "export_scnl",
                "id": "export_scnl_n1",
                "enabled": True,
                "values": {
                    "ServerIPAdr": "0.0.0.0",
                    "ServerPort": 16015,
                    "Send_scnl": "* * * *",
                    "RingName": "WAVE_RING",
                },
            },
            {
                "family": "export_scnl",
                "id": "export_scnl_n2",
                "enabled": True,
                "values": {
                    "ServerIPAdr": "0.0.0.0",
                    "ServerPort": 16015,
                    "Send_scnl": "* * * *",
                    "RingName": "WAVE_RING",
                },
            },
        ]
        r = client.post(
            "/api/compose/validate",
            headers=HEADERS,
            json={"site": board["site"], "instances": inst},
        )
        assert r.status_code == 200
        codes = {i["code"] for i in r.json()["issues"]}
        assert "dup_listen" in codes
        apply = client.post(
            "/api/compose/apply",
            headers=HEADERS,
            json={"site": board["site"], "instances": inst},
        )
        assert apply.status_code == 409
        params = Path(parsed_core()["EW_PARAMS"])
        assert not (params / "export_scnl_n1.d").is_file()


def test_dup_tank_rejected(ew_home):
    with TestClient(app) as client:
        _complete(client, ew_home)
        board = client.get("/api/compose", headers=HEADERS).json()
        tank = "/tmp/same.tnk"
        inst = [
            {
                "family": "wave_serverV",
                "id": "wave_serverV_n1",
                "enabled": False,
                "values": {
                    "ServerIPAdr": "0.0.0.0",
                    "ServerPort": 16022,
                    "Tank": tank,
                    "TankStructFile": "/tmp/a.str",
                    "RingName": "WAVE_RING",
                },
            },
            {
                "family": "wave_serverV",
                "id": "wave_serverV_n2",
                "enabled": False,
                "values": {
                    "ServerIPAdr": "0.0.0.0",
                    "ServerPort": 16023,
                    "Tank": tank,
                    "TankStructFile": "/tmp/b.str",
                    "RingName": "WAVE_RING",
                },
            },
        ]
        r = client.post("/api/compose/validate", headers=HEADERS, json={"site": board["site"], "instances": inst})
        assert "dup_tank" in {i["code"] for i in r.json()["issues"]}


def test_bad_name_400(ew_home):
    with TestClient(app) as client:
        _complete(client, ew_home)
        board = client.get("/api/compose", headers=HEADERS).json()
        inst = [_q330("../etc/passwd", 16030, 16031)]
        inst[0]["id"] = "../etc/passwd"
        r = client.post("/api/compose/validate", headers=HEADERS, json={"site": board["site"], "instances": inst})
        assert r.status_code == 200
        assert "bad_name" in {i["code"] for i in r.json()["issues"]}
        apply = client.post(
            "/api/compose/apply", headers=HEADERS, json={"site": board["site"], "instances": inst}
        )
        assert apply.status_code == 409


def test_max_child_rejected(ew_home, monkeypatch):
    import app.services.compose as compose

    monkeypatch.setattr(compose, "MAX_CHILD", 0)
    with TestClient(app) as client:
        _complete(client, ew_home)
        board = client.get("/api/compose", headers=HEADERS).json()
        # enabling a new process should exceed 0
        inst = [_q330("q3302ew_sta1", 16030, 16031)]
        r = client.post("/api/compose/validate", headers=HEADERS, json={"site": board["site"], "instances": inst})
        assert "max_child" in {i["code"] for i in r.json()["issues"]}


def test_apply_rollback_on_second_clone(ew_home, monkeypatch):
    import app.services.compose as compose
    from app.services.clone import clone_module

    calls = {"n": 0}
    orig = clone_module

    def wrapped(src: str, name: str):
        calls["n"] += 1
        if calls["n"] >= 2:
            raise CloneError("forced fail")
        return orig(src, name)

    monkeypatch.setattr(compose, "clone_module", wrapped)
    with TestClient(app) as client:
        _complete(client, ew_home)
        board = client.get("/api/compose", headers=HEADERS).json()
        keep = [i for i in board["instances"] if i["family"] != "q3302ew"]
        keep.extend([_q330("q3302ew_sta1", 16030, 16031), _q330("q3302ew_sta2", 16032, 16033)])
        r = client.post(
            "/api/compose/apply",
            headers=HEADERS,
            json={"site": board["site"], "instances": keep},
        )
        assert r.status_code == 409, r.text
        params = Path(parsed_core()["EW_PARAMS"])
        assert not (params / "q3302ew_sta1.d").is_file()
        assert not (params / "q3302ew_sta2.d").is_file()


def test_suggest_names(ew_home):
    with TestClient(app) as client:
        _complete(client, ew_home)
        r = client.post("/api/compose/suggest", headers=HEADERS, json={"family": "q3302ew"})
        assert r.status_code == 200, r.text
        assert r.json()["id"].startswith("q3302ew_")
        vals = r.json()["values"]
        assert "SourcePortControl" in vals
        assert vals["IPAddress"] == "0.0.0.0"
        assert vals["LC"] == "0 BHZ 100"
        assert "AuthCode" not in vals


def test_apply_seed_board_ok(ew_home):
    with TestClient(app) as client:
        _complete(client, ew_home)
        board = client.get("/api/compose", headers=HEADERS).json()
        r = client.post("/api/compose/apply", headers=HEADERS, json=board)
        assert r.status_code == 200, r.text
        assert r.json()["ok"] is True


def test_disabled_incomplete_q330_does_not_block_apply(ew_home):
    with TestClient(app) as client:
        _complete(client, ew_home)
        board = client.get("/api/compose", headers=HEADERS).json()
        board["instances"].append(
            {
                "family": "q3302ew",
                "id": "q3302ew_sta1",
                "enabled": False,
                "values": {"RingName": "WAVE_RING", "SourcePortControl": 16032, "SourcePortData": 16033},
            }
        )
        checked = client.post("/api/compose/validate", headers=HEADERS, json=board)
        assert checked.status_code == 200, checked.text
        codes = {(i["code"], i["level"]) for i in checked.json()["issues"]}
        assert ("auth_empty", "warning") in codes
        r = client.post("/api/compose/apply", headers=HEADERS, json=board)
        assert r.status_code == 200, r.text
        params = Path(parsed_core()["EW_PARAMS"])
        assert (params / "q3302ew_sta1.d").is_file()
        audit = client.get("/api/audit", headers=HEADERS).json()["events"]
        rows = [e for e in audit if e["action"] == "compose_apply" and e["result"] == "ok"]
        assert rows


def test_enabled_q330_without_auth_rejected(ew_home):
    with TestClient(app) as client:
        _complete(client, ew_home)
        board = client.get("/api/compose", headers=HEADERS).json()
        inst = _q330("q3302ew_sta1", 16032, 16033)
        inst["values"].pop("AuthCode")
        body = {"site": board["site"], "instances": [inst]}
        r = client.post("/api/compose/apply", headers=HEADERS, json=body)
        assert r.status_code == 409, r.text
        issues = r.json()["detail"]["issues"]
        assert any(i["code"] == "auth_empty" and i["level"] == "error" for i in issues)
        params = Path(parsed_core()["EW_PARAMS"])
        assert not (params / "q3302ew_sta1.d").is_file()
