from __future__ import annotations

import uuid

from app.config import settings
from app.db import SessionLocal
from app.seed import seed_users
from tests.test_wizard import _project


def _login_admin(client) -> None:
    settings.dev_bootstrap_admin = True
    db = SessionLocal()
    try:
        seed_users(db)
    finally:
        db.close()
    response = client.post("/api/login", json={"username": "admin", "password": "admin"})
    assert response.status_code == 200, response.text


def test_archive_hides_project_and_only_admin_can_restore(client):
    assert client.post(
        "/api/login", json={"username": "stub", "password": "stub"}
    ).status_code == 200
    project = _project(client)

    archived = client.post(f"/api/projects/{project['id']}/archive")
    assert archived.status_code == 200, archived.text
    assert archived.json() == {"ok": True, "project_id": project["id"]}

    active_ids = {
        row["id"] for row in client.get("/api/projects").json()["projects"]
    }
    assert project["id"] not in active_ids
    assert client.get(f"/api/projects/{project['id']}").status_code == 404
    assert client.get("/api/projects", params={"archived": True}).status_code == 403
    assert client.post(f"/api/projects/{project['id']}/restore").status_code == 403

    assert client.post("/api/logout").status_code == 200
    _login_admin(client)
    archived_list = client.get("/api/projects", params={"archived": True})
    assert archived_list.status_code == 200, archived_list.text
    archived_projects = {
        row["id"]: row for row in archived_list.json()["projects"]
    }
    assert project["id"] in archived_projects
    assert archived_projects[project["id"]]["archived_at"]
    assert archived_projects[project["id"]]["archived_by"] == "stub"

    restored = client.post(f"/api/projects/{project['id']}/restore")
    assert restored.status_code == 200, restored.text
    assert restored.json()["id"] == project["id"]
    assert restored.json()["archived_at"] is None
    assert restored.json()["archived_by"] is None

    active_ids = {
        row["id"] for row in client.get("/api/projects").json()["projects"]
    }
    assert project["id"] in active_ids
    archived_ids = {
        row["id"]
        for row in client.get("/api/projects", params={"archived": True}).json()["projects"]
    }
    assert project["id"] not in archived_ids

    logs = client.get(
        "/api/admin/audit-logs",
        params={"project_id": project["id"], "limit": 100},
    )
    assert logs.status_code == 200, logs.text
    actions = [row["action"] for row in logs.json()["audit_logs"]]
    assert "project_archive" in actions
    assert "project_restore" in actions


def test_cannot_archive_read_only_project(client):
    assert client.post(
        "/api/login", json={"username": "stub", "password": "stub"}
    ).status_code == 200
    project = _project(client)
    assert client.post("/api/logout").status_code == 200

    _login_admin(client)
    username = f"archive-viewer-{uuid.uuid4().hex[:8]}"
    viewer = client.post(
        "/api/admin/users",
        json={"username": username, "password": "viewer-pass", "role": "viewer"},
    )
    assert viewer.status_code == 200, viewer.text
    member = client.put(
        f"/api/projects/{project['id']}/members",
        json={"user_id": viewer.json()["id"], "role": "viewer"},
    )
    assert member.status_code == 200, member.text
    assert client.post("/api/logout").status_code == 200
    assert client.post(
        "/api/login", json={"username": username, "password": "viewer-pass"}
    ).status_code == 200
    response = client.post(f"/api/projects/{project['id']}/archive")
    assert response.status_code == 403
