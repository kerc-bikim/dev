"""비HTTP Transport 시험용 stub.

SNMP·gRPC 는 실제 장비를 붙이지 않는다. 목적은 하나다.
프로토콜 교체가 Adapter 안에 머물고, 수집기 코드가 그 존재를 모르게 하는 것.

운영에서 쓰려면 이 파일을 실제 SDK 호출로 바꾸되, 예외는 반드시 TransportResult 로
가둔다. 제조사 SDK 가 프로세스를 죽이면 수집 루프 전체가 멈춘다.
"""
from __future__ import annotations

from typing import Any

from app.domain.enums import PollErrorCode

from .base import TransportResult


class SnmpStubTransport:
    """SNMP GET 자리. OID 수집은 구현하지 않는다."""

    name = "snmp"

    async def fetch(self, context: Any) -> TransportResult:
        del context
        return TransportResult(
            success=False,
            error_code=PollErrorCode.ADAPTER_ERROR,
            error_message="SNMP transport 는 시험용 stub 이다. OID 수집은 구현하지 않았다",
        )


class GrpcStubTransport:
    """외부 Adapter Runner 자리. 프로세스 격리는 문서(grpc-runner) 를 따른다."""

    name = "grpc"

    async def fetch(self, context: Any) -> TransportResult:
        del context
        return TransportResult(
            success=False,
            error_code=PollErrorCode.ADAPTER_ERROR,
            error_message="gRPC transport 는 시험용 stub 이다. 외부 Runner 로 격리해 호출한다",
        )


class CrashingTransport:
    """계약 검증용. SDK 가 예외를 던져도 Adapter 가 PollResult 로 바꿔야 한다."""

    name = "crash"

    async def fetch(self, context: Any) -> TransportResult:
        del context
        raise RuntimeError("제조사 SDK 가 프로세스를 죽이려 했다")
