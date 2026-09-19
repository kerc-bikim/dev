"""ACME Mock Recorder Adapter.

확장성 검증용 두 번째 구현체다. 필드명·상태문자열·단위가 Centaur CTR 과 다르다.
수집기·스케줄러·DB·Grafana 는 이 패키지를 알지 못한다.
"""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import httpx

from app.adapters.contract import (
    AdapterManifest,
    ConnectionTest,
    DeviceContext,
    RecorderAdapter,
)
from app.adapters.transport import (
    CrashingTransport,
    GrpcStubTransport,
    HttpJsonTransport,
    SnmpStubTransport,
    Transport,
)
from app.domain.enums import PollErrorCode
from app.domain.models import CapabilityReport, DeviceIdentity, PollResult, utcnow

from . import capabilities as capability_detector
from .mapper import map_soh, unknown_channels
from .parser import ParseError, parse_soh

MANIFEST_PATH = Path(__file__).with_name("manifest.json")

_SECRET_KEY_MARKERS = ("password", "secret", "token", "credential", "apikey", "api_key", "community")


class MockRecorderAdapter(RecorderAdapter):
    def __init__(
        self,
        *,
        transport: Transport | httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.manifest = AdapterManifest.from_file(MANIFEST_PATH)
        self._injected = transport

    def validate_configuration(self, connection: dict[str, Any]) -> list[str]:
        problems: list[str] = []
        hostname = str(connection.get("hostname") or "").strip()
        if not hostname:
            problems.append("IP 또는 호스트명이 필요하다")

        protocol = str(connection.get("protocol") or connection.get("scheme") or "http").lower()
        if protocol not in {"http", "https", "snmp", "grpc"}:
            problems.append(f"지원하지 않는 프로토콜이다: {protocol}")

        port = connection.get("port")
        if port is not None:
            try:
                port_number = int(port)
            except (TypeError, ValueError):
                problems.append("포트는 숫자여야 한다")
            else:
                if not 1 <= port_number <= 65535:
                    problems.append("포트는 1~65535 범위여야 한다")

        if protocol == "snmp" and not connection.get("community"):
            problems.append("SNMP 를 쓰려면 community 가 필요하다")
        return problems

    def _protocol(self, connection: dict[str, Any]) -> str:
        return str(connection.get("protocol") or connection.get("scheme") or "http").lower()

    def _transport(self, context: DeviceContext) -> Transport:
        if isinstance(self._injected, (SnmpStubTransport, GrpcStubTransport, CrashingTransport, HttpJsonTransport)):
            return self._injected
        protocol = self._protocol(context.connection)
        if protocol == "snmp":
            return SnmpStubTransport()
        if protocol == "grpc":
            return GrpcStubTransport()
        httpx_transport = self._injected if isinstance(self._injected, httpx.AsyncBaseTransport) else None
        return HttpJsonTransport(path=str(context.connection.get("path") or "/soh"), httpx_transport=httpx_transport)

    def _credential(self, context: DeviceContext) -> dict[str, str] | None:
        if not context.credential:
            return None
        cleaned = {key: value for key, value in context.credential.items() if value}
        return cleaned or None

    async def _fetch(self, context: DeviceContext):
        return await self._transport(context).fetch(context)

    async def test_connection(self, context: DeviceContext) -> ConnectionTest:
        problems = self.validate_configuration(context.connection)
        if problems:
            return ConnectionTest(reachable=False, message="; ".join(problems))

        result = await self._fetch(context)
        if not result.success:
            return ConnectionTest(
                reachable=False,
                latency_ms=result.latency_ms,
                http_status=result.http_status,
                message=f"[{result.error_code.value if result.error_code else 'UNKNOWN'}] "
                f"{result.error_message or '연결하지 못했다'}",
            )
        try:
            soh = parse_soh(result.payload)
        except ParseError as exc:
            return ConnectionTest(
                reachable=False,
                latency_ms=result.latency_ms,
                http_status=result.http_status,
                message=f"응답을 SOH 로 해석할 수 없다: {exc}",
            )
        return ConnectionTest(
            reachable=True,
            latency_ms=result.latency_ms,
            http_status=result.http_status,
            message=f"읽기값 {len(soh.readings)}개를 확인했다",
            identity=self._identity_from(soh),
        )

    def _identity_from(self, soh) -> DeviceIdentity:
        firmware = soh.raw("fw.rev")
        return DeviceIdentity(
            manufacturer="ACME",
            model=soh.model,
            serial_number=soh.device_id,
            instrument_id=soh.device_id,
            firmware_version=str(firmware) if firmware is not None else None,
            channel_count=None,
            sensor_ports=(),
            external_soh_channels=0,
        )

    async def probe(self, context: DeviceContext) -> DeviceIdentity:
        result = await self._fetch(context)
        if not result.success:
            return DeviceIdentity(manufacturer="ACME")
        try:
            return self._identity_from(parse_soh(result.payload))
        except ParseError:
            return DeviceIdentity(manufacturer="ACME")

    async def detect_capabilities(self, context: DeviceContext) -> CapabilityReport:
        result = await self._fetch(context)
        if not result.success:
            return CapabilityReport()
        try:
            return capability_detector.detect(parse_soh(result.payload))
        except ParseError:
            return CapabilityReport()

    async def collect(self, context: DeviceContext) -> PollResult:
        poll_id = str(uuid.uuid4())
        observed_at = utcnow()
        try:
            result = await self._fetch(context)
        except Exception as exc:  # noqa: BLE001 - SDK 예외를 수집 루프에 넘기지 않는다
            return PollResult(
                poll_id=poll_id,
                device_id=context.device_id,
                adapter_key=self.adapter_key,
                adapter_version=self.adapter_version,
                observed_at=observed_at,
                success=False,
                error_code=PollErrorCode.ADAPTER_ERROR,
                error_message=str(exc),
            )

        if not result.success:
            return PollResult(
                poll_id=poll_id,
                device_id=context.device_id,
                adapter_key=self.adapter_key,
                adapter_version=self.adapter_version,
                observed_at=observed_at,
                success=False,
                latency_ms=result.latency_ms,
                http_status=result.http_status,
                payload_bytes=result.payload_bytes,
                error_code=result.error_code,
                error_message=result.error_message,
            )

        try:
            soh = parse_soh(result.payload)
        except ParseError as exc:
            return PollResult(
                poll_id=poll_id,
                device_id=context.device_id,
                adapter_key=self.adapter_key,
                adapter_version=self.adapter_version,
                observed_at=observed_at,
                success=False,
                latency_ms=result.latency_ms,
                http_status=result.http_status,
                payload_bytes=result.payload_bytes,
                error_code=PollErrorCode.INVALID_PAYLOAD,
                error_message=str(exc),
            )

        identity = self._identity_from(soh)
        expected = context.expected_identity
        if expected is not None:
            differences = identity.differences(expected)
            if "instrument_id" in differences or "serial_number" in differences:
                mismatch = "; ".join(
                    f"{field}: 등록 {want} / 실제 {got}"
                    for field, (want, got) in differences.items()
                )
                return PollResult(
                    poll_id=poll_id,
                    device_id=context.device_id,
                    adapter_key=self.adapter_key,
                    adapter_version=self.adapter_version,
                    observed_at=observed_at,
                    success=False,
                    latency_ms=result.latency_ms,
                    http_status=result.http_status,
                    payload_bytes=result.payload_bytes,
                    identity=identity,
                    error_code=PollErrorCode.IDENTITY_MISMATCH,
                    error_message=f"장비 신원이 등록값과 다르다 ({mismatch})",
                )

        mapping = map_soh(soh)
        return PollResult(
            poll_id=poll_id,
            device_id=context.device_id,
            adapter_key=self.adapter_key,
            adapter_version=self.adapter_version,
            observed_at=observed_at,
            success=True,
            samples=tuple(mapping.samples),
            capabilities=capability_detector.detect(soh),
            identity=identity,
            latency_ms=result.latency_ms,
            http_status=result.http_status,
            payload_bytes=result.payload_bytes,
            unmapped_values=mapping.unmapped_values,
            unknown_channels=unknown_channels(soh, mapping),
        )

    def redact(self, payload: Any) -> Any:
        if isinstance(payload, dict):
            cleaned: dict[str, Any] = {}
            for key, value in payload.items():
                lowered = str(key).lower()
                if any(marker in lowered for marker in _SECRET_KEY_MARKERS):
                    cleaned[key] = "***"
                else:
                    cleaned[key] = self.redact(value)
            return cleaned
        if isinstance(payload, list):
            return [self.redact(item) for item in payload]
        return payload
