from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app

HEADERS = {"X-API-Key": "test-key"}


def _complete(client: TestClient, ew_home: Path) -> None:
    r = client.put(
        "/api/setup/directories",
        headers=HEADERS,
        json={
            "EW_HOME": str(ew_home),
            "EW_VERSION": "earthworm_8.0",
            "EW_RUN_DIR": str(ew_home / "run_working"),
            "retention_days": 14,
        },
    )
    assert r.status_code == 200, r.text
    r = client.put(
        "/api/setup/installation",
        headers=HEADERS,
        json={"EW_INSTALLATION": "INST_UNKNOWN"},
    )
    assert r.status_code == 200, r.text
    rings = client.get("/api/setup/defaults", headers=HEADERS).json()["rings"]
    r = client.put("/api/setup/rings", headers=HEADERS, json={"rings": rings})
    assert r.status_code == 200, r.text
    done = client.post("/api/setup/complete", headers=HEADERS)
    assert done.status_code == 200, done.text


def _login(client: TestClient, username: str, password: str) -> TestClient:
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return client


def test_bootstrap_login_and_me(ew_home):
    with TestClient(app) as client:
        assert client.get("/api/auth/status").json()["bootstrap_required"] is True
        r = client.get("/api/setup/status")
        assert r.status_code == 401
        boot = client.post(
            "/api/auth/bootstrap",
            json={"username": "admin1", "display_name": "관리자", "password": "tenchars!!"},
        )
        assert boot.status_code == 200, boot.text
        me = client.get("/api/auth/me")
        assert me.status_code == 200
        assert me.json()["display_name"] == "관리자"
        assert me.json()["role"] == "admin"
        again = client.post(
            "/api/auth/bootstrap",
            json={"username": "admin2", "display_name": "x", "password": "tenchars!!"},
        )
        assert again.status_code == 403


def test_viewer_start_denied_is_audited(ew_home):
    with TestClient(app) as client:
        _complete(client, ew_home)
        client.post(
            "/api/auth/bootstrap",
            json={"username": "admin1", "display_name": "관리자", "password": "tenchars!!"},
        )
        client.post(
            "/api/operators",
            json={
                "username": "view1",
                "display_name": "조회자",
                "password": "viewpass12",
                "role": "viewer",
            },
        )
        client.post("/api/auth/logout")
        _login(client, "view1", "viewpass12")
        start = client.post("/api/control/start")
        assert start.status_code == 403
        audit = client.get("/api/audit").json()
        denied = [e for e in audit["events"] if e["action"] == "control_start" and e["result"] == "denied"]
        assert denied
        assert denied[0]["actor_display_name"] == "조회자"


def test_operator_pau_audit_display_name(ew_home):
    with TestClient(app) as client:
        _complete(client, ew_home)
        client.post(
            "/api/auth/bootstrap",
            json={"username": "admin1", "display_name": "관리자", "password": "tenchars!!"},
        )
        client.post(
            "/api/operators",
            json={
                "username": "op1",
                "display_name": "운영이",
                "password": "operpass12",
                "role": "operator",
            },
        )
        client.post("/api/auth/logout")
        _login(client, "op1", "operpass12")
        client.post("/api/control/start")
        pau = client.post("/api/control/stop")
        assert pau.status_code == 200, pau.text
        audit = client.get("/api/audit").json()["events"]
        rows = [e for e in audit if e["action"] == "control_pau" and e["result"] == "ok"]
        assert rows
        assert rows[0]["actor_display_name"] == "운영이"


def test_login_failed_has_no_password_in_detail(ew_home):
    with TestClient(app) as client:
        client.post(
            "/api/auth/bootstrap",
            json={"username": "admin1", "display_name": "관리자", "password": "tenchars!!"},
        )
        client.post("/api/auth/logout")
        bad = client.post("/api/auth/login", json={"username": "admin1", "password": "wrong-password"})
        assert bad.status_code == 403
        # login as admin again
        _login(client, "admin1", "tenchars!!")
        events = client.get("/api/audit").json()["events"]
        failed = [e for e in events if e["action"] == "login_failed"]
        assert failed
        blob = str(failed[0].get("detail"))
        assert "wrong-password" not in blob
        assert "tenchars" not in blob
        assert "password" not in blob.lower() or "***" in blob or failed[0]["detail"] == {"reason": "invalid"}


def test_last_admin_cannot_disable(ew_home):
    with TestClient(app) as client:
        boot = client.post(
            "/api/auth/bootstrap",
            json={"username": "admin1", "display_name": "관리자", "password": "tenchars!!"},
        )
        op_id = boot.json()["operator"]["id"]
        r = client.patch(f"/api/operators/{op_id}", json={"enabled": False})
        assert r.status_code == 400
        assert "마지막 관리자" in r.text


def test_health_stays_public(ew_home):
    with TestClient(app) as client:
        r = client.get("/api/health")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}


def test_ws_ticket_not_password(ew_home):
    with TestClient(app) as client:
        client.post(
            "/api/auth/bootstrap",
            json={"username": "admin1", "display_name": "관리자", "password": "tenchars!!"},
        )
        t = client.post("/api/auth/ws-ticket")
        assert t.status_code == 200
        assert "ticket" in t.json()
        assert t.json()["ticket"] != "tenchars!!"
