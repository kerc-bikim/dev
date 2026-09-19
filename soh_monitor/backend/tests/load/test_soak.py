"""부하 시험 (계획서 M10.3). CI 에서는 작은 함대로 같은 경로를 돈다.

100대·느린 장비 20% 는 `make soak devices=100` 으로 돌린다. 여기서는
목표 주기 유지 · Influx 중단 중 수집 지속 · 재시작 후 스케줄 복구를 못 박는다.
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
from app.db.models import Device, DeviceRuntimeState, PollRun
from app.domain.models import utcnow
from app.health.notifier import CollectingNotifier
from app.health.service import HealthService
from app.repository.influx.sink import BufferedMetricSink, InMemoryMetricSink

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from mock.centaur_mock.server import create_app  # noqa: E402
from scripts.soak_collector import build_fleet, register_all  # noqa: E402

pytestmark = pytest.mark.asyncio


async def test_느린_장비와_적재_중단에도_주기를_지킨다(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path/'soak.db'}", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    fleet = build_fleet(12, slow_ratio=0.25, fail_ratio=0.15)
    register_all(factory, fleet, interval_minutes=1)

    from mock.centaur_mock.devices import DeviceRegistry

    mock = DeviceRegistry(fleet)
    registry = AdapterRegistry()
    registry.register(
        CentaurCtrAdapter(transport=ASGITransport(app=create_app(mock))),
        manifest_path=MANIFEST_PATH,
    )
    inner = InMemoryMetricSink()
    sink = BufferedMetricSink(inner)
    scheduler = CollectorScheduler(
        factory,
        sink,
        settings=Settings(
            app_env="test",
            max_concurrent_polls=8,
            poll_jitter_percent=0,
            default_poll_interval_minutes=1,
        ),
        registry=registry,
        owner="load",
        health=HealthService(notifier=CollectingNotifier()),
    )

    inner.fail = True
    first = await scheduler.tick()
    assert first.due == 12
    assert first.succeeded + first.failed == 12
    assert first.sink_failed is True
    assert sink.buffered_points > 0

    inner.fail = False
    with factory() as session:
        for device in session.scalars(select(Device)):
            device.next_poll_at = utcnow() - timedelta(seconds=1)
        session.commit()
    second = await scheduler.tick()
    assert second.sink_failed is False
    assert sink.buffered_points == 0

    recovered = CollectorScheduler(
        factory,
        sink,
        settings=Settings(app_env="test", max_concurrent_polls=8, poll_jitter_percent=0),
        registry=registry,
        owner="load-restart",
        health=HealthService(notifier=CollectingNotifier()),
    )
    with factory() as session:
        for device in session.scalars(select(Device)):
            device.next_poll_at = utcnow() - timedelta(seconds=1)
        session.commit()
    third = await recovered.tick()
    assert third.due == 12

    with factory() as session:
        leases = session.scalar(
            select(func.count())
            .select_from(DeviceRuntimeState)
            .where(DeviceRuntimeState.poll_lease_owner.is_not(None))
        )
        runs = session.scalar(select(func.count()).select_from(PollRun))
    assert leases == 0
    assert runs >= 24
