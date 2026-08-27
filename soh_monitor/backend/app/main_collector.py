"""collector 프로세스 실행점.

`collection_mode=DIRECT` 장비를 중앙에서 직접 수집한다. 스케줄링·재시도·InfluxDB
적재는 M3 에서 이 골격 위에 붙는다. 현재는 Tick 골격과 종료 처리만 동작한다.
"""
from __future__ import annotations

import asyncio

from app.adapters.registry import get_registry
from app.config.settings import get_settings
from app.metrics.catalog import load_catalog
from app.observability.logging import configure_logging, get_logger
from app.runtime.service import PeriodicService, install_signal_handlers


async def run_collector(max_ticks: int | None = None) -> PeriodicService:
    settings = get_settings()
    logger = get_logger("app.collector", role="collector")

    catalog = load_catalog()
    registry = get_registry()
    logger.info(
        "수집기 준비",
        extra={
            "metric_count": len(catalog.metrics),
            "adapter_count": len(registry),
            "tick_seconds": settings.scheduler_tick_seconds,
        },
    )
    if len(registry) == 0:
        # 등록된 Adapter 가 없으면 수집할 수 없다. 조용히 도는 것보다 이유를 남긴다.
        logger.warning("등록된 기록계 Adapter 가 없다. 수집 대상이 없는 상태로 대기한다")

    async def tick() -> None:
        # M3: next_poll_at 이 지난 DIRECT 장비를 조회해 Adapter 로 수집한다.
        logger.debug("스케줄 Tick", extra={"due_devices": 0})

    service = PeriodicService(
        "collector",
        interval_seconds=settings.scheduler_tick_seconds,
        handler=tick,
        max_ticks=max_ticks,
    )
    install_signal_handlers(service)
    await service.run()
    return service


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, role="collector", json_output=settings.is_production)
    asyncio.run(run_collector())


if __name__ == "__main__":
    main()
