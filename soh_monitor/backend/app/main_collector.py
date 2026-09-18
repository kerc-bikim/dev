"""collector 프로세스 실행점.

`collection_mode=DIRECT` 장비를 중앙에서 직접 수집한다. Edge 수집 장비는 건드리지 않는다.
"""
from __future__ import annotations

import asyncio

from app.adapters.registry import get_registry
from app.config.settings import Settings, get_settings
from app.db.session import get_session_factory
from app.metrics.catalog import load_catalog
from app.observability.logging import configure_logging, get_logger
from app.repository.influx.sink import BufferedMetricSink, InfluxMetricSink, MetricSink
from app.runtime.service import PeriodicService, install_signal_handlers


def build_sink(settings: Settings) -> MetricSink:
    """적재 경로를 만든다.

    InfluxDB 가 잠시 멈춰도 수집은 계속돼야 하므로 버퍼로 감싼다.
    토큰이 없으면(개발 중 미설정) 적재를 건너뛰지 않고 기동을 막는다. 조용히 버리는
    것보다 이유를 아는 편이 낫다.
    """
    token = settings.resolved_secret("influx_token")
    if not token:
        raise SystemExit("SOH_INFLUX_TOKEN 이 없다. 시계열을 적재할 수 없다")

    inner = InfluxMetricSink(
        url=settings.influx_url,
        token=token,
        org=settings.influx_org,
        bucket=settings.influx_bucket,
    )
    return BufferedMetricSink(inner)


async def run_collector(max_ticks: int | None = None, sink: MetricSink | None = None) -> PeriodicService:
    settings = get_settings()
    logger = get_logger("app.collector", role="collector")

    catalog = load_catalog()
    registry = get_registry()
    logger.info(
        "수집기 준비",
        extra={
            "metric_count": len(catalog.metrics),
            "adapters": list(registry.keys()),
            "tick_seconds": settings.scheduler_tick_seconds,
            "max_concurrent_polls": settings.max_concurrent_polls,
        },
    )

    # 스케줄러를 늦게 import 한다. 시험에서 DB 없이 이 모듈을 불러올 수 있게 한다.
    from app.collector.scheduler import CollectorScheduler

    scheduler = CollectorScheduler(
        get_session_factory(),
        sink or build_sink(settings),
        settings=settings,
        registry=registry,
    )

    async def tick() -> None:
        await scheduler.tick()
        from app.db.session import session_scope
        from app.health.edge_watch import evaluate_all

        with session_scope() as session:
            evaluate_all(session)

    service = PeriodicService(
        "collector",
        interval_seconds=settings.scheduler_tick_seconds,
        handler=tick,
        max_ticks=max_ticks,
    )
    install_signal_handlers(service)
    await service.run()
    scheduler.sink.close()
    return service


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, role="collector", json_output=settings.is_production)
    asyncio.run(run_collector())


if __name__ == "__main__":
    main()
