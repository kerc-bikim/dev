"""Adapter 원본 경로 → 표준 Metric 변환 표.

펌웨어가 필드명을 바꾸면 코드 분기 대신 행을 추가한다. 수집기·Edge 는
DB 없이도 Adapter 옆 YAML 을 읽는다. Seed 가 같은 내용을
adapter_metric_mappings 에 복사해 운영자가 조회할 수 있게 한다.

표현식 평가는 하지 않는다. scale·offset 만 적용한다.
"""
from __future__ import annotations

import functools
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

import yaml

from app.domain.enums import SupportState, ValueType
from app.domain.models import MetricSample
from app.metrics.catalog import load_catalog
from app.metrics.status import load_status_mappings


class ChannelSource(Protocol):
    def has(self, name: str) -> bool: ...
    def raw(self, name: str) -> Any: ...
    def units(self, name: str) -> str | None: ...


@dataclass(frozen=True)
class MappingRule:
    adapter_key: str
    adapter_version: str
    firmware_range: str
    source_path: str
    canonical_metric_key: str
    dimension_value: str = ""
    source_unit: str | None = None
    target_unit: str | None = None
    scale: float = 1.0
    offset: float = 0.0
    notes: str | None = None


@dataclass(frozen=True)
class MappingTable:
    adapter_key: str
    adapter_version: str
    rules: tuple[MappingRule, ...]


class MappingTableError(ValueError):
    """매핑 표가 잘못된 경우."""


def parse_version(raw: str | None) -> tuple[int, ...]:
    if not raw:
        return ()
    parts: list[int] = []
    for token in raw.strip().split("."):
        digits = ""
        for char in token:
            if char.isdigit():
                digits += char
            else:
                break
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts)


def firmware_matches(range_spec: str, firmware: str | None) -> bool:
    spec = (range_spec or "*").strip()
    if spec in {"*", "", "all"}:
        return True
    if not firmware:
        return False
    version = firmware.strip()
    if spec == version:
        return True
    if spec.endswith(".*"):
        prefix = spec[:-2]
        return version == prefix or version.startswith(prefix + ".")
    parsed = parse_version(version)
    if spec.startswith("<="):
        return bool(parsed) and parsed <= parse_version(spec[2:].strip())
    if spec.startswith(">="):
        return bool(parsed) and parsed >= parse_version(spec[2:].strip())
    if spec.startswith("<"):
        return bool(parsed) and parsed < parse_version(spec[1:].strip())
    if spec.startswith(">"):
        return bool(parsed) and parsed > parse_version(spec[1:].strip())
    return False


@functools.lru_cache(maxsize=8)
def load_mapping_table(path: Path) -> MappingTable:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    adapter_key = str(raw.get("adapter_key") or "").strip()
    adapter_version = str(raw.get("adapter_version") or "1.0").strip()
    if not adapter_key:
        raise MappingTableError(f"{path}: adapter_key 가 없다")

    catalog = load_catalog()
    rules: list[MappingRule] = []
    for item in raw.get("rules") or []:
        if not isinstance(item, dict):
            continue
        metric_key = str(item.get("canonical_metric_key") or "").strip()
        source_path = str(item.get("source_path") or "").strip()
        if not metric_key or not source_path:
            continue
        if metric_key not in catalog.metrics:
            raise MappingTableError(f"{path}: 카탈로그에 없는 Metric '{metric_key}'")
        rules.append(
            MappingRule(
                adapter_key=adapter_key,
                adapter_version=adapter_version,
                firmware_range=str(item.get("firmware_range") or "*"),
                source_path=source_path,
                canonical_metric_key=metric_key,
                dimension_value=str(item.get("dimension_value") or ""),
                source_unit=item.get("source_unit"),
                target_unit=item.get("target_unit"),
                scale=float(item.get("scale") or 1.0),
                offset=float(item.get("offset") or 0.0),
                notes=item.get("notes"),
            )
        )
    return MappingTable(adapter_key=adapter_key, adapter_version=adapter_version, rules=tuple(rules))


def apply_mapping_table(
    result: Any,
    source: ChannelSource,
    table: MappingTable,
    *,
    firmware: str | None,
) -> None:
    """표에만 있는 별칭 경로를 표준 Metric 으로 옮긴다.

    이미 같은 Metric·차원이 있으면 건너뛴다. 내장 mapper 가 우선이다.
    """
    catalog = load_catalog()
    statuses = load_status_mappings()
    for rule in table.rules:
        if not firmware_matches(rule.firmware_range, firmware):
            continue
        if not source.has(rule.source_path):
            continue
        definition = catalog.metrics.get(rule.canonical_metric_key)
        if definition is None:
            continue
        dimensions = _dimensions(rule.dimension_value, definition.dimensions)
        if _already_have(result, rule.canonical_metric_key, dimensions):
            continue
        raw = source.raw(rule.source_path)
        sample = _sample_from_rule(rule, definition.value_type, raw, dimensions, statuses)
        if sample is None:
            continue
        result.add(sample, rule.source_path)


def _dimensions(value: str, order: tuple[str, ...]) -> dict[str, str]:
    if not value.strip():
        return {}
    parts = [part for part in value.split("/") if part]
    if not order:
        return {}
    return {name: parts[index] for index, name in enumerate(order) if index < len(parts)}


def _already_have(result: Any, metric_key: str, dimensions: dict[str, str]) -> bool:
    samples = getattr(result, "samples", ())
    return any(sample.metric_key == metric_key and sample.dimensions == dimensions for sample in samples)


def _sample_from_rule(
    rule: MappingRule,
    value_type: ValueType,
    raw: Any,
    dimensions: dict[str, str],
    statuses,
) -> MetricSample | None:
    if raw is None:
        return MetricSample(
            metric_key=rule.canonical_metric_key,
            dimensions=dimensions,
            support_state=SupportState.UNKNOWN,
            raw_value=None,
        )
    if value_type is ValueType.STATUS:
        resolution = statuses.resolve(rule.adapter_key, rule.canonical_metric_key, raw)
        return MetricSample(
            metric_key=rule.canonical_metric_key,
            dimensions=dimensions,
            value_status=resolution.severity,
            raw_value=resolution.raw_value,
            support_state=SupportState.SUPPORTED_ENABLED,
        )
    if value_type is ValueType.TEXT:
        return MetricSample(
            metric_key=rule.canonical_metric_key,
            dimensions=dimensions,
            value_text=str(raw),
            support_state=SupportState.SUPPORTED_ENABLED,
        )
    if value_type is ValueType.TIMESTAMP:
        parsed = _parse_time(raw)
        if parsed is None:
            return MetricSample(
                metric_key=rule.canonical_metric_key,
                dimensions=dimensions,
                support_state=SupportState.UNKNOWN,
                raw_value=str(raw),
            )
        return MetricSample(
            metric_key=rule.canonical_metric_key,
            dimensions=dimensions,
            value_timestamp=parsed,
            support_state=SupportState.SUPPORTED_ENABLED,
        )
    if value_type is ValueType.BOOLEAN:
        if isinstance(raw, bool):
            flag = raw
        elif str(raw).strip().lower() in {"1", "true", "yes", "on"}:
            flag = True
        elif str(raw).strip().lower() in {"0", "false", "no", "off"}:
            flag = False
        else:
            return MetricSample(
                metric_key=rule.canonical_metric_key,
                dimensions=dimensions,
                support_state=SupportState.UNKNOWN,
                raw_value=str(raw),
            )
        return MetricSample(
            metric_key=rule.canonical_metric_key,
            dimensions=dimensions,
            value_bool=flag,
            support_state=SupportState.SUPPORTED_ENABLED,
        )

    number = _to_float(raw)
    if number is None:
        return MetricSample(
            metric_key=rule.canonical_metric_key,
            dimensions=dimensions,
            support_state=SupportState.UNKNOWN,
            raw_value=str(raw),
        )
    converted = number * rule.scale + rule.offset
    if value_type is ValueType.INTEGER:
        return MetricSample(
            metric_key=rule.canonical_metric_key,
            dimensions=dimensions,
            value_int=int(converted),
            support_state=SupportState.SUPPORTED_ENABLED,
        )
    return MetricSample(
        metric_key=rule.canonical_metric_key,
        dimensions=dimensions,
        value_float=round(converted, 6),
        support_state=SupportState.SUPPORTED_ENABLED,
    )


def _to_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _parse_time(raw: Any) -> datetime | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    text = raw.strip().replace("Z", "+00:00")
    if "T" not in text and text.count(" ") == 1 and ":" in text:
        text = text.replace(" ", "T", 1)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
