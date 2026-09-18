"""계약 조회 API 검증.

프론트엔드가 Metric 목록을 하드코딩하지 않고 이 API 로 받는다는 전제를 지킨다.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.app import create_app
from app.metrics.catalog import load_catalog


@pytest.fixture(scope="module")
def client():
    with TestClient(create_app()) as test_client:
        yield test_client


def test_healthz(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readyz는_계약_적재_결과를_보고한다(client):
    response = client.get("/readyz")
    assert response.status_code == 200
    body = response.json()
    assert body["ready"] is True
    assert body["checks"]["contracts"]["metric_count"] == len(load_catalog().metrics)


def test_metric_catalog_응답이_카탈로그와_일치한다(client):
    response = client.get("/api/v1/metric-catalog")
    assert response.status_code == 200
    body = response.json()

    catalog = load_catalog()
    assert body["version"] == catalog.version
    assert len(body["metrics"]) == len(catalog.metrics)

    keys = {metric["key"] for metric in body["metrics"]}
    assert keys == set(catalog.metrics)

    reachable = next(m for m in body["metrics"] if m["key"] == "connectivity.reachable")
    assert reachable["required"] is True
    assert reachable["valueType"] == "boolean"

    mass_position = next(m for m in body["metrics"] if m["key"] == "sensor.mass_position_v")
    assert mass_position["dimensions"] == ["sensor_port", "axis"]


def test_카탈로그_응답에는_제조사_원본_필드가_없다(client):
    """CTR 원본 경로가 API 로 새어 나가면 Gen5 확장 때 화면을 전면 수정해야 한다."""
    body = client.get("/api/v1/metric-catalog").json()
    serialized = str(body).lower()
    for token in ("instrumentstatus", "powersupply/voltage", "externalsoh", "storepercentageused"):
        assert token not in serialized


def test_capabilities_응답(client):
    body = client.get("/api/v1/capabilities").json()
    assert "SUPPORTED_ENABLED" in body["supportStates"]
    assert "UNSUPPORTED" in body["supportStates"]
    keys = {c["key"] for c in body["capabilities"]}
    assert "storage.removable" in keys
    assert "gnss.receiver" in keys


def test_adapters_응답은_등록된_Adapter만_보여준다(client):
    body = client.get("/api/v1/adapters").json()
    keys = {adapter["adapterKey"] for adapter in body["adapters"]}
    assert keys == {"nanometrics.centaur.ctr"}


def test_adapters_응답에_등록_화면이_필요한_정보가_들어_있다(client):
    """등록 화면은 이 응답만으로 제조사별 입력 폼을 만든다."""
    adapter = client.get("/api/v1/adapters").json()["adapters"][0]
    assert adapter["manufacturer"] == "Nanometrics"
    assert adapter["selectable"] is True
    schema = adapter["configurationSchema"]
    assert "hostname" in schema["properties"]
    assert schema["required"] == ["hostname"]
    assert schema["secretFields"] == ["password"]


def test_adapters_응답에_비밀값이_들어_있지_않다(client):
    """Manifest 는 비밀 필드의 '이름' 만 알려 준다. 값은 다루지 않는다."""
    body = client.get("/api/v1/adapters").text
    assert "secretFields" in body
    for leaked in ("password=", "credentialReference", "device_credential_key"):
        assert leaked not in body


def test_관리_API_경로가_OpenAPI에_있다(client):
    spec = client.get("/openapi.json").json()
    for path in (
        "/api/v1/auth/login",
        "/api/v1/stations",
        "/api/v1/stations/import",
        "/api/v1/devices/{device_id}/test-connection",
        "/api/v1/devices/{device_id}/soh-preview",
        "/api/v1/metric-profiles",
        "/api/v1/audit-logs",
    ):
        assert path in spec["paths"]
