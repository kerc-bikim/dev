from __future__ import annotations

from app.config import settings
from app.db import SessionLocal
from app.seed import seed_users


def test_stub_login(client):
    response = client.post("/api/login", json={"username": "stub", "password": "stub"})
    assert response.status_code == 200
    body = response.json()
    assert body["username"] == "stub"
    assert body["role"] == "editor"
    assert body["active"] is True
    assert body["display_name"] == "stub"
    assert client.cookies.get("pdcc_session")


def test_stub_me_and_logout(client):
    client.post("/api/login", json={"username": "stub", "password": "stub"})
    me = client.get("/api/me")
    assert me.status_code == 200
    assert me.json()["username"] == "stub"
    out = client.post("/api/logout")
    assert out.status_code == 200
    assert client.get("/api/me").status_code == 401


def test_me_without_session(client):
    assert client.get("/api/me").status_code == 401


def test_wrong_password(client):
    response = client.post("/api/login", json={"username": "stub", "password": "nope"})
    assert response.status_code == 401


def test_admin_rejected_when_bootstrap_off(client):
    response = client.post("/api/login", json={"username": "admin", "password": "admin"})
    assert response.status_code == 403
    assert "DEV_BOOTSTRAP_ADMIN" in response.json()["detail"]


def test_admin_allowed_when_bootstrap_on(client):
    settings.dev_bootstrap_admin = True
    db = SessionLocal()
    try:
        seed_users(db)
    finally:
        db.close()
    response = client.post("/api/login", json={"username": "admin", "password": "admin"})
    assert response.status_code == 200
    assert response.json()["username"] == "admin"
    assert response.json()["role"] == "admin"
