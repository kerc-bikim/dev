"""edge 프로세스 실행점.

지역망에서 기록계를 수집해 로컬 Spool 에 쌓고 중앙으로 올린다. 중앙 Collector 와
같은 Adapter 코드를 쓴다. 수집 결과 형식이 같아야 Grafana 대시보드를 공유할 수 있다.

중앙이 꺼져 있어도 수집은 멈추지 않는다. 전송만 미룬다.
"""
from __future__ import annotations

import asyncio

from app.adapters.registry import get_registry
from app.config.settings import get_settings
from app.edgeagent.runtime import EdgeRuntime
from app.observability.logging import configure_logging, get_logger
from app.runtime.service import PeriodicService, install_signal_handlers


async def run_edge(max_ticks: int | None = None, runtime: EdgeRuntime | None = None) -> PeriodicService:
    settings = get_settings()
    logger = get_logger("app.edge", role="edge")

    if not settings.edge_id:
        logger.error("SOH_EDGE_ID 가 없다. Edge 는 중앙에 자신을 식별할 수 없으면 동작하지 않는다")
        raise SystemExit(2)

    registry = get_registry()
    agent = runtime or EdgeRuntime.from_settings(settings, registry)
    logger.info(
        "Edge 준비",
        extra={
            "edge_id": settings.edge_id,
            "central_url": settings.central_url,
            "spool_path": str(settings.edge_spool_path),
            "adapter_count": len(registry),
        },
    )

    async def tick() -> None:
        stats = await agent.tick()
        logger.debug(
            "Edge Tick",
            extra={
                "config_version": stats.config_version,
                "collected": stats.collected,
                "uploaded": stats.uploaded,
                "central_down": stats.central_down,
                "pending_batches": agent.spool.pending_count(),
            },
        )

    service = PeriodicService(
        "edge",
        interval_seconds=settings.scheduler_tick_seconds,
        handler=tick,
        max_ticks=max_ticks,
    )
    install_signal_handlers(service)
    try:
        await service.run()
    finally:
        await agent.aclose()
    return service


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, role="edge", json_output=settings.is_production)
    asyncio.run(run_edge())


if __name__ == "__main__":
    main()
