"""샘플 하나를 판정한다.

여기서 지키는 규칙이 알림 신뢰도를 결정한다.

  * 장비가 그 기능을 갖고 있지 않으면 판정하지 않는다 (UNSUPPORTED)
  * 값이 없으면 정상이 아니라 확인 불가다 (UNKNOWN)
  * 상태 Metric 이 UNKNOWN 을 보고하면 조건과 무관하게 확인 불가다
  * 조건이 비어 있으면 값만 감시하고 알림은 만들지 않는다
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.domain.enums import Severity, SupportState, ValueType
from app.domain.models import CapabilityReport, MetricSample
from app.health.conditions import evaluate_condition
from app.metrics.catalog import MetricCatalog, MetricDefinition, load_catalog


@dataclass(frozen=True)
class EffectiveRule:
    """프로파일과 장비 Override 를 합친 최종 규칙."""

    metric_key: str
    enabled: bool = True
    alerting_enabled: bool = True
    warning_condition: dict[str, Any] = field(default_factory=dict)
    critical_condition: dict[str, Any] = field(default_factory=dict)
    hold_seconds: int = 0
    recovery_seconds: int = 60
    consecutive_violations: int = 1

    @property
    def has_threshold(self) -> bool:
        return bool(self.warning_condition or self.critical_condition)


@dataclass(frozen=True)
class Evaluation:
    """판정 결과 한 건."""

    metric_key: str
    category: str
    dimension_value: str
    severity: Severity
    support_state: SupportState
    alerting_enabled: bool
    value_text: str | None = None
    numeric_value: float | None = None
    threshold: float | None = None
    reason: str = ""
    rule: EffectiveRule | None = None


def dimension_key(dimensions: dict[str, str], order: tuple[str, ...] = ()) -> str:
    """차원을 한 문자열로 만든다. DB 열 하나로 다루기 위한 표기다.

    순서는 카탈로그가 선언한 차원 순서를 따른다. `sensor_port, axis` 로 선언했으면
    `A/U` 가 되고 `U/A` 가 되지 않는다. 운영자가 장비별 Override 를 손으로 쓸 때
    순서가 흔들리면 규칙이 조용히 적용되지 않는다.
    """
    if not dimensions:
        return ""
    if order:
        ordered = [dimensions[name] for name in order if name in dimensions]
        remaining = [value for name, value in sorted(dimensions.items()) if name not in order]
        return "/".join(ordered + remaining)
    return "/".join(value for _, value in sorted(dimensions.items()))


def _numeric_of(sample: MetricSample, definition: MetricDefinition) -> float | None:
    if definition.value_type is ValueType.FLOAT:
        return sample.value_float
    if definition.value_type is ValueType.INTEGER:
        return None if sample.value_int is None else float(sample.value_int)
    return None


def _value_text(sample: MetricSample) -> str | None:
    value = sample.value
    if value is None:
        return None
    if isinstance(value, Severity):
        return value.value
    return str(value)


def evaluate_sample(
    sample: MetricSample,
    rule: EffectiveRule | None,
    capabilities: CapabilityReport,
    *,
    catalog: MetricCatalog | None = None,
    maintenance: bool = False,
) -> Evaluation | None:
    """샘플 하나를 판정한다. 카탈로그에 없는 Metric 이면 None 을 돌려준다."""
    catalog = catalog or load_catalog()
    definition = catalog.metrics.get(sample.metric_key)
    if definition is None:
        return None

    dimension = dimension_key(sample.dimensions, definition.dimensions)
    # 기능 지원 상태는 첫 차원(센서 포트 등)을 기준으로 본다.
    primary_dimension = (
        sample.dimensions.get(definition.dimensions[0]) if definition.dimensions else None
    )

    def build(
        severity: Severity,
        *,
        support_state: SupportState,
        alerting: bool,
        reason: str,
        value_text: str | None = None,
        numeric: float | None = None,
        threshold: float | None = None,
    ) -> Evaluation:
        return Evaluation(
            metric_key=sample.metric_key,
            category=definition.category,
            dimension_value=dimension,
            severity=severity,
            support_state=support_state,
            alerting_enabled=alerting,
            value_text=value_text,
            numeric_value=numeric,
            threshold=threshold,
            reason=reason,
            rule=rule,
        )

    if rule is not None and not rule.enabled:
        return build(
            Severity.DISABLED,
            support_state=SupportState.SUPPORTED_DISABLED,
            alerting=False,
            reason="프로파일에서 감시를 껐다",
            value_text=_value_text(sample),
        )

    support_state = (
        capabilities.state_of(definition.capability, primary_dimension)
        if definition.capability
        else SupportState.SUPPORTED_ENABLED
    )

    if definition.capability and not support_state.evaluable:
        # 장비에 없는 기능을 장애로 세면 알림 신뢰도가 무너진다.
        severity = (
            Severity.UNKNOWN
            if support_state in {SupportState.UNKNOWN, SupportState.ERROR}
            else Severity.DISABLED
        )
        return build(
            severity,
            support_state=support_state,
            alerting=False,
            reason=f"기능 지원 상태 {support_state.value}",
            value_text=_value_text(sample),
        )

    if maintenance:
        return build(
            Severity.MAINTENANCE,
            support_state=support_state,
            alerting=False,
            reason="유지보수 시간",
            value_text=_value_text(sample),
        )

    if not sample.has_value:
        # 값이 없는데 정상이라고 하면 장애를 놓친다.
        return build(
            Severity.UNKNOWN,
            support_state=sample.support_state,
            alerting=bool(rule and rule.alerting_enabled),
            reason=f"값 없음 (원값 {sample.raw_value})" if sample.raw_value else "값 없음",
        )

    if definition.value_type is ValueType.STATUS and sample.value_status is Severity.UNKNOWN:
        # 장비가 우리가 모르는 상태 문자열을 보냈다. 정상으로 접지 않는다.
        return build(
            Severity.UNKNOWN,
            support_state=support_state,
            alerting=bool(rule and rule.alerting_enabled),
            reason=f"해석하지 못한 상태 (원값 {sample.raw_value})",
            value_text=Severity.UNKNOWN.value,
        )

    number = _numeric_of(sample, definition)

    if rule is None or not rule.has_threshold:
        # 임계값이 없는 항목은 값만 남긴다. 전압·온도·Mass Position 처럼 관측소마다
        # 기준이 다른 값을 공통 임계값으로 강요하면 오탐이 된다.
        return build(
            Severity.OK,
            support_state=support_state,
            alerting=False,
            reason="임계값 미설정",
            value_text=_value_text(sample),
            numeric=number,
        )

    status = sample.value_status if definition.value_type is ValueType.STATUS else None
    flag = sample.value_bool if definition.value_type is ValueType.BOOLEAN else None

    critical = evaluate_condition(rule.critical_condition, number=number, status=status, flag=flag)
    if critical.matched:
        return build(
            Severity.CRITICAL,
            support_state=support_state,
            alerting=rule.alerting_enabled,
            reason=critical.description,
            value_text=_value_text(sample),
            numeric=number,
            threshold=critical.threshold,
        )

    warning = evaluate_condition(rule.warning_condition, number=number, status=status, flag=flag)
    if warning.matched:
        return build(
            Severity.WARNING,
            support_state=support_state,
            alerting=rule.alerting_enabled,
            reason=warning.description,
            value_text=_value_text(sample),
            numeric=number,
            threshold=warning.threshold,
        )

    return build(
        Severity.OK,
        support_state=support_state,
        alerting=rule.alerting_enabled,
        reason="정상 범위",
        value_text=_value_text(sample),
        numeric=number,
    )
