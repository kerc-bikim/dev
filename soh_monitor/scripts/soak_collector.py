"""수집기 부하·안정성 시험 (계획서 M3 Exit 조건).

가상 기록계 N대를 등록하고 수집 Tick 을 반복해 다음을 확인한다.

  * 목표 주기를 지키는지
  * 느린 장비가 다른 장비의 수집을 지연시키지 않는지
  * 실패한 장비가 다른 장비에 영향을 주지 않는지
  * InfluxDB 가 멈춘 구간에서도 수집이 계속되고 데이터를 잃지 않는지

사용법
    python scripts/soak_collector.py --devices 50 --ticks 5
"""
from __future__ import annotations

import argparse
import asyncio
import statistics
import sys
import time
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from httpx import ASGITransport  # noqa: E402
from sqlalchemy import create_engine, func, select  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.adapters.centaur_ctr.adapter import MANIFEST_PATH, CentaurCtrAdapter  # noqa: E402
from app.adapters.registry import AdapterRegistry  # noqa: E402
from app.collector.scheduler import CollectorScheduler  # noqa: E402
from app.config.settings import Settings  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.models import (  # noqa: E402
    CollectionMode,
    CollectionProfile,
    Device,
    DeviceEndpoint,
    DeviceRuntimeState,
    LifecycleStatus,
    PollRun,
    Station,
)
from app.domain.models import utcnow  # noqa: E402
from app.repository.influx.sink import BufferedMetricSink, InMemoryMetricSink  # noqa: E402

from mock.centaur_mock.devices import DeviceRegistry, VirtualDevice  # noqa: E402
from mock.centaur_mock.scenarios import PayloadScenario, TransportScenario  # noqa: E402
from mock.centaur_mock.server import create_app  # noqa: E402


def build_fleet(count: int, slow_ratio: float, fail_ratio: float) -> list[VirtualDevice]:
    devices: list[VirtualDevice] = []
    slow_every = int(1 / slow_ratio) if slow_ratio > 0 else 0
    fail_every = int(1 / fail_ratio) if fail_ratio > 0 else 0

    for index in range(1, count + 1):
        slow = slow_every and index % slow_every == 0
        fail = fail_every and index % fail_every == 0
        six_channel = index % 3 != 0

        transport = TransportScenario.OK
        if fail:
            transport = TransportScenario.HTTP_500
        elif slow:
            transport = TransportScenario.SLOW_RESPONSE

        payload = PayloadScenario.NORMAL
        if not six_channel:
            payload = PayloadScenario.THREE_CHANNEL
        elif index % 7 == 0:
            payload = PayloadScenario.GPS_UNLOCKED
        elif index % 11 == 0:
            payload = PayloadScenario.NO_SD_CARD

        devices.append(
            VirtualDevice(
                instrument_id=f"centaur-{6 if six_channel else 3}__{index:04d}",
                station_code=f"S{index:03d}",
                model="CTR4-6S" if six_channel else "CTR4-3S",
                firmware_version="3.2.8",
                serial_number=f"{index:04d}",
                channel_count=6 if six_channel else 3,
                payload_scenario=payload,
                transport_scenario=transport,
                latency_ms=800 if slow else 0,
            )
        )
    return devices


def register_all(session_factory, fleet: list[VirtualDevice], interval_minutes: int) -> None:
    with session_factory() as session:
        profile = CollectionProfile(
            name="부하 시험",
            poll_interval_minutes=interval_minutes,
            retry_count=0,
            retry_delay_seconds=0,
            is_default=True,
        )
        session.add(profile)
        session.flush()

        for virtual in fleet:
            station = Station(
                station_code=virtual.station_code,
                network_code="KS",
                name=f"{virtual.station_code} 관측소",
                status=LifecycleStatus.ACTIVE,
            )
            session.add(station)
            session.flush()

            device = Device(
                station_id=station.id,
                adapter_key="nanometrics.centaur.ctr",
                adapter_version="1.0",
                instrument_id=virtual.instrument_id,
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
                    hostname=f"ctr-{virtual.station_code.lower()}",
                    base_path="",
                    connect_timeout_ms=2000,
                    request_timeout_ms=3000,
                )
            )
        session.commit()


async def main() -> int:
    parser = argparse.ArgumentParser(description="수집기 부하·안정성 시험")
    parser.add_argument("--devices", type=int, default=50)
    parser.add_argument("--ticks", type=int, default=5)
    parser.add_argument("--interval-minutes", type=int, default=1)
    parser.add_argument("--concurrency", type=int, default=20)
    parser.add_argument("--slow-ratio", type=float, default=0.2)
    parser.add_argument("--fail-ratio", type=float, default=0.1)
    parser.add_argument("--sink-outage-tick", type=int, default=3, help="이 Tick 에서 적재를 끊는다")
    args = parser.parse_args()

    db_path = Path("/tmp/soh_soak.db")
    db_path.unlink(missing_ok=True)
    engine = create_engine(f"sqlite:///{db_path}", future=True)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)

    fleet = build_fleet(args.devices, args.slow_ratio, args.fail_ratio)
    register_all(session_factory, fleet, args.interval_minutes)

    app = create_app(DeviceRegistry(fleet))
    registry = AdapterRegistry()
    registry.register(
        CentaurCtrAdapter(transport=ASGITransport(app=app)), manifest_path=MANIFEST_PATH
    )

    inner = InMemoryMetricSink()
    sink = BufferedMetricSink(inner)
    scheduler = CollectorScheduler(
        session_factory,
        sink,
        settings=Settings(
            app_env="test",
            max_concurrent_polls=args.concurrency,
            poll_jitter_percent=10,
            default_poll_interval_minutes=args.interval_minutes,
        ),
        registry=registry,
        owner="soak",
    )

    slow_count = sum(1 for d in fleet if d.transport_scenario is TransportScenario.SLOW_RESPONSE)
    fail_count = sum(1 for d in fleet if d.transport_scenario is TransportScenario.HTTP_500)
    print(
        f"장비 {len(fleet)}대 (느린 장비 {slow_count}대 800ms, 실패 장비 {fail_count}대), "
        f"동시 수집 {args.concurrency}, 주기 {args.interval_minutes}분"
    )
    print("-" * 92)
    print(f"{'Tick':>4} {'대상':>5} {'성공':>5} {'실패':>5} {'Point':>7} {'소요(s)':>9} "
          f"{'초당 수집':>9} {'적재':>6} {'버퍼':>7}")
    print("-" * 92)

    durations: list[float] = []
    for tick_index in range(1, args.ticks + 1):
        # 두 번째 Tick 부터는 주기를 기다리지 않고 곧바로 대상이 되게 당긴다.
        if tick_index > 1:
            with session_factory() as session:
                for device in session.scalars(select(Device)):
                    device.next_poll_at = utcnow() - timedelta(seconds=1)
                session.commit()

        inner.fail = tick_index == args.sink_outage_tick

        started = time.monotonic()
        report = await scheduler.tick()
        elapsed = time.monotonic() - started
        durations.append(elapsed)

        print(
            f"{tick_index:>4} {report.due:>5} {report.succeeded:>5} {report.failed:>5} "
            f"{report.points_written:>7} {elapsed:>9.2f} "
            f"{(report.succeeded + report.failed) / elapsed:>9.1f} "
            f"{'실패' if report.sink_failed else '정상':>6} {sink.buffered_points:>7}"
        )

    print("-" * 92)

    with session_factory() as session:
        total_runs = session.scalar(select(func.count()).select_from(PollRun))
        successes = session.scalar(
            select(func.count()).select_from(PollRun).where(PollRun.success.is_(True))
        )
        latencies = [
            row for row in session.scalars(select(PollRun.latency_ms)) if row is not None
        ]
        severities: dict[str, int] = {}
        for state in session.scalars(select(DeviceRuntimeState)):
            key = state.overall_severity.value
            severities[key] = severities.get(key, 0) + 1
        leases_held = session.scalar(
            select(func.count())
            .select_from(DeviceRuntimeState)
            .where(DeviceRuntimeState.poll_lease_owner.is_not(None))
        )
        duplicate_polls = session.scalar(
            select(func.count()).select_from(
                select(PollRun.device_id, PollRun.observed_at)
                .group_by(PollRun.device_id, PollRun.observed_at)
                .having(func.count() > 1)
                .subquery()
            )
        )

    print(f"수집 이력          : {total_runs}건 (성공 {successes}, 실패 {total_runs - successes})")
    print(f"Tick 소요          : 평균 {statistics.mean(durations):.2f}s, 최대 {max(durations):.2f}s")
    if latencies:
        ordered = sorted(latencies)
        p95 = ordered[int(len(ordered) * 0.95) - 1]
        print(
            f"장비 응답시간      : 중앙값 {statistics.median(latencies):.0f}ms, "
            f"p95 {p95:.0f}ms, 최대 {max(latencies):.0f}ms"
        )
    print(f"장비 상태 분포     : {severities}")
    print(f"남은 Lease         : {leases_held}건 (0 이어야 한다)")
    print(f"중복 수집          : {duplicate_polls}건 (0 이어야 한다)")
    print(f"적재된 Point       : {len(inner.points)}, 버퍼 잔량 {sink.buffered_points}, "
          f"버린 지점 {sink.dropped_points}")
    print(f"적재 실패 횟수     : {sink.failed_writes}")

    ok = leases_held == 0 and duplicate_polls == 0 and sink.dropped_points == 0
    print("\n판정: " + ("통과" if ok else "확인 필요"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
