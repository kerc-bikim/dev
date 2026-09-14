"""브이월드 제공자의 요청 구성과 오류 처리 검증.

실제 키가 없어도 요청 파라미터와 폴백·재시도 동작을 확인할 수 있도록
세션을 대신 끼워 넣는다.
"""

from __future__ import annotations

import json

import pytest

from latlon_converter.config import FIXTURES_DIR, Settings
from latlon_converter.errors import AuthError, NetworkError, QuotaError
from latlon_converter.providers import vworld as vworld_module
from latlon_converter.providers.vworld import VWorldProvider


def load(name: str) -> dict:
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


class FakeResponse:
    def __init__(self, payload: dict | None, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


class FakeSession:
    """URL별로 정해진 응답을 돌려주고 요청을 기록한다."""

    def __init__(self, routes: dict[str, object]):
        self.routes = routes
        self.calls: list[tuple[str, dict]] = []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, dict(params or {})))
        response = self.routes[url]
        if isinstance(response, list):
            response = response.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def params_for(self, url: str) -> dict:
        for called_url, params in self.calls:
            if called_url == url:
                return params
        raise AssertionError(f"{url} 요청이 없습니다")


@pytest.fixture
def settings() -> Settings:
    return Settings(provider="vworld", api_key="TEST-KEY", domain="http://localhost", retries=3)


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(vworld_module.time, "sleep", lambda seconds: None)


def test_missing_key_is_rejected_up_front():
    with pytest.raises(AuthError):
        VWorldProvider(Settings(provider="vworld", api_key=""))


def test_cadastral_request_parameters(settings):
    session = FakeSession({vworld_module.DATA_URL: FakeResponse(load("cadastral_yeoksam.json"))})
    provider = VWorldProvider(settings, session=session)

    parcel = provider.get_parcel(37.50435, 127.02505)
    assert parcel is not None and parcel.pnu == "1168010100108080000"

    params = session.params_for(vworld_module.DATA_URL)
    assert params["data"] == vworld_module.CADASTRAL_LAYER
    assert params["request"] == "GetFeature"
    # POINT는 경도가 먼저다.
    assert params["geomFilter"] == "POINT(127.02505 37.50435)"
    assert params["crs"] == "EPSG:4326"
    assert params["key"] == "TEST-KEY"
    assert params["domain"] == "http://localhost"


def test_geocoder_fallback_builds_pnu(settings):
    session = FakeSession(
        {
            vworld_module.DATA_URL: FakeResponse(load("cadastral_empty.json")),
            vworld_module.ADDRESS_URL: FakeResponse(load("geocoder_yeoksam.json")),
        }
    )
    parcel = VWorldProvider(settings, session=session).get_parcel(37.50435, 127.02505)

    assert parcel is not None
    assert parcel.source == "geocoder"
    assert parcel.pnu == "1168010100108080000"
    assert session.params_for(vworld_module.ADDRESS_URL)["type"] == "PARCEL"
    assert session.params_for(vworld_module.ADDRESS_URL)["point"] == "127.02505,37.50435"


def test_road_address_uses_second_geocoder_call(settings):
    session = FakeSession(
        {
            vworld_module.DATA_URL: FakeResponse(load("cadastral_yeoksam.json")),
            vworld_module.ADDRESS_URL: FakeResponse(load("geocoder_yeoksam.json")),
        }
    )
    parcel = VWorldProvider(settings, session=session).get_parcel(37.50435, 127.02505, with_road=True)

    assert parcel is not None
    assert parcel.road_address == "서울특별시 강남구 테헤란로 305"
    assert session.params_for(vworld_module.ADDRESS_URL)["type"] == "BOTH"


def test_ned_requests_carry_pnu_and_domain(settings):
    session = FakeSession(
        {
            vworld_module.LADFRL_URL: FakeResponse(load("ladfrl_yeoksam.json")),
            vworld_module.LANDCHAR_URL: FakeResponse(load("landchar_yeoksam.json")),
        }
    )
    provider = VWorldProvider(settings, session=session)

    ledger = provider.get_ledger("1168010100108080000")
    characteristics = provider.get_characteristics("1168010100108080000", 2025)

    assert ledger is not None and ledger.ownership_type == "개인"
    assert characteristics is not None and characteristics.use_area1 == "일반상업지역"
    for url in (vworld_module.LADFRL_URL, vworld_module.LANDCHAR_URL):
        params = session.params_for(url)
        assert params["pnu"] == "1168010100108080000"
        assert params["format"] == "json"
        assert params["domain"] == "http://localhost"
    assert session.params_for(vworld_module.LANDCHAR_URL)["stdrYear"] == "2025"


def test_error_payloads_are_classified(settings):
    auth_session = FakeSession({vworld_module.DATA_URL: FakeResponse(load("error_incorrect_key.json"))})
    with pytest.raises(AuthError):
        VWorldProvider(settings, session=auth_session).get_parcel(37.5, 127.0)

    quota_session = FakeSession({vworld_module.DATA_URL: FakeResponse(load("error_over_quota.json"))})
    with pytest.raises(QuotaError):
        VWorldProvider(settings, session=quota_session).get_parcel(37.5, 127.0)


def test_server_error_is_retried_then_succeeds(settings):
    session = FakeSession(
        {
            vworld_module.DATA_URL: [
                FakeResponse(None, status_code=503),
                FakeResponse(None, status_code=502),
                FakeResponse(load("cadastral_yeoksam.json")),
            ]
        }
    )
    parcel = VWorldProvider(settings, session=session).get_parcel(37.50435, 127.02505)

    assert parcel is not None
    assert len(session.calls) == 3


def test_retries_are_bounded(settings):
    session = FakeSession({vworld_module.DATA_URL: [FakeResponse(None, status_code=500)] * 3})
    with pytest.raises(NetworkError):
        VWorldProvider(settings, session=session).get_parcel(37.5, 127.0)
    assert len(session.calls) == settings.retries


def test_client_error_is_not_retried(settings):
    session = FakeSession({vworld_module.DATA_URL: FakeResponse(None, status_code=404)})
    with pytest.raises(NetworkError):
        VWorldProvider(settings, session=session).get_parcel(37.5, 127.0)
    assert len(session.calls) == 1


def test_transport_failure_is_retried_then_raises(settings):
    session = FakeSession({vworld_module.DATA_URL: [ConnectionError("network down")] * 3})
    with pytest.raises(NetworkError):
        VWorldProvider(settings, session=session).get_parcel(37.5, 127.0)
    assert len(session.calls) == 3
