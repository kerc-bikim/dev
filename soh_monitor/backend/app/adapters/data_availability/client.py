"""데이터 서버 통신.

HTTP(FDSNWS·Centaur availability) 와 SeedLink INFO STREAMS 를 여기서만 다룬다.
수집기는 URI 스킴을 모른다. 실패는 예외가 아니라 TransportResult 다.
"""
from __future__ import annotations

from urllib.parse import urlparse

import httpx

from app.adapters.transport.base import TransportResult
from app.adapters.transport.http import classify_exception
from app.domain.enums import PollErrorCode

from .seedlink import SeedLinkTransport

SeedLinkStubTransport = SeedLinkTransport

DEFAULT_MAX_PAYLOAD_BYTES = 4 * 1024 * 1024


def normalize_uri(uri: str) -> tuple[str, str]:
    """(스킴, 실제 조회 URL 또는 seedlink 권한)."""
    parsed = urlparse(uri.strip())
    scheme = (parsed.scheme or "http").lower()
    if scheme == "fdsnws":
        rebuilt = parsed._replace(scheme="https")
        return "http", rebuilt.geturl()
    if scheme in {"http", "https"}:
        return "http", uri.strip()
    if scheme == "seedlink":
        return "seedlink", uri.strip()
    raise ValueError(f"지원하지 않는 데이터 소스 스킴이다: {scheme}")


class HttpAvailabilityTransport:
    def __init__(
        self,
        *,
        httpx_transport: httpx.AsyncBaseTransport | None = None,
        max_payload_bytes: int = DEFAULT_MAX_PAYLOAD_BYTES,
    ) -> None:
        self._httpx_transport = httpx_transport
        self.max_payload_bytes = max_payload_bytes

    async def fetch(self, url: str, *, connect_timeout_ms: int, request_timeout_ms: int) -> TransportResult:
        timeout = httpx.Timeout(
            connect=connect_timeout_ms / 1000,
            read=request_timeout_ms / 1000,
            write=request_timeout_ms / 1000,
            pool=request_timeout_ms / 1000,
        )
        kwargs: dict = {"timeout": timeout, "follow_redirects": False}
        if self._httpx_transport is not None:
            kwargs["transport"] = self._httpx_transport
        try:
            async with httpx.AsyncClient(**kwargs) as client:
                response = await client.get(url)
                latency_ms = response.elapsed.total_seconds() * 1000
                body = response.content
                if response.status_code >= 400:
                    return TransportResult(
                        success=False,
                        latency_ms=latency_ms,
                        http_status=response.status_code,
                        payload_bytes=len(body),
                        error_code=PollErrorCode.HTTP_ERROR,
                        error_message=f"HTTP {response.status_code}",
                    )
                if len(body) > self.max_payload_bytes:
                    return TransportResult(
                        success=False,
                        latency_ms=latency_ms,
                        http_status=response.status_code,
                        payload_bytes=len(body),
                        error_code=PollErrorCode.INVALID_PAYLOAD,
                        error_message="availability 응답이 너무 크다",
                    )
                try:
                    payload = response.json()
                except Exception as exc:  # noqa: BLE001
                    return TransportResult(
                        success=False,
                        latency_ms=latency_ms,
                        http_status=response.status_code,
                        payload_bytes=len(body),
                        error_code=PollErrorCode.INVALID_PAYLOAD,
                        error_message=f"JSON 을 해석할 수 없다: {exc}",
                    )
                return TransportResult(
                    success=True,
                    payload=payload,
                    latency_ms=latency_ms,
                    http_status=response.status_code,
                    payload_bytes=len(body),
                )
        except Exception as exc:  # noqa: BLE001
            error_code, message = classify_exception(exc)
            return TransportResult(success=False, error_code=error_code, error_message=message)


