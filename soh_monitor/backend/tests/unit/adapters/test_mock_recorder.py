"""가상 제조사 Adapter 계약 시험.

Centaur 와 다른 필드명·상태문자열·단위를 표준 Metric 으로 옮기는 것이 목적이다.
수집기 코드를 고치지 않고도 같은 poll_device 경로로 수집되어야 한다.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
from httpx import ASGITransport

from app.adapters.contract import DeviceContext
from app.adapters.mock_recorder.adapter import MANIFEST_PATH, MockRecorderAdapter
from app.adapters.mock_recorder.mapper import map_soh
from app.adapters.mock_recorder.parser import parse_soh
from app.adapters.registry import AdapterRegistry
from app.adapters.transport import CrashingTransport, SnmpStubTransport
from app.auth.credentials import CredentialResolver
from app.collector.retry import RetryPolicy
from app.collector.runner import poll_device
from app.db.models import CollectionMode
from app.domain.enums import PollErrorCode, Severity, SupportState
from app.domain.models import DeviceIdentity
from app.metrics.catalog import validate_sample
from app.repository.influx.points import DeviceTags
from app.repository.postgres.collector_repo import DueDevice

TESTDATA = Path(__file__).resolve().parents[3] / "app" / "adapters" / "mock_recorder" / "testdata"


def _payload(name: str) -> dict:
    return json.loads((TESTDATA / name).read_text(encoding="utf-8"))


def _asgi_app(payload: dict, status_code: int = 200):
    body = json.dumps(payload).encode("utf-8")

    async def app(scope, receive, send):  # noqa: ANN001
        assert scope["type"] == "http"
        await send(
            {
                "type": "http.response.start",
                "status": status_code,
                "headers": [[b"content-type", b"application/json"]],
            }
        )
        await send({"type": "http.response.body", "body": body})

    return app


def build(payload: dict | None = None, **connection) -> tuple[MockRecorderAdapter, DeviceContext]:
    document = payload if payload is not None else _payload("synthetic-normal.json")
    adapter = MockRecorderAdapter(transport=ASGITransport(app=_asgi_app(document)))
    context = DeviceContext(
        device_id="mock-1",
        station_code="M01",
        connection={"hostname": "mock-m01", "path": "/soh", **connection},
        connect_timeout_ms=2000,
        request_timeout_ms=2000,
    )
    return adapter, context


class Test설정검증:
    def test_호스트명이_없으면_거부한다(self):
        adapter, _ = build()
        assert adapter.validate_configuration({}) == ["IP 또는 호스트명이 필요하다"]

    def test_SNMP는_community를_요구한다(self):
        adapter, _ = build()
        problems = adapter.validate_configuration({"hostname": "10.1.2.3", "protocol": "snmp"})
        assert any("community" in item for item in problems)

    def test_지원하지_않는_프로토콜을_거부한다(self):
        adapter, _ = build()
        problems = adapter.validate_configuration({"hostname": "10.1.2.3", "protocol": "ftp"})
        assert any("프로토콜" in item for item in problems)


class Test단위와상태:
    def test_mV와_비율을_표준단위로_옮긴다(self):
        soh = parse_soh(_payload("synthetic-normal.json"))
        mapping = map_soh(soh)
        by_key = {sample.metric_key: sample for sample in mapping.samples}
        assert by_key["power.input_voltage_v"].value_float == pytest.approx(12.6)
        assert by_key["power.current_a"].value_float == pytest.approx(0.18)
        assert by_key["timing.quality_percent"].value_float == pytest.approx(98.0)
        assert by_key["storage.used_percent"].value_float == pytest.approx(42.0)
        assert by_key["device.overall_status"].value_status is Severity.OK
        assert by_key["timing.status"].value_status is Severity.OK
        assert by_key["storage.recording_status"].value_status is Severity.OK

    def test_응답단위가_있으면_그것을_우선한다(self):
        soh = parse_soh(
            {
                "deviceId": "MR-9",
                "readings": {
                    "psu.millivolts": {"value": 12.5, "units": "V"},
                    "clk.quality": {"value": 80, "units": "percent"},
                },
            }
        )
        mapping = map_soh(soh)
        by_key = {sample.metric_key: sample for sample in mapping.samples}
        assert by_key["power.input_voltage_v"].value_float == pytest.approx(12.5)
        assert by_key["timing.quality_percent"].value_float == pytest.approx(80.0)

    def test_모르는_상태문자열은_UNKNOWN이고_원문을_남긴다(self):
        soh = parse_soh(_payload("synthetic-unknown-status.json"))
        mapping = map_soh(soh)
        by_key = {sample.metric_key: sample for sample in mapping.samples}
        assert by_key["device.overall_status"].value_status is Severity.UNKNOWN
        assert mapping.unmapped_values["device.overall_status"] == "QUANTUM"
        assert by_key["timing.status"].value_status is Severity.UNKNOWN


class Test수집계약:
    async def test_정상_수집은_표준_Metric만_낸다(self):
        adapter, context = build()
        result = await adapter.collect(context)
        assert result.success is True
        assert result.adapter_key == "acme.mock.recorder"
        assert result.identity is not None
        assert result.identity.manufacturer == "ACME"
        assert result.identity.serial_number == "MR-1001"
        for sample in result.samples:
            validate_sample(sample)
            assert not sample.metric_key.startswith("vendor.")
        keys = {sample.metric_key for sample in result.samples}
        assert "power.input_voltage_v" in keys
        assert "sensor.status" not in keys
        assert "external_soh.value" not in keys

    async def test_없는_기능은_UNSUPPORTED이다(self):
        adapter, context = build()
        report = await adapter.detect_capabilities(context)
        assert report.state_of("power.input_voltage") is SupportState.SUPPORTED_ENABLED
        assert report.state_of("sensor.status") is SupportState.UNSUPPORTED
        assert report.state_of("external_soh.analog") is SupportState.UNSUPPORTED
        assert report.state_of("storage.removable") is SupportState.UNSUPPORTED
        assert report.evaluable("sensor.status") is False

    async def test_값이_빠진_채널을_0으로_채우지_않는다(self):
        adapter, context = build(_payload("synthetic-missing-fields.json"))
        result = await adapter.collect(context)
        assert result.success is True
        keys = {sample.metric_key for sample in result.samples}
        assert "power.input_voltage_v" not in keys
        assert result.capabilities.state_of("power.input_voltage") is SupportState.UNSUPPORTED

    async def test_연결_시험_성공(self):
        adapter, context = build()
        test = await adapter.test_connection(context)
        assert test.reachable is True
        assert test.identity is not None
        assert test.identity.instrument_id == "MR-1001"

    async def test_신원_불일치는_수집을_거부한다(self):
        adapter, context = build()
        context = DeviceContext(
            device_id=context.device_id,
            station_code=context.station_code,
            connection=context.connection,
            expected_identity=DeviceIdentity(serial_number="OTHER"),
        )
        result = await adapter.collect(context)
        assert result.success is False
        assert result.error_code is PollErrorCode.IDENTITY_MISMATCH

    def test_미리보기에서_비밀값을_지운다(self):
        adapter, _ = build()
        cleaned = adapter.redact({"apiToken": "s3cret", "community": "private", "readings": {"sys.health": "GOOD"}})
        assert cleaned["apiToken"] == "***"
        assert cleaned["community"] == "***"
        assert cleaned["readings"]["sys.health"] == "GOOD"


class TestTransport격리:
    async def test_SNMP는_Adapter_안에서만_실패한다(self):
        adapter = MockRecorderAdapter()
        context = DeviceContext(
            device_id="mock-1",
            station_code="M01",
            connection={"hostname": "10.1.2.3", "protocol": "snmp", "community": "public"},
        )
        result = await adapter.collect(context)
        assert result.success is False
        assert result.error_code is PollErrorCode.ADAPTER_ERROR
        assert "SNMP" in (result.error_message or "")

    async def test_주입한_SNMP_stub도_같은_결과다(self):
        adapter = MockRecorderAdapter(transport=SnmpStubTransport())
        context = DeviceContext(
            device_id="mock-1",
            station_code="M01",
            connection={"hostname": "10.1.2.3", "protocol": "snmp", "community": "public"},
        )
        result = await adapter.collect(context)
        assert result.success is False
        assert result.error_code is PollErrorCode.ADAPTER_ERROR

    async def test_SDK_예외는_PollResult로_가둔다(self):
        adapter = MockRecorderAdapter(transport=CrashingTransport())
        context = DeviceContext(
            device_id="mock-1",
            station_code="M01",
            connection={"hostname": "10.1.2.3"},
        )
        result = await adapter.collect(context)
        assert result.success is False
        assert result.error_code is PollErrorCode.ADAPTER_ERROR
        assert "SDK" in (result.error_message or "")


def _due(adapter_key: str, connection: dict) -> DueDevice:
    device_id = uuid.uuid4()
    station_id = uuid.uuid4()
    return DueDevice(
        device_id=device_id,
        station_id=station_id,
        station_code="M01",
        adapter_key=adapter_key,
        collection_mode=CollectionMode.DIRECT,
        connection=connection,
        credential_reference=None,
        connect_timeout_ms=2000,
        request_timeout_ms=2000,
        poll_interval_minutes=1,
        retry_count=0,
        retry_delay_seconds=0,
        consecutive_failures=0,
        last_observed_at=None,
        tags=DeviceTags(
            device_id=str(device_id),
            station_id=str(station_id),
            station_code="M01",
            collection_mode="DIRECT",
            manufacturer="ACME",
        ),
    )


async def test_같은_poll_device_경로로_수집한다():
    """스케줄러를 고치지 않고 Registry 에만 등록하면 수집된다."""
    registry = AdapterRegistry()
    adapter = MockRecorderAdapter(transport=ASGITransport(app=_asgi_app(_payload("synthetic-normal.json"))))
    registry.register(adapter, manifest_path=MANIFEST_PATH)
    outcome = await poll_device(
        _due("acme.mock.recorder", {"hostname": "mock-m01", "path": "/soh"}),
        registry,
        CredentialResolver(),
        RetryPolicy(max_attempts=1),
    )
    assert outcome.result.success is True
    assert outcome.result.adapter_key == "acme.mock.recorder"
    assert any(sample.metric_key == "power.input_voltage_v" for sample in outcome.result.samples)
