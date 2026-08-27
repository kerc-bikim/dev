"""Centaur CTR Adapter 계약 시험.

가상 서버에 실제 HTTP 규약으로 붙어(ASGI 전송) 본문 시나리오 13종과 통신 시나리오 9종을
지난다. 계획서 13절의 Adapter 계약 시험 목록이 여기에 대응한다.
"""
from __future__ import annotations

import sys
from pathlib import Path

import httpx
import pytest
from httpx import ASGITransport

from app.adapters.centaur_ctr.adapter import CentaurCtrAdapter, is_allowed_host
from app.adapters.contract import DeviceContext
from app.domain.enums import PollErrorCode, Severity, SupportState
from app.domain.models import DeviceIdentity, dimensioned_capability
from app.metrics.catalog import validate_sample

# 가상 서버는 backend 밖(mock/)에 있다. 런타임 이미지에 들어가지 않게 하려는 배치다.
sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from mock.centaur_mock.devices import DeviceRegistry, VirtualDevice  # noqa: E402
from mock.centaur_mock.envelope import EnvelopeShape  # noqa: E402
from mock.centaur_mock.scenarios import PayloadScenario, TransportScenario  # noqa: E402
from mock.centaur_mock.server import create_app  # noqa: E402

INSTRUMENT_ID = "centaur-6__0242"


def build(instrument_id: str = INSTRUMENT_ID, **changes) -> tuple[CentaurCtrAdapter, DeviceContext]:
    device = VirtualDevice(
        instrument_id=instrument_id,
        station_code="A01",
        model="CTR4-6S",
        firmware_version="3.2.8",
        serial_number=instrument_id.split("_")[-1],
        channel_count=changes.pop("channel_count", 6),
        **changes,
    )
    app = create_app(DeviceRegistry([device]))
    adapter = CentaurCtrAdapter(transport=ASGITransport(app=app))
    context = DeviceContext(
        device_id="device-1",
        station_code="A01",
        connection={"scheme": "http", "hostname": "ctr-a01", "instrumentId": instrument_id},
        connect_timeout_ms=2000,
        request_timeout_ms=2000,
    )
    return adapter, context


class Test설정검증:
    def test_호스트명이_없으면_거부한다(self):
        adapter, _ = build()
        assert adapter.validate_configuration({}) == ["IP 또는 호스트명이 필요하다"]

    def test_정상_설정은_통과한다(self):
        adapter, _ = build()
        assert adapter.validate_configuration({"hostname": "10.1.2.3"}) == []

    @pytest.mark.parametrize("port", [0, 70000, "여덟"])
    def test_잘못된_포트를_거부한다(self, port):
        adapter, _ = build()
        assert adapter.validate_configuration({"hostname": "10.1.2.3", "port": port}) != []

    def test_지원하지_않는_프로토콜을_거부한다(self):
        adapter, _ = build()
        problems = adapter.validate_configuration({"hostname": "10.1.2.3", "scheme": "ftp"})
        assert any("프로토콜" in p for p in problems)

    def test_비밀번호만_주면_사용자_이름을_요구한다(self):
        adapter, _ = build()
        problems = adapter.validate_configuration({"hostname": "10.1.2.3", "password": "x"})
        assert any("사용자 이름" in p for p in problems)

    def test_낯선_InstrumentID는_막지_않고_알린다(self):
        adapter, _ = build()
        problems = adapter.validate_configuration(
            {"hostname": "10.1.2.3", "instrumentId": "meridian-1234"}
        )
        assert any("낯설다" in p for p in problems)


class Test연결시험과탐지:
    async def test_연결_시험_성공(self):
        adapter, context = build()
        result = await adapter.test_connection(context)
        assert result.reachable is True
        assert result.latency_ms is not None
        assert result.identity is not None
        assert result.identity.instrument_id == INSTRUMENT_ID

    async def test_연결_시험은_실패_이유를_알려준다(self):
        adapter, context = build(transport_scenario=TransportScenario.HTTP_500)
        result = await adapter.test_connection(context)
        assert result.reachable is False
        assert "HTTP_ERROR" in result.message

    async def test_장비_신원_추정(self):
        """SOH API 는 모델명을 주지 않는다. 추정할 수 없는 것은 비워 둔다."""
        adapter, context = build()
        identity = await adapter.probe(context)
        assert identity.instrument_id == INSTRUMENT_ID
        assert identity.channel_count == 6
        assert identity.serial_number == "0242"
        assert identity.firmware_version == "3.2.8"
        assert identity.sensor_ports == ("A", "B")
        assert identity.model is None


class Test기능탐지:
    async def test_6채널은_두_포트를_모두_지원한다(self):
        adapter, context = build()
        report = await adapter.detect_capabilities(context)
        assert report.state_of("sensor.status", "A") is SupportState.SUPPORTED_ENABLED
        assert report.state_of("sensor.status", "B") is SupportState.SUPPORTED_ENABLED

    async def test_3채널_모델의_SensorB는_미지원이다(self):
        """없는 포트를 장애로 세면 알림 신뢰도가 무너진다."""
        adapter, context = build(
            instrument_id="centaur-3__0117",
            channel_count=3,
            payload_scenario=PayloadScenario.THREE_CHANNEL,
        )
        report = await adapter.detect_capabilities(context)
        assert report.state_of("sensor.status", "A") is SupportState.SUPPORTED_ENABLED
        assert report.state_of("sensor.status", "B") is SupportState.UNSUPPORTED
        assert report.evaluable("sensor.status", "B") is False

    async def test_SD_슬롯이_없는_모델은_미지원이다(self):
        adapter, context = build(payload_scenario=PayloadScenario.SLOT_ABSENT)
        report = await adapter.detect_capabilities(context)
        assert report.state_of("storage.removable") is SupportState.UNSUPPORTED

    async def test_카드_미장착은_미지원이_아니다(self):
        """슬롯은 있다. 기능 없음과 카드 없음은 다른 상태다."""
        adapter, context = build(payload_scenario=PayloadScenario.NO_SD_CARD)
        report = await adapter.detect_capabilities(context)
        assert report.state_of("storage.removable") is SupportState.SUPPORTED_ENABLED

    async def test_외부SOH가_없는_모델(self):
        adapter, context = build(payload_scenario=PayloadScenario.NO_EXTERNAL_SOH)
        report = await adapter.detect_capabilities(context)
        assert report.state_of("external_soh.analog") is SupportState.UNSUPPORTED

    async def test_확정할_수_없는_기능은_확인_불가로_둔다(self):
        adapter, context = build()
        report = await adapter.detect_capabilities(context)
        assert report.state_of("acquisition.data_check") is SupportState.UNKNOWN
        assert report.state_of("environment.weather_station") is SupportState.UNKNOWN

    async def test_포트는_있는데_채널만_없으면_확인_불가다(self):
        """MISSING_FIELDS 는 Sensor B 의 상태 채널만 빠뜨린다. Mass Position 은 온다.

        포트는 존재하므로 '기능 없음' 이 아니다. 없는 기능으로 단정하면 실제 이상을
        감시에서 빼 버린다.
        """
        adapter, context = build(payload_scenario=PayloadScenario.MISSING_FIELDS)
        report = await adapter.detect_capabilities(context)
        assert report.states[dimensioned_capability("sensor.status", "B")] is SupportState.UNKNOWN
        assert (
            report.states[dimensioned_capability("sensor.mass_position", "B")]
            is SupportState.SUPPORTED_ENABLED
        )

    async def test_6채널_장비가_포트정보를_통째로_주지_않으면_확인_불가다(self):
        adapter, context = build(payload_scenario=PayloadScenario.THREE_CHANNEL)
        report = await adapter.detect_capabilities(context)
        # Instrument ID 가 6채널이라고 알려 왔는데 포트 B 정보가 전혀 없는 상황이다.
        assert report.states[dimensioned_capability("sensor.status", "B")] is SupportState.UNKNOWN


class Test본문시나리오:
    @pytest.mark.parametrize("shape", [EnvelopeShape.CHANNEL_LIST, EnvelopeShape.FLAT_MAP])
    async def test_두_응답_형태_모두_수집된다(self, shape):
        adapter, context = build(envelope_shape=shape)
        result = await adapter.collect(context)
        assert result.success is True
        assert len(result.samples) > 20

    @pytest.mark.parametrize("scenario", list(PayloadScenario))
    async def test_모든_본문_시나리오에서_수집이_성공하고_샘플이_유효하다(self, scenario):
        """장비가 이상을 보고하는 것은 수집 실패가 아니다. 값으로 받아 판정에 넘긴다."""
        adapter, context = build(payload_scenario=scenario)
        result = await adapter.collect(context)
        assert result.success is True, result.error_message
        assert result.samples
        for sample in result.samples:
            validate_sample(sample)

    async def test_GPS_미잠금(self):
        adapter, context = build(payload_scenario=PayloadScenario.GPS_UNLOCKED)
        result = await adapter.collect(context)
        samples = {s.metric_key: s for s in result.samples}
        assert samples["timing.status"].value_status is Severity.WARNING
        assert samples["timing.phase_lock"].value_status is Severity.CRITICAL
        assert samples["gnss.satellite_count"].value_int == 0

    async def test_저전압(self):
        adapter, context = build(payload_scenario=PayloadScenario.LOW_VOLTAGE)
        result = await adapter.collect(context)
        samples = {s.metric_key: s for s in result.samples}
        assert samples["power.input_voltage_v"].value_float < 11.5

    async def test_저장소_가득(self):
        adapter, context = build(payload_scenario=PayloadScenario.STORE_FULL)
        result = await adapter.collect(context)
        samples = {s.metric_key: s for s in result.samples}
        assert samples["storage.used_percent"].value_float > 95
        assert samples["storage.recording_status"].value_status is Severity.CRITICAL
        assert samples["archive.continuous_status"].value_status is Severity.CRITICAL

    async def test_센서_오류(self):
        adapter, context = build(payload_scenario=PayloadScenario.SENSOR_ERROR)
        result = await adapter.collect(context)
        by_port = {
            s.dimensions["sensor_port"]: s.value_status
            for s in result.samples
            if s.metric_key == "sensor.status"
        }
        assert by_port["A"] is Severity.CRITICAL

    async def test_모르는_상태_문자열은_정상으로_오인되지_않는다(self):
        adapter, context = build(payload_scenario=PayloadScenario.UNKNOWN_STATUS_STRING)
        result = await adapter.collect(context)
        samples = {s.metric_key: s for s in result.samples}
        assert samples["timing.status"].value_status is Severity.UNKNOWN
        assert samples["device.overall_status"].value_status is Severity.UNKNOWN
        assert result.unmapped_values["timing.status"] == "quantum drift compensating"
        assert result.unmapped_values["device.overall_status"] == "nominal"

    async def test_채널이_누락돼도_부분_결과를_낸다(self):
        adapter, context = build(payload_scenario=PayloadScenario.MISSING_FIELDS)
        result = await adapter.collect(context)
        keys = {s.metric_key for s in result.samples}
        assert result.success is True
        assert "device.temperature_c" not in keys
        assert "power.input_voltage_v" in keys

    async def test_Mass_Position이_SOH에_없는_경우(self):
        """M-1.3 결과가 '없다' 로 나올 경우에 대비한 경로다.

        포트 자체는 응답에 있으므로 '기능 없음' 으로 단정하지 않고 '확인 불가' 로 둔다.
        실장비가 실제로 SOH API 로 축별 값을 주지 않는다고 확정되면, 추론이 아니라
        모델 정의(device_models)나 등록 설정에서 UNSUPPORTED 로 못 박아야 한다.
        """
        adapter, context = build(payload_scenario=PayloadScenario.NO_MASS_POSITION)
        result = await adapter.collect(context)
        keys = {s.metric_key for s in result.samples}
        assert "sensor.mass_position_v" not in keys
        assert result.capabilities.state_of("sensor.mass_position", "A") is SupportState.UNKNOWN
        assert result.capabilities.evaluable("sensor.mass_position", "A") is False

    async def test_예전_펌웨어의_수치_코드(self):
        adapter, context = build(
            payload_scenario=PayloadScenario.OLD_FIRMWARE,
            envelope_shape=EnvelopeShape.FLAT_MAP,
        )
        result = await adapter.collect(context)
        samples = {s.metric_key: s for s in result.samples}
        assert samples["timing.status"].value_status is Severity.OK
        assert samples["device.firmware_version"].value_text == "2.9.4"
        assert result.unmapped_values == {}


class Test통신시나리오:
    async def test_HTTP_오류(self):
        adapter, context = build(transport_scenario=TransportScenario.HTTP_500)
        result = await adapter.collect(context)
        assert result.success is False
        assert result.error_code is PollErrorCode.HTTP_ERROR
        assert result.http_status == 500

    async def test_인증_오류는_HTTP_오류와_구분된다(self):
        adapter, context = build(transport_scenario=TransportScenario.HTTP_401)
        result = await adapter.collect(context)
        assert result.error_code is PollErrorCode.AUTH_ERROR

    async def test_깨진_JSON은_본문_오류다(self):
        adapter, context = build(transport_scenario=TransportScenario.INVALID_JSON)
        result = await adapter.collect(context)
        assert result.error_code is PollErrorCode.INVALID_PAYLOAD

    async def test_잘린_본문도_본문_오류다(self):
        adapter, context = build(transport_scenario=TransportScenario.TRUNCATED_BODY)
        result = await adapter.collect(context)
        assert result.error_code is PollErrorCode.INVALID_PAYLOAD

    async def test_Content_Type이_틀려도_JSON이면_읽는다(self):
        """장비가 헤더를 잘못 붙이는 것만으로 수집을 포기하지 않는다."""
        adapter, context = build(transport_scenario=TransportScenario.WRONG_CONTENT_TYPE)
        result = await adapter.collect(context)
        assert result.success is True

    async def test_과대_응답은_거부한다(self):
        adapter, context = build(transport_scenario=TransportScenario.HUGE_PAYLOAD)
        result = await adapter.collect(context)
        assert result.success is False
        assert result.error_code is PollErrorCode.INVALID_PAYLOAD
        assert "너무 크다" in (result.error_message or "")

    @pytest.mark.parametrize(
        ("exception", "expected"),
        [
            (httpx.ConnectTimeout("연결 시간 초과"), PollErrorCode.CONNECT_TIMEOUT),
            (httpx.ReadTimeout("응답 시간 초과"), PollErrorCode.REQUEST_TIMEOUT),
            (httpx.PoolTimeout("풀 대기 초과"), PollErrorCode.REQUEST_TIMEOUT),
            (httpx.ConnectError("Connection refused"), PollErrorCode.CONNECTION_REFUSED),
            (
                httpx.ConnectError("[Errno -2] Name or service not known"),
                PollErrorCode.DNS_FAILURE,
            ),
            (httpx.RemoteProtocolError("서버가 연결을 끊었다"), PollErrorCode.INVALID_PAYLOAD),
            (httpx.ReadError("읽기 실패"), PollErrorCode.CONNECTION_REFUSED),
        ],
    )
    async def test_통신_예외를_유형별로_구분한다(self, exception, expected):
        """'장비가 죽었다'와 '회선이 느리다'와 '본문이 깨졌다'는 조치가 다르다.

        httpx 의 ASGI 전송은 Timeout 을 적용하지 않으므로(같은 프로세스에서 앱을 직접
        await 한다) 실제 지연 대신 예외를 주입해 분류 경로를 지난다. 실제 회선에서의
        Timeout 은 M3 통합 시험에서 실 HTTP 로 확인한다.
        """

        def raise_it(request: httpx.Request) -> httpx.Response:
            raise exception

        adapter = CentaurCtrAdapter(transport=httpx.MockTransport(raise_it))
        context = DeviceContext(
            device_id="device-1",
            station_code="A01",
            connection={"scheme": "http", "hostname": "ctr-a01"},
        )
        result = await adapter.collect(context)
        assert result.success is False
        assert result.error_code is expected
        assert result.error_message

    async def test_느린_응답도_시간_안에_오면_성공이다(self):
        adapter, context = build(
            transport_scenario=TransportScenario.SLOW_RESPONSE, latency_ms=200
        )
        result = await adapter.collect(context)
        assert result.success is True
        assert result.latency_ms is not None

    async def test_장비_신원_불일치는_수집을_거부한다(self):
        """다른 관측소 데이터가 섞이면 나중에 되돌릴 수 없다."""
        adapter, context = build(transport_scenario=TransportScenario.IDENTITY_MISMATCH)
        result = await adapter.collect(context)
        assert result.success is False
        assert result.error_code is PollErrorCode.IDENTITY_MISMATCH
        assert "centaur-6__9999" in (result.error_message or "")

    async def test_등록된_시리얼과_다르면_거부한다(self):
        adapter, base = build()
        context = DeviceContext(
            device_id=base.device_id,
            station_code=base.station_code,
            connection={"scheme": "http", "hostname": "ctr-a01"},
            expected_identity=DeviceIdentity(serial_number="9999"),
        )
        result = await adapter.collect(context)
        assert result.error_code is PollErrorCode.IDENTITY_MISMATCH

    async def test_성공_실패_반복에서도_예외가_새지_않는다(self):
        adapter, context = build(transport_scenario=TransportScenario.FLAPPING)
        outcomes = [(await adapter.collect(context)).success for _ in range(6)]
        assert True in outcomes and False in outcomes

    async def test_알_수_없는_InstrumentID는_HTTP_오류로_돌아온다(self):
        adapter, base = build()
        context = DeviceContext(
            device_id=base.device_id,
            station_code=base.station_code,
            connection={"scheme": "http", "hostname": "ctr-a01", "instrumentId": "centaur-6__0000"},
        )
        result = await adapter.collect(context)
        assert result.success is False
        assert result.error_code is PollErrorCode.HTTP_ERROR
        assert result.http_status == 404


class Test인증:
    async def test_인증이_필요한_장비에_인증정보_없이_붙으면_인증_오류다(self):
        adapter, context = build(requires_auth=True)
        result = await adapter.collect(context)
        assert result.error_code is PollErrorCode.AUTH_ERROR

    async def test_인증정보를_주면_수집된다(self):
        """매뉴얼 7.6절 절차: GET /key → POST /login → 세션 쿠키."""
        adapter, base = build(requires_auth=True, password="centaur", username="admin")
        context = DeviceContext(
            device_id=base.device_id,
            station_code=base.station_code,
            connection=base.connection,
            credential={"username": "admin", "password": "centaur"},
        )
        result = await adapter.collect(context)
        assert result.success is True

    async def test_비밀번호가_틀리면_인증_오류다(self):
        adapter, base = build(requires_auth=True, password="centaur")
        context = DeviceContext(
            device_id=base.device_id,
            station_code=base.station_code,
            connection=base.connection,
            credential={"username": "admin", "password": "틀린비밀번호"},
        )
        result = await adapter.collect(context)
        assert result.error_code is PollErrorCode.AUTH_ERROR

    async def test_수집_결과에_비밀값이_남지_않는다(self):
        secret = "Zq7-관측소-비밀번호"
        adapter, base = build(requires_auth=True, password=secret)
        context = DeviceContext(
            device_id=base.device_id,
            station_code=base.station_code,
            connection=base.connection,
            credential={"username": "admin", "password": secret},
        )
        result = await adapter.collect(context)
        assert result.success is True
        assert secret not in result.model_dump_json()


class Test미리보기:
    def test_비밀값을_제거한다(self):
        adapter, _ = build()
        cleaned = adapter.redact(
            {
                "instrumentId": "centaur-6__0242",
                "password": "비밀",
                "nested": {"apiToken": "abc", "value": 1},
                "list": [{"credentialReference": "secret://x"}],
            }
        )
        assert cleaned["password"] == "***"
        assert cleaned["nested"]["apiToken"] == "***"
        assert cleaned["list"][0]["credentialReference"] == "***"
        assert cleaned["instrumentId"] == "centaur-6__0242"
        assert cleaned["nested"]["value"] == 1


class TestSSRF방지:
    @pytest.mark.parametrize("host", ["10.1.2.3", "172.16.0.9", "192.168.1.20"])
    def test_사설망은_허용한다(self, host):
        assert is_allowed_host(host, ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"]) is True

    @pytest.mark.parametrize("host", ["8.8.8.8", "169.254.169.254", "example.org"])
    def test_그_밖의_주소는_허용하지_않는다(self, host):
        assert is_allowed_host(host, ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"]) is False


async def test_Registry에_CTR_Adapter가_등록된다():
    from app.adapters.registry import get_registry, reset_registry

    reset_registry()
    registry = get_registry()
    assert "nanometrics.centaur.ctr" in registry
    manifest = registry.get("nanometrics.centaur.ctr").manifest
    assert manifest.manufacturer == "Nanometrics"
    assert manifest.selectable is True
    assert "password" in manifest.secret_fields
    reset_registry()
