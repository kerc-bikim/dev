"""Adapter 내부 Transport.

수집기·스케줄러·Grafana 는 이 패키지를 가져오지 않는다.
"""

from .base import Transport, TransportResult
from .http import HttpJsonTransport, classify_exception
from .stub import CrashingTransport, GrpcStubTransport, SnmpStubTransport

__all__ = (
    "CrashingTransport",
    "GrpcStubTransport",
    "HttpJsonTransport",
    "SnmpStubTransport",
    "Transport",
    "TransportResult",
    "classify_exception",
)
