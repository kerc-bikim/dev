"""표준 Metric 카탈로그 계약 검증.

카탈로그가 깨지면 모든 계층이 조용히 어긋난다. 그래서 카탈로그 자체를 테스트한다.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
import yaml

from app.domain.enums import MetricSource, Severity, SupportState, ValueType
from app.domain.models import MetricSample
from app.metrics.catalog import (
    CATALOG_PATH,
    CatalogError,
    SampleValidationError,
    _parse_capabilities,
    _parse_catalog,
    load_catalog,
    validate_sample,
)
from app.metrics.status import load_status_mappings


def test_카탈로그를_읽고_검증한다():
    catalog = load_catalog()
    assert catalog.version >= 1
    assert len(catalog.metrics) > 30
    assert "connectivity.reachable" in catalog.metrics
    assert "power.input_voltage_v" in catalog.metrics


def test_통신_가능_여부는_필수_Metric이다():
    """수집 성공 여부를 남기지 않으면 '데이터 없음'과 '장비 죽음'을 구분할 수 없다."""
    catalog = load_catalog()
    assert catalog.metrics["connectivity.reachable"].required is True
    assert catalog.metrics["connectivity.latency_ms"].required is True


def test_표준_Metric_키에는_제조사_이름이_없다():
    catalog = load_catalog()
    offenders = [
        key
        for key in catalog.metrics
        if not key.startswith("vendor.")
        and any(word in key.lower() for word in ("centaur", "nanometrics", "gen5"))
    ]
    assert offenders == [], f"표준 Metric 키에 제조사 이름이 있다: {offenders}"


def test_모든_Metric은_등록된_capability만_참조한다():
    catalog = load_catalog()
    for metric in catalog.metrics.values():
        if metric.capability is not None:
            assert metric.capability in catalog.capabilities, metric.key


def test_measurement_필드가_겹치지_않는다():
    catalog = load_catalog()
    slots: dict[tuple[str, str], str] = {}
    for metric in catalog.metrics.values():
        if metric.measurement == "recorder_vendor_metric":
            continue
        slot = (metric.measurement, metric.field)
        assert slot not in slots, f"{metric.key} 가 {slots.get(slot)} 와 같은 자리를 쓴다"
        slots[slot] = metric.key


def test_source가_collector인_Metric은_기록계_응답에_의존하지_않는다():
    catalog = load_catalog()
    collector_metrics = {m.key for m in catalog.by_source(MetricSource.COLLECTOR)}
    assert "connectivity.reachable" in collector_metrics
    assert "power.input_voltage_v" not in collector_metrics


def test_상태_Mapping은_카탈로그의_status_Metric만_다룬다():
    catalog = load_catalog()
    mappings = load_status_mappings()
    for adapter_key in ("nanometrics.centaur.ctr", "acme.mock.recorder"):
        for metric_key in mappings.known_metrics(adapter_key):
            assert metric_key in catalog.metrics
            assert catalog.metrics[metric_key].value_type is ValueType.STATUS


def test_카탈로그의_statuses가_열거형과_다르면_기동에_실패한다():
    raw = yaml.safe_load(CATALOG_PATH.read_text(encoding="utf-8"))
    raw["statuses"] = ["OK", "WARNING"]
    capabilities = _parse_capabilities(
        yaml.safe_load(
            (CATALOG_PATH.parent / "capabilities.yaml").read_text(encoding="utf-8")
        )
    )
    with pytest.raises(CatalogError, match="statuses"):
        _parse_catalog(raw, capabilities)


def test_등록되지_않은_dimension을_쓰면_실패한다():
    raw = yaml.safe_load(CATALOG_PATH.read_text(encoding="utf-8"))
    raw["metrics"][0]["dimensions"] = ["nonexistent_dimension"]
    capabilities = _parse_capabilities(
        yaml.safe_load(
            (CATALOG_PATH.parent / "capabilities.yaml").read_text(encoding="utf-8")
        )
    )
    with pytest.raises(CatalogError, match="dimension"):
        _parse_catalog(raw, capabilities)


class Test샘플검증:
    def test_값_타입이_카탈로그와_다르면_거부한다(self):
        sample = MetricSample(metric_key="power.input_voltage_v", value_text="12.4")
        with pytest.raises(SampleValidationError, match="value_type"):
            validate_sample(sample)

    def test_dimension이_빠지면_거부한다(self):
        sample = MetricSample(metric_key="sensor.mass_position_v", value_float=0.4)
        with pytest.raises(SampleValidationError, match="dimension"):
            validate_sample(sample)

    def test_dimension이_맞으면_통과한다(self):
        sample = MetricSample(
            metric_key="sensor.mass_position_v",
            dimensions={"sensor_port": "A", "axis": "U"},
            value_float=0.4,
        )
        validate_sample(sample)

    def test_값이_없으면_미지원_또는_확인불가로_표시해야_한다(self):
        missing = MetricSample(metric_key="storage.sd_free_bytes")
        with pytest.raises(SampleValidationError, match="support_state"):
            validate_sample(missing)

        unsupported = MetricSample(
            metric_key="storage.sd_free_bytes", support_state=SupportState.UNSUPPORTED
        )
        validate_sample(unsupported)

    def test_카탈로그에_없는_Metric은_거부한다(self):
        with pytest.raises(SampleValidationError, match="카탈로그에 없는"):
            validate_sample(MetricSample(metric_key="power.nonexistent", value_float=1.0))

    def test_status_Metric은_표준_상태만_받는다(self):
        sample = MetricSample(metric_key="timing.status", value_status=Severity.WARNING)
        validate_sample(sample)

    def test_timestamp에는_시간대가_있어야_한다(self):
        naive = MetricSample(
            metric_key="timing.last_lock_at", value_timestamp=datetime(2026, 1, 1, 0, 0, 0)
        )
        with pytest.raises(SampleValidationError, match="시간대"):
            validate_sample(naive)

        aware = MetricSample(
            metric_key="timing.last_lock_at",
            value_timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        validate_sample(aware)
