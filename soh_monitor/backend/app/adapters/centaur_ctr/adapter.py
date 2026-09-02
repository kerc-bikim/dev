"""Centaur CTR Adapter.

계약(`app.adapters.contract.RecorderAdapter`)의 첫 번째 구현체다.
제조사 고유 지식은 이 패키지 안에만 있다.

지켜야 하는 것
  * 예외를 밖으로 던지지 않는다. 실패는 PollResult(success=False) 로 표현한다.
    한 장비의 예외가 수집 루프를 멈추면 안 된다.
  * 지원하지 않는 기능은 값 없이 UNSUPPORTED 로 표시한다. 0 이나 OK 로 채우지 않는다.
  * 비밀값은 결과·로그·미리보기에 남기지 않는다.
"""
from __future__ import annotations

import ipaddress
import re
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
from app.domain.enums import PollErrorCode
from app.domain.models import CapabilityReport, DeviceIdentity, PollResult, utcnow

from . import capabilities as capability_detector
from .client import CentaurClient, build_base_url
from .mapper import map_soh, unknown_channels
from .parser import ParsedSoh, ParseError, parse_soh

MANIFEST_PATH = Path(__file__).with_name("manifest.json")

# Instrument ID 예: centaur-6__0242 → 6채널, 시리얼 0242
_INSTRUMENT_ID_PATTERN = re.compile(r"^centaur-(?P<channels>\d)_+(?P<serial>[0-9A-Za-z]+)$")

# 비밀값으로 취급해 원본 미리보기에서 제거할 키.
_SECRET_KEY_MARKERS = ("password", "secret", "token", "credential", "apikey", "api_key")


class CentaurCtrAdapter(RecorderAdapter):
    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.manifest = AdapterManifest.from_file(MANIFEST_PATH)
        # 시험에서 가상 서버에 직접 붙기 위한 통로. 운영에서는 None 이다.
        self._transport = transport

    # ------------------------------------------------------------------ 설정

    def validate_configuration(self, connection: dict[str, Any]) -> list[str]:
        problems: list[str] = []

        hostname = str(connection.get("hostname") or "").strip()
        if not hostname:
            problems.append("IP 또는 호스트명이 필요하다")

        scheme = str(connection.get("scheme") or "http").lower()
        if scheme not in {"http", "https"}:
            problems.append(f"지원하지 않는 프로토콜이다: {scheme}")

        port = connection.get("port")
        if port is not None:
            try:
                port_number = int(port)
            except (TypeError, ValueError):
                problems.append("포트는 숫자여야 한다")
            else:
                if not 1 <= port_number <= 65535:
                    problems.append("포트는 1~65535 범위여야 한다")

        instrument_id = connection.get("instrumentId")
        if instrument_id and not _INSTRUMENT_ID_PATTERN.match(str(instrument_id)):
            # 막지는 않는다. 형식이 다른 장비가 있을 수 있으므로 경고로만 남긴다.
            problems.append(
                f"Instrument ID 형식이 낯설다: {instrument_id} (예: centaur-6__0242)"
            )

        if connection.get("password") and not connection.get("username"):
            problems.append("비밀번호를 쓰려면 사용자 이름도 필요하다")

        return problems

    def _client(self, context: DeviceContext) -> CentaurClient:
        return CentaurClient(
            build_base_url(context.connection),
            connect_timeout_ms=context.connect_timeout_ms,
            request_timeout_ms=context.request_timeout_ms,
            tls_verify=bool(context.connection.get("tlsVerify", True)),
            transport=self._transport,
        )

    @staticmethod
    def _credential(context: DeviceContext) -> dict[str, str] | None:
        if context.credential and context.credential.get("password"):
            return {
                "username": str(
                    context.credential.get("username")
                    or context.connection.get("username")
                    or "admin"
                ),
                "password": str(context.credential["password"]),
            }
        return None

    @staticmethod
    def _requested_instrument_id(context: DeviceContext) -> str | None:
        value = context.connection.get("instrumentId")
        return str(value) if value else None

    # ------------------------------------------------------------------ 조회

    async def _fetch(self, context: DeviceContext):
        client = self._client(context)
        return await client.fetch_soh(
            instrument_id=self._requested_instrument_id(context),
            credential=self._credential(context),
        )

    async def test_connection(self, context: DeviceContext) -> ConnectionTest:
        problems = self.validate_configuration(context.connection)
        blocking = [p for p in problems if "낯설다" not in p]
        if blocking:
            return ConnectionTest(reachable=False, message="; ".join(blocking))

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

        identity = self._identity_from(soh)
        return ConnectionTest(
            reachable=True,
            latency_ms=result.latency_ms,
            http_status=result.http_status,
            message=f"SOH 채널 {len(soh.channels)}개를 확인했다",
            identity=identity,
        )

    def _identity_from(self, soh: ParsedSoh) -> DeviceIdentity:
        """응답에서 확인할 수 있는 장비 신원.

        SOH API 는 모델명을 주지 않는다. Instrument ID 로 채널 수와 시리얼을 추정하고,
        모델은 비워 둔다. 추정할 수 없는 것을 채워 넣으면 등록값 비교가 거짓으로 어긋난다.
        """
        instrument_id = soh.instrument_id
        channel_count: int | None = None
        serial: str | None = None

        if instrument_id:
            match = _INSTRUMENT_ID_PATTERN.match(instrument_id)
            if match:
                channel_count = int(match.group("channels"))
                serial = match.group("serial")

        firmware = soh.raw("systemSoftwareVersion")
        ports: list[str] = []
        for port, name in (("0", "A"), ("1", "B")):
            if (
                soh.has(f"digitizer/sensor/status#_{port}")
                or soh.has(f"sensor/controlLines/state#_{port}")
                or any(
                    soh.has(f"digitizer/sensor/massPosition#_{port}_{axis}") for axis in (1, 2, 3)
                )
            ):
                ports.append(name)

        external = len(soh.names_with_prefix("externalSoh/voltage#_"))

        return DeviceIdentity(
            manufacturer="Nanometrics",
            model=None,
            serial_number=serial,
            instrument_id=instrument_id,
            firmware_version=str(firmware) if firmware is not None else None,
            channel_count=channel_count,
            sensor_ports=tuple(ports),
            external_soh_channels=external,
        )

    async def probe(self, context: DeviceContext) -> DeviceIdentity:
        result = await self._fetch(context)
        if not result.success:
            return DeviceIdentity(manufacturer="Nanometrics")
        try:
            soh = parse_soh(result.payload)
        except ParseError:
            return DeviceIdentity(manufacturer="Nanometrics")
        return self._identity_from(soh)

    async def detect_capabilities(self, context: DeviceContext) -> CapabilityReport:
        result = await self._fetch(context)
        if not result.success:
            return CapabilityReport()
        try:
            soh = parse_soh(result.payload)
        except ParseError:
            return CapabilityReport()
        identity = self._identity_from(soh)
        return capability_detector.detect(soh, expected_channel_count=identity.channel_count)

    # ------------------------------------------------------------------ 수집

    async def collect(self, context: DeviceContext) -> PollResult:
        poll_id = str(uuid.uuid4())
        observed_at = utcnow()

        try:
            result = await self._fetch(context)
        except Exception as exc:  # noqa: BLE001 - 계약상 예외를 던지지 않는다
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
        requested = self._requested_instrument_id(context)

        # 등록값과 실제 장비가 다르면 그 값을 그대로 쌓지 않는다. 다른 관측소의 데이터가
        # 섞이면 나중에 되돌릴 수 없다.
        mismatch: str | None = None
        if requested and identity.instrument_id and requested != identity.instrument_id:
            mismatch = f"요청 {requested} → 응답 {identity.instrument_id}"
        elif expected is not None:
            differences = identity.differences(expected)
            if "instrument_id" in differences or "serial_number" in differences:
                mismatch = "; ".join(
                    f"{field}: 등록 {want} / 실제 {got}"
                    for field, (want, got) in differences.items()
                )

        if mismatch:
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
        report = capability_detector.detect(soh, expected_channel_count=identity.channel_count)

        return PollResult(
            poll_id=poll_id,
            device_id=context.device_id,
            adapter_key=self.adapter_key,
            adapter_version=self.adapter_version,
            observed_at=observed_at,
            success=True,
            samples=tuple(mapping.samples),
            capabilities=report,
            identity=identity,
            latency_ms=result.latency_ms,
            http_status=result.http_status,
            payload_bytes=result.payload_bytes,
            unmapped_values=mapping.unmapped_values,
            unknown_channels=unknown_channels(soh, mapping),
        )

    # ------------------------------------------------------------------ 미리보기

    def redact(self, payload: Any) -> Any:
        """원본 미리보기에서 비밀값을 제거한다.

        soh-preview 는 운영자가 원본을 확인하는 통로이므로, 인증정보가 섞여 들어가면
        화면과 로그에 남는다.
        """
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


def is_allowed_host(hostname: str, allowed_networks: list[str]) -> bool:
    """연결 시험 SSRF 차단용 보조 판정.

    사설망 또는 승인된 대역만 허용한다. 호스트명이 IP 가 아니면 여기서 판정하지 않고
    호출 측에서 이름을 해석한 뒤 다시 확인한다.
    """
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return False
    for network in allowed_networks:
        try:
            if address in ipaddress.ip_network(network, strict=False):
                return True
        except ValueError:
            continue
    return False
