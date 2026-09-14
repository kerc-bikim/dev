"""판정 엔진의 데이터 접근.

규칙은 프로파일에서 오고 장비 Override 가 덮는다. Override 는 차원까지 지정할 수 있다.
예를 들어 같은 관측소에서도 Sensor A 와 B 의 Mass Position 기준이 다를 수 있다.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Device, DeviceMetricOverride, HealthState, ProfileMetric
from app.domain.enums import Severity, SupportState
from app.health.evaluator import EffectiveRule


def load_rules(session: Session, device: Device) -> dict[tuple[str, str], EffectiveRule]:
    """(metric_key, dimension_value) → 최종 규칙.

    dimension_value 가 빈 문자열인 항목은 모든 차원에 적용되는 기본값이다.
    """
    rules: dict[tuple[str, str], EffectiveRule] = {}

    if device.metric_profile_id is not None:
        for entry in session.scalars(
            select(ProfileMetric).where(ProfileMetric.profile_id == device.metric_profile_id)
        ):
            rules[(entry.metric_key, "")] = EffectiveRule(
                metric_key=entry.metric_key,
                enabled=entry.enabled,
                alerting_enabled=entry.alerting_enabled,
                warning_condition=entry.warning_condition or {},
                critical_condition=entry.critical_condition or {},
                hold_seconds=entry.hold_seconds,
                recovery_seconds=entry.recovery_seconds,
                consecutive_violations=entry.consecutive_violations,
            )

    for override in session.scalars(
        select(DeviceMetricOverride).where(DeviceMetricOverride.device_id == device.id)
    ):
        base = rules.get((override.metric_key, "")) or EffectiveRule(metric_key=override.metric_key)
        rules[(override.metric_key, override.dimension_value or "")] = EffectiveRule(
            metric_key=override.metric_key,
            enabled=base.enabled if override.enabled is None else override.enabled,
            alerting_enabled=(
                base.alerting_enabled
                if override.alerting_enabled is None
                else override.alerting_enabled
            ),
            warning_condition=(
                base.warning_condition
                if override.warning_condition is None
                else override.warning_condition
            ),
            critical_condition=(
                base.critical_condition
                if override.critical_condition is None
                else override.critical_condition
            ),
            hold_seconds=(
                base.hold_seconds if override.hold_seconds is None else override.hold_seconds
            ),
            recovery_seconds=(
                base.recovery_seconds
                if override.recovery_seconds is None
                else override.recovery_seconds
            ),
            consecutive_violations=base.consecutive_violations,
        )

    return rules


def rule_for(
    rules: dict[tuple[str, str], EffectiveRule], metric_key: str, dimension_value: str
) -> EffectiveRule | None:
    """차원별 규칙을 먼저 찾고, 없으면 기본 규칙을 쓴다."""
    if dimension_value:
        specific = rules.get((metric_key, dimension_value))
        if specific is not None:
            return specific
    return rules.get((metric_key, ""))


def load_states(session: Session, device_id: uuid.UUID) -> dict[tuple[str, str, str], HealthState]:
    return {
        (state.category, state.metric_key or "", state.dimension_value or ""): state
        for state in session.scalars(
            select(HealthState).where(HealthState.device_id == device_id)
        )
    }


def upsert_state(
    session: Session,
    device_id: uuid.UUID,
    *,
    category: str,
    metric_key: str,
    dimension_value: str,
    severity: Severity,
    support_state: SupportState,
    is_stale: bool,
    observed_at: datetime | None,
    evaluated_at: datetime,
    value_text: str | None,
    detail: dict,
    existing: HealthState | None = None,
) -> HealthState:
    state = existing
    if state is None:
        state = HealthState(
            device_id=device_id,
            category=category,
            metric_key=metric_key,
            dimension_value=dimension_value,
        )
        session.add(state)

    state.severity = severity
    state.support_state = support_state
    state.is_stale = is_stale
    state.observed_at = observed_at
    state.evaluated_at = evaluated_at
    state.value_text = value_text[:128] if value_text else None
    state.detail = detail
    session.flush()
    return state
