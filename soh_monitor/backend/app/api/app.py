"""FastAPI 애플리케이션 조립."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routers import (
    audit,
    auth,
    contracts,
    devices,
    edge,
    health,
    health_status,
    maintenance,
    profiles,
    stations,
    users,
)
from app.config.settings import get_settings
from app.metrics.catalog import load_catalog
from app.metrics.status import load_status_mappings
from app.observability.logging import configure_logging, get_logger

API_TITLE = "관측소 SOH 통합 모니터링 API"
API_VERSION = "0.8.0"


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logger = get_logger("app.api", role="api")

    # 계약을 기동 시점에 읽어 검증한다. 여기서 실패하면 뜨지 않는 편이 낫다.
    catalog = load_catalog()
    mappings = load_status_mappings()
    logger.info(
        "계약 적재 완료",
        extra={
            "catalog_version": catalog.version,
            "metric_count": len(catalog.metrics),
            "status_mapping_version": mappings.version,
        },
    )

    for problem in settings.startup_problems():
        logger.error("설정 점검 실패", extra={"problem": problem})

    yield


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level, role="api", json_output=settings.is_production)

    app = FastAPI(
        title=API_TITLE,
        version=API_VERSION,
        description=(
            "Centaur CTR 계열을 1차 대상으로 하는 기록계 SOH 통합 모니터링 API. "
            "제조사 고유 필드는 노출하지 않고 표준 Metric 만 다룬다."
        ),
        lifespan=lifespan,
    )

    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(contracts.router)
    app.include_router(stations.router)
    app.include_router(devices.router)
    app.include_router(profiles.router)
    app.include_router(health_status.router)
    app.include_router(users.router)
    app.include_router(audit.router)
    app.include_router(maintenance.router)
    app.include_router(edge.manager)
    app.include_router(edge.agent)
    return app


app = create_app()
