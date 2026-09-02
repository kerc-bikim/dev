"""계약 조회 엔드포인트.

프론트엔드는 Metric 목록·분류·단위를 하드코딩하지 않고 이 API 로 받는다.
카탈로그에 Metric 을 추가하면 화면이 따라온다.
"""
from __future__ import annotations

from fastapi import APIRouter

from app.adapters.registry import get_registry
from app.metrics.catalog import load_catalog

router = APIRouter(prefix="/api/v1", tags=["contracts"])


@router.get("/metric-catalog", summary="표준 Metric 카탈로그")
def metric_catalog() -> dict[str, object]:
    catalog = load_catalog()
    return {
        "version": catalog.version,
        "statuses": [s for s in ("OK", "WARNING", "CRITICAL", "UNKNOWN", "DISABLED", "MAINTENANCE")],
        "dimensions": sorted(catalog.dimensions),
        "categories": [
            {
                "key": category.key,
                "displayName": category.display_name,
                "order": category.order,
            }
            for category in sorted(catalog.categories.values(), key=lambda c: c.order)
        ],
        "metrics": [
            {
                "key": metric.key,
                "category": metric.category,
                "displayName": metric.display_name,
                "valueType": metric.value_type.value,
                "unit": metric.unit,
                "source": metric.source.value,
                "measurement": metric.measurement,
                "field": metric.field,
                "required": metric.required,
                "aggregation": metric.aggregation.value,
                "dimensions": list(metric.dimensions),
                "capability": metric.capability,
                "description": metric.description,
            }
            for metric in catalog.metrics.values()
        ],
    }


@router.get("/capabilities", summary="장비 기능 정의")
def capabilities() -> dict[str, object]:
    catalog = load_catalog()
    return {
        "supportStates": [
            "SUPPORTED_ENABLED",
            "SUPPORTED_DISABLED",
            "UNSUPPORTED",
            "UNKNOWN",
            "ERROR",
        ],
        "capabilities": [
            {
                "key": capability.key,
                "displayName": capability.display_name,
                "detectable": capability.detectable,
                "dimension": capability.dimension,
                "description": capability.description,
            }
            for capability in catalog.capabilities.values()
        ],
    }


@router.get("/adapters", summary="등록된 기록계 Adapter")
def adapters() -> dict[str, object]:
    """등록 화면의 제조사·모델 선택 목록.

    구현되지 않은 Adapter 는 목록에 없다. 화면은 이 목록이 비어 있으면
    '지원 장비 준비 중' 으로 표시하고 장비 등록을 막는다.
    """
    registry = get_registry()
    return {
        "adapters": [
            {
                "adapterKey": manifest.adapter_key,
                "adapterVersion": manifest.adapter_version,
                "manufacturer": manifest.manufacturer,
                "productFamilies": list(manifest.product_families),
                "generation": manifest.generation,
                "supportedModels": list(manifest.supported_models),
                "protocols": list(manifest.protocols),
                "capabilities": list(manifest.capabilities),
                "status": manifest.status,
                "selectable": manifest.selectable,
                "configurationSchema": manifest.configuration_schema,
                "uiHints": manifest.ui_hints,
            }
            for manifest in registry.manifests()
        ]
    }
