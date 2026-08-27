"""수집기 통합 시험.

가상 Centaur CTR 서버를 붙여 스케줄러 전 과정을 지난다. 확인하려는 것은 다음이다.

  * 한 장비의 장애가 다른 장비 수집을 막지 않는다
  * 같은 장비를 두 인스턴스가 동시에 수집하지 않는다
  * 실패도 이력에 남는다
  * 연속 실패가 쌓여야 상태가 내려간다
  * 늦게 도착한 과거 데이터가 현재 상태를 되돌리지 않는다
  * InfluxDB 가 멈춰도 수집은 계속되고 데이터를 잃지 않는다
"""
from __future__ import annotations

import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from httpx import ASGITransport
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.adapters.centaur_ctr.adapter import MANIFEST_PATH, CentaurCtrAdapter
from app.adapters.registry import AdapterRegistry
from app.auth.credentials import CredentialResolver
from app.collector.scheduler import CollectorScheduler
from app.config.settings import Settings
from app.db.base import Base
from app.db.models import (
    CollectionMode,
    CollectionProfile,
    Device,
    DeviceCapability,
    DeviceEndpoint,
    DeviceRuntimeState,
    LifecycleStatus,
    PollRun,
    Station,
)
from app.domain.enums import PollErrorCode, Severity, SupportState
from app.domain.models import PollResult, utcnow
from app.repository.influx.sink import BufferedMetricSink, InMemoryMetricSink
from app.repository.postgres import collector_repo as repo

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from mock.centaur_mock.devices import DeviceRegistry, VirtualDevice  # noqa: E402
from mock.centaur_mock.scenarios import PayloadScenario, TransportScenario  # noqa: E402
from mock.centaur_mock.server import create_app  # noqa: E402


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path/'collector.db'}", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    yield factory
    engine.dispose()


def settings(**changes) -> Settings:
    defaults = dict(
        app_env="test",
        max_concurrent_polls=5,
        poll_jitter_percent=10,
        failure_warning_threshold=2,
        failure_critical_threshold=3,
        default_poll_interval_minutes=5,
    )
    defaults.update(changes)
    return Settings(**defaults)


def register_station(session, *, station_code: str, instrument_id: str, interval: int = 5,
                     retry_count: int = 0) -> Device:
    profile = session.scalar(select(CollectionProfile).where(CollectionProfile.name == "시험"))
    if profile is None:
        profile = CollectionProfile(
            name="시험",
            poll_interval_minutes=interval,
            retry_count=retry_count,
            retry_delay_seconds=0,
        )
        session.add(profile)
        session.flush()

    station = Station(
        station_code=station_code,
        network_code="KS",
        name=f"{station_code} 관측소",
        status=LifecycleStatus.ACTIVE,
    )
    session.add(station)
    session.flush()

    device = Device(
        station_id=station.id,
        adapter_key="nanometrics.centaur.ctr",
        adapter_version="1.0",
        instrument_id=instrument_id,
        collection_mode=CollectionMode.DIRECT,
        collection_profile_id=profile.id,
        enabled=True,
        status=LifecycleStatus.ACTIVE,
    )
    session.add(device)
    session.flush()

    session.add(
        DeviceEndpoint(
            device_id=device.id,
            scheme="http",
            hostname=f"ctr-{station_code.lower()}",
            base_path="",
            connect_timeout_ms=2000,
            request_timeout_ms=2000,
        )
    )
    session.commit()
    return device


def build_scheduler(session_factory, devices: list[VirtualDevice], *, sink=None, **setting_changes):
    app = create_app(DeviceRegistry(devices))
    registry = AdapterRegistry()
    registry.register(
        CentaurCtrAdapter(transport=ASGITransport(app=app)), manifest_path=MANIFEST_PATH
    )
    scheduler = CollectorScheduler(
        session_factory,
        sink or InMemoryMetricSink(),
        settings=settings(**setting_changes),
        registry=registry,
        resolver=CredentialResolver(),
        owner="test-owner",
        sleep=_no_sleep,
    )
    return scheduler


async def _no_sleep(_seconds: float) -> None:
    """재시도 대기를 건너뛴다. 시험이 실제로 기다릴 이유가 없다."""
    return None


def virtual(instrument_id: str, station_code: str, **changes) -> VirtualDevice:
    return VirtualDevice(
        instrument_id=instrument_id,
        station_code=station_code,
        model="CTR4-6S",
        firmware_version="3.2.8",
        serial_number=instrument_id.split("_")[-1],
        **changes,
    )


class Test기본수집:
    async def test_한_대를_수집해_시계열과_이력에_남긴다(self, session_factory):
        with session_factory() as session:
            device = register_station(session, station_code="A01", instrument_id="centaur-6__0242")

        sink = InMemoryMetricSink()
        scheduler = build_scheduler(session_factory, [virtual("centaur-6__0242", "A01")], sink=sink)
        report = await scheduler.tick()

        assert report.due == 1
        assert report.succeeded == 1
        assert report.points_written > 0

        assert "recorder_poll" in sink.measurements()
        assert "recorder_power" in sink.measurements()
        assert sink.fields_of("recorder_poll")[0]["reachable"] is True

        with session_factory() as session:
            run = session.scalar(select(PollRun))
            assert run.success is True
            assert run.sample_count > 20
            state = session.get(DeviceRuntimeState, device.id)
            assert state.overall_severity is Severity.OK
            assert state.consecutive_failures == 0
            assert state.poll_lease_owner is None  # 끝나면 Lease 를 놓는다

    async def test_기능_지원_상태를_저장한다(self, session_factory):
        """InfluxDB 에 값이 비어 있을 때 그 이유를 여기서 설명한다."""
        with session_factory() as session:
            device = register_station(session, station_code="A02", instrument_id="centaur-3__0117")

        scheduler = build_scheduler(
            session_factory,
            [virtual("centaur-3__0117", "A02", channel_count=3,
                     payload_scenario=PayloadScenario.THREE_CHANNEL)],
        )
        await scheduler.tick()

        with session_factory() as session:
            rows = {
                (row.capability_key, row.dimension_value): row.support_state
                for row in session.scalars(
                    select(DeviceCapability).where(DeviceCapability.device_id == device.id)
                )
            }
        assert rows[("sensor.status", "A")] is SupportState.SUPPORTED_ENABLED
        assert rows[("sensor.status", "B")] is SupportState.UNSUPPORTED

    async def test_다음_수집_시각에_Jitter가_들어간다(self, session_factory):
        with session_factory() as session:
            device = register_station(
                session, station_code="A03", instrument_id="centaur-6__0242", interval=5
            )

        scheduler = build_scheduler(session_factory, [virtual("centaur-6__0242", "A03")])
        before = utcnow()
        await scheduler.tick()

        with session_factory() as session:
            next_at = repo.as_utc(session.get(Device, device.id).next_poll_at)

        delta = (next_at - before).total_seconds()
        # 5분 ± 10%
        assert 265 <= delta <= 335

    async def test_수집_시각이_안_된_장비는_건너뛴다(self, session_factory):
        with session_factory() as session:
            device = register_station(session, station_code="A04", instrument_id="centaur-6__0242")
            session.get(Device, device.id).next_poll_at = utcnow() + timedelta(minutes=10)
            session.commit()

        scheduler = build_scheduler(session_factory, [virtual("centaur-6__0242", "A04")])
        report = await scheduler.tick()
        assert report.due == 0
        assert report.succeeded == 0


class Test장애격리:
    async def test_한_장비의_장애가_다른_장비를_막지_않는다(self, session_factory):
        with session_factory() as session:
            register_station(session, station_code="B01", instrument_id="centaur-6__0001")
            register_station(session, station_code="B02", instrument_id="centaur-6__0002")
            register_station(session, station_code="B03", instrument_id="centaur-6__0003")

        devices = [
            virtual("centaur-6__0001", "B01"),
            virtual("centaur-6__0002", "B02", transport_scenario=TransportScenario.HTTP_500),
            virtual("centaur-6__0003", "B03"),
        ]
        scheduler = build_scheduler(session_factory, devices)
        report = await scheduler.tick()

        assert report.due == 3
        assert report.succeeded == 2
        assert report.failed == 1
        assert report.errors == {"HTTP_ERROR": 1}

    async def test_실패도_이력에_남는다(self, session_factory):
        with session_factory() as session:
            device = register_station(session, station_code="B04", instrument_id="centaur-6__0004")

        scheduler = build_scheduler(
            session_factory,
            [virtual("centaur-6__0004", "B04", transport_scenario=TransportScenario.HTTP_500)],
        )
        await scheduler.tick()

        with session_factory() as session:
            run = session.scalar(select(PollRun))
            assert run.success is False
            assert run.error_code is PollErrorCode.HTTP_ERROR
            assert run.http_status == 500

    async def test_연속_실패가_쌓여야_상태가_내려간다(self, session_factory):
        """1회 실패로 장애를 만들면 순간적인 회선 흔들림이 알림이 된다."""
        with session_factory() as session:
            device = register_station(session, station_code="B05", instrument_id="centaur-6__0005")

        scheduler = build_scheduler(
            session_factory,
            [virtual("centaur-6__0005", "B05", transport_scenario=TransportScenario.HTTP_500)],
        )

        severities = []
        for _ in range(3):
            with session_factory() as session:
                session.get(Device, device.id).next_poll_at = utcnow() - timedelta(seconds=1)
                session.commit()
            await scheduler.tick()
            with session_factory() as session:
                state = session.get(DeviceRuntimeState, device.id)
                severities.append((state.consecutive_failures, state.overall_severity))

        assert severities[0][1] is Severity.UNKNOWN
        assert severities[1] == (2, Severity.WARNING)
        assert severities[2] == (3, Severity.CRITICAL)

    async def test_복구되면_실패_횟수가_초기화된다(self, session_factory):
        with session_factory() as session:
            device = register_station(session, station_code="B06", instrument_id="centaur-6__0006")

        failing = virtual("centaur-6__0006", "B06", transport_scenario=TransportScenario.HTTP_500)
        scheduler = build_scheduler(session_factory, [failing])
        await scheduler.tick()

        healthy = virtual("centaur-6__0006", "B06")
        recovered = build_scheduler(session_factory, [healthy])
        with session_factory() as session:
            session.get(Device, device.id).next_poll_at = utcnow() - timedelta(seconds=1)
            session.commit()
        await recovered.tick()

        with session_factory() as session:
            state = session.get(DeviceRuntimeState, device.id)
        assert state.consecutive_failures == 0
        assert state.overall_severity is Severity.OK

    async def test_등록되지_않은_Adapter를_요구하는_장비(self, session_factory):
        with session_factory() as session:
            device = register_station(session, station_code="B07", instrument_id="centaur-6__0007")
            session.get(Device, device.id).adapter_key = "vendor.unknown.recorder"
            session.commit()

        scheduler = build_scheduler(session_factory, [virtual("centaur-6__0007", "B07")])
        report = await scheduler.tick()

        assert report.failed == 1
        with session_factory() as session:
            run = session.scalar(select(PollRun))
        assert run.error_code is PollErrorCode.ADAPTER_ERROR


class Test중복수집방지:
    async def test_다른_인스턴스가_잡은_장비는_건너뛴다(self, session_factory):
        with session_factory() as session:
            device = register_station(session, station_code="C01", instrument_id="centaur-6__0011")
            # 다른 인스턴스가 방금 Lease 를 잡은 상황을 만든다.
            assert repo.acquire_lease(session, device.id, "other-instance", ttl_seconds=300)
            session.commit()

        scheduler = build_scheduler(session_factory, [virtual("centaur-6__0011", "C01")])
        report = await scheduler.tick()

        assert report.due == 1
        assert report.leased == 0
        assert report.skipped_leased == 1
        assert report.succeeded == 0

    async def test_만료된_Lease는_다시_잡을_수_있다(self, session_factory):
        """프로세스가 급사해도 만료 시각이 지나면 자동으로 풀린다."""
        with session_factory() as session:
            device = register_station(session, station_code="C02", instrument_id="centaur-6__0012")
            session.add(
                DeviceRuntimeState(
                    device_id=device.id,
                    poll_lease_owner="dead-instance",
                    poll_lease_until=utcnow() - timedelta(minutes=10),
                )
            )
            session.commit()

        scheduler = build_scheduler(session_factory, [virtual("centaur-6__0012", "C02")])
        report = await scheduler.tick()
        assert report.succeeded == 1

    async def test_Lease는_한_인스턴스만_잡는다(self, session_factory):
        with session_factory() as session:
            device = register_station(session, station_code="C03", instrument_id="centaur-6__0013")

        with session_factory() as session:
            first = repo.acquire_lease(session, device.id, "instance-1")
            session.commit()
        with session_factory() as session:
            second = repo.acquire_lease(session, device.id, "instance-2")
            session.commit()

        assert first is True
        assert second is False


class Test적재실패:
    async def test_Influx가_멈춰도_수집은_계속된다(self, session_factory):
        with session_factory() as session:
            register_station(session, station_code="D01", instrument_id="centaur-6__0021")

        failing_sink = BufferedMetricSink(InMemoryMetricSink(fail=True))
        scheduler = build_scheduler(
            session_factory, [virtual("centaur-6__0021", "D01")], sink=failing_sink
        )
        report = await scheduler.tick()

        assert report.succeeded == 1  # 장비는 정상이다
        assert report.sink_failed is True
        assert failing_sink.buffered_points > 0

        with session_factory() as session:
            assert session.scalar(select(PollRun)).success is True

    async def test_복구되면_버퍼가_함께_전송된다(self, session_factory):
        inner = InMemoryMetricSink(fail=True)
        sink = BufferedMetricSink(inner)

        with session_factory() as session:
            device = register_station(session, station_code="D02", instrument_id="centaur-6__0022")

        scheduler = build_scheduler(
            session_factory, [virtual("centaur-6__0022", "D02")], sink=sink
        )
        await scheduler.tick()
        buffered = sink.buffered_points
        assert buffered > 0

        inner.fail = False
        with session_factory() as session:
            session.get(Device, device.id).next_poll_at = utcnow() - timedelta(seconds=1)
            session.commit()
        await scheduler.tick()

        assert sink.buffered_points == 0
        assert len(inner.points) > buffered  # 이전 분량까지 함께 올라갔다

    def test_버퍼_한도를_넘으면_오래된_것부터_버린다(self):
        """InfluxDB 가 장시간 죽어 있을 때 메모리로 죽으면 데이터를 더 크게 잃는다."""
        from app.repository.influx.points import PointSpec

        inner = InMemoryMetricSink(fail=True)
        sink = BufferedMetricSink(inner, max_buffered_points=10)
        for index in range(6):
            sink.write([PointSpec(measurement="m", tags={"i": str(index)}, fields={"v": index})] * 3)

        assert sink.buffered_points == 10
        assert sink.dropped_points == 8


class Test지연도달데이터:
    def test_과거_데이터가_현재_상태를_되돌리지_않는다(self, session_factory):
        """Edge 가 하루 뒤 올린 데이터로 '지금 정상' 이라고 표시하면 안 된다."""
        with session_factory() as session:
            device = register_station(session, station_code="E01", instrument_id="centaur-6__0031")
            due = repo.due_devices(session)[0]

            recent = PollResult(
                poll_id=str(uuid.uuid4()),
                device_id=str(device.id),
                adapter_key="nanometrics.centaur.ctr",
                adapter_version="1.0",
                observed_at=utcnow(),
                success=True,
            )
            repo.update_runtime_state(
                session, due, recent, warning_threshold=2, critical_threshold=3
            )
            session.commit()
            newest_observed = repo.as_utc(session.get(DeviceRuntimeState, device.id).last_observed_at)

            stale = PollResult(
                poll_id=str(uuid.uuid4()),
                device_id=str(device.id),
                adapter_key="nanometrics.centaur.ctr",
                adapter_version="1.0",
                observed_at=utcnow() - timedelta(days=1),
                success=True,
            )
            repo.update_runtime_state(
                session, due, stale, warning_threshold=2, critical_threshold=3
            )
            session.commit()

            state = session.get(DeviceRuntimeState, device.id)
            assert repo.as_utc(state.last_observed_at) == newest_observed


class Test수집중단감지:
    def test_마지막_성공이_오래된_장비를_찾는다(self, session_factory):
        """수집기가 죽어 있는 동안에는 실패 기록조차 남지 않는다."""
        with session_factory() as session:
            device = register_station(session, station_code="F01", instrument_id="centaur-6__0041")
            session.add(
                DeviceRuntimeState(
                    device_id=device.id,
                    last_success_at=utcnow() - timedelta(hours=2),
                )
            )
            session.commit()

            stale = repo.stale_devices(session, threshold_seconds=1800)
            assert stale == [device.id]

            fresh = repo.stale_devices(session, threshold_seconds=86400)
            assert fresh == []


class Test동시성:
    async def test_동시_수집_수를_제한한다(self, session_factory):
        with session_factory() as session:
            for index in range(6):
                register_station(
                    session,
                    station_code=f"G{index:02d}",
                    instrument_id=f"centaur-6__01{index:02d}",
                )

        devices = [virtual(f"centaur-6__01{index:02d}", f"G{index:02d}") for index in range(6)]
        scheduler = build_scheduler(session_factory, devices, max_concurrent_polls=2)

        original = scheduler._semaphore
        peak = 0
        active = 0

        class Counting:
            async def __aenter__(self):
                nonlocal peak, active
                await original.acquire()
                active += 1
                peak = max(peak, active)
                return self

            async def __aexit__(self, *args):
                nonlocal active
                active -= 1
                original.release()

        scheduler._semaphore = Counting()  # type: ignore[assignment]
        report = await scheduler.tick()

        assert report.succeeded == 6
        assert peak <= 2

    async def test_진행_중인_장비는_다시_집지_않는다(self, session_factory):
        with session_factory() as session:
            register_station(session, station_code="H01", instrument_id="centaur-6__0051")

        scheduler = build_scheduler(session_factory, [virtual("centaur-6__0051", "H01")])
        scheduler._in_flight.add(str(repo.due_devices(session_factory()) [0].device_id))

        report = await scheduler.tick()
        assert report.skipped_leased == 1
        assert report.leased == 0


class Test재시도:
    async def test_회선_오류는_다시_시도한다(self, session_factory):
        with session_factory() as session:
            register_station(
                session, station_code="I01", instrument_id="centaur-6__0061", retry_count=1
            )

        # FLAPPING 은 성공/실패를 번갈아 낸다. 첫 시도 실패 → 재시도 성공이 되어야 한다.
        scheduler = build_scheduler(
            session_factory,
            [virtual("centaur-6__0061", "I01", transport_scenario=TransportScenario.HTTP_500)],
            retry_count=1,
        )
        report = await scheduler.tick()
        assert report.failed == 1  # 계속 500 이면 재시도해도 실패다

        with session_factory() as session:
            runs = session.scalars(select(PollRun)).all()
        assert len(runs) == 1  # 재시도는 한 Poll 로 기록한다

    async def test_인증_오류는_다시_시도하지_않는다(self, session_factory):
        """반복하면 장비 계정이 잠길 수 있다."""
        from app.collector.retry import RetryPolicy

        policy = RetryPolicy(max_attempts=3)
        assert policy.should_retry(PollErrorCode.AUTH_ERROR, 1) is False
        assert policy.should_retry(PollErrorCode.IDENTITY_MISMATCH, 1) is False
        assert policy.should_retry(PollErrorCode.INVALID_PAYLOAD, 1) is False
        assert policy.should_retry(PollErrorCode.REQUEST_TIMEOUT, 1) is True

    def test_Backoff는_상한을_넘지_않는다(self):
        from app.collector.retry import RetryPolicy

        policy = RetryPolicy(delay_seconds=10, backoff_multiplier=3, max_delay_seconds=45)
        assert policy.delay_for(1) == 10
        assert policy.delay_for(2) == 30
        assert policy.delay_for(3) == 45


class Test수집대상선택:
    def test_EDGE_장비는_중앙_수집_대상이_아니다(self, session_factory):
        from app.db.models import EdgeCollector

        with session_factory() as session:
            device = register_station(session, station_code="J01", instrument_id="centaur-6__0071")
            edge = EdgeCollector(edge_code="edge-j", name="지역 J Edge")
            session.add(edge)
            session.flush()

            target = session.get(Device, device.id)
            target.collection_mode = CollectionMode.EDGE
            target.edge_id = edge.id
            session.commit()

            assert repo.due_devices(session) == []

    def test_EDGE_모드에_Edge_지정이_없으면_DB가_거부한다(self, session_factory):
        """수집 주체가 없는 장비를 만들 수 없게 스키마 수준에서 막는다."""
        from sqlalchemy.exc import IntegrityError

        with session_factory() as session:
            device = register_station(session, station_code="J06", instrument_id="centaur-6__0076")
            session.get(Device, device.id).collection_mode = CollectionMode.EDGE
            with pytest.raises(IntegrityError):
                session.commit()

    def test_비활성_장비는_제외한다(self, session_factory):
        with session_factory() as session:
            device = register_station(session, station_code="J02", instrument_id="centaur-6__0072")
            session.get(Device, device.id).enabled = False
            session.commit()

            assert repo.due_devices(session) == []

    def test_폐기된_장비는_제외한다(self, session_factory):
        with session_factory() as session:
            device = register_station(session, station_code="J03", instrument_id="centaur-6__0073")
            session.get(Device, device.id).status = LifecycleStatus.RETIRED
            session.commit()

            assert repo.due_devices(session) == []

    def test_한_번도_수집하지_않은_장비는_대상이다(self, session_factory):
        with session_factory() as session:
            register_station(session, station_code="J04", instrument_id="centaur-6__0074")
            due = repo.due_devices(session)
            assert len(due) == 1
            assert due[0].last_observed_at is None

    def test_수동_수집_요청은_다음_Tick에_반영된다(self, session_factory):
        with session_factory() as session:
            device = register_station(session, station_code="J05", instrument_id="centaur-6__0075")
            session.get(Device, device.id).next_poll_at = utcnow() + timedelta(hours=1)
            session.commit()
            assert repo.due_devices(session) == []

            repo.request_immediate_poll(session, device.id)
            session.commit()
            assert len(repo.due_devices(session)) == 1
