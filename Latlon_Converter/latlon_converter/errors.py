"""도구 전역 예외와 종료코드."""

from __future__ import annotations

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
