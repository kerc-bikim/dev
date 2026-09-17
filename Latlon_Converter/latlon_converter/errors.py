"""도구 전역 예외와 종료코드."""

from __future__ import annotations

import re
from typing import Any

# 요청이 실패하면 requests 예외 문자열에 인증키가 붙은 URL이 통째로 들어간다.
# 그대로 두면 오류 메시지, 로그, 배치 결과의 비고 칸에 키가 남는다.
_SECRET_PARAM_RE = re.compile(r"(?i)(key|servicekey|authkey)=([^&\s'\")]+)")
REDACTED = "<가려짐>"


def redact_secrets(value: Any) -> str:
    """URL 질의문자열에 섞인 인증키를 가린다."""
    return _SECRET_PARAM_RE.sub(lambda match: f"{match.group(1)}={REDACTED}", str(value))


EXIT_OK = 0
EXIT_INPUT = 1
EXIT_AUTH = 2
EXIT_QUOTA = 3
EXIT_NETWORK = 4
EXIT_TLS = 5


class LatlonError(Exception):
    """이 도구가 발생시키는 모든 예외의 조상."""

    exit_code = EXIT_INPUT


class InputError(LatlonError):
    """입력값이 잘못된 경우."""

    exit_code = EXIT_INPUT


class AuthError(LatlonError):
    """인증키 미설정, 키 오류, 도메인 불일치."""

    exit_code = EXIT_AUTH


class ConfigError(LatlonError):
    """설정값이 가리키는 대상이 없거나 형식이 잘못된 경우."""

    exit_code = EXIT_AUTH


class TlsError(LatlonError):
    """서버 인증서 검증 실패. 사내망 TLS 검사 장비를 거칠 때 주로 난다."""

    exit_code = EXIT_TLS


class QuotaError(LatlonError):
    """일일 호출 한도 초과."""

    exit_code = EXIT_QUOTA


class NetworkError(LatlonError):
    """타임아웃, 연결 실패, 서버 오류."""

    exit_code = EXIT_NETWORK
