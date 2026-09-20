"""관측소·기록계·프로파일 관리 API."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.adapters.contract import ConnectionTest
from app.auth.passwords import hash_password
from app.db.base import Base
from app.db.models import User, UserRole
from app.db.seed import seed_default_profiles, seed_metric_definitions
from app.db.session import get_engine, reset_engine_cache, session_scope
from app.domain.models import DeviceIdentity

ADMIN_PASSWORD = "admin-pass-123"
OPERATOR_PASSWORD = "operator-pass-123"
VIEWER_PASSWORD = "viewer-pass-123"


class FakeAdapter:
    def validate_configuration(self, connection):
        return []

    async def test_connection(self, context):
        return ConnectionTest(
            reachable=True,
            latency_ms=7.5,
            http_status=200,
            message="SOH 채널 12개를 확인했다",
            identity=DeviceIdentity(
                manufacturer="Nanometrics",
                serial_number="0242",
                instrument_id="centaur-6__0242",
                channel_count=6,
            ),
        )

    async def probe(self, context):
        return DeviceIdentity(
            manufacturer="Nanometrics",
            serial_number="0242",
            instrument_id="centaur-6__0242",
            channel_count=6,
        )

    def redact(self, payload):
        if isinstance(payload, dict):
            cleaned = {}
            for key, value in payload.items():
                if "password" in str(key).lower() or "secret" in str(key).lower():
                    cleaned[key] = "***"
                else:
                    cleaned[key] = self.redact(value)
            return cleaned
        if isinstance(payload, list):
            return [self.redact(item) for item in payload]
        return payload

    async def _fetch(self, context):
        class Result:
            success = True
            payload = {"instrumentId": "centaur-6__0242", "password": "비밀"}
            http_status = 200
            error_code = None
            error_message = None

        return Result()


class FakeRegistry:
    def get(self, adapter_key: str):
        from app.adapters.registry import AdapterRegistrationError

        if adapter_key != "nanometrics.centaur.ctr":
            raise AdapterRegistrationError(adapter_key)
        return FakeAdapter()


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SOH_DATABASE_URL_OVERRIDE", f"sqlite:///{tmp_path}/mgmt.db")
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

    monkeypatch.setattr("app.api.connection.get_registry", lambda: FakeRegistry())

    from app.api.app import create_app

    with TestClient(create_app()) as test_client:
        yield test_client

    reset_engine_cache()
    get_settings.cache_clear()


def login(client: TestClient, username: str = "admin", password: str = ADMIN_PASSWORD) -> None:
    response = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text


def create_station(client: TestClient, code: str = "A01") -> str:
    response = client.post(
        "/api/v1/stations",
        json={
            "networkCode": "KS",
            "stationCode": code,
            "name": f"{code} 관측소",
            "latitude": 37.5,
            "longitude": 127.1,
            "powerProfile": "12V 배터리",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["station"]["id"]


def create_device(client: TestClient, station_id: str, host: str = "10.10.1.20") -> str:
    response = client.post(
        f"/api/v1/stations/{station_id}/devices",
        json={
            "adapterKey": "nanometrics.centaur.ctr",
            "label": "CTR-6",
            "instrumentId": "centaur-6__0242",
            "endpoint": {
                "hostname": host,
                "scheme": "http",
                "credentialReference": "env:SOH_DEVICE_PW_A01",
            },
        },
    )
    assert response.status_code == 201, response.text
    device = response.json()["device"]
    assert device["endpoint"]["hostname"] == host
    assert device["endpoint"]["credentialReference"] == "env:SOH_DEVICE_PW_A01"
    return device["id"]


class Test관측소:
    def test_등록_수정_폐기는_물리삭제가_아니다(self, client):
        login(client)
        station_id = create_station(client, "A01")
        listed = client.get("/api/v1/stations").json()["stations"]
        assert listed[0]["stationCode"] == "A01"
        assert listed[0]["categories"] == {}
        assert listed[0]["lastSuccessAt"] is None
        assert listed[0]["collectionMode"] is None
        assert "worstSeverity" in listed[0]

        updated = client.put(
            f"/api/v1/stations/{station_id}",
            json={"name": "설악산", "status": "ACTIVE"},
        )
        assert updated.status_code == 200
        assert updated.json()["station"]["name"] == "설악산"
        assert updated.json()["station"]["status"] == "ACTIVE"

        retired = client.post(f"/api/v1/stations/{station_id}/retire")
        assert retired.status_code == 200
        assert retired.json()["station"]["status"] == "RETIRED"
        still = client.get(f"/api/v1/stations/{station_id}")
        assert still.status_code == 200
        assert still.json()["station"]["status"] == "RETIRED"

    def test_목록은_장비_수집방식과_분류상태를_같이_준다(self, client):
        login(client)
        station_id = create_station(client, "B02")
        create_device(client, station_id, host="10.10.1.21")
        listed = client.get("/api/v1/stations").json()["stations"]
        row = next(item for item in listed if item["stationCode"] == "B02")
        assert row["collectionMode"] == "DIRECT"
        assert row["categories"] == {}
        assert row["deviceCount"] == 1

    def test_종합상태는_분류의_최악값이다(self):
        import uuid

        from app.api.routers.stations import _worst_from_categories

        station_id = uuid.uuid4()
        worst = _worst_from_categories(
            {station_id: {"power": "OK", "timing": "CRITICAL", "storage": "WARNING"}}
        )
        assert worst[station_id] == "CRITICAL"

    def test_같은_코드는_거절한다(self, client):
        login(client)
        create_station(client, "A01")
        duplicate = client.post(
            "/api/v1/stations",
            json={"networkCode": "KS", "stationCode": "A01", "name": "중복"},
        )
        assert duplicate.status_code == 409


class Test기록계:
    def test_비밀번호_평문은_거절한다(self, client):
        login(client)
        station_id = create_station(client)
        response = client.post(
            f"/api/v1/stations/{station_id}/devices",
            json={
                "adapterKey": "nanometrics.centaur.ctr",
                "password": "plain-text",
                "endpoint": {"hostname": "10.10.1.20"},
            },
        )
        assert response.status_code in {400, 422}

    def test_응답에_비밀번호가_없다(self, client):
        login(client)
        station_id = create_station(client)
        device_id = create_device(client, station_id)
        body = client.get(f"/api/v1/devices/{device_id}").json()
        serialized = str(body).lower()
        assert "password" not in serialized
        assert body["device"]["endpoint"]["credentialReference"] == "env:SOH_DEVICE_PW_A01"
        assert "credential_value" not in serialized

    def test_센서와_외부SOH와_Override(self, client):
        login(client)
        station_id = create_station(client)
        device_id = create_device(client, station_id)

        sensors = client.put(
            f"/api/v1/devices/{device_id}/sensors",
            json=[{"port": "A", "model": "Trillium", "axisCount": 3}],
        )
        assert sensors.status_code == 200
        axes = {axis["axisCode"] for axis in sensors.json()["sensors"][0]["axes"]}
        assert axes == {"U", "V", "W"}

        channels = client.put(
            f"/api/v1/devices/{device_id}/external-soh-channels",
            json=[
                {
                    "channelNumber": 1,
                    "name": "도어",
                    "scale": 0.001,
                    "offset": 0.0,
                    "rawUnit": "mV",
                    "outputUnit": "V",
                }
            ],
        )
        assert channels.status_code == 200
        channel = channels.json()["channels"][0]
        assert channel["formula"] == "value = raw × scale + offset"
        assert channel["scale"] == 0.001

        overrides = client.put(
            f"/api/v1/devices/{device_id}/metric-overrides",
            json=[
                {
                    "metricKey": "power.input_voltage_v",
                    "warningCondition": {"op": "<=", "value": 11.8},
                    "criticalCondition": {"op": "<=", "value": 11.0},
                    "reason": "12V 배터리",
                }
            ],
        )
        assert overrides.status_code == 200
        assert overrides.json()["overrides"][0]["metricKey"] == "power.input_voltage_v"

        bad = client.put(
            f"/api/v1/devices/{device_id}/metric-overrides",
            json=[{"metricKey": "not.a.metric", "warningCondition": {"op": ">=", "value": 1}}],
        )
        assert bad.status_code == 400

        client.post("/api/v1/auth/logout")
        login(client, "operator", OPERATOR_PASSWORD)
        forbidden = client.put(
            f"/api/v1/devices/{device_id}/metric-overrides",
            json=[{"metricKey": "power.input_voltage_v", "warningCondition": {"op": "<=", "value": 11.8}}],
        )
        assert forbidden.status_code == 403

    def test_데이터서버_URI를_바꾸고_비울_수_있다(self, client):
        login(client)
        station_id = create_station(client)
        device_id = create_device(client, station_id)
        uri = "seedlink://10.0.0.8:18000/KS_A01"

        updated = client.put(f"/api/v1/devices/{device_id}", json={"dataSourceUri": uri})
        assert updated.status_code == 200, updated.text
        assert updated.json()["device"]["dataSourceUri"] == uri

        kept = client.put(f"/api/v1/devices/{device_id}", json={"label": "CTR-6b"})
        assert kept.status_code == 200
        assert kept.json()["device"]["dataSourceUri"] == uri
        assert kept.json()["device"]["label"] == "CTR-6b"

        cleared = client.put(f"/api/v1/devices/{device_id}", json={"dataSourceUri": None})
        assert cleared.status_code == 200, cleared.text
        assert cleared.json()["device"]["dataSourceUri"] is None

        restored = client.put(
            f"/api/v1/devices/{device_id}",
            json={"dataSourceUri": "https://10.0.0.8/fdsnws/availability/1/query?net=KS&sta=A01"},
        )
        assert restored.status_code == 200
        blank = client.put(f"/api/v1/devices/{device_id}", json={"dataSourceUri": "  "})
        assert blank.status_code == 200
        assert blank.json()["device"]["dataSourceUri"] is None

    def test_허용하지_않는_데이터서버_스킴은_거절한다(self, client):
        login(client)
        station_id = create_station(client)
        device_id = create_device(client, station_id)
        response = client.put(
            f"/api/v1/devices/{device_id}",
            json={"dataSourceUri": "ftp://example/data"},
        )
        assert response.status_code == 400
        assert "스킴" in response.json()["detail"]

        created = client.post(
            f"/api/v1/stations/{station_id}/devices",
            json={
                "adapterKey": "nanometrics.centaur.ctr",
                "label": "CTR-ftp",
                "endpoint": {"hostname": "10.10.1.22"},
                "dataSourceUri": "ftp://example/data",
            },
        )
        assert created.status_code == 400

    def test_OPERATOR는_데이터서버_URI를_못_바꾼다(self, client):
        login(client)
        station_id = create_station(client)
        device_id = create_device(client, station_id)
        client.post("/api/v1/auth/logout")
        login(client, "operator", OPERATOR_PASSWORD)
        response = client.put(
            f"/api/v1/devices/{device_id}",
            json={"dataSourceUri": "http://10.0.0.8/availability"},
        )
        assert response.status_code == 403

    def test_접속_호스트와_인증_참조를_바꾼다(self, client):
        login(client)
        station_id = create_station(client)
        device_id = create_device(client, station_id)
        updated = client.put(
            f"/api/v1/devices/{device_id}",
            json={
                "endpoint": {
                    "hostname": "10.10.1.30",
                    "scheme": "https",
                    "credentialReference": "env:SOH_DEVICE_PW_C11",
                }
            },
        )
        assert updated.status_code == 200, updated.text
        endpoint = updated.json()["device"]["endpoint"]
        assert endpoint["hostname"] == "10.10.1.30"
        assert endpoint["scheme"] == "https"
        assert endpoint["credentialReference"] == "env:SOH_DEVICE_PW_C11"

        cleared = client.put(
            f"/api/v1/devices/{device_id}",
            json={"endpoint": {"hostname": "10.10.1.30", "credentialReference": ""}},
        )
        assert cleared.status_code == 200, cleared.text
        assert cleared.json()["device"]["endpoint"]["credentialReference"] is None

    def test_공인_주소는_접속_저장이_막힌다(self, client):
        login(client)
        station_id = create_station(client)
        device_id = create_device(client, station_id)
        response = client.put(
            f"/api/v1/devices/{device_id}",
            json={"endpoint": {"hostname": "8.8.8.8"}},
        )
        assert response.status_code == 400
        assert "허용 대역" in response.json()["detail"]
        kept = client.get(f"/api/v1/devices/{device_id}").json()["device"]["endpoint"]
        assert kept["hostname"] == "10.10.1.20"

        created = client.post(
            f"/api/v1/stations/{station_id}/devices",
            json={
                "adapterKey": "nanometrics.centaur.ctr",
                "label": "공인",
                "endpoint": {"hostname": "8.8.8.8"},
            },
        )
        assert created.status_code == 400

    def test_비밀번호_평문은_접속_수정에서도_거절한다(self, client):
        login(client)
        station_id = create_station(client)
        device_id = create_device(client, station_id)
        top_level = client.put(
            f"/api/v1/devices/{device_id}",
            json={"password": "plain-text", "endpoint": {"hostname": "10.10.1.20"}},
        )
        assert top_level.status_code in {400, 422}

        reference = client.put(
            f"/api/v1/devices/{device_id}",
            json={"endpoint": {"hostname": "10.10.1.20", "credentialReference": "hunter2"}},
        )
        assert reference.status_code == 422

    def test_OPERATOR는_접속을_못_바꾼다(self, client):
        login(client)
        station_id = create_station(client)
        device_id = create_device(client, station_id)
        client.post("/api/v1/auth/logout")
        login(client, "operator", OPERATOR_PASSWORD)
        response = client.put(
            f"/api/v1/devices/{device_id}",
            json={"endpoint": {"hostname": "10.10.1.31", "credentialReference": "env:SOH_DEVICE_PW_C11"}},
        )
        assert response.status_code == 403

    def test_수집을_끄고_켤_수_있다(self, client):
        login(client)
        station_id = create_station(client)
        device_id = create_device(client, station_id)

        disabled = client.put(f"/api/v1/devices/{device_id}", json={"enabled": False})
        assert disabled.status_code == 200, disabled.text
        assert disabled.json()["device"]["enabled"] is False

        polled = client.post(f"/api/v1/devices/{device_id}/poll-now")
        assert polled.status_code == 409
        assert "비활성" in polled.json()["detail"]

        health = client.get(f"/api/v1/devices/{device_id}/current-health")
        assert health.status_code == 200
        assert health.json()["overall"] == "DISABLED"
        assert health.json()["categories"]["connectivity"]["severity"] == "DISABLED"

        station_health = client.get(f"/api/v1/stations/{station_id}/current-health")
        assert station_health.status_code == 200
        assert station_health.json()["overall"] == "DISABLED"
        assert station_health.json()["devices"][0]["enabled"] is False
        assert station_health.json()["devices"][0]["overall"] == "DISABLED"

        listed = client.get("/api/v1/stations").json()["stations"]
        row = next(item for item in listed if item["id"] == station_id)
        assert row["worstSeverity"] == "DISABLED"
        assert row["categories"]["connectivity"] == "DISABLED"

        enabled = client.put(f"/api/v1/devices/{device_id}", json={"enabled": True})
        assert enabled.status_code == 200
        assert enabled.json()["device"]["enabled"] is True
        restored = client.post(f"/api/v1/devices/{device_id}/poll-now")
        assert restored.status_code == 202, restored.text

    def test_OPERATOR는_수집_여부를_못_바꾼다(self, client):
        login(client)
        station_id = create_station(client)
        device_id = create_device(client, station_id)
        client.post("/api/v1/auth/logout")
        login(client, "operator", OPERATOR_PASSWORD)
        response = client.put(f"/api/v1/devices/{device_id}", json={"enabled": False})
        assert response.status_code == 403


class Test연결시험:
    def test_공인_주소는_연결_시험이_막힌다(self, client):
        login(client, "operator", OPERATOR_PASSWORD)
        response = client.post(
            "/api/v1/devices/test-connection",
            json={"hostname": "8.8.8.8", "adapterKey": "nanometrics.centaur.ctr"},
        )
        assert response.status_code == 400
        assert "허용 대역" in response.json()["detail"]

    def test_메타데이터_주소는_막힌다(self, client):
        login(client, "operator", OPERATOR_PASSWORD)
        response = client.post(
            "/api/v1/devices/test-connection",
            json={"hostname": "169.254.169.254", "adapterKey": "nanometrics.centaur.ctr"},
        )
        assert response.status_code == 400

    def test_사설망_연결_시험과_탐지(self, client):
        login(client, "operator", OPERATOR_PASSWORD)
        tested = client.post(
            "/api/v1/devices/test-connection",
            json={"hostname": "10.10.1.20", "adapterKey": "nanometrics.centaur.ctr"},
        )
        assert tested.status_code == 200
        assert tested.json()["reachable"] is True
        assert tested.json()["identity"]["instrumentId"] == "centaur-6__0242"

        probed = client.post(
            "/api/v1/devices/probe",
            json={"hostname": "10.10.1.20", "adapterKey": "nanometrics.centaur.ctr"},
        )
        assert probed.status_code == 200
        assert probed.json()["identity"]["channelCount"] == 6

    def test_등록된_장비_연결_시험(self, client):
        login(client)
        station_id = create_station(client, "T01")
        device_id = create_device(client, station_id, host="10.10.1.23")
        client.post("/api/v1/auth/logout")
        login(client, "operator", OPERATOR_PASSWORD)
        tested = client.post(f"/api/v1/devices/{device_id}/test-connection")
        assert tested.status_code == 200, tested.text
        assert tested.json()["reachable"] is True
        assert tested.json()["identity"]["instrumentId"] == "centaur-6__0242"

        client.post("/api/v1/auth/logout")
        login(client, "viewer", VIEWER_PASSWORD)
        assert client.post(f"/api/v1/devices/{device_id}/test-connection").status_code == 403

    def test_미리보기에서_비밀값을_지운다(self, client):
        login(client)
        station_id = create_station(client)
        device_id = create_device(client, station_id)
        preview = client.get(f"/api/v1/devices/{device_id}/soh-preview")
        assert preview.status_code == 200
        payload = preview.json()["payload"]
        assert payload["password"] == "***"
        assert payload["instrumentId"] == "centaur-6__0242"
        assert "비밀" not in preview.text


class Test프로파일:
    def test_영향_관측소_수를_알려준다(self, client):
        login(client)
        station_id = create_station(client)
        create_device(client, station_id)
        profiles = client.get("/api/v1/metric-profiles").json()["profiles"]
        default = next(item for item in profiles if item["isDefault"])
        assert default["affectedDeviceCount"] == 1

        updated = client.put(
            f"/api/v1/metric-profiles/{default['id']}",
            json={"description": "전압 임계는 관측소별로 Override", "entries": default["entries"]},
        )
        assert updated.status_code == 200
        assert updated.json()["profile"]["affectedDeviceCount"] == 1

    def test_잘못된_조건은_저장되지_않는다(self, client):
        login(client)
        created = client.post(
            "/api/v1/metric-profiles",
            json={
                "name": "깨진 조건",
                "entries": [
                    {
                        "metricKey": "storage.used_percent",
                        "warningCondition": {"op": "??", "value": 1},
                    }
                ],
            },
        )
        assert created.status_code == 400


class TestCsv와감사:
    def test_부분실패_CSV와_감사로그(self, client):
        login(client)
        create_station(client, "A01")
        csv_text = (
            "networkCode,stationCode,name,hostname,credentialReference\n"
            "KS,A01,이미있음,10.1.1.1,env:SOH_PW_A01\n"
            "KS,A02,=CMD,10.1.1.2,env:SOH_PW_A02\n"
            "KS,A03,정상,10.1.1.3,env:SOH_PW_A03\n"
        )
        response = client.post(
            "/api/v1/stations/import",
            files={"file": ("stations.csv", csv_text.encode("utf-8"), "text/csv")},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["imported"] == 1
        assert body["failed"] == 2
        assert body["stations"][0]["stationCode"] == "A03"

        logs = client.get("/api/v1/audit-logs").json()["logs"]
        actions = {item["action"] for item in logs}
        assert "import" in actions
        assert "create" in actions
        blob = str(logs).lower()
        assert "password" not in blob or "***" in blob

    def test_CSV_공인주소와_잘못된_URI는_거절한다(self, client):
        login(client)
        csv_text = (
            "networkCode,stationCode,name,hostname,dataSourceUri\n"
            "KS,X01,공인,8.8.8.8,\n"
            "KS,X02,ftp,,ftp://example/data\n"
            "KS,X03,정상,10.1.1.4,\n"
        )
        response = client.post(
            "/api/v1/stations/import",
            files={"file": ("stations.csv", csv_text.encode("utf-8"), "text/csv")},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["imported"] == 1
        assert body["failed"] == 2
        fields = {item["field"] for item in body["errors"]}
        assert "hostname" in fields
        assert "dataSourceUri" in fields
        assert body["stations"][0]["stationCode"] == "X03"

    def test_VIEWER는_감사로그를_못_본다(self, client):
        login(client, "viewer", VIEWER_PASSWORD)
        assert client.get("/api/v1/audit-logs").status_code == 403


class Test유지보수:
    def test_OPERATOR가_유지보수_시간을_연다(self, client):
        login(client)
        station_id = create_station(client)
        client.post("/api/v1/auth/logout")
        login(client, "operator", OPERATOR_PASSWORD)
        now = datetime.now(timezone.utc)
        response = client.post(
            "/api/v1/maintenance-windows",
            json={
                "scope": "station",
                "scopeId": station_id,
                "startsAt": now.isoformat(),
                "endsAt": (now + timedelta(hours=2)).isoformat(),
                "reason": "센서 교체",
            },
        )
        assert response.status_code == 201, response.text
        assert response.json()["window"]["scope"] == "station"
        window_id = response.json()["window"]["id"]

        listed = client.get(
            "/api/v1/maintenance-windows",
            params={"scope": "station", "scopeId": station_id, "active": True},
        )
        assert listed.status_code == 200
        assert listed.json()["windows"][0]["id"] == window_id

        closed = client.post(f"/api/v1/maintenance-windows/{window_id}/close")
        assert closed.status_code == 200, closed.text
        ended = datetime.fromisoformat(closed.json()["window"]["endsAt"].replace("Z", "+00:00"))
        assert ended <= datetime.now(timezone.utc)

        again = client.post(f"/api/v1/maintenance-windows/{window_id}/close")
        assert again.status_code == 409

        client.post("/api/v1/auth/logout")
        login(client, "viewer", VIEWER_PASSWORD)
        assert client.get("/api/v1/maintenance-windows").status_code == 200
        blocked = client.post(
            "/api/v1/maintenance-windows",
            json={
                "scope": "station",
                "scopeId": station_id,
                "startsAt": now.isoformat(),
                "endsAt": (now + timedelta(hours=1)).isoformat(),
                "reason": "불가",
            },
        )
        assert blocked.status_code == 403
