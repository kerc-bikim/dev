from __future__ import annotations

import uuid

import pytest
from app.config import settings
from app.db import SessionLocal
from app.models import AuditLog
from app.nrl.client import set_nrl_client
from app.seed import seed_users
from sqlalchemy import select
from tests.test_nrl_api import FakeNrl


@pytest.fixture
def fake_nrl():
    fake = FakeNrl()
    set_nrl_client(fake)
    yield fake
    set_nrl_client(None)


def _login_admin(client) -> None:
    settings.dev_bootstrap_admin = True
    db = SessionLocal()
    try:
        seed_users(db)
    finally:
        db.close()
    response = client.post("/api/login", json={"username": "admin", "password": "admin"})
    assert response.status_code == 200, response.text


def test_editor_cannot_manage_nrl_search_rules(client):
    login = client.post("/api/login", json={"username": "stub", "password": "stub"})
    assert login.status_code == 200
    assert client.get("/api/admin/nrl/aliases").status_code == 403
    assert client.get("/api/admin/nrl/excluded").status_code == 403
    assert (
        client.post(
            "/api/admin/nrl/aliases",
            json={"query": "private", "manufacturer": "Guralp", "model": ""},
        ).status_code
        == 403
    )


def test_admin_alias_edits_apply_to_the_next_search(client, fake_nrl):
    _login_admin(client)
    token = uuid.uuid4().hex[:10]
    first_query = f"alias-{token}"
    second_query = f"renamed-{token}"

    created = client.post(
        "/api/admin/nrl/aliases",
        json={
            "query": f"  {first_query.upper()}  ",
            "manufacturer": " Guralp ",
            "model": " CMG-3T ",
        },
    )
    assert created.status_code == 200, created.text
    alias = created.json()
    assert alias == {
        "id": alias["id"],
        "query": first_query,
        "manufacturer": "Guralp",
        "model": "CMG-3T",
    }

    immediate = client.get(
        "/api/nrl/search", params={"q": first_query, "element": "sensor"}
    )
    assert immediate.status_code == 200, immediate.text
    assert [
        (row["manufacturer"], row["model"], row["via"])
        for row in immediate.json()["hits"]
    ] == [("Guralp", "CMG-3T", "alias")]

    updated = client.put(
        f"/api/admin/nrl/aliases/{alias['id']}",
        json={"query": second_query, "manufacturer": "Guralp", "model": "CMG-3TB"},
    )
    assert updated.status_code == 200, updated.text
    old_search = client.get(
        "/api/nrl/search", params={"q": first_query, "element": "sensor"}
    ).json()
    assert old_search["hits"] == []
    new_search = client.get(
        "/api/nrl/search", params={"q": second_query, "element": "sensor"}
    ).json()
    assert [
        (row["manufacturer"], row["model"], row["via"])
        for row in new_search["hits"]
    ] == [("Guralp", "CMG-3TB", "alias")]

    duplicate = client.post(
        "/api/admin/nrl/aliases",
        json={"query": " METROZET ", "manufacturer": "Guralp", "model": ""},
    )
    assert duplicate.status_code == 409

    listed = client.get("/api/admin/nrl/aliases")
    assert listed.status_code == 200
    assert second_query in {row["query"] for row in listed.json()["aliases"]}
    deleted = client.delete(f"/api/admin/nrl/aliases/{alias['id']}")
    assert deleted.status_code == 200, deleted.text
    assert client.get(
        "/api/nrl/search", params={"q": second_query, "element": "sensor"}
    ).json()["hits"] == []

    db = SessionLocal()
    try:
        actions = db.scalars(
            select(AuditLog.action).where(AuditLog.target.in_([first_query, second_query]))
        ).all()
    finally:
        db.close()
    assert actions == ["nrl_alias_create", "nrl_alias_update", "nrl_alias_delete"]


def test_admin_exclusion_edits_apply_to_the_next_search(client, fake_nrl):
    _login_admin(client)
    token = uuid.uuid4().hex[:10]
    first_query = f"exclude-{token}"
    second_query = f"blocked-{token}"

    created = client.post(
        "/api/admin/nrl/excluded",
        json={
            "query": first_query,
            "name": "현장 교정 장비",
            "message": "교정 시트를 가져오세요.",
        },
    )
    assert created.status_code == 200, created.text
    rule = created.json()
    immediate = client.get(
        "/api/nrl/search", params={"q": first_query, "element": "sensor"}
    ).json()
    assert immediate["hits"] == []
    assert immediate["excluded"] == {
        "query": first_query,
        "name": "현장 교정 장비",
        "message": "교정 시트를 가져오세요.",
    }

    updated = client.put(
        f"/api/admin/nrl/excluded/{rule['id']}",
        json={
            "query": second_query,
            "name": "별도 응답 장비",
            "message": "RESP를 가져오세요.",
        },
    )
    assert updated.status_code == 200, updated.text
    assert client.get(
        "/api/nrl/search", params={"q": first_query, "element": "sensor"}
    ).json()["excluded"] is None
    changed = client.get(
        "/api/nrl/search", params={"q": second_query, "element": "sensor"}
    ).json()
    assert changed["excluded"]["name"] == "별도 응답 장비"
    assert changed["message"] == "RESP를 가져오세요."

    listed = client.get("/api/admin/nrl/excluded")
    assert listed.status_code == 200
    assert second_query in {row["query"] for row in listed.json()["excluded"]}
    deleted = client.delete(f"/api/admin/nrl/excluded/{rule['id']}")
    assert deleted.status_code == 200, deleted.text
    assert client.get(
        "/api/nrl/search", params={"q": second_query, "element": "sensor"}
    ).json()["excluded"] is None
