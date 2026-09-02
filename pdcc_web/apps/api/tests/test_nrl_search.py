from __future__ import annotations

from app.db import SessionLocal
from app.models import User, hash_password
from app.nrl.client import set_nrl_client
from sqlalchemy import select

from tests.test_nrl_api import FakeNrl
from tests.test_wizard import _login

import pytest


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


def test_search_3t_finds_cmg3t(stub):
    found = stub.get("/api/nrl/search", params={"q": "3t", "element": "sensor"})
    assert found.status_code == 200, found.text
    models = {row["model"] for row in found.json()["hits"] if row["model"]}
    assert "CMG-3T" in models
    assert "CMG-3TB" in models
    assert all(row["manufacturer"] == "Guralp" for row in found.json()["hits"] if row["model"] and "3T" in row["model"])


def test_search_aliases_metrozet_and_cme(stub):
    metro = stub.get("/api/nrl/search", params={"q": "metrozet", "element": "sensor"})
    assert metro.status_code == 200, metro.text
    mfrs = {row["manufacturer"] for row in metro.json()["hits"]}
    assert "EQMet" in mfrs
    assert metro.json()["excluded"] is None
    cme = stub.get("/api/nrl/search", params={"q": "cme", "element": "sensor"})
    assert cme.status_code == 200, cme.text
    assert "RSensors" in {row["manufacturer"] for row in cme.json()["hits"]}


def test_search_certimus_excluded(stub):
    found = stub.get("/api/nrl/search", params={"q": "Certimus", "element": "sensor"})
    assert found.status_code == 200, found.text
    body = found.json()
    assert body["hits"] == []
    assert body["excluded"]["name"] == "Certimus"
    assert "교정 시트" in body["excluded"]["message"]


def test_nrl_status_and_editor_cannot_test(stub):
    status = stub.get("/api/nrl/status")
    assert status.status_code == 200
    assert status.json()["mode"] == "online"
    denied = stub.post("/api/nrl/test")
    assert denied.status_code == 403


def test_admin_nrl_test(client, fake_nrl):
    db = SessionLocal()
    try:
        if db.scalar(select(User).where(User.username == "admin")) is None:
            db.add(User(username="admin", password_hash=hash_password("admin"), role="admin"))
            db.commit()
    finally:
        db.close()
    client.app  # keep fixture
    from app.config import settings

    settings.dev_bootstrap_admin = True
    try:
        _login(client, "admin", "admin")
        probed = client.post("/api/nrl/test")
        assert probed.status_code == 200, probed.text
        body = probed.json()
        assert body["ok"] is True
        assert body["status_code"] == 200
        assert "sensor" in body["elements"]
        assert ("probe",) in fake_nrl.calls
    finally:
        settings.dev_bootstrap_admin = False
