"""기동·준비 상태 점검 엔드포인트."""
from __future__ import annotations

from fastapi import APIRouter, Response, status

from app.config.settings import get_settings
from app.metrics.catalog import CatalogError, load_catalog
from app.metrics.status import load_status_mappings

router = APIRouter(tags=["health"])


@router.get("/healthz", summary="살아 있는지")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz", summary="요청을 받을 준비가 됐는지")
def readyz(response: Response) -> dict[str, object]:
    """계약 파일을 읽을 수 있고 필수 설정이 채워졌는지 확인한다.

    계약 파일이 깨진 채로 서비스가 트래픽을 받으면 잘못된 Metric 이름으로
    데이터가 쌓인다. 그것보다 준비 안 됨을 알리는 편이 낫다.
    """
    settings = get_settings()
    checks: dict[str, object] = {}
    ready = True

    try:
        catalog = load_catalog()
        mappings = load_status_mappings()
        checks["contracts"] = {
            "catalog_version": catalog.version,
            "metric_count": len(catalog.metrics),
            "status_mapping_version": mappings.version,
        }
    except CatalogError as exc:
        ready = False
        checks["contracts"] = {"error": str(exc)}

    problems = settings.startup_problems()
    checks["configuration"] = {"problems": problems}
    if problems:
        ready = False

    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return {"ready": ready, "environment": settings.app_env, "checks": checks}
