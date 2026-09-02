"""판정 실행.

한 번의 수집 결과를 받아 다음을 한다.

  1. 통신 상태를 판정한다 (연속 실패 기준). 통신이 끊겼으면 값 기반 판정은 하지 않는다.
     응답이 없는데 '전압 정상' 이라고 표시하면 안 된다.
  2. 값 기반 항목을 판정한다 (프로파일 + 장비 Override).
  3. 지속시간·Hysteresis 를 적용해 상태를 확정한다.
  4. 분류별·장비별로 집계한다.
  5. 확정된 전이에 대해서만 Incident 를 열거나 복구한다.
  6. `recorder_health` 로 적재해 Grafana 가 severity 만 보고 알림을 만들 수 있게 한다.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.db.models import Device, Station
from app.domain.enums import Severity, SupportState
from app.domain.models import PollResult
from app.health import incidents as incident_ops
from app.health import maintenance as maintenance_ops
from app.health.evaluator import EffectiveRule, Evaluation, dimension_key, evaluate_sample
from app.health.notifier import Notifier
from app.health.state_machine import PendingState, advance, rollup
from app.metrics.catalog import load_catalog
from app.observability.logging import get_logger
from app.repository.influx.points import DeviceTags, PointSpec
from app.repository.postgres import health_repo

logger = get_logger("app.health", role="collector")

CONNECTIVITY_CATEGORY = "connectivity"
CONNECTIVITY_METRIC = "connectivity.reachable"
HEALTH_MEASUREMENT = "recorder_health"


@dataclass
class HealthReport:
    device_id: uuid.UUID
    overall: Severity = Severity.UNKNOWN
    categories: dict[str, Severity] = field(default_factory=dict)
    opened: list[str] = field(default_factory=list)
    resolved: list[str] = field(default_factory=list)
    escalated: list[str] = field(default_factory=list)
    points: list[PointSpec] = field(default_factory=list)
    maintenance: bool = False
    is_stale: bool = False


def _connectivity_evaluation(
    result: PollResult,
    consecutive_failures: int,
    *,
    warning_threshold: int,
    critical_threshold: int,
    maintenance: bool,
) -> Evaluation:
    if maintenance:
        severity = Severity.MAINTENANCE
        reason = "유지보수 시간"
    elif result.success:
        severity = Severity.OK
        reason = "응답 정상"
    elif consecutive_failures >= critical_threshold:
        severity = Severity.CRITICAL
        reason = f"연속 실패 {consecutive_failures}회"
    elif consecutive_failures >= warning_threshold:
        severity = Severity.WARNING
        reason = f"연속 실패 {consecutive_failures}회"
    else:
        # 1회 실패로는 상태를 내리지 않는다. 다만 정상이라고도 하지 않는다.
        severity = Severity.UNKNOWN
        reason = f"실패 {consecutive_failures}회 (임계 미달)"

    return Evaluation(
        metric_key=CONNECTIVITY_METRIC,
        category=CONNECTIVITY_CATEGORY,
        dimension_value="",
        severity=severity,
        support_state=SupportState.SUPPORTED_ENABLED,
        alerting_enabled=True,
        value_text=(
            "reachable"
            if result.success
            else (result.error_code.value if result.error_code else "unreachable")
        ),
        reason=reason,
        # 통신은 지연을 두지 않는다. 악화는 이미 '연속 실패 N회' 로 걸러지고, 회복은
        # 응답이 왔다는 사실 자체가 근거다. 여기에 회복 지연을 더하면 수집기가 보고하는
        # 상태와 판정 결과가 서로 다른 값을 말하게 된다.
        rule=EffectiveRule(metric_key=CONNECTIVITY_METRIC, hold_seconds=0, recovery_seconds=0),
    )


class HealthService:
    def __init__(
        self,
        *,
        warning_threshold: int = 2,
        critical_threshold: int = 3,
        stale_factor: float = 3.0,
        notifier: Notifier | None = None,
    ) -> None:
        self.warning_threshold = warning_threshold
        self.critical_threshold = critical_threshold
        self.stale_factor = stale_factor
        self.notifier = notifier

    # ------------------------------------------------------------------ 판정

    def evaluate(
        self,
        session: Session,
        device: Device,
        station: Station,
        result: PollResult,
        *,
        consecutive_failures: int,
        tags: DeviceTags,
        poll_interval_minutes: int = 5,
        last_success_at: datetime | None = None,
        now: datetime | None = None,
    ) -> HealthReport:
        now = now or datetime.now(timezone.utc)
        report = HealthReport(device_id=device.id)

        window = maintenance_ops.in_maintenance(
            session,
            device_id=device.id,
            station_id=station.id,
            edge_id=device.edge_id,
            region_id=station.region_id,
            now=now,
        )
        report.maintenance = window is not None

        # 값을 신뢰할 수 있는지 판정한다. 기준이 두 갈래다.
        #   * 수집이 성공했으면 관측 시각이 낡았는지 본다. Edge 가 뒤늦게 올린 데이터로
        #     '지금 정상' 이라고 표시하면 안 된다.
        #   * 수집이 실패했으면 마지막 성공이 얼마나 오래됐는지 본다. 수집이 멈춘 동안에는
        #     실패 기록조차 남지 않으므로 이 값이 유일한 근거다.
        stale_threshold = poll_interval_minutes * 60 * self.stale_factor
        if result.success:
            report.is_stale = (now - result.observed_at).total_seconds() > stale_threshold
        elif last_success_at is not None:
            report.is_stale = (now - last_success_at).total_seconds() > stale_threshold
        else:
            report.is_stale = True

        catalog = load_catalog()
        rules = health_repo.load_rules(session, device)
        states = health_repo.load_states(session, device.id)

        evaluations: list[Evaluation] = [
            _connectivity_evaluation(
                result,
                consecutive_failures,
                warning_threshold=self.warning_threshold,
                critical_threshold=self.critical_threshold,
                maintenance=report.maintenance,
            )
        ]

        # 통신이 끊긴 동안에는 값 기반 판정을 하지 않는다. 이전 값으로 '지금 정상' 이라고
        # 표시하면 안 되고, 새 장애를 만들어도 안 된다.
        if result.success:
            for sample in result.samples:
                definition = catalog.metrics.get(sample.metric_key)
                if definition is None or definition.category == CONNECTIVITY_CATEGORY:
                    continue
                dimension = dimension_key(sample.dimensions, definition.dimensions)
                rule = health_repo.rule_for(rules, sample.metric_key, dimension)
                evaluation = evaluate_sample(
                    sample,
                    rule,
                    result.capabilities,
                    catalog=catalog,
                    maintenance=report.maintenance,
                )
                if evaluation is not None:
                    evaluations.append(evaluation)

        confirmed: list[tuple[Evaluation, Severity, bool]] = []
        for evaluation in evaluations:
            key = (evaluation.category, evaluation.metric_key, evaluation.dimension_value)
            existing = states.get(key)
            current = existing.severity if existing else Severity.UNKNOWN
            pending = PendingState.from_json(existing.detail if existing else None)
            rule = evaluation.rule

            transition = advance(
                current,
                evaluation.severity,
                pending,
                now=now,
                hold_seconds=rule.hold_seconds if rule else 0,
                recovery_seconds=rule.recovery_seconds if rule else 60,
                required_violations=rule.consecutive_violations if rule else 1,
                first_observation=existing is None,
            )

            health_repo.upsert_state(
                session,
                device.id,
                category=evaluation.category,
                metric_key=evaluation.metric_key,
                dimension_value=evaluation.dimension_value,
                severity=transition.severity,
                support_state=evaluation.support_state,
                is_stale=report.is_stale,
                observed_at=result.observed_at,
                evaluated_at=now,
                value_text=evaluation.value_text,
                detail={
                    "reason": evaluation.reason,
                    "threshold": evaluation.threshold,
                    "transition": transition.reason,
                    **transition.pending.to_json(),
                },
                existing=existing,
            )
            confirmed.append((evaluation, transition.severity, transition.changed))

        self._apply_incidents(session, device, station, result, confirmed, report)
        self._rollup(session, device, states, confirmed, report, now=now, tags=tags)
        return report

    # ------------------------------------------------------------------ 장애

    def _apply_incidents(
        self,
        session: Session,
        device: Device,
        station: Station,
        result: PollResult,
        confirmed: list[tuple[Evaluation, Severity, bool]],
        report: HealthReport,
    ) -> None:
        if report.maintenance:
            # 유지보수 중에는 새 장애를 만들지 않는다. 이미 열린 장애는 그대로 둔다.
            return

        for evaluation, severity, changed in confirmed:
            target = incident_ops.IncidentTarget(
                device_id=device.id,
                station_id=station.id,
                station_code=station.station_code,
                category=evaluation.category,
                metric_key=evaluation.metric_key,
                dimension_value=evaluation.dimension_value,
            )

            if severity in {Severity.WARNING, Severity.CRITICAL}:
                if not evaluation.alerting_enabled:
                    continue
                _, kind = incident_ops.open_or_escalate(
                    session,
                    target,
                    severity=severity,
                    title=self._title(station, evaluation, severity),
                    observed_at=result.observed_at,
                    value=evaluation.numeric_value,
                    threshold=evaluation.threshold,
                    reason=evaluation.reason,
                    notifier=self.notifier,
                )
                if kind == "OPENED":
                    report.opened.append(evaluation.metric_key)
                elif kind == "ESCALATED":
                    report.escalated.append(evaluation.metric_key)

            elif severity is Severity.OK and changed:
                resolved = incident_ops.resolve(
                    session,
                    target,
                    observed_at=result.observed_at,
                    reason=evaluation.reason,
                    notifier=self.notifier,
                )
                if resolved is not None:
                    report.resolved.append(evaluation.metric_key)

    @staticmethod
    def _title(station: Station, evaluation: Evaluation, severity: Severity) -> str:
        label = evaluation.metric_key
        if evaluation.dimension_value:
            label = f"{label}[{evaluation.dimension_value}]"
        return f"[{station.station_code}] {label} {severity.value}"

    # ------------------------------------------------------------------ 집계

    def _rollup(
        self,
        session: Session,
        device: Device,
        states: dict,
        confirmed: list[tuple[Evaluation, Severity, bool]],
        report: HealthReport,
        *,
        now: datetime,
        tags: DeviceTags,
    ) -> None:
        by_category: dict[str, list[Severity]] = {}
        for evaluation, severity, _ in confirmed:
            by_category.setdefault(evaluation.category, []).append(severity)

        for category, severities in by_category.items():
            severity = rollup(severities)
            report.categories[category] = severity

            health_repo.upsert_state(
                session,
                device.id,
                category=category,
                metric_key="",
                dimension_value="",
                severity=severity,
                support_state=SupportState.SUPPORTED_ENABLED,
                is_stale=report.is_stale,
                observed_at=now,
                evaluated_at=now,
                value_text=severity.value,
                detail={"metric_count": len(severities)},
                existing=states.get((category, "", "")),
            )

            report.points.append(
                PointSpec(
                    measurement=HEALTH_MEASUREMENT,
                    tags={**tags.as_dict(), "category": category},
                    fields={"severity": severity.code, "is_stale": report.is_stale},
                    timestamp=now,
                )
            )

        report.overall = rollup(list(report.categories.values()))
        report.points.append(
            PointSpec(
                measurement=HEALTH_MEASUREMENT,
                tags={**tags.as_dict(), "category": "overall"},
                fields={"severity": report.overall.code, "is_stale": report.is_stale},
                timestamp=now,
            )
        )

        logger.info(
            "판정 완료",
            extra={
                "device_id": str(device.id),
                "overall": report.overall.value,
                "categories": {k: v.value for k, v in report.categories.items()},
                "opened": report.opened,
                "resolved": report.resolved,
                "escalated": report.escalated,
                "maintenance": report.maintenance,
                "is_stale": report.is_stale,
            },
        )
