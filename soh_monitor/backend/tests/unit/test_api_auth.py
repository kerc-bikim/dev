"""관리 API 인증·역할 시험."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.auth.passwords import hash_password
from app.db.base import Base
from app.db.models import User, UserRole
from app.db.seed import seed_default_profiles, seed_metric_definitions
from app.db.session import get_engine, reset_engine_cache, session_scope


ADMIN_PASSWORD = "admin-pass-123"
OPERATOR_PASSWORD = "operator-pass-123"
VIEWER_PASSWORD = "viewer-pass-123"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SOH_DATABASE_URL_OVERRIDE", f"sqlite:///{tmp_path}/auth.db")
    monkeypatch.setenv("SOH_SESSION_SECRET", "unit-test-session-secret")
    monkeypatch.setenv("SOH_APP_ENV", "development")
    from app.config.settings import get_settings

    get_settings.cache_clear()
    reset_engine_cache()
    engine = get_engine()
    Base.metadata.create_all(engine)

    with session_scope() as session:
        seed_metric_definitions(session)
        seed_default_profiles(session)
        session.add(
            User(
                username="admin",
                display_name="관리자",
                password_hash=hash_password(ADMIN_PASSWORD, n=2**10),
                role=UserRole.ADMIN,
                enabled=True,
                must_change_password=False,
            )
        )
        session.add(
            User(
                username="operator",
                display_name="운영자",
                password_hash=hash_password(OPERATOR_PASSWORD, n=2**10),
                role=UserRole.OPERATOR,
                enabled=True,
            )
        )
        session.add(
            User(
                username="viewer",
                display_name="조회자",
                password_hash=hash_password(VIEWER_PASSWORD, n=2**10),
                role=UserRole.VIEWER,
                enabled=True,
            )
        )
        session.add(
            User(
                username="fresh-admin",
                display_name="초기 관리자",
                password_hash=hash_password(ADMIN_PASSWORD, n=2**10),
                role=UserRole.ADMIN,
                enabled=True,
                must_change_password=True,
            )
        )

    from app.api.app import create_app

    with TestClient(create_app()) as test_client:
        yield test_client

    reset_engine_cache()
    get_settings.cache_clear()


def login(client: TestClient, username: str, password: str) -> TestClient:
    response = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return client


class Test로그인:
    def test_틀린_비밀번호는_실패한다(self, client):
        response = client.post(
            "/api/v1/auth/login", json={"username": "admin", "password": "wrong-password"}
        )
        assert response.status_code == 401
        assert "soh_session" not in response.cookies

    def test_로그인하면_me를_볼_수_있다(self, client):
        login(client, "admin", ADMIN_PASSWORD)
        me = client.get("/api/v1/auth/me")
        assert me.status_code == 200
        body = me.json()["user"]
        assert body["username"] == "admin"
        assert body["role"] == "ADMIN"
        assert "passwordHash" not in body
        assert "scrypt$" not in str(body)

    def test_로그아웃하면_다시_막힌다(self, client):
        login(client, "admin", ADMIN_PASSWORD)
        assert client.post("/api/v1/auth/logout").status_code == 200
        assert client.get("/api/v1/auth/me").status_code == 401

    def test_비밀번호_변경_전에는_설정을_못_바꾼다(self, client):
        login(client, "fresh-admin", ADMIN_PASSWORD)
        blocked = client.post(
            "/api/v1/stations",
            json={"networkCode": "KS", "stationCode": "Z99", "name": "차단"},
        )
        assert blocked.status_code == 403
        changed = client.post(
            "/api/v1/auth/change-password",
            json={"currentPassword": ADMIN_PASSWORD, "newPassword": "new-password-1"},
        )
        assert changed.status_code == 200
        assert changed.json()["user"]["mustChangePassword"] is False
        created = client.post(
            "/api/v1/stations",
            json={"networkCode": "KS", "stationCode": "Z99", "name": "통과"},
        )
        assert created.status_code == 201


class Test역할:
    def test_VIEWER는_조회만_한다(self, client):
        login(client, "admin", ADMIN_PASSWORD)
        created = client.post(
            "/api/v1/stations",
            json={"networkCode": "KS", "stationCode": "V01", "name": "조회용"},
        )
        assert created.status_code == 201
        client.post("/api/v1/auth/logout")

        login(client, "viewer", VIEWER_PASSWORD)
        listed = client.get("/api/v1/stations")
        assert listed.status_code == 200
        assert listed.json()["stations"][0]["stationCode"] == "V01"
        forbidden = client.post(
            "/api/v1/stations",
            json={"networkCode": "KS", "stationCode": "V02", "name": "불가"},
        )
        assert forbidden.status_code == 403

    def test_OPERATOR는_설정_변경이_막히고_연결시험은_된다(self, client):
        login(client, "operator", OPERATOR_PASSWORD)
        create = client.post(
            "/api/v1/stations",
            json={"networkCode": "KS", "stationCode": "O01", "name": "불가"},
        )
        assert create.status_code == 403
        windows = client.get("/api/v1/maintenance-windows")
        assert windows.status_code == 200
        users = client.get("/api/v1/users")
        assert users.status_code == 403

    def test_미인증은_관리_API를_못_본다(self, client):
        assert client.get("/api/v1/stations").status_code == 401
        assert client.get("/api/v1/fleet/summary").status_code == 401
        assert client.get("/api/v1/audit-logs").status_code == 401
        # 계약 조회는 로그인 전 화면에서도 쓴다.
        assert client.get("/api/v1/metric-catalog").status_code == 200
