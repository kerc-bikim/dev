"""제조사 중립 HTTP JSON Transport.

인증 방식은 제조사마다 다르므로, 여기서는 Bearer 토큰과 기본 GET 만 다룬다.
Centaur 의 세션 로그인처럼 고유한 절차는 해당 Adapter client 에 남긴다.
"""
from __future__ import annotations

import json
from typing import Any

import httpx

from app.domain.enums import PollErrorCode

from .base import TransportResult

DEFAULT_MAX_PAYLOAD_BYTES = 4 * 1024 * 1024


def classify_exception(exc: Exception) -> tuple[PollErrorCode, str]:
    message = str(exc) or exc.__class__.__name__
    if isinstance(exc, httpx.ConnectTimeout):
        return PollErrorCode.CONNECT_TIMEOUT, message
    if isinstance(exc, (httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout, httpx.TimeoutException)):
        return PollErrorCode.REQUEST_TIMEOUT, message
    if isinstance(exc, httpx.ConnectError):
        lowered = message.lower()
        if any(
            marker in lowered
            for marker in (
                "name or service not known",
                "nodename nor servname",
                "temporary failure in name resolution",
                "getaddrinfo",
                "name resolution",
            )
        ):
            return PollErrorCode.DNS_FAILURE, message
        return PollErrorCode.CONNECTION_REFUSED, message
    if isinstance(exc, httpx.RemoteProtocolError):
        return PollErrorCode.INVALID_PAYLOAD, message
    if isinstance(exc, (httpx.ReadError, httpx.TransportError)):
        return PollErrorCode.CONNECTION_REFUSED, message
    return PollErrorCode.ADAPTER_ERROR, message


class HttpJsonTransport:
    """GET 으로 JSON 을 받는 기본 통로."""

    name = "http"

    def __init__(
        self,
        *,
        path: str = "/soh",
        httpx_transport: httpx.AsyncBaseTransport | None = None,
        max_payload_bytes: int = DEFAULT_MAX_PAYLOAD_BYTES,
    ) -> None:
        self.path = path
        self._httpx_transport = httpx_transport
        self.max_payload_bytes = max_payload_bytes

    def _base_url(self, connection: dict[str, Any]) -> str:
        scheme = str(connection.get("scheme") or connection.get("protocol") or "http").lower()
        if scheme not in {"http", "https"}:
            scheme = "http"
        hostname = str(connection.get("hostname") or "").strip()
        port = connection.get("port")
        authority = f"{hostname}:{int(port)}" if port else hostname
        base_path = str(connection.get("basePath") or "").rstrip("/")
        return f"{scheme}://{authority}{base_path}"

    async def fetch(self, context: Any) -> TransportResult:
        connection = context.connection
        path = str(connection.get("path") or self.path)
        timeout = httpx.Timeout(
            connect=context.connect_timeout_ms / 1000,
            read=context.request_timeout_ms / 1000,
            write=context.request_timeout_ms / 1000,
            pool=context.request_timeout_ms / 1000,
        )
        headers: dict[str, str] = {}
        token = None
        if context.credential:
            token = context.credential.get("apiToken") or context.credential.get("token")
        if not token:
            token = connection.get("apiToken")
        if token:
            headers["Authorization"] = f"Bearer {token}"

        kwargs: dict[str, Any] = {
            "base_url": self._base_url(connection),
            "timeout": timeout,
            "follow_redirects": False,
        }
        if self._httpx_transport is not None:
            kwargs["transport"] = self._httpx_transport
        else:
            kwargs["verify"] = bool(connection.get("tlsVerify", True))

        try:
            async with httpx.AsyncClient(**kwargs) as client:
                response = await client.get(path)
                latency_ms = response.elapsed.total_seconds() * 1000
                body = response.content
                payload_bytes = len(body)

                if response.status_code in (401, 403):
                    return TransportResult(
                        success=False,
                        latency_ms=latency_ms,
                        http_status=response.status_code,
                        payload_bytes=payload_bytes,
                        error_code=PollErrorCode.AUTH_ERROR,
                        error_message="인증이 필요하다",
                    )
                if response.status_code >= 400:
                    return TransportResult(
                        success=False,
                        latency_ms=latency_ms,
                        http_status=response.status_code,
                        payload_bytes=payload_bytes,
                        error_code=PollErrorCode.HTTP_ERROR,
                        error_message=f"HTTP {response.status_code}",
                    )
                if payload_bytes > self.max_payload_bytes:
                    return TransportResult(
                        success=False,
                        latency_ms=latency_ms,
                        http_status=response.status_code,
                        payload_bytes=payload_bytes,
                        error_code=PollErrorCode.INVALID_PAYLOAD,
                        error_message=f"응답이 너무 크다 ({payload_bytes} bytes)",
                    )
                try:
                    payload = json.loads(body.decode("utf-8"))
                except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                    return TransportResult(
                        success=False,
                        latency_ms=latency_ms,
                        http_status=response.status_code,
                        payload_bytes=payload_bytes,
                        error_code=PollErrorCode.INVALID_PAYLOAD,
                        error_message=f"JSON 을 해석할 수 없다: {exc}",
                    )
                return TransportResult(
                    success=True,
                    payload=payload,
                    latency_ms=latency_ms,
                    http_status=response.status_code,
                    payload_bytes=payload_bytes,
                )
        except Exception as exc:  # noqa: BLE001 - 예외를 Adapter 밖으로 던지지 않는다
            error_code, message = classify_exception(exc)
            return TransportResult(success=False, error_code=error_code, error_message=message)
