"""Adapter 내부 Transport 계약.

수집기·스케줄러는 HTTP/SNMP/gRPC 를 모른다. Transport 선택은 Adapter 안에서만 일어난다.
실패는 예외가 아니라 TransportResult 로 표현한다. SDK 가 죽어도 수집 루프는 살아야 한다.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from app.domain.enums import PollErrorCode


@dataclass(frozen=True)
class TransportResult:
    """한 번의 원격 조회 결과. 성공이든 실패든 항상 만들어진다."""

    success: bool
    payload: Any = None
    latency_ms: float | None = None
    http_status: int | None = None
    payload_bytes: int | None = None
    error_code: PollErrorCode | None = None
    error_message: str | None = None


class Transport(Protocol):
    """Adapter 가 장비와 말하는 통로."""

    name: str

    async def fetch(self, context: Any) -> TransportResult: ...
