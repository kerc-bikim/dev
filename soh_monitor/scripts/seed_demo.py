"""시연·수동 시험용 예시 관측소를 넣고 한 번 수집한다.

가상 기록계를 붙여 실제 수집·판정을 한 번 돌리므로, 화면과 API 에 볼 것이 생긴다.
운영 DB 에 쓰지 않도록 접속 문자열을 명시적으로 받는다.

사용법
    SOH_DATABASE_URL_OVERRIDE=sqlite:////tmp/soh_dev.db python scripts/seed_demo.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from httpx import ASGITransport  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.adapters.centaur_ctr.adapter import MANIFEST_PATH, CentaurCtrAdapter  # noqa: E402
from app.adapters.registry import AdapterRegistry  # noqa: E402
from app.collector.scheduler import CollectorScheduler  # noqa: E402
from app.config.settings import get_settings  # noqa: E402
from app.db.models import (  # noqa: E402
    CollectionMode,
    CollectionProfile,
    Device,
    DeviceEndpoint,
    LifecycleStatus,
    MetricDefinitionRow,
    MetricProfile,
    ProfileMetric,
    Region,
    Station,
)
from app.db.session import get_session_factory  # noqa: E402
from app.health.notifier import LoggingNotifier  # noqa: E402
from app.health.service import HealthService  # noqa: E402
from app.repository.influx.sink import InMemoryMetricSink  # noqa: E402

from mock.centaur_mock.devices import load_fleet  # noqa: E402
from mock.centaur_mock.server import create_app  # noqa: E402

# 계획서 8절의 MVP 기본 규칙.
DEMO_THRESHOLDS: dict[str, tuple[dict, dict]] = {
    "storage.used_percent": ({"op": ">=", "value": 80}, {"op": ">=", "value": 90}),
    "storage.recording_status": ({"status": "WARNING"}, {"status": "CRITICAL"}),
    "storage.sd_status": ({"status": "WARNING"}, {"status": "CRITICAL"}),
    "timing.status": ({"status": "WARNING"}, {"status": "CRITICAL"}),
    "timing.phase_lock": ({"status": "WARNING"}, {"status": "CRITICAL"}),
    "device.overall_status": ({"status": "WARNING"}, {"status": "CRITICAL"}),
    "device.configuration_status": ({"status": "WARNING"}, {}),
    "sensor.status": ({"status": "WARNING"}, {"status": "CRITICAL"}),
    "archive.continuous_status": ({"status": "WARNING"}, {"status": "CRITICAL"}),
}

REGIONS = {"A": "수도권", "B": "중부", "C": "남부", "D": "동해"}


def seed(session_factory, fleet) -> None:
    from app.db.seed import seed_metric_definitions

    with session_factory() as session:
        if session.scalar(select(Device).limit(1)) is not None:
            print("이미 예시 데이터가 있다. 그대로 수집만 실행한다")
            return

        seed_metric_definitions(session)
        session.flush()

        metric_profile = MetricProfile(
            name="예시 감시 프로파일",
            description="계획서 8절 MVP 기본 규칙",
            is_default=True,
        )
        session.add(metric_profile)
        session.flush()
        for metric_key, (warning, critical) in DEMO_THRESHOLDS.items():
            if session.get(MetricDefinitionRow, metric_key) is None:
                continue
            session.add(
                ProfileMetric(
                    profile_id=metric_profile.id,
                    metric_key=metric_key,
                    warning_condition=warning,
                    critical_condition=critical,
                    hold_seconds=0,
                    recovery_seconds=0,
                )
            )

        collection_profile = session.scalar(
            select(CollectionProfile).where(CollectionProfile.is_default.is_(True))
        )
        if collection_profile is None:
            collection_profile = CollectionProfile(
                name="예시 5분 수집", poll_interval_minutes=5, is_default=True
            )
            session.add(collection_profile)
            session.flush()

        regions: dict[str, Region] = {}
        for code, name in REGIONS.items():
            region = Region(region_code=code, name=name)
            session.add(region)
            session.flush()
            regions[code] = region

        for virtual in fleet.all():
            region = regions.get(virtual.station_code[0])
            station = Station(
                station_code=virtual.station_code,
                network_code="KS",
                name=f"{virtual.station_code} 관측소",
                region_id=region.id if region else None,
                latitude=37.5 + (hash(virtual.station_code) % 100) / 100,
                longitude=127.0 + (hash(virtual.station_code) % 90) / 100,
                elevation_m=50.0,
                power_profile="12V 배터리",
                status=LifecycleStatus.ACTIVE,
            )
            session.add(station)
            session.flush()

            device = Device(
                station_id=station.id,
                adapter_key="nanometrics.centaur.ctr",
                adapter_version="1.0",
                instrument_id=virtual.instrument_id,
                label=virtual.model,
                serial_number=virtual.serial_number,
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
                    hostname=f"ctr-{virtual.station_code.lower()}",
                    base_path="",
                )
            )

        session.commit()
        print(f"관측소 {len(fleet)}곳을 등록했다")


async def main() -> int:
    settings = get_settings()
    if "sqlite" not in settings.database_url and not os.environ.get("SOH_ALLOW_DEMO_SEED"):
        print("운영 DB 로 보인다. SOH_ALLOW_DEMO_SEED=1 을 주면 강제로 실행한다")
        return 2

    fleet = load_fleet()
    session_factory = get_session_factory()
    seed(session_factory, fleet)

    registry = AdapterRegistry()
    registry.register(
        CentaurCtrAdapter(transport=ASGITransport(app=create_app(fleet))),
        manifest_path=MANIFEST_PATH,
    )

    scheduler = CollectorScheduler(
        session_factory,
        InMemoryMetricSink(),
        registry=registry,
        owner="seed-demo",
        health=HealthService(notifier=LoggingNotifier()),
    )
    report = await scheduler.tick()

    print(
        f"수집 {report.succeeded}대 성공 / {report.failed}대 실패, "
        f"장애 {report.opened}건 생성, 상태 분포 {report.severities}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
