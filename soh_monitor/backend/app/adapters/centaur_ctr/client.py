"""Centaur CTR HTTP 통신.

실패를 유형별로 구분하는 것이 이 파일의 핵심이다. "장비가 죽었다"와 "회선이 느리다"와
"본문이 깨졌다"는 조치가 완전히 다르다. 하나의 오류로 뭉개면 운영자가 현장에 헛걸음한다.

인증은 매뉴얼 7.6절을 따른다.
    GET /key → POST /login (X-NMX-USERNAME, X-NMX-PASSWORD) → 이후 세션 쿠키
    비밀번호 = MD5( MD5(비밀번호) + key )
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

import httpx

from app.domain.enums import PollErrorCode

SOH_PATH = "/api/v1/instruments/soh"
KEY_PATH = "/key"
LOGIN_PATH = "/login"
AVAILABILITY_PATH = "/api/v1/bands/availability.json"

# 본문 크기 상한. 장비가 비정상적으로 큰 응답을 내놓을 때 수집기 메모리를 지킨다.
DEFAULT_MAX_PAYLOAD_BYTES = 4 * 1024 * 1024


@dataclass(frozen=True)
class FetchResult:
    success: bool
    payload: Any = None
    latency_ms: float | None = None
    http_status: int | None = None
    payload_bytes: int | None = None
    error_code: PollErrorCode | None = None
    error_message: str | None = None


def build_base_url(connection: dict[str, Any]) -> str:
    scheme = str(connection.get("scheme") or "http").lower()
    hostname = str(connection.get("hostname") or "").strip()
    port = connection.get("port")
    base_path = str(connection.get("basePath") or "").rstrip("/")

    authority = hostname
    if port:
        authority = f"{hostname}:{int(port)}"
    return f"{scheme}://{authority}{base_path}"


def password_digest(password: str, session_key: str) -> str:
    """매뉴얼 7.6절 규격. 장비가 MD5 를 요구하므로 그대로 따른다."""
    inner = hashlib.md5(password.encode("utf-8")).hexdigest()  # noqa: S324 - 장비 규격
    return hashlib.md5((inner + session_key).encode("utf-8")).hexdigest()  # noqa: S324


def classify_exception(exc: Exception) -> tuple[PollErrorCode, str]:
    """예외를 수집 실패 유형으로 옮긴다."""
    message = str(exc) or exc.__class__.__name__

    if isinstance(exc, httpx.ConnectTimeout):
        return PollErrorCode.CONNECT_TIMEOUT, message
    if isinstance(exc, (httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout)):
        return PollErrorCode.REQUEST_TIMEOUT, message
    if isinstance(exc, httpx.TimeoutException):
        return PollErrorCode.REQUEST_TIMEOUT, message
    if isinstance(exc, httpx.ConnectError):
        lowered = message.lower()
        dns_markers = (
            "name or service not known",
            "nodename nor servname",
            "temporary failure in name resolution",
            "getaddrinfo",
            "name resolution",
        )
        if any(marker in lowered for marker in dns_markers):
            return PollErrorCode.DNS_FAILURE, message
        return PollErrorCode.CONNECTION_REFUSED, message
    if isinstance(exc, httpx.RemoteProtocolError):
        # 장비가 응답 도중 연결을 끊은 경우. 통신은 됐으나 본문을 신뢰할 수 없다.
        return PollErrorCode.INVALID_PAYLOAD, message
    if isinstance(exc, httpx.ReadError):
        return PollErrorCode.CONNECTION_REFUSED, message
    if isinstance(exc, httpx.TransportError):
        return PollErrorCode.CONNECTION_REFUSED, message
    return PollErrorCode.ADAPTER_ERROR, message


class CentaurClient:
    """한 장비에 대한 통신 담당.

    `transport` 를 주면 시험에서 HTTP 를 띄우지 않고 가상 서버에 직접 붙는다.
    """

    def __init__(
        self,
        base_url: str,
        *,
        connect_timeout_ms: int = 5000,
        request_timeout_ms: int = 15000,
        tls_verify: bool = True,
        max_payload_bytes: int = DEFAULT_MAX_PAYLOAD_BYTES,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.max_payload_bytes = max_payload_bytes
        self._timeout = httpx.Timeout(
            connect=connect_timeout_ms / 1000,
            read=request_timeout_ms / 1000,
            write=request_timeout_ms / 1000,
            pool=request_timeout_ms / 1000,
        )
        self._tls_verify = tls_verify
        self._transport = transport

    def _client(self) -> httpx.AsyncClient:
        kwargs: dict[str, Any] = {
            "base_url": self.base_url,
            "timeout": self._timeout,
            "follow_redirects": False,
        }
        if self._transport is not None:
            kwargs["transport"] = self._transport
        else:
            kwargs["verify"] = self._tls_verify
        return httpx.AsyncClient(**kwargs)

    async def _authenticate(
        self, client: httpx.AsyncClient, username: str, password: str
    ) -> FetchResult | None:
        """인증이 필요한 장비를 위한 절차. 실패하면 그 결과를 돌려준다."""
        key_response = await client.get(KEY_PATH)
        if key_response.status_code != 200:
            return FetchResult(
                success=False,
                http_status=key_response.status_code,
                error_code=PollErrorCode.AUTH_ERROR,
                error_message="세션 키를 받지 못했다",
            )
        try:
            session_key = key_response.json().get("key")
        except (json.JSONDecodeError, ValueError):
            session_key = None
        if not session_key:
            return FetchResult(
                success=False,
                error_code=PollErrorCode.AUTH_ERROR,
                error_message="세션 키 응답을 해석할 수 없다",
            )

        login_response = await client.post(
            LOGIN_PATH,
            headers={
                "X-NMX-USERNAME": username,
                "X-NMX-PASSWORD": password_digest(password, session_key),
            },
        )
        if login_response.status_code != 200:
            return FetchResult(
                success=False,
                http_status=login_response.status_code,
                error_code=PollErrorCode.AUTH_ERROR,
                error_message="인증이 거부됐다",
            )
        return None

    async def fetch_soh(
        self,
        *,
        instrument_id: str | None = None,
        credential: dict[str, str] | None = None,
    ) -> FetchResult:
        params: dict[str, str] = {"pretty": "false"}
        if instrument_id:
            params["instrumentId"] = instrument_id

        try:
            async with self._client() as client:
                if credential and credential.get("password"):
                    failure = await self._authenticate(
                        client,
                        credential.get("username", "admin"),
                        credential["password"],
                    )
                    if failure is not None:
                        return failure

                started = client  # 참조 보존용. 실제 계측은 응답의 elapsed 로 한다.
                del started
                response = await client.get(SOH_PATH, params=params)
                latency_ms = response.elapsed.total_seconds() * 1000
                body = response.content
                payload_bytes = len(body)

                if response.status_code in (401, 403):
                    return FetchResult(
                        success=False,
                        latency_ms=latency_ms,
                        http_status=response.status_code,
                        payload_bytes=payload_bytes,
                        error_code=PollErrorCode.AUTH_ERROR,
                        error_message="인증이 필요하다",
                    )

                if response.status_code >= 400:
                    return FetchResult(
                        success=False,
                        latency_ms=latency_ms,
                        http_status=response.status_code,
                        payload_bytes=payload_bytes,
                        error_code=PollErrorCode.HTTP_ERROR,
                        error_message=f"HTTP {response.status_code}",
                    )

                if payload_bytes > self.max_payload_bytes:
                    return FetchResult(
                        success=False,
                        latency_ms=latency_ms,
                        http_status=response.status_code,
                        payload_bytes=payload_bytes,
                        error_code=PollErrorCode.INVALID_PAYLOAD,
                        error_message=(
                            f"응답이 너무 크다 ({payload_bytes} bytes > {self.max_payload_bytes})"
                        ),
                    )

                content_type = response.headers.get("content-type", "")
                try:
                    payload = json.loads(body.decode("utf-8"))
                except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                    return FetchResult(
                        success=False,
                        latency_ms=latency_ms,
                        http_status=response.status_code,
                        payload_bytes=payload_bytes,
                        error_code=PollErrorCode.INVALID_PAYLOAD,
                        error_message=f"JSON 을 해석할 수 없다 (content-type={content_type}): {exc}",
                    )

                return FetchResult(
                    success=True,
                    payload=payload,
                    latency_ms=latency_ms,
                    http_status=response.status_code,
                    payload_bytes=payload_bytes,
                )

        except Exception as exc:  # noqa: BLE001 - 예외를 밖으로 던지지 않는 것이 계약이다
            error_code, message = classify_exception(exc)
            return FetchResult(success=False, error_code=error_code, error_message=message)

    async def fetch_availability(self, *, instrument_id: str | None = None) -> FetchResult:
        params: dict[str, str] = {}
        if instrument_id:
            params["instrumentId"] = instrument_id
        try:
            async with self._client() as client:
                response = await client.get(AVAILABILITY_PATH, params=params)
                if response.status_code >= 400:
                    return FetchResult(
                        success=False,
                        http_status=response.status_code,
                        error_code=PollErrorCode.HTTP_ERROR,
                        error_message=f"HTTP {response.status_code}",
                    )
                return FetchResult(
                    success=True,
                    payload=response.json(),
                    http_status=response.status_code,
                    latency_ms=response.elapsed.total_seconds() * 1000,
                )
        except Exception as exc:  # noqa: BLE001
            error_code, message = classify_exception(exc)
            return FetchResult(success=False, error_code=error_code, error_message=message)
