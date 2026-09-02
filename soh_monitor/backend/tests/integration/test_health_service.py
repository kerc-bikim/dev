"""판정 엔진 통합 시험.

가상 기록계로 실제 수집을 돌리고 장애가 열리고 복구되는지 확인한다. 계획서 M4 Exit
조건인 다음 셋을 겨냥한다.

  * 동일한 장애가 중복 생성되지 않는다
  * 복구가 자동 인식된다
  * 미지원·확인 불가·정상이 구분된다
"""
from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

import pytest
from httpx import ASGITransport
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.adapters.centaur_ctr.adapter import MANIFEST_PATH, CentaurCtrAdapter
from app.adapters.registry import AdapterRegistry
from app.collector.scheduler import CollectorScheduler
from app.config.settings import Settings
from app.db.base import Base
from app.db.models import (
    CollectionMode,
    CollectionProfile,
    Device,
    DeviceEndpoint,
    DeviceMetricOverride,
    HealthState,
    Incident,
    IncidentEvent,
    IncidentStatus,
    LifecycleStatus,
    MaintenanceWindow,
    MetricDefinitionRow,
    MetricProfile,
    ProfileMetric,
    Station,
)
from app.domain.enums import Severity
from app.domain.models import utcnow
from app.health import incidents as incident_ops
from app.health.notifier import CollectingNotifier
from app.health.service import HealthService
from app.repository.influx.sink import InMemoryMetricSink

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from mock.centaur_mock.devices import DeviceRegistry, VirtualDevice  # noqa: E402
from mock.centaur_mock.scenarios import PayloadScenario, TransportScenario  # noqa: E402
from mock.centaur_mock.server import create_app  # noqa: E402

INSTRUMENT = "centaur-6__0242"

# metric_key: (warning, critical, hold_seconds, recovery_seconds)
THRESHOLDS: dict[str, tuple[dict, dict, int, int]] = {
    "storage.used_percent": ({"op": ">=", "value": 80}, {"op": ">=", "value": 90}, 0, 0),
    "storage.recording_status": ({"status": "WARNING"}, {"status": "CRITICAL"}, 0, 0),
    "storage.sd_status": ({"status": "WARNING"}, {"status": "CRITICAL"}, 0, 0),
    "timing.status": ({"status": "WARNING"}, {"status": "CRITICAL"}, 0, 0),
    "timing.phase_lock": ({"status": "WARNING"}, {"status": "CRITICAL"}, 0, 0),
    "device.overall_status": ({"status": "WARNING"}, {"status": "CRITICAL"}, 0, 0),
    "sensor.status": ({"status": "WARNING"}, {"status": "CRITICAL"}, 0, 0),
    "power.input_voltage_v": ({"op": "<=", "value": 11.8}, {"op": "<=", "value": 11.0}, 0, 0),
}


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path/'health.db'}", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)

    # 프로파일이 Metric 정의를 외래키로 참조하므로 카탈로그를 먼저 넣는다.
    from app.db.seed import seed_metric_definitions

    with factory() as session:
        seed_metric_definitions(session)
        session.commit()

    yield factory
    engine.dispose()


def register(
    session, *, station_code: str, instrument_id: str = INSTRUMENT, thresholds: dict | None = None
) -> Device:
    metric_profile = session.scalar(select(MetricProfile).where(MetricProfile.name == "시험"))
    if metric_profile is None:
        metric_profile = MetricProfile(name="시험", is_default=True)
        session.add(metric_profile)
        session.flush()
        for metric_key, (warning, critical, hold, recovery) in (thresholds or THRESHOLDS).items():
            if session.get(MetricDefinitionRow, metric_key) is None:
                continue
            session.add(
                ProfileMetric(
                    profile_id=metric_profile.id,
                    metric_key=metric_key,
                    enabled=True,
                    alerting_enabled=True,
                    warning_condition=warning,
                    critical_condition=critical,
                    hold_seconds=hold,
                    recovery_seconds=recovery,
                )
            )

    collection_profile = session.scalar(
        select(CollectionProfile).where(CollectionProfile.name == "시험")
    )
    if collection_profile is None:
        collection_profile = CollectionProfile(
            name="시험", poll_interval_minutes=5, retry_count=0, retry_delay_seconds=0
        )
        session.add(collection_profile)
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
        collection_profile_id=collection_profile.id,
        metric_profile_id=metric_profile.id,
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


async def _no_sleep(_seconds: float) -> None:
    return None


def virtual(instrument_id: str = INSTRUMENT, station_code: str = "A01", **changes) -> VirtualDevice:
    return VirtualDevice(
        instrument_id=instrument_id,
        station_code=station_code,
        model="CTR4-6S",
        firmware_version="3.2.8",
        serial_number=instrument_id.split("_")[-1],
        **changes,
    )


def build(session_factory, devices, *, notifier=None, sink=None):
    app = create_app(DeviceRegistry(devices))
    registry = AdapterRegistry()
    registry.register(
        CentaurCtrAdapter(transport=ASGITransport(app=app)), manifest_path=MANIFEST_PATH
    )
    return CollectorScheduler(
        session_factory,
        sink or InMemoryMetricSink(),
        settings=Settings(
            app_env="test",
            max_concurrent_polls=5,
            poll_jitter_percent=0,
            failure_warning_threshold=2,
            failure_critical_threshold=3,
        ),
        registry=registry,
        owner="health-test",
        sleep=_no_sleep,
        health=HealthService(notifier=notifier),
    )


def due_now(session_factory, device_id) -> None:
    with session_factory() as session:
        session.get(Device, device_id).next_poll_at = utcnow() - timedelta(seconds=1)
        session.commit()


def states_of(session_factory, device_id) -> dict[tuple[str, str, str], HealthState]:
    with session_factory() as session:
        return {
            (s.category, s.metric_key or "", s.dimension_value or ""): s
            for s in session.scalars(select(HealthState).where(HealthState.device_id == device_id))
        }


class Test정상판정:
    async def test_정상_장비는_분류별로_정상이다(self, session_factory):
        with session_factory() as session:
            device = register(session, station_code="A01")

        scheduler = build(session_factory, [virtual()])
        await scheduler.tick()

        states = states_of(session_factory, device.id)
        assert states[("connectivity", "", "")].severity is Severity.OK
        assert states[("storage", "", "")].severity is Severity.OK
        assert states[("timing", "", "")].severity is Severity.OK

        with session_factory() as session:
            assert session.scalar(select(func.count()).select_from(Incident)) == 0

    async def test_판정_결과를_시계열로_적재한다(self, session_factory):
        """Grafana 가 severity 만 보고 알림을 만들 수 있어야 한다."""
        with session_factory() as session:
            register(session, station_code="A02")

        sink = InMemoryMetricSink()
        scheduler = build(session_factory, [virtual(station_code="A02")], sink=sink)
        await scheduler.tick()

        health_points = [p for p in sink.points if p.measurement == "recorder_health"]
        assert health_points
        assert "overall" in {p.tags["category"] for p in health_points}
        for point in health_points:
            assert "severity" in point.fields
            assert "is_stale" in point.fields

    async def test_미지원_확인불가_정상을_구분한다(self, session_factory):
        with session_factory() as session:
            device = register(session, station_code="A03", instrument_id="centaur-3__0117")

        scheduler = build(
            session_factory,
            [
                virtual(
                    "centaur-3__0117",
                    "A03",
                    channel_count=3,
                    payload_scenario=PayloadScenario.THREE_CHANNEL,
                )
            ],
        )
        await scheduler.tick()

        states = states_of(session_factory, device.id)
        assert states[("sensor", "sensor.status", "A")].severity is Severity.OK
        sensor_b = states.get(("sensor", "sensor.status", "B"))
        # 3채널 모델의 Sensor B 는 없는 기능이므로 장애로 세지 않는다.
        assert sensor_b is None or sensor_b.severity in {Severity.DISABLED, Severity.UNKNOWN}

        with session_factory() as session:
            incidents = session.scalars(select(Incident)).all()
        assert [i for i in incidents if i.dimension_value == "B"] == []


class Test장애생성과복구:
    async def test_저장소_가득_장애가_열린다(self, session_factory):
        with session_factory() as session:
            register(session, station_code="B01")

        notifier = CollectingNotifier()
        scheduler = build(
            session_factory,
            [virtual(station_code="B01", payload_scenario=PayloadScenario.STORE_FULL)],
            notifier=notifier,
        )
        await scheduler.tick()

        with session_factory() as session:
            incidents = session.scalars(select(Incident)).all()

        keys = {(i.category, i.metric_key, i.severity) for i in incidents}
        assert ("storage", "storage.used_percent", Severity.CRITICAL) in keys
        assert ("storage", "storage.recording_status", Severity.CRITICAL) in keys
        assert notifier.kinds().count("OPENED") == len(incidents)

    async def test_같은_장애를_중복_생성하지_않는다(self, session_factory):
        """같은 원인으로 장애가 계속 새로 생기면 이력이 쓸모없어진다."""
        with session_factory() as session:
            device = register(session, station_code="B02")

        notifier = CollectingNotifier()
        scheduler = build(
            session_factory,
            [virtual(station_code="B02", payload_scenario=PayloadScenario.STORE_FULL)],
            notifier=notifier,
        )

        for _ in range(4):
            due_now(session_factory, device.id)
            await scheduler.tick()

        with session_factory() as session:
            total = session.scalar(select(func.count()).select_from(Incident))
            by_target = session.execute(
                select(Incident.category, Incident.metric_key, func.count()).group_by(
                    Incident.category, Incident.metric_key
                )
            ).all()

        # 4회 수집했지만 대상별 장애는 하나씩만 존재한다.
        assert all(row[2] == 1 for row in by_target)
        # 알림도 처음 한 번만 나간다.
        assert notifier.kinds().count("OPENED") == total
        assert "RESOLVED" not in notifier.kinds()

    async def test_복구를_자동_인식한다(self, session_factory):
        with session_factory() as session:
            device = register(session, station_code="B03")

        notifier = CollectingNotifier()
        broken = build(
            session_factory,
            [virtual(station_code="B03", payload_scenario=PayloadScenario.STORE_FULL)],
            notifier=notifier,
        )
        await broken.tick()

        with session_factory() as session:
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(Incident)
                    .where(Incident.status == IncidentStatus.OPEN)
                )
                > 0
            )

        healthy = build(session_factory, [virtual(station_code="B03")], notifier=notifier)
        due_now(session_factory, device.id)
        await healthy.tick()

        with session_factory() as session:
            still_open = session.scalar(
                select(func.count())
                .select_from(Incident)
                .where(Incident.status != IncidentStatus.RESOLVED)
            )
            resolved = session.scalars(
                select(Incident).where(Incident.status == IncidentStatus.RESOLVED)
            ).all()

        assert still_open == 0
        assert resolved
        assert all(incident.resolved_at is not None for incident in resolved)
        assert "RESOLVED" in notifier.kinds()

    async def test_상태가_나빠지면_승격하고_새로_만들지_않는다(self, session_factory):
        with session_factory() as session:
            device = register(session, station_code="B04")

        notifier = CollectingNotifier()
        scheduler = build(
            session_factory,
            [virtual(station_code="B04", payload_scenario=PayloadScenario.LOW_VOLTAGE)],
            notifier=notifier,
        )
        await scheduler.tick()

        with session_factory() as session:
            incident = session.scalar(
                select(Incident).where(Incident.metric_key == "power.input_voltage_v")
            )
        assert incident is not None
        assert incident.severity is Severity.WARNING

        # 같은 항목을 장애 수준으로 만든다.
        with session_factory() as session:
            session.add(
                DeviceMetricOverride(
                    device_id=device.id,
                    metric_key="power.input_voltage_v",
                    warning_condition={"op": "<=", "value": 13.0},
                    critical_condition={"op": "<=", "value": 12.0},
                )
            )
            session.commit()

        due_now(session_factory, device.id)
        await scheduler.tick()

        with session_factory() as session:
            incidents = session.scalars(
                select(Incident).where(Incident.metric_key == "power.input_voltage_v")
            ).all()
            events = session.scalars(
                select(IncidentEvent).where(IncidentEvent.incident_id == incidents[0].id)
            ).all()

        assert len(incidents) == 1
        assert incidents[0].severity is Severity.CRITICAL
        assert [event.event_type for event in events] == ["OPENED", "ESCALATED"]

        # 해당 항목에 대한 알림은 열림 1회, 승격 1회뿐이다.
        voltage_alerts = [
            notification.kind
            for notification in notifier.sent
            if notification.metric_key == "power.input_voltage_v"
        ]
        assert voltage_alerts == ["OPENED", "ESCALATED"]

    async def test_통신_장애는_연속_실패_후에_열린다(self, session_factory):
        with session_factory() as session:
            device = register(session, station_code="B05")

        scheduler = build(
            session_factory,
            [virtual(station_code="B05", transport_scenario=TransportScenario.HTTP_500)],
            notifier=CollectingNotifier(),
        )

        opened_after: list[int] = []
        for _ in range(3):
            due_now(session_factory, device.id)
            await scheduler.tick()
            with session_factory() as session:
                opened_after.append(
                    session.scalar(
                        select(func.count())
                        .select_from(Incident)
                        .where(Incident.category == "connectivity")
                    )
                )

        # 1회 실패로는 장애를 만들지 않는다.
        assert opened_after == [0, 1, 1]

        with session_factory() as session:
            incident = session.scalar(select(Incident).where(Incident.category == "connectivity"))
        assert incident.severity is Severity.CRITICAL

    async def test_통신이_끊긴_동안에는_값_기반_장애를_만들지_않는다(self, session_factory):
        """응답이 없는데 '전압 정상' 이라고 표시하면 안 되고, 새 장애도 만들면 안 된다."""
        with session_factory() as session:
            device = register(session, station_code="B06")

        scheduler = build(
            session_factory,
            [virtual(station_code="B06", transport_scenario=TransportScenario.HTTP_500)],
            notifier=CollectingNotifier(),
        )
        await scheduler.tick()

        with session_factory() as session:
            incidents = session.scalars(select(Incident)).all()
        assert all(incident.category == "connectivity" for incident in incidents)

        states = states_of(session_factory, device.id)
        assert ("storage", "storage.used_percent", "") not in states

    async def test_통신_복구는_지연_없이_반영된다(self, session_factory):
        """악화는 이미 연속 실패로 걸러진다. 회복까지 미루면 수집기 상태와 판정이 어긋난다."""
        with session_factory() as session:
            device = register(session, station_code="B07")

        broken = build(
            session_factory,
            [virtual(station_code="B07", transport_scenario=TransportScenario.HTTP_500)],
        )
        for _ in range(3):
            due_now(session_factory, device.id)
            await broken.tick()

        healthy = build(session_factory, [virtual(station_code="B07")])
        due_now(session_factory, device.id)
        await healthy.tick()

        states = states_of(session_factory, device.id)
        assert states[("connectivity", "", "")].severity is Severity.OK

        with session_factory() as session:
            open_connectivity = session.scalar(
                select(func.count())
                .select_from(Incident)
                .where(
                    Incident.category == "connectivity",
                    Incident.status != IncidentStatus.RESOLVED,
                )
            )
        assert open_connectivity == 0


class Test지속시간:
    async def test_지속시간을_넘기기_전에는_장애를_만들지_않는다(self, session_factory):
        with session_factory() as session:
            device = register(
                session,
                station_code="C01",
                thresholds={
                    "storage.used_percent": (
                        {"op": ">=", "value": 10},
                        {"op": ">=", "value": 20},
                        600,  # 10분 지속돼야 확정
                        0,
                    )
                },
            )

        scheduler = build(session_factory, [virtual(station_code="C01")])
        await scheduler.tick()

        with session_factory() as session:
            assert session.scalar(select(func.count()).select_from(Incident)) == 0

        state = states_of(session_factory, device.id)[("storage", "storage.used_percent", "")]
        assert state.severity is Severity.UNKNOWN  # 아직 확정 전
        assert state.detail["pending_severity"] == "CRITICAL"


class Test유지보수:
    async def test_유지보수_중에는_장애를_만들지_않는다(self, session_factory):
        with session_factory() as session:
            device = register(session, station_code="D01")
            session.add(
                MaintenanceWindow(
                    scope="device",
                    scope_id=device.id,
                    starts_at=utcnow() - timedelta(hours=1),
                    ends_at=utcnow() + timedelta(hours=1),
                    reason="센서 교체",
                )
            )
            session.commit()

        notifier = CollectingNotifier()
        scheduler = build(
            session_factory,
            [virtual(station_code="D01", payload_scenario=PayloadScenario.STORE_FULL)],
            notifier=notifier,
        )
        await scheduler.tick()

        with session_factory() as session:
            assert session.scalar(select(func.count()).select_from(Incident)) == 0
        assert notifier.sent == []

        # 상태는 정상으로 위조하지 않고 유지보수로 기록한다.
        states = states_of(session_factory, device.id)
        assert states[("connectivity", "", "")].severity is Severity.MAINTENANCE

    async def test_관측소_범위_유지보수도_적용된다(self, session_factory):
        with session_factory() as session:
            device = register(session, station_code="D02")
            session.add(
                MaintenanceWindow(
                    scope="station",
                    scope_id=device.station_id,
                    starts_at=utcnow() - timedelta(minutes=10),
                    ends_at=utcnow() + timedelta(minutes=10),
                )
            )
            session.commit()

        scheduler = build(
            session_factory,
            [virtual(station_code="D02", payload_scenario=PayloadScenario.STORE_FULL)],
        )
        await scheduler.tick()

        with session_factory() as session:
            assert session.scalar(select(func.count()).select_from(Incident)) == 0

    async def test_지난_유지보수_구간은_영향을_주지_않는다(self, session_factory):
        with session_factory() as session:
            device = register(session, station_code="D03")
            session.add(
                MaintenanceWindow(
                    scope="device",
                    scope_id=device.id,
                    starts_at=utcnow() - timedelta(days=2),
                    ends_at=utcnow() - timedelta(days=1),
                )
            )
            session.commit()

        scheduler = build(
            session_factory,
            [virtual(station_code="D03", payload_scenario=PayloadScenario.STORE_FULL)],
        )
        await scheduler.tick()

        with session_factory() as session:
            assert session.scalar(select(func.count()).select_from(Incident)) > 0


class Test장비Override:
    async def test_장비별_임계값이_프로파일을_덮는다(self, session_factory):
        """전압은 12V 배터리와 24V 전원에서 기준이 달라야 한다."""
        with session_factory() as session:
            device = register(session, station_code="E01")
            session.add(
                DeviceMetricOverride(
                    device_id=device.id,
                    metric_key="power.input_voltage_v",
                    warning_condition={"op": "<=", "value": 13.5},
                    critical_condition={},
                )
            )
            session.commit()

        scheduler = build(session_factory, [virtual(station_code="E01")])
        await scheduler.tick()

        with session_factory() as session:
            incident = session.scalar(
                select(Incident).where(Incident.metric_key == "power.input_voltage_v")
            )
        # 기본 프로파일(11.8V)로는 정상이지만 Override(13.5V)로는 주의다.
        assert incident is not None
        assert incident.severity is Severity.WARNING

    async def test_차원별_Override(self, session_factory):
        with session_factory() as session:
            device = register(session, station_code="E02")
            session.add(
                DeviceMetricOverride(
                    device_id=device.id,
                    metric_key="sensor.mass_position_v",
                    dimension_value="A/U",
                    warning_condition={"op": "abs>=", "value": 0.01},
                    critical_condition={},
                )
            )
            session.commit()

        scheduler = build(session_factory, [virtual(station_code="E02")])
        await scheduler.tick()

        with session_factory() as session:
            incidents = session.scalars(
                select(Incident).where(Incident.metric_key == "sensor.mass_position_v")
            ).all()

        # 지정한 축에만 규칙이 적용된다.
        assert len(incidents) == 1
        assert incidents[0].dimension_value == "A/U"


class Test장애확인:
    async def test_확인은_복구가_아니다(self, session_factory):
        with session_factory() as session:
            device = register(session, station_code="F01")

        scheduler = build(
            session_factory,
            [virtual(station_code="F01", payload_scenario=PayloadScenario.STORE_FULL)],
        )
        await scheduler.tick()

        with session_factory() as session:
            incident = session.scalar(
                select(Incident).where(Incident.metric_key == "storage.used_percent")
            )
            acknowledged = incident_ops.acknowledge(
                session, incident.id, actor_id=None, occurred_at=utcnow(), message="현장 출동"
            )
            session.commit()
            assert acknowledged.status is IncidentStatus.ACKNOWLEDGED

        # 확인된 장애도 여전히 '열린 장애' 다. 같은 원인으로 새로 만들지 않는다.
        due_now(session_factory, device.id)
        await scheduler.tick()

        with session_factory() as session:
            same_target = session.scalars(
                select(Incident).where(Incident.metric_key == "storage.used_percent")
            ).all()
        assert len(same_target) == 1
        assert same_target[0].status is IncidentStatus.ACKNOWLEDGED

    async def test_복구되면_확인된_장애도_닫힌다(self, session_factory):
        with session_factory() as session:
            device = register(session, station_code="F02")

        broken = build(
            session_factory,
            [virtual(station_code="F02", payload_scenario=PayloadScenario.STORE_FULL)],
        )
        await broken.tick()

        with session_factory() as session:
            incident = session.scalar(
                select(Incident).where(Incident.metric_key == "storage.used_percent")
            )
            incident_ops.acknowledge(session, incident.id, actor_id=None, occurred_at=utcnow())
            session.commit()

        healthy = build(session_factory, [virtual(station_code="F02")])
        due_now(session_factory, device.id)
        await healthy.tick()

        with session_factory() as session:
            refreshed = session.scalar(
                select(Incident).where(Incident.metric_key == "storage.used_percent")
            )
        assert refreshed.status is IncidentStatus.RESOLVED


class Test낡은값:
    async def test_수집이_성공하면_값은_최신이다(self, session_factory):
        with session_factory() as session:
            device = register(session, station_code="G01")

        scheduler = build(session_factory, [virtual(station_code="G01")])
        await scheduler.tick()

        states = states_of(session_factory, device.id)
        assert states[("connectivity", "", "")].is_stale is False

    async def test_수집이_실패하고_마지막_성공이_오래되면_낡은_값이다(self, session_factory):
        """수집이 멈춘 동안에는 실패 기록조차 남지 않는다. 마지막 성공이 유일한 근거다."""
        with session_factory() as session:
            device = register(session, station_code="G02")

        healthy = build(session_factory, [virtual(station_code="G02")])
        await healthy.tick()

        with session_factory() as session:
            from app.db.models import DeviceRuntimeState

            state = session.get(DeviceRuntimeState, device.id)
            state.last_success_at = utcnow() - timedelta(hours=3)
            session.commit()

        broken = build(
            session_factory,
            [virtual(station_code="G02", transport_scenario=TransportScenario.HTTP_500)],
        )
        due_now(session_factory, device.id)
        await broken.tick()

        states = states_of(session_factory, device.id)
        assert states[("connectivity", "", "")].is_stale is True
