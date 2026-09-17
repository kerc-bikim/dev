"""오류 메시지·로그에 인증키가 남지 않는지 검증.

requests 예외 문자열에는 요청 URL이 통째로 들어가고, 거기에는 인증키가
붙어 있다. 그대로 두면 화면, 로그, 배치 결과의 비고 칸을 거쳐 키가 새어
나간다.
"""

from __future__ import annotations

import logging

import pytest
import requests

from latlon_converter.config import Settings
from latlon_converter.errors import REDACTED, NetworkError, TlsError, redact_secrets
from latlon_converter.providers import vworld as vworld_module
from latlon_converter.providers.vworld import VWorldProvider
from latlon_converter.service import LandLookupService
from latlon_converter.tls import check_connection, tls_error_message

# 실제 인증키와 같은 모양의 가짜 값. 진짜 키를 저장소에 두지 않는다.
KEY = "00000000-1111-2222-3333-444444444444"


@pytest.mark.parametrize(
    "text",
    [
        f"https://api.vworld.kr/req/data?format=json&key={KEY}&domain=http://localhost",
        f"url: /req/data?size=10&key={KEY} (Caused by NewConnectionError)",
        f"?serviceKey={KEY}&pnu=1",
        f"?authKey={KEY}",
        f"?KEY={KEY}&x=1",
    ],
)
def test_key_is_removed_from_text(text):
    cleaned = redact_secrets(text)
    assert KEY not in cleaned
    assert REDACTED in cleaned


def test_other_parameters_survive():
    cleaned = redact_secrets(f"?geomFilter=POINT(127.0 37.5)&key={KEY}&pnu=1168010100108080000")
    assert "geomFilter=POINT(127.0 37.5)" in cleaned
    assert "pnu=1168010100108080000" in cleaned


def test_words_containing_key_are_untouched():
    # 값이 붙지 않은 코드 이름은 건드리지 않는다.
    assert redact_secrets("INCORRECT_KEY 인증키 정보가 올바르지 않습니다") == (
        "INCORRECT_KEY 인증키 정보가 올바르지 않습니다"
    )


def test_accepts_exception_objects():
    assert KEY not in redact_secrets(ValueError(f"key={KEY}"))


class BrokenSession:
    """전송 단계에서 실패하는 세션. 예외에 요청 URL이 들어간다."""

    verify = True

    def __init__(self, error):
        self.error = error

    def get(self, url, params=None, timeout=None):
        query = "&".join(f"{name}={value}" for name, value in (params or {}).items())
        raise self.error(f"HTTPSConnectionPool(host='api.vworld.kr'): url: /req/data?{query}")


def make_provider(error) -> VWorldProvider:
    settings = Settings(provider="vworld", api_key=KEY, domain="http://localhost", retries=1)
    return VWorldProvider(settings, session=BrokenSession(error), cache=None)


def test_transport_error_message_hides_the_key(monkeypatch):
    monkeypatch.setattr(vworld_module.time, "sleep", lambda seconds: None)
    with pytest.raises(NetworkError) as info:
        make_provider(requests.exceptions.ConnectionError).get_parcel(37.5, 127.0)

    message = str(info.value)
    assert KEY not in message
    assert REDACTED in message


def test_tls_error_message_hides_the_key():
    with pytest.raises(TlsError) as info:
        make_provider(requests.exceptions.SSLError).get_parcel(37.5, 127.0)

    message = str(info.value)
    assert KEY not in message
    assert "LATLON_CA_BUNDLE" in message


def test_debug_logs_hide_the_key(monkeypatch, caplog):
    monkeypatch.setattr(vworld_module.time, "sleep", lambda seconds: None)
    with caplog.at_level(logging.DEBUG, logger="latlon_converter.providers.vworld"):
        with pytest.raises(NetworkError):
            make_provider(requests.exceptions.ConnectionError).get_parcel(37.5, 127.0)

    assert caplog.text
    assert KEY not in caplog.text


def test_batch_note_hides_the_key(monkeypatch):
    """조회 결과의 비고 칸으로도 새지 않아야 한다."""
    monkeypatch.setattr(vworld_module.time, "sleep", lambda seconds: None)
    provider = make_provider(requests.exceptions.ConnectionError)

    with pytest.raises(NetworkError) as info:
        LandLookupService(provider).lookup_point(37.5, 127.0)
    assert KEY not in str(info.value)


def test_connection_check_hides_the_key():
    settings = Settings(provider="vworld", api_key=KEY, domain="http://localhost", timeout=1)
    session = BrokenSession(requests.exceptions.SSLError)

    check = check_connection(settings, "https://api.vworld.kr/req/data", session=session)

    assert KEY not in check.detail
    assert KEY not in check.hint


def test_tls_helper_hides_the_key_directly():
    message = tls_error_message(True, Exception(f"url: /req/data?key={KEY}"))
    assert KEY not in message
