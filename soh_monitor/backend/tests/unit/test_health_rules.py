"""임계 조건과 상태 전이 규칙 검증.

이 두 모듈이 알림 신뢰도를 결정한다. 오탐이 쌓이면 운영자가 알림을 무시하고,
그때부터 감시 체계는 없는 것과 같다.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.domain.enums import Severity, SupportState
from app.domain.models import CapabilityReport, MetricSample, dimensioned_capability
from app.health.conditions import ConditionError, evaluate_condition, validate_condition
from app.health.evaluator import EffectiveRule, dimension_key, evaluate_sample
from app.health.state_machine import PendingState, advance, rollup

NOW = datetime(2026, 8, 27, 3, 0, 0, tzinfo=timezone.utc)


class Test조건검증:
    @pytest.mark.parametrize(
        "condition",
        [
            {},
            {"op": ">=", "value": 80},
            {"op": "abs>=", "value": 3.5},
            {"op": "outside", "min": 11.5, "max": 15.0},
            {"status": "CRITICAL"},
            {"status_in": ["WARNING", "UNKNOWN"]},
            {"status_at_least": "WARNING"},
            {"expect": True},
        ],
    )
    def test_올바른_조건은_통과한다(self, condition):
        validate_condition(condition)

    @pytest.mark.parametrize(
        "condition",
        [
            {"op": "~=", "value": 1},
            {"op": ">="},
            {"op": "outside", "min": 10},
            {"op": "outside", "min": 20, "max": 10},
            {"status": "SORT_OF_OK"},
            {"status_in": []},
            {"expect": "yes"},
            {"unknown": 1},
        ],
    )
    def test_잘못된_조건은_저장_전에_걸러진다(self, condition):
        """잘못된 조건이 조용히 '항상 정상' 이 되면 장애를 통째로 놓친다."""
        with pytest.raises(ConditionError):
            validate_condition(condition)


class Test조건평가:
    def test_수치_비교(self):
        assert evaluate_condition({"op": ">=", "value": 80}, number=90).matched is True
        assert evaluate_condition({"op": ">=", "value": 80}, number=79).matched is False
        assert evaluate_condition({"op": "<=", "value": 11.5}, number=11.2).matched is True

    def test_부호_무관_크기(self):
        """Mass Position 은 양쪽으로 벗어날 수 있다."""
        condition = {"op": "abs>=", "value": 3.5}
        assert evaluate_condition(condition, number=3.6).matched is True
        assert evaluate_condition(condition, number=-3.6).matched is True
        assert evaluate_condition(condition, number=-3.4).matched is False

    def test_범위_밖(self):
        condition = {"op": "outside", "min": 11.5, "max": 15.0}
        assert evaluate_condition(condition, number=11.4).matched is True
        assert evaluate_condition(condition, number=15.1).matched is True
        assert evaluate_condition(condition, number=12.6).matched is False

    def test_상태_일치(self):
        assert evaluate_condition({"status": "CRITICAL"}, status=Severity.CRITICAL).matched is True
        assert evaluate_condition({"status": "CRITICAL"}, status=Severity.WARNING).matched is False

    def test_상태_이상(self):
        condition = {"status_at_least": "WARNING"}
        assert evaluate_condition(condition, status=Severity.CRITICAL).matched is True
        assert evaluate_condition(condition, status=Severity.WARNING).matched is True
        assert evaluate_condition(condition, status=Severity.OK).matched is False

    def test_참거짓_기대값(self):
        assert evaluate_condition({"expect": True}, flag=False).matched is True
        assert evaluate_condition({"expect": True}, flag=True).matched is False

    def test_조건이_없으면_위반이_아니다(self):
        assert evaluate_condition({}, number=999).matched is False
        assert evaluate_condition(None, number=999).matched is False

    def test_값의_종류가_맞지_않으면_위반으로_보지_않는다(self):
        """잘못된 설정으로 거짓 장애를 만드는 것이 더 나쁘다."""
        assert evaluate_condition({"op": ">=", "value": 80}, status=Severity.OK).matched is False
        assert evaluate_condition({"status": "CRITICAL"}, number=90).matched is False


class Test차원표기:
    def test_카탈로그가_선언한_순서를_따른다(self):
        """운영자가 손으로 Override 를 쓸 때 순서가 흔들리면 규칙이 적용되지 않는다."""
        dimensions = {"axis": "U", "sensor_port": "A"}
        assert dimension_key(dimensions, ("sensor_port", "axis")) == "A/U"

    def test_차원이_없으면_빈_문자열이다(self):
        assert dimension_key({}) == ""


class Test샘플판정:
    def _sample(self, **changes):
        defaults = dict(metric_key="storage.used_percent", value_float=85.0)
        defaults.update(changes)
        return MetricSample(**defaults)

    def _rule(self, **changes):
        defaults = dict(
            metric_key="storage.used_percent",
            warning_condition={"op": ">=", "value": 80},
            critical_condition={"op": ">=", "value": 90},
        )
        defaults.update(changes)
        return EffectiveRule(**defaults)

    def _capable(self):
        return CapabilityReport(states={"storage.internal": SupportState.SUPPORTED_ENABLED})

    def test_주의_판정(self):
        evaluation = evaluate_sample(self._sample(), self._rule(), self._capable())
        assert evaluation.severity is Severity.WARNING
        assert evaluation.threshold == 80

    def test_장애_판정이_주의보다_우선한다(self):
        evaluation = evaluate_sample(
            self._sample(value_float=95.0), self._rule(), self._capable()
        )
        assert evaluation.severity is Severity.CRITICAL
        assert evaluation.threshold == 90

    def test_미지원_기능은_판정하지_않는다(self):
        evaluation = evaluate_sample(
            MetricSample(metric_key="storage.sd_status", value_status=Severity.OK),
            EffectiveRule(metric_key="storage.sd_status", critical_condition={"status": "CRITICAL"}),
            CapabilityReport(states={"storage.removable": SupportState.UNSUPPORTED}),
        )
        assert evaluation.severity is Severity.DISABLED
        assert evaluation.alerting_enabled is False

    def test_기능_확인_불가는_확인_불가로_남긴다(self):
        evaluation = evaluate_sample(
            MetricSample(metric_key="storage.sd_status", value_status=Severity.OK),
            EffectiveRule(metric_key="storage.sd_status"),
            CapabilityReport(states={"storage.removable": SupportState.UNKNOWN}),
        )
        assert evaluation.severity is Severity.UNKNOWN

    def test_값이_없으면_정상이_아니다(self):
        evaluation = evaluate_sample(
            MetricSample(
                metric_key="storage.sd_free_bytes",
                support_state=SupportState.UNKNOWN,
                raw_value="-1",
            ),
            EffectiveRule(metric_key="storage.sd_free_bytes"),
            CapabilityReport(states={"storage.removable": SupportState.SUPPORTED_ENABLED}),
        )
        assert evaluation.severity is Severity.UNKNOWN
        assert "-1" in evaluation.reason

    def test_해석하지_못한_상태는_확인_불가다(self):
        """새 펌웨어 문자열을 정상으로 접으면 장애를 놓친다."""
        evaluation = evaluate_sample(
            MetricSample(
                metric_key="timing.status",
                value_status=Severity.UNKNOWN,
                raw_value="quantum drift",
            ),
            EffectiveRule(metric_key="timing.status", warning_condition={"status": "WARNING"}),
            CapabilityReport(states={"timing.status": SupportState.SUPPORTED_ENABLED}),
        )
        assert evaluation.severity is Severity.UNKNOWN
        assert "quantum drift" in evaluation.reason

    def test_임계값이_없으면_값만_감시한다(self):
        """전압·온도·Mass Position 은 관측소마다 기준이 다르다."""
        evaluation = evaluate_sample(
            MetricSample(metric_key="power.input_voltage_v", value_float=11.0),
            EffectiveRule(metric_key="power.input_voltage_v", alerting_enabled=False),
            CapabilityReport(states={"power.input_voltage": SupportState.SUPPORTED_ENABLED}),
        )
        assert evaluation.severity is Severity.OK
        assert evaluation.alerting_enabled is False
        assert evaluation.reason == "임계값 미설정"

    def test_감시를_끈_항목(self):
        evaluation = evaluate_sample(self._sample(), self._rule(enabled=False), self._capable())
        assert evaluation.severity is Severity.DISABLED

    def test_유지보수_중에는_판정하지_않는다(self):
        evaluation = evaluate_sample(
            self._sample(value_float=99.0), self._rule(), self._capable(), maintenance=True
        )
        assert evaluation.severity is Severity.MAINTENANCE

    def test_차원별_기능_지원_상태를_본다(self):
        report = CapabilityReport(
            states={
                "sensor.status": SupportState.SUPPORTED_ENABLED,
                dimensioned_capability("sensor.status", "B"): SupportState.UNSUPPORTED,
            }
        )
        evaluation = evaluate_sample(
            MetricSample(
                metric_key="sensor.status",
                dimensions={"sensor_port": "B"},
                value_status=Severity.OK,
            ),
            EffectiveRule(metric_key="sensor.status", critical_condition={"status": "CRITICAL"}),
            report,
        )
        assert evaluation.severity is Severity.DISABLED
        assert evaluation.dimension_value == "B"

    def test_카탈로그에_없는_Metric은_판정하지_않는다(self):
        assert (
            evaluate_sample(
                MetricSample(metric_key="power.imaginary", value_float=1.0),
                None,
                CapabilityReport(),
            )
            is None
        )


class Test상태전이:
    def test_지속시간을_넘기기_전에는_확정하지_않는다(self):
        """순간적인 임계값 초과로 장애를 만들면 알림이 폭주한다."""
        first = advance(Severity.OK, Severity.WARNING, PendingState(), now=NOW, hold_seconds=120)
        assert first.severity is Severity.OK
        assert first.changed is False
        assert first.pending.severity is Severity.WARNING

    def test_지속시간을_넘기면_확정한다(self):
        pending = PendingState(severity=Severity.WARNING, since=NOW, violations=1)
        later = advance(
            Severity.OK,
            Severity.WARNING,
            pending,
            now=NOW + timedelta(seconds=130),
            hold_seconds=120,
        )
        assert later.severity is Severity.WARNING
        assert later.changed is True
        assert later.escalated is True

    def test_연속_위반_횟수도_함께_요구한다(self):
        pending = PendingState(severity=Severity.WARNING, since=NOW, violations=1)
        result = advance(
            Severity.OK,
            Severity.WARNING,
            pending,
            now=NOW + timedelta(seconds=300),
            hold_seconds=0,
            required_violations=3,
        )
        assert result.changed is False
        assert result.pending.violations == 2

    def test_회복에도_지연을_둔다(self):
        """값이 임계값 근처에서 흔들릴 때 장애와 복구 알림이 번갈아 오는 것을 막는다."""
        immediate = advance(
            Severity.CRITICAL, Severity.OK, PendingState(), now=NOW, recovery_seconds=180
        )
        assert immediate.severity is Severity.CRITICAL
        assert immediate.changed is False

        sustained = advance(
            Severity.CRITICAL,
            Severity.OK,
            PendingState(severity=Severity.OK, since=NOW, violations=1),
            now=NOW + timedelta(seconds=200),
            recovery_seconds=180,
        )
        assert sustained.severity is Severity.OK
        assert sustained.recovered is True

    def test_첫_판정이_정상이면_즉시_확정한다(self):
        """새로 등록한 관측소가 첫 회복 구간 동안 '확인 불가' 로 보이면 안 된다."""
        result = advance(
            Severity.UNKNOWN,
            Severity.OK,
            PendingState(),
            now=NOW,
            recovery_seconds=600,
            first_observation=True,
        )
        assert result.severity is Severity.OK
        assert result.changed is True

    def test_첫_판정이_나쁜_값이면_지속시간을_요구한다(self):
        """설치 중 흔들리는 값 한 샘플로 장애를 만들지 않는다."""
        result = advance(
            Severity.UNKNOWN,
            Severity.CRITICAL,
            PendingState(),
            now=NOW,
            hold_seconds=600,
            first_observation=True,
        )
        assert result.severity is Severity.UNKNOWN
        assert result.changed is False

    def test_같은_상태가_이어지면_보류를_비운다(self):
        pending = PendingState(severity=Severity.WARNING, since=NOW, violations=2)
        result = advance(Severity.WARNING, Severity.WARNING, pending, now=NOW)
        assert result.changed is False
        assert result.pending.severity is None

    def test_흔들리다_제자리로_오면_전이하지_않는다(self):
        state = Severity.OK
        pending = PendingState()
        for index in range(6):
            candidate = Severity.WARNING if index % 2 == 0 else Severity.OK
            transition = advance(
                state,
                candidate,
                pending,
                now=NOW + timedelta(seconds=index * 10),
                hold_seconds=120,
                recovery_seconds=120,
            )
            state = transition.severity
            pending = transition.pending
        assert state is Severity.OK

    def test_감시_제외와_유지보수는_즉시_반영한다(self):
        result = advance(
            Severity.CRITICAL, Severity.MAINTENANCE, PendingState(), now=NOW, hold_seconds=600
        )
        assert result.severity is Severity.MAINTENANCE
        assert result.changed is True

    def test_유지보수에서_빠져나올_때도_즉시_반영한다(self):
        result = advance(
            Severity.MAINTENANCE, Severity.OK, PendingState(), now=NOW, recovery_seconds=600
        )
        assert result.severity is Severity.OK
        assert result.changed is True

    def test_보류_상태는_JSON으로_왕복한다(self):
        pending = PendingState(severity=Severity.WARNING, since=NOW, violations=2)
        restored = PendingState.from_json(pending.to_json())
        assert restored.severity is Severity.WARNING
        assert restored.since == NOW
        assert restored.violations == 2

    def test_깨진_보류_기록은_비운_상태로_읽는다(self):
        restored = PendingState.from_json({"pending_severity": None, "pending_since": "어제"})
        assert restored.severity is None
        assert restored.since is None


class Test집계:
    def test_가장_나쁜_상태를_고른다(self):
        assert rollup([Severity.OK, Severity.WARNING, Severity.OK]) is Severity.WARNING
        assert rollup([Severity.WARNING, Severity.CRITICAL]) is Severity.CRITICAL

    def test_확인_불가는_정상보다_나쁘다(self):
        assert rollup([Severity.OK, Severity.UNKNOWN]) is Severity.UNKNOWN

    def test_미지원과_유지보수는_집계에서_빠진다(self):
        assert rollup([Severity.OK, Severity.DISABLED]) is Severity.OK

    def test_판정_대상이_없으면_정상이라고_하지_않는다(self):
        assert rollup([]) is Severity.UNKNOWN
        assert rollup([Severity.DISABLED]) is Severity.DISABLED
        assert rollup([Severity.MAINTENANCE]) is Severity.MAINTENANCE
        assert rollup([Severity.DISABLED, Severity.MAINTENANCE]) is Severity.DISABLED
