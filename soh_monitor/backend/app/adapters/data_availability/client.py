"""데이터 서버 통신.

HTTP(FDSNWS·Centaur availability) 와 SeedLink stub 을 여기서만 다룬다.
수집기는 URI 스킴을 모른다. 실패는 예외가 아니라 TransportResult 다.
"""
from __future__ import annotations

from urllib.parse import urlparse

import httpx

from app.adapters.transport.base import TransportResult
from app.adapters.transport.http import classify_exception
from app.domain.enums import PollErrorCode

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


class SeedLinkStubTransport:
    """SeedLink 는 이진 프로토콜이다. 여기서는 연결 가능 여부만 확인하고,
    채널 시각은 HTTP availability 가 있을 때 그쪽으로 넘긴다.

    실서버 INFO STREAMS 파싱은 이 stub 을 교체하는 자리에서 한다.
    수집 루프를 죽이지 않는 것이 계약이다.
    """

    async def fetch(self, uri: str, *, connect_timeout_ms: int, request_timeout_ms: int) -> TransportResult:
        del request_timeout_ms
        parsed = urlparse(uri)
        host = parsed.hostname
        port = parsed.port or 18000
        if not host:
            return TransportResult(
                success=False,
                error_code=PollErrorCode.ADAPTER_ERROR,
                error_message="SeedLink 호스트가 없다",
            )
        try:
            reader, writer = await _open_tcp(host, port, connect_timeout_ms / 1000)
        except Exception as exc:  # noqa: BLE001
            return TransportResult(
                success=False,
                error_code=PollErrorCode.CONNECTION_REFUSED,
                error_message=str(exc),
            )
        try:
            writer.write(b"HELLO\r")
            await writer.drain()
            banner = await reader.read(256)
        except Exception as exc:  # noqa: BLE001
            return TransportResult(
                success=False,
                error_code=PollErrorCode.REQUEST_TIMEOUT,
                error_message=str(exc),
            )
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:  # noqa: BLE001
                pass
        if not banner:
            return TransportResult(
                success=False,
                error_code=PollErrorCode.INVALID_PAYLOAD,
                error_message="SeedLink HELLO 응답이 비어 있다",
            )
        return TransportResult(
            success=False,
            error_code=PollErrorCode.ADAPTER_ERROR,
            error_message="SeedLink INFO STREAMS 는 아직 구현하지 않았다. HTTP/FDSN availability 를 쓴다",
        )


async def _open_tcp(host: str, port: int, timeout: float):
    import asyncio

    return await asyncio.wait_for(asyncio.open_connection(host, port), timeout=timeout)
