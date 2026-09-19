"""데이터 연속성 검사. SOH 와 독립이며 값 없음을 0 으로 채우지 않는다."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport

from app.adapters.contract import DeviceContext
from app.adapters.data_availability.checker import DataAvailabilityChecker, merge_availability
from app.adapters.data_availability.mapper import map_channels
from app.adapters.data_availability.parser import parse_availability
from app.domain.enums import SupportState
from app.domain.models import CapabilityReport, PollResult
from app.metrics.catalog import validate_sample

NOW = datetime(2026, 9, 19, 2, 0, tzinfo=timezone.utc)


def context() -> DeviceContext:
    return DeviceContext(
        device_id="d1",
        station_code="A01",
        connection={"hostname": "ctr-a01"},
        connect_timeout_ms=2000,
        request_timeout_ms=2000,
    )


class Test파서:
    def test_Centaur_bands(self):
        channels = parse_availability(
            {
                "bands": [
                    {
                        "channel": "HHZ",
                        "ranges": [{"start": "2026-09-19T00:00:00Z", "end": "2026-09-19T01:00:00Z"}],
                    }
                ]
            }
        )
        assert channels[0].channel == "HHZ"
        assert channels[0].ranges[0].end.hour == 1

    def test_FDSN_datasources(self):
        channels = parse_availability(
            {
                "datasources": [
                    {"chan": "HHN", "timespans": [["2026-09-19T00:00:00Z", "2026-09-19T00:10:00Z"]]}
                ]
            }
        )
        assert channels[0].channel == "HHN"

    def test_빈_응답은_해석_실패다(self):
        with pytest.raises(Exception, match="하나도"):
            parse_availability({"bands": []})

    def test_구간이_빈_채널은_유지한다(self):
        """파형이 멈춘 채널을 응답에서 빼 버리면 정지를 0 으로 숨기게 된다."""
        channels = parse_availability({"bands": [{"channel": "HHZ", "ranges": []}]})
        assert channels[0].channel == "HHZ"
        assert channels[0].ranges == ()


class Test매핑:
    def test_경과와_공백을_계산한다(self):
        from app.adapters.data_availability.parser import ChannelAvailability, TimeRange

        gap_start = NOW - timedelta(hours=4)
        gap_end = NOW - timedelta(hours=3)
        latest = NOW - timedelta(seconds=30)
        channels = (
            ChannelAvailability(
                channel="HHZ",
                ranges=(
                    TimeRange(start=NOW - timedelta(hours=6), end=gap_start),
                    TimeRange(start=gap_end, end=latest),
                ),
            ),
        )
        samples = { (s.metric_key, s.dimensions["channel"]): s for s in map_channels(
            channels, now=NOW, lookback_seconds=6 * 3600, active_age_seconds=120
        )}
        assert samples[("acquisition.latest_sample_age_seconds", "HHZ")].value_float == pytest.approx(30.0)
        assert samples[("acquisition.gap_duration_seconds", "HHZ")].value_float == pytest.approx(3600.0)
        assert samples[("acquisition.channel_active", "HHZ")].value_bool is True

    def test_구간이_없으면_정지로_본다(self):
        from app.adapters.data_availability.parser import ChannelAvailability

        samples = map_channels(
            (ChannelAvailability(channel="HHZ", ranges=()),),
            now=NOW,
            lookback_seconds=100,
            active_age_seconds=120,
        )
        by_key = {s.metric_key: s for s in samples}
        assert by_key["acquisition.channel_active"].value_bool is False
        assert by_key["acquisition.latest_sample_age_seconds"].value_float == pytest.approx(100)


class Test검사기:
    async def test_URI가_없으면_UNSUPPORTED이고_값을_만들지_않는다(self):
        samples, report = await DataAvailabilityChecker().collect(context(), data_source_uri=None)
        assert samples == ()
        assert report.state_of("acquisition.data_check") is SupportState.UNSUPPORTED

    async def test_가상서버_availability를_표준_Metric으로_옮긴다(self):
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
        from mock.centaur_mock.devices import DeviceRegistry, VirtualDevice
        from mock.centaur_mock.server import create_app

        device = VirtualDevice(
            instrument_id="centaur-6__0242",
            station_code="A01",
            model="CTR4-6S",
            firmware_version="3.2.8",
            serial_number="0242",
        )
        transport = ASGITransport(app=create_app(DeviceRegistry([device])))
        checker = DataAvailabilityChecker(httpx_transport=transport)
        samples, report = await checker.collect(
            context(),
            data_source_uri="http://ctr-a01/api/v1/bands/availability.json?instrumentId=centaur-6__0242",
            now=NOW,
        )
        assert report.state_of("acquisition.data_check") is SupportState.SUPPORTED_ENABLED
        assert samples
        for sample in samples:
            validate_sample(sample)
        ages = [s for s in samples if s.metric_key == "acquisition.latest_sample_age_seconds"]
        assert ages
        assert all(s.dimensions.get("channel", "").startswith("HH") for s in ages)

    async def test_낡은_파형은_경과가_크다(self):
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
        from mock.centaur_mock.devices import DeviceRegistry, VirtualDevice
        from mock.centaur_mock.scenarios import PayloadScenario
        from mock.centaur_mock.server import create_app

        device = VirtualDevice(
            instrument_id="centaur-6__0242",
            station_code="A01",
            model="CTR4-6S",
            firmware_version="3.2.8",
            serial_number="0242",
            payload_scenario=PayloadScenario.WAVEFORM_STALE,
        )
        transport = ASGITransport(app=create_app(DeviceRegistry([device])))
        samples, _ = await DataAvailabilityChecker(httpx_transport=transport).collect(
            context(),
            data_source_uri="http://ctr-a01/api/v1/bands/availability.json?instrumentId=centaur-6__0242",
            poll_interval_minutes=5,
        )
        ages = [s.value_float for s in samples if s.metric_key == "acquisition.latest_sample_age_seconds"]
        assert ages and min(ages) >= 30 * 60
        assert any(
            s.metric_key == "acquisition.channel_active" and s.value_bool is False for s in samples
        )

    async def test_멈춘_파형은_활성이_아니다(self):
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
        from mock.centaur_mock.devices import DeviceRegistry, VirtualDevice
        from mock.centaur_mock.scenarios import PayloadScenario
        from mock.centaur_mock.server import create_app

        device = VirtualDevice(
            instrument_id="centaur-6__0242",
            station_code="A01",
            model="CTR4-6S",
            firmware_version="3.2.8",
            serial_number="0242",
            payload_scenario=PayloadScenario.WAVEFORM_STOPPED,
        )
        transport = ASGITransport(app=create_app(DeviceRegistry([device])))
        samples, report = await DataAvailabilityChecker(httpx_transport=transport).collect(
            context(),
            data_source_uri="http://ctr-a01/api/v1/bands/availability.json?instrumentId=centaur-6__0242",
        )
        assert report.state_of("acquisition.data_check") is SupportState.SUPPORTED_ENABLED
        assert samples
        assert all(
            s.value_bool is False
            for s in samples
            if s.metric_key == "acquisition.channel_active"
        )

    async def test_지원하지_않는_스킴은_ERROR다(self):
        samples, report = await DataAvailabilityChecker().collect(
            context(), data_source_uri="ftp://example/data"
        )
        assert samples == ()
        assert report.state_of("acquisition.data_check") is SupportState.ERROR

    async def test_SeedLink는_SOH를_실패로_뒤집지_않는다(self):
        soh = PollResult(
            poll_id="p1",
            device_id="d1",
            adapter_key="nanometrics.centaur.ctr",
            adapter_version="1.0",
            success=True,
        )
        samples, report = await DataAvailabilityChecker().collect(
            context(), data_source_uri="seedlink://127.0.0.1:9"
        )
        merged = merge_availability(soh, samples, report)
        assert merged.success is True
        assert merged.capabilities.state_of("acquisition.data_check") is SupportState.ERROR


async def test_poll_device가_SOH와_파형검사를_함께_붙인다():
    import sys
    import uuid
    from pathlib import Path

    from httpx import ASGITransport

    from app.adapters.centaur_ctr.adapter import MANIFEST_PATH, CentaurCtrAdapter
    from app.adapters.registry import AdapterRegistry
    from app.auth.credentials import CredentialResolver
    from app.collector.retry import RetryPolicy
    from app.collector.runner import poll_device
    from app.db.models import CollectionMode
    from app.repository.influx.points import DeviceTags
    from app.repository.postgres.collector_repo import DueDevice

    sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
    from mock.centaur_mock.devices import DeviceRegistry, VirtualDevice
    from mock.centaur_mock.server import create_app

    instrument = "centaur-6__0242"
    app = create_app(
        DeviceRegistry(
            [
                VirtualDevice(
                    instrument_id=instrument,
                    station_code="A01",
                    model="CTR4-6S",
                    firmware_version="3.2.8",
                    serial_number="0242",
                )
            ]
        )
    )
    registry = AdapterRegistry()
    registry.register(CentaurCtrAdapter(transport=ASGITransport(app=app)), manifest_path=MANIFEST_PATH)
    device_id = uuid.uuid4()
    station_id = uuid.uuid4()
    due = DueDevice(
        device_id=device_id,
        station_id=station_id,
        station_code="A01",
        adapter_key="nanometrics.centaur.ctr",
        collection_mode=CollectionMode.DIRECT,
        connection={"hostname": "ctr-a01", "instrumentId": instrument},
        credential_reference=None,
        connect_timeout_ms=2000,
        request_timeout_ms=2000,
        poll_interval_minutes=5,
        retry_count=0,
        retry_delay_seconds=0,
        consecutive_failures=0,
        last_observed_at=None,
        data_source_uri=f"http://ctr-a01/api/v1/bands/availability.json?instrumentId={instrument}",
        tags=DeviceTags(
            device_id=str(device_id),
            station_id=str(station_id),
            station_code="A01",
            collection_mode="DIRECT",
        ),
    )
    outcome = await poll_device(due, registry, CredentialResolver(), RetryPolicy(max_attempts=1))
    assert outcome.result.success is True
    assert any(s.metric_key == "power.input_voltage_v" for s in outcome.result.samples)
    assert any(s.metric_key == "acquisition.latest_sample_age_seconds" for s in outcome.result.samples)
    assert outcome.result.capabilities.state_of("acquisition.data_check") is SupportState.SUPPORTED_ENABLED


async def test_URI없으면_poll_device가_UNKNOWN을_UNSUPPORTED로_바꾼다():
    import sys
    import uuid
    from pathlib import Path

    from httpx import ASGITransport

    from app.adapters.centaur_ctr.adapter import MANIFEST_PATH, CentaurCtrAdapter
    from app.adapters.registry import AdapterRegistry
    from app.auth.credentials import CredentialResolver
    from app.collector.retry import RetryPolicy
    from app.collector.runner import poll_device
    from app.db.models import CollectionMode
    from app.repository.influx.points import DeviceTags
    from app.repository.postgres.collector_repo import DueDevice

    sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
    from mock.centaur_mock.devices import DeviceRegistry, VirtualDevice
    from mock.centaur_mock.server import create_app

    instrument = "centaur-6__0242"
    app = create_app(
        DeviceRegistry(
            [
                VirtualDevice(
                    instrument_id=instrument,
                    station_code="A01",
                    model="CTR4-6S",
                    firmware_version="3.2.8",
                    serial_number="0242",
                )
            ]
        )
    )
    registry = AdapterRegistry()
    registry.register(CentaurCtrAdapter(transport=ASGITransport(app=app)), manifest_path=MANIFEST_PATH)
    device_id = uuid.uuid4()
    station_id = uuid.uuid4()
    due = DueDevice(
        device_id=device_id,
        station_id=station_id,
        station_code="A01",
        adapter_key="nanometrics.centaur.ctr",
        collection_mode=CollectionMode.DIRECT,
        connection={"hostname": "ctr-a01", "instrumentId": instrument},
        credential_reference=None,
        connect_timeout_ms=2000,
        request_timeout_ms=2000,
        poll_interval_minutes=5,
        retry_count=0,
        retry_delay_seconds=0,
        consecutive_failures=0,
        last_observed_at=None,
        tags=DeviceTags(
            device_id=str(device_id),
            station_id=str(station_id),
            station_code="A01",
            collection_mode="DIRECT",
        ),
    )
    outcome = await poll_device(due, registry, CredentialResolver(), RetryPolicy(max_attempts=1))
    assert outcome.result.success is True
    assert not any(s.metric_key.startswith("acquisition.") for s in outcome.result.samples)
    assert outcome.result.capabilities.state_of("acquisition.data_check") is SupportState.UNSUPPORTED
