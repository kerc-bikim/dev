"""제조사 상태 문자열 → 표준 상태 변환.

핵심 규칙은 하나다. **모르는 값은 OK 가 아니다.** 새 펌웨어가 새 문자열을 내보낼 때
정상으로 오인하면 장애를 놓친다. 모르는 값은 UNKNOWN 으로 떨어뜨리고 원문을 남겨
Mapping 을 보강한다.
"""
from __future__ import annotations

import functools
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from app.domain.enums import Severity
from app.metrics.catalog import CONTRACTS_DIR, CatalogError, load_catalog

STATUS_MAPPING_PATH = CONTRACTS_DIR / "metrics" / "status-mappings.yaml"
_CAMEL_SPLIT = re.compile(r"(?<!^)([A-Z])")


def status_lookup_keys(raw: str) -> tuple[str, ...]:
    """URI·camelCase 실응답을 표의 짧은 문자열과 맞춘다.

    `http://nmx.ca/05/soh/timing/timestatus/timeOK` → `time ok`
    """
    text = raw.strip()
    if not text:
        return ()
    candidates: list[str] = []

    def add(value: str) -> None:
        normalized = " ".join(value.strip().lower().split())
        if normalized and normalized not in candidates:
            candidates.append(normalized)

    add(text)
    tail = text.rstrip("/").rsplit("/", 1)[-1] if "://" in text else text
    add(tail)
    add(_CAMEL_SPLIT.sub(r" \1", tail))
    return tuple(candidates)


@dataclass(frozen=True)
class StatusResolution:
    """변환 결과. 원문과 매핑 성공 여부를 함께 들고 다닌다."""

    severity: Severity
    raw_value: str | None
    mapped: bool


@dataclass(frozen=True)
class StatusMappings:
    version: int
    text_maps: dict[str, dict[str, dict[str, Severity]]] = field(default_factory=dict)
    numeric_maps: dict[str, dict[str, dict[int, Severity]]] = field(default_factory=dict)

    def resolve(self, adapter_key: str, metric_key: str, raw_value: object) -> StatusResolution:
        if raw_value is None:
            return StatusResolution(Severity.UNKNOWN, None, mapped=False)

        if isinstance(raw_value, bool):
            # 상태를 참/거짓으로 주는 장비는 Adapter 에서 명시적으로 변환해야 한다.
            return StatusResolution(Severity.UNKNOWN, str(raw_value), mapped=False)

        if isinstance(raw_value, int):
            numeric = self.numeric_maps.get(adapter_key, {}).get(metric_key, {})
            if raw_value in numeric:
                return StatusResolution(numeric[raw_value], str(raw_value), mapped=True)
            return StatusResolution(Severity.UNKNOWN, str(raw_value), mapped=False)

        text = str(raw_value)
        table = self.text_maps.get(adapter_key, {}).get(metric_key, {})
        for candidate in status_lookup_keys(text):
            if candidate in table:
                return StatusResolution(table[candidate], text, mapped=True)
        return StatusResolution(Severity.UNKNOWN, text, mapped=False)

    def known_metrics(self, adapter_key: str) -> tuple[str, ...]:
        keys = set(self.text_maps.get(adapter_key, {})) | set(self.numeric_maps.get(adapter_key, {}))
        return tuple(sorted(keys))


def _parse_severity(value: object, context: str) -> Severity:
    try:
        return Severity(str(value))
    except ValueError as exc:
        raise CatalogError(f"{context}: 알 수 없는 표준 상태 '{value}'") from exc


@functools.lru_cache(maxsize=1)
def load_status_mappings(path: Path | None = None) -> StatusMappings:
    mapping_path = path or STATUS_MAPPING_PATH
    if not mapping_path.exists():
        raise CatalogError(f"계약 파일이 없다: {mapping_path}")

    raw = yaml.safe_load(mapping_path.read_text(encoding="utf-8")) or {}
    catalog = load_catalog()

    text_maps: dict[str, dict[str, dict[str, Severity]]] = {}
    for adapter_key, metrics in (raw.get("adapters") or {}).items():
        per_metric: dict[str, dict[str, Severity]] = {}
        for metric_key, table in (metrics or {}).items():
            definition = catalog.metrics.get(metric_key)
            if definition is None:
                raise CatalogError(
                    f"status-mappings.yaml: 카탈로그에 없는 Metric '{metric_key}' ({adapter_key})"
                )
            if definition.value_type.value != "status":
                raise CatalogError(
                    f"status-mappings.yaml: '{metric_key}' 는 status 타입이 아니다"
                )
            per_metric[metric_key] = {
                " ".join(str(source).strip().lower().split()): _parse_severity(
                    target, f"{adapter_key}.{metric_key}.{source}"
                )
                for source, target in (table or {}).items()
            }
        text_maps[adapter_key] = per_metric

    numeric_maps: dict[str, dict[str, dict[int, Severity]]] = {}
    for adapter_key, metrics in (raw.get("numeric_codes") or {}).items():
        per_metric_numeric: dict[str, dict[int, Severity]] = {}
        for metric_key, table in (metrics or {}).items():
            if metric_key not in catalog.metrics:
                raise CatalogError(
                    f"status-mappings.yaml numeric_codes: 카탈로그에 없는 Metric '{metric_key}'"
                )
            per_metric_numeric[metric_key] = {
                int(code): _parse_severity(target, f"{adapter_key}.{metric_key}.{code}")
                for code, target in (table or {}).items()
            }
        numeric_maps[adapter_key] = per_metric_numeric

    return StatusMappings(
        version=int(raw.get("version", 0)),
        text_maps=text_maps,
        numeric_maps=numeric_maps,
    )
