"""로그 설정과 인증키 가림 검증."""

from __future__ import annotations

from latlon_converter.logutil import redact, safe_params


def test_safe_params_redacts_api_key():
    assert safe_params({"key": "SECRET", "pnu": "1", "domain": "http://localhost"}) == {
        "key": "(redacted)",
        "pnu": "1",
        "domain": "http://localhost",
    }


def test_redact_replaces_secret_in_error_text():
    assert "SECRET" not in redact("https://api.vworld.kr/?key=SECRET", "SECRET")
    assert redact("ok", "") == "ok"
