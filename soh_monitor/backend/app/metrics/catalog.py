"""표준 Metric 카탈로그 로더와 검증기.

`contracts/metrics/*.yaml` 이 단일 원본이다. 코드에 Metric 목록을 중복해서 적지 않는다.
카탈로그와 실제 적재값이 어긋나는 것을 막기 위해, 샘플 검증도 여기서 한다.
"""
from __future__ import annotations

import functools
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import yaml

from app.domain.enums import Aggregation, MetricSource, Severity, SupportState, ValueType
from app.domain.models import MetricSample

CONTRACTS_DIR = Path(__file__).resolve().parents[3] / "contracts"
CATALOG_PATH = CONTRACTS_DIR / "metrics" / "catalog.yaml"
CAPABILITIES_PATH = CONTRACTS_DIR / "metrics" / "capabilities.yaml"


class CatalogError(Exception):
    """카탈로그 자체가 잘못된 경우. 기동 시점에 즉시 실패시킨다."""


class SampleValidationError(Exception):
    """Adapter 가 카탈로그와 어긋나는 샘플을 만든 경우."""


@dataclass(frozen=True)
class MetricDefinition:
    key: str
    category: str
    display_name: str
    value_type: ValueType
    unit: str | None
    source: MetricSource
    measurement: str
    field: str
    required: bool
    aggregation: Aggregation
    dimensions: tuple[str, ...]
    capability: str | None
    description: str


@dataclass(frozen=True)
class CategoryDefinition:
    key: str
    display_name: str
    order: int


@dataclass(frozen=True)
class CapabilityDefinition:
    key: str
    display_name: str
    detectable: bool
    dimension: str | None
    description: str


@dataclass(frozen=True)
class MetricCatalog:
    version: int
    metrics: dict[str, MetricDefinition]
    categories: dict[str, CategoryDefinition]
    capabilities: dict[str, CapabilityDefinition]
    dimensions: frozenset[str]

    def get(self, metric_key: str) -> MetricDefinition:
        try:
            return self.metrics[metric_key]
        except KeyError as exc:
            raise SampleValidationError(f"카탈로그에 없는 Metric: {metric_key}") from exc

    def by_category(self, category: str) -> tuple[MetricDefinition, ...]:
        return tuple(m for m in self.metrics.values() if m.category == category)

    def by_source(self, source: MetricSource) -> tuple[MetricDefinition, ...]:
        return tuple(m for m in self.metrics.values() if m.source is source)

    def measurements(self) -> tuple[str, ...]:
        return tuple(sorted({m.measurement for m in self.metrics.values()}))


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        raise CatalogError(f"계약 파일이 없다: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise CatalogError(f"계약 파일 형식이 잘못됐다: {path}")
    return data


def _parse_capabilities(raw: dict) -> dict[str, CapabilityDefinition]:
    declared_states = set(raw.get("support_states") or [])
    expected_states = {state.value for state in SupportState}
    if declared_states != expected_states:
        raise CatalogError(
            "capabilities.yaml 의 support_states 가 SupportState 열거형과 다르다: "
            f"{sorted(declared_states ^ expected_states)}"
        )

    capabilities: dict[str, CapabilityDefinition] = {}
    for entry in raw.get("capabilities") or []:
        key = entry.get("key")
        if not key:
            raise CatalogError("capability 에 key 가 없다")
        if key in capabilities:
            raise CatalogError(f"capability 키가 중복됐다: {key}")
        capabilities[key] = CapabilityDefinition(
            key=key,
            display_name=entry.get("display_name") or key,
            detectable=bool(entry.get("detectable", True)),
            dimension=entry.get("dimension"),
            description=(entry.get("description") or "").strip(),
        )
    if not capabilities:
        raise CatalogError("capability 가 하나도 없다")
    return capabilities


def _parse_catalog(raw: dict, capabilities: dict[str, CapabilityDefinition]) -> MetricCatalog:
    declared_statuses = set(raw.get("statuses") or [])
    expected_statuses = {severity.value for severity in Severity}
    if declared_statuses != expected_statuses:
        raise CatalogError(
            "catalog.yaml 의 statuses 가 Severity 열거형과 다르다: "
            f"{sorted(declared_statuses ^ expected_statuses)}"
        )

    dimensions = frozenset((raw.get("dimensions") or {}).keys())

    categories: dict[str, CategoryDefinition] = {}
    for entry in raw.get("categories") or []:
        key = entry["key"]
        if key in categories:
            raise CatalogError(f"category 키가 중복됐다: {key}")
        categories[key] = CategoryDefinition(
            key=key,
            display_name=entry.get("display_name") or key,
            order=int(entry.get("order", 0)),
        )
    if not categories:
        raise CatalogError("category 가 하나도 없다")

    metrics: dict[str, MetricDefinition] = {}
    for entry in raw.get("metrics") or []:
        key = entry.get("key")
        if not key:
            raise CatalogError("metric 에 key 가 없다")
        if key in metrics:
            raise CatalogError(f"metric 키가 중복됐다: {key}")

        category = entry.get("category")
        if category not in categories:
            raise CatalogError(f"{key}: 등록되지 않은 category '{category}'")

        metric_dimensions = tuple(entry.get("dimensions") or ())
        unknown_dimensions = set(metric_dimensions) - dimensions
        if unknown_dimensions:
            raise CatalogError(f"{key}: 등록되지 않은 dimension {sorted(unknown_dimensions)}")

        capability = entry.get("capability")
        if capability is not None and capability not in capabilities:
            raise CatalogError(f"{key}: 등록되지 않은 capability '{capability}'")

        try:
            metrics[key] = MetricDefinition(
                key=key,
                category=category,
                display_name=entry.get("display_name") or key,
                value_type=ValueType(entry["value_type"]),
                unit=entry.get("unit"),
                source=MetricSource(entry["source"]),
                measurement=entry["measurement"],
                field=entry["field"],
                required=bool(entry.get("required", False)),
                aggregation=Aggregation(entry.get("aggregation", "last")),
                dimensions=metric_dimensions,
                capability=capability,
                description=(entry.get("description") or "").strip(),
            )
        except KeyError as exc:
            raise CatalogError(f"{key}: 필수 항목이 빠졌다 ({exc})") from exc
        except ValueError as exc:
            raise CatalogError(f"{key}: 값이 잘못됐다 ({exc})") from exc

    if not metrics:
        raise CatalogError("metric 이 하나도 없다")

    _check_measurement_field_conflicts(metrics)

    return MetricCatalog(
        version=int(raw.get("version", 0)),
        metrics=metrics,
        categories=categories,
        capabilities=capabilities,
        dimensions=dimensions,
    )


def _check_measurement_field_conflicts(metrics: dict[str, MetricDefinition]) -> None:
    """같은 measurement+field 를 두 Metric 이 쓰면 InfluxDB 에서 서로 덮어쓴다.

    단, dimensions 로 갈라지는 경우(vendor metric 처럼 metric_key 를 tag 로 쓰는 설계)는
    허용한다. 그때는 measurement 가 recorder_vendor_metric 이어야 한다.
    """
    seen: dict[tuple[str, str], str] = {}
    for metric in metrics.values():
        slot = (metric.measurement, metric.field)
        if slot in seen:
            first = seen[slot]
            if metric.measurement == "recorder_vendor_metric":
                continue
            raise CatalogError(
                f"measurement/field 충돌: '{first}' 와 '{metric.key}' 가 "
                f"{metric.measurement}.{metric.field} 를 함께 쓴다"
            )
        seen[slot] = metric.key


@functools.lru_cache(maxsize=1)
def load_catalog() -> MetricCatalog:
    """카탈로그를 읽어 검증한다. 프로세스 기동 시 한 번만 수행된다."""
    capabilities = _parse_capabilities(_load_yaml(CAPABILITIES_PATH))
    return _parse_catalog(_load_yaml(CATALOG_PATH), capabilities)


_VALUE_FIELD_BY_TYPE: dict[ValueType, str] = {
    ValueType.FLOAT: "value_float",
    ValueType.INTEGER: "value_int",
    ValueType.BOOLEAN: "value_bool",
    ValueType.TEXT: "value_text",
    ValueType.STATUS: "value_status",
    ValueType.TIMESTAMP: "value_timestamp",
}


def validate_sample(sample: MetricSample, catalog: MetricCatalog | None = None) -> None:
    """샘플이 카탈로그와 맞는지 검사한다.

    Adapter 단위 테스트에서 이 함수를 통과하지 못하면 Adapter 를 등록하지 않는다.
    """
    catalog = catalog or load_catalog()
    definition = catalog.get(sample.metric_key)

    expected_dimensions = set(definition.dimensions)
    actual_dimensions = set(sample.dimensions)
    if expected_dimensions != actual_dimensions:
        raise SampleValidationError(
            f"{sample.metric_key}: dimension 이 다르다. 기대 {sorted(expected_dimensions)}, "
            f"실제 {sorted(actual_dimensions)}"
        )

    if not sample.has_value:
        if sample.support_state.expects_value:
            raise SampleValidationError(
                f"{sample.metric_key}: 값이 없는데 support_state 가 "
                f"{sample.support_state.value} 다. 값 없음은 UNSUPPORTED/UNKNOWN/ERROR 로 표시한다"
            )
        return

    allowed_field = _VALUE_FIELD_BY_TYPE[definition.value_type]
    filled = [
        name
        for name in _VALUE_FIELD_BY_TYPE.values()
        if getattr(sample, name) is not None
    ]
    if filled != [allowed_field]:
        raise SampleValidationError(
            f"{sample.metric_key}: value_type 은 {definition.value_type.value} 인데 "
            f"채워진 필드는 {filled} 다"
        )

    if definition.value_type is ValueType.TIMESTAMP:
        value = sample.value_timestamp
        assert isinstance(value, datetime)
        if value.tzinfo is None:
            raise SampleValidationError(f"{sample.metric_key}: timestamp 에 시간대가 없다")
