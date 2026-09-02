from __future__ import annotations

import io
import json
import zipfile
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select

from app.config import INSECURE_SECRET, Settings
from app.db import SessionLocal
from app.inventory.xmlbuild import empty_inventory
from app.models import AuditLog, Project, StationLock, User
from app.runtime import apply_runtime_policy, collect_policy_issues, RuntimePolicyError
from app.seed import seed_users


def _login(client, username="stub", password="stub"):
    response = client.post("/api/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return response


def test_live_ok(client):
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert client.get("/api/health/live").json() == {"ok": True}


def test_ready_matches_health(client):
    health = client.get("/health")
    ready = client.get("/health/ready")
    assert health.status_code == 200
    assert ready.status_code == 200
    assert health.json() == ready.json() == {"ok": True, "db": True, "redis": True}


def test_request_id_echo_and_generated(client):
    echoed = client.get("/health/live", headers={"X-Request-ID": "ops-test-id"})
    assert echoed.headers.get("x-request-id") == "ops-test-id"
    generated = client.get("/health/live")
    assert generated.headers.get("x-request-id")
    assert generated.headers.get("x-request-id") != "ops-test-id"


def test_session_cookie_httponly_samesite(client):
    response = _login(client)
    header = response.headers.get("set-cookie") or ""
    assert "pdcc_session=" in header
    assert "HttpOnly" in header
    assert "samesite=lax" in header.lower()
    assert "secure" not in header.lower()


def test_stub_login_rejected_when_disabled(client):
    from app.config import settings

    settings.allow_stub_login = False
    try:
        response = client.post("/api/login", json={"username": "stub", "password": "stub"})
        assert response.status_code == 403
        assert "ALLOW_STUB_LOGIN" in response.json()["detail"]
    finally:
        settings.allow_stub_login = True


def test_production_policy_fail_closed():
    cfg = Settings(
        app_env="production",
        app_secret=INSECURE_SECRET,
        allow_stub_login=True,
        dev_bootstrap_admin=True,
    )
    warnings, errors = collect_policy_issues(cfg)
    assert not warnings
    assert any("APP_SECRET" in msg for msg in errors)
    assert any("DEV_BOOTSTRAP_ADMIN" in msg for msg in errors)
    assert any("ALLOW_STUB_LOGIN" in msg for msg in errors)
    try:
        apply_runtime_policy(cfg)
        raise AssertionError("should fail closed")
    except RuntimePolicyError:
        pass


def test_production_policy_ok_with_secret():
    cfg = Settings(
        app_env="production",
        app_secret="unit-test-secret-not-default",
        allow_stub_login=False,
        dev_bootstrap_admin=False,
        session_cookie_secure=True,
    )
    warnings, errors = collect_policy_issues(cfg)
    assert errors == []
    assert warnings == []


def test_audit_requires_login(client):
    assert client.get("/api/ops/audit").status_code == 401


def test_audit_lists_project_create(client):
    _login(client)
    created = client.post(
        "/api/projects",
        json={"name": "YZ 상시망", "network_code": "YZ", "operator": "KIGAM"},
    )
    assert created.status_code == 200, created.text
    project_id = created.json()["id"]
    listing = client.get("/api/ops/audit")
    assert listing.status_code == 200
    body = listing.json()
    assert body["total"] >= 1
    assert body["retention_days"] == 365
    actions = {row["action"] for row in body["items"]}
    assert "create" in actions
    filtered = client.get(f"/api/ops/audit?project_id={project_id}&action=create")
    assert filtered.status_code == 200
    assert filtered.json()["items"][0]["target"] == "YZ"


def test_ops_status(client):
    _login(client)
    response = client.get("/api/ops/status")
    assert response.status_code == 200
    body = response.json()
    assert body["env"] == "development"
    assert body["allow_stub_login"] is True
    assert body["production"] is False
    assert body["session_cookie_samesite"] == "lax"
    assert body["username"] == "stub"


def test_backup_and_restore_roundtrip(client):
    _login(client)
    created = client.post(
        "/api/projects",
        json={"name": "YZ 상시망", "network_code": "YZ", "operator": "KIGAM"},
    )
    assert created.status_code == 200
    source_id = created.json()["id"]
    xml = client.get(f"/api/projects/{source_id}/xml")
    assert xml.status_code == 200
    assert b"FDSNStationXML" in xml.content

    backup = client.get("/api/ops/backup")
    assert backup.status_code == 200
    assert backup.headers["content-type"].startswith("application/zip")
    disposition = backup.headers.get("content-disposition", "")
    assert "pdcc-stationxml-" in disposition
    with zipfile.ZipFile(io.BytesIO(backup.content)) as zf:
        names = zf.namelist()
        assert "manifest.json" in names
        manifest = json.loads(zf.read("manifest.json"))
        assert manifest["format"] == "pdcc-stationxml-backup-v1"
        assert manifest["project_count"] >= 1
        xml_files = [n for n in names if n.endswith(".xml")]
        assert xml_files
        assert b"FDSNStationXML" in zf.read(xml_files[0])

    restored = client.post(
        "/api/ops/restore",
        content=backup.content,
        headers={"Content-Type": "application/zip"},
    )
    assert restored.status_code == 200, restored.text
    body = restored.json()
    assert body["count"] >= 1
    assert body["created"]
    new_id = body["created"][0]["id"]
    assert new_id != source_id
    copied = client.get(f"/api/projects/{new_id}/xml")
    assert copied.status_code == 200
    assert b"FDSNStationXML" in copied.content
    assert b'code="YZ"' in copied.content
    assert b"<Source>PDCC</Source>" in copied.content

    audit = client.get("/api/ops/audit?action=restore")
    assert audit.json()["total"] >= 1


def test_restore_single_xml(client):
    _login(client)
    xml_text = empty_inventory("AB", operator="KIGAM")
    restored = client.post(
        "/api/ops/restore",
        content=xml_text.encode("utf-8"),
        headers={"Content-Type": "application/xml"},
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["created"][0]["network_code"] == "AB"


def test_restore_rejects_zip_slip(client):
    _login(client)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../evil.xml", empty_inventory("EV"))
        zf.writestr("manifest.json", json.dumps({"format": "pdcc-stationxml-backup-v1"}))
    slipped = client.post(
        "/api/ops/restore",
        content=buf.getvalue(),
        headers={"Content-Type": "application/zip"},
    )
    assert slipped.status_code == 400


def test_replace_restore_forbidden_for_editor(client):
    _login(client)
    created = client.post(
        "/api/projects",
        json={"name": "YZ", "network_code": "YZ"},
    )
    backup = client.get("/api/ops/backup")
    denied = client.post(
        "/api/ops/restore?replace=true",
        content=backup.content,
        headers={"Content-Type": "application/zip"},
    )
    assert denied.status_code == 403


def test_audit_purge_forbidden_for_editor(client):
    _login(client)
    response = client.post("/api/ops/audit/purge")
    assert response.status_code == 403


def test_bootstrap_status_false_when_users_exist(client):
    response = client.get("/api/ops/bootstrap")
    assert response.status_code == 200
    assert response.json() == {"available": False}
    taken = client.post(
        "/api/ops/bootstrap",
        json={"username": "operator1", "password": "secret-pass"},
    )
    assert taken.status_code == 409


def test_bootstrap_creates_first_admin(client):
    db = SessionLocal()
    try:
        db.execute(delete(AuditLog))
        db.execute(delete(StationLock))
        db.execute(delete(Project))
        db.execute(delete(User))
        db.commit()
    finally:
        db.close()
    available = client.get("/api/ops/bootstrap")
    assert available.json() == {"available": True}
    created = client.post(
        "/api/ops/bootstrap",
        json={"username": "operator1", "password": "secret-pass"},
    )
    assert created.status_code == 200, created.text
    assert created.json() == {"ok": True, "username": "operator1", "role": "admin"}
    login = client.post(
        "/api/login", json={"username": "operator1", "password": "secret-pass"}
    )
    assert login.status_code == 200
    assert login.json()["role"] == "admin"
    reserved = client.post(
        "/api/ops/bootstrap",
        json={"username": "other", "password": "secret-pass"},
    )
    assert reserved.status_code == 409
    db = SessionLocal()
    try:
        seed_users(db)
    finally:
        db.close()


def test_seed_skips_stub_when_disabled(client):
    from app.config import settings

    settings.allow_stub_login = False
    db = SessionLocal()
    try:
        db.execute(delete(AuditLog))
        db.execute(delete(StationLock))
        db.execute(delete(Project))
        db.execute(delete(User))
        db.commit()
        seed_users(db)
        names = set(db.scalars(select(User.username)).all())
        assert "stub" not in names
        assert "stub2" not in names
        settings.allow_stub_login = True
        seed_users(db)
        names = set(db.scalars(select(User.username)).all())
        assert "stub" in names
    finally:
        settings.allow_stub_login = True
        db.close()


def test_ready_503_when_redis_down(client, redis_client):
    from app.cache import set_redis

    class DeadRedis:
        def ping(self):
            raise ConnectionError("down")

    set_redis(DeadRedis())
    try:
        response = client.get("/health/ready")
        assert response.status_code == 503
        assert response.json()["ok"] is False
        assert response.json()["redis"] is False
        live = client.get("/health/live")
        assert live.status_code == 200
    finally:
        set_redis(redis_client)


def test_admin_purge_old_audit(client):
    from app.config import settings
    from app.seed import seed_users

    settings.dev_bootstrap_admin = True
    db = SessionLocal()
    try:
        seed_users(db)
        db.add(
            AuditLog(
                project_id=None,
                actor="stub",
                action="create",
                target="old",
                summary="만료 대상",
                created_at=datetime.now(timezone.utc) - timedelta(days=400),
            )
        )
        db.commit()
    finally:
        db.close()
    try:
        _login(client, "admin", "admin")
        response = client.post("/api/ops/audit/purge")
        assert response.status_code == 200, response.text
        assert response.json()["deleted"] >= 1
    finally:
        settings.dev_bootstrap_admin = False
