from __future__ import annotations

import uuid

from app.config import settings
from app.db import SessionLocal
from app.seed import seed_users
from tests.test_wizard import WIZARD, _project


def _name(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:8]}"


def _enable_admin(client):
    settings.dev_bootstrap_admin = True
    db = SessionLocal()
    try:
        seed_users(db)
    finally:
        db.close()
    ok = client.post("/api/login", json={"username": "admin", "password": "admin"})
    assert ok.status_code == 200, ok.text
    return client


def test_editor_cannot_list_users(client):
    client.post("/api/login", json={"username": "stub", "password": "stub"})
    response = client.get("/api/admin/users")
    assert response.status_code == 403
    assert "관리자" in response.json()["detail"]


def test_admin_creates_editor_and_viewer(client):
    _enable_admin(client)
    editor_name = _name("kim")
    viewer_name = _name("lee")
    editor = client.post(
        "/api/admin/users",
        json={"username": editor_name, "password": "kim-pass", "role": "editor", "display_name": "김편집"},
    )
    assert editor.status_code == 200, editor.text
    assert editor.json()["role"] == "editor"
    assert editor.json()["display_name"] == "김편집"
    assert editor.json()["active"] is True
    viewer = client.post(
        "/api/admin/users",
        json={"username": viewer_name, "password": "lee-pass", "role": "조회자", "display_name": "이조회"},
    )
    assert viewer.status_code == 200, viewer.text
    assert viewer.json()["role"] == "viewer"
    listed = client.get("/api/admin/users")
    names = {row["username"] for row in listed.json()["users"]}
    assert {editor_name, viewer_name, "admin"} <= names


def test_inactive_user_cannot_login_and_keeps_username(client):
    _enable_admin(client)
    username = _name("park")
    created = client.post(
        "/api/admin/users",
        json={"username": username, "password": "park-pass", "role": "editor"},
    )
    user_id = created.json()["id"]
    stopped = client.post(f"/api/admin/users/{user_id}/deactivate")
    assert stopped.status_code == 200
    assert stopped.json()["username"] == username
    assert stopped.json()["display_name"] == username
    assert stopped.json()["active"] is False
    client.post("/api/logout")
    denied = client.post("/api/login", json={"username": username, "password": "park-pass"})
    assert denied.status_code == 401
    assert "비활성" in denied.json()["detail"]
    _enable_admin(client)
    client.post(f"/api/admin/users/{user_id}/activate")
    client.post("/api/logout")
    ok = client.post("/api/login", json={"username": username, "password": "park-pass"})
    assert ok.status_code == 200


def test_password_reset(client):
    _enable_admin(client)
    username = _name("choi")
    created = client.post(
        "/api/admin/users",
        json={"username": username, "password": "old-pass", "role": "editor"},
    )
    client.post(f"/api/admin/users/{created.json()['id']}/password", json={"password": "new-pass"})
    client.post("/api/logout")
    bad = client.post("/api/login", json={"username": username, "password": "old-pass"})
    assert bad.status_code == 401
    ok = client.post("/api/login", json={"username": username, "password": "new-pass"})
    assert ok.status_code == 200


def test_project_hidden_until_member_added(client):
    client.post("/api/login", json={"username": "stub", "password": "stub"})
    project = _project(client)
    client.post("/api/logout")
    client.post("/api/login", json={"username": "stub2", "password": "stub2"})
    listed = client.get("/api/projects")
    ids = {row["id"] for row in listed.json()["projects"]}
    assert project["id"] not in ids
    missing = client.get(f"/api/projects/{project['id']}")
    assert missing.status_code == 404
    client.post("/api/logout")
    _enable_admin(client)
    users = {row["username"]: row for row in client.get("/api/admin/users").json()["users"]}
    added = client.put(
        f"/api/projects/{project['id']}/members",
        json={"user_id": users["stub2"]["id"], "role": "editor"},
    )
    assert added.status_code == 200, added.text
    client.post("/api/logout")
    client.post("/api/login", json={"username": "stub2", "password": "stub2"})
    listed = client.get("/api/projects")
    ids = {row["id"] for row in listed.json()["projects"]}
    assert project["id"] in ids


def test_viewer_is_read_only_xml_only(client):
    client.post("/api/login", json={"username": "stub", "password": "stub"})
    project = _project(client)
    wizard = client.post(f"/api/projects/{project['id']}/wizard", json=WIZARD)
    assert wizard.status_code == 200, wizard.text
    client.post("/api/logout")
    _enable_admin(client)
    viewer_name = _name("view")
    viewer = client.post(
        "/api/admin/users",
        json={"username": viewer_name, "password": "view1", "role": "viewer"},
    )
    assert viewer.status_code == 200, viewer.text
    client.put(
        f"/api/projects/{project['id']}/members",
        json={"user_id": viewer.json()["id"], "role": "viewer"},
    )
    client.post("/api/logout")
    client.post("/api/login", json={"username": viewer_name, "password": "view1"})
    me = client.get("/api/me")
    assert me.json()["role"] == "viewer"
    got = client.get(f"/api/projects/{project['id']}")
    assert got.status_code == 200
    assert got.json()["my_role"] == "viewer"
    assert got.json()["can_edit"] is False
    xml = client.get(f"/api/projects/{project['id']}/xml")
    assert xml.status_code == 200
    assert b"<FDSNStationXML" in xml.content
    draft = client.put(
        f"/api/projects/{project['id']}/draft",
        json={"station": "TEST1", "start_time": "2009-04-10T00:00:00", "latitude": 10.1},
    )
    assert draft.status_code == 403
    seed = client.post(f"/api/projects/{project['id']}/export/seed")
    assert seed.status_code == 403
    created = client.post(
        "/api/projects",
        json={"name": "숨김", "network_code": "YZ"},
    )
    assert created.status_code == 403
    issues = client.get(f"/api/projects/{project['id']}/issues")
    assert issues.status_code == 200
