"""임계 조건 표현과 평가.

조건은 JSON 으로 저장된다. 화면에서 편집하고 프로파일로 물려 쓰기 때문이다.
표현식 문자열(`"value > 80"`) 대신 구조를 쓴다. 문자열을 평가하면 설정 화면이
코드 실행 경로가 되고, 잘못 입력한 값이 런타임에만 드러난다.

지원 형식
    {}                                    조건 없음 (값만 감시)
    {"op": ">=", "value": 80}
    {"op": "<=", "value": 11.5}
    {"op": ">", "value": 0} / "<" / "==" / "!="
    {"op": "abs>=", "value": 3.5}          부호 무관 크기 (Mass Position)
    {"op": "outside", "min": 11.5, "max": 15.0}
    {"op": "inside", "min": 0, "max": 1}
    {"status": "CRITICAL"}                 장비가 그 상태를 보고했을 때
    {"status_in": ["WARNING", "UNKNOWN"]}
    {"status_at_least": "WARNING"}         그 상태 이상으로 나쁠 때
    {"expect": true}                       참거짓 Metric 이 기대와 다를 때
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.domain.enums import Severity

# 나쁜 정도 비교 순서. DISABLED·MAINTENANCE 는 '판정 대상 아님' 이라 비교에 넣지 않는다.
_SEVERITY_RANK = {
    Severity.OK: 0,
    Severity.UNKNOWN: 1,
    Severity.WARNING: 2,
    Severity.CRITICAL: 3,
}

_NUMERIC_OPS = {">=", "<=", ">", "<", "==", "!=", "abs>=", "abs<=", "outside", "inside"}


class ConditionError(ValueError):
    """조건 자체가 잘못된 경우. 설정을 저장할 때 걸러야 한다."""


@dataclass(frozen=True)
class ConditionMatch:
    matched: bool
    threshold: float | None = None
    description: str = ""


def validate_condition(condition: dict[str, Any] | None) -> None:
    """조건을 저장하기 전에 검사한다. 잘못된 조건은 조용히 '항상 정상' 이 되어 위험하다."""
    if not condition:
        return
    if not isinstance(condition, dict):
        raise ConditionError("조건은 객체여야 한다")

    if "op" in condition:
        op = condition["op"]
        if op not in _NUMERIC_OPS:
            raise ConditionError(f"지원하지 않는 연산자: {op}")
        if op in {"outside", "inside"}:
            if "min" not in condition or "max" not in condition:
                raise ConditionError(f"{op} 조건에는 min 과 max 가 필요하다")
            if float(condition["min"]) > float(condition["max"]):
                raise ConditionError("min 이 max 보다 크다")
        elif "value" not in condition:
            raise ConditionError(f"{op} 조건에는 value 가 필요하다")
        return

    for key in ("status", "status_at_least"):
        if key in condition:
            try:
                Severity(condition[key])
            except ValueError as exc:
                raise ConditionError(f"알 수 없는 상태값: {condition[key]}") from exc
            return

    if "status_in" in condition:
        values = condition["status_in"]
        if not isinstance(values, (list, tuple)) or not values:
            raise ConditionError("status_in 은 비어 있지 않은 목록이어야 한다")
        for value in values:
            try:
                Severity(value)
            except ValueError as exc:
                raise ConditionError(f"알 수 없는 상태값: {value}") from exc
        return

    if "expect" in condition:
        if not isinstance(condition["expect"], bool):
            raise ConditionError("expect 는 참거짓이어야 한다")
        return

    raise ConditionError(f"해석할 수 없는 조건: {sorted(condition)}")


def _numeric_match(condition: dict[str, Any], value: float) -> ConditionMatch:
    op = condition["op"]

    if op in {"outside", "inside"}:
        low = float(condition["min"])
        high = float(condition["max"])
        inside = low <= value <= high
        matched = (not inside) if op == "outside" else inside
        boundary = low if value < low else high
        return ConditionMatch(
            matched=matched,
            threshold=boundary,
            description=f"{value} {'벗어남' if op == 'outside' else '범위 내'} [{low}, {high}]",
        )

    threshold = float(condition["value"])
    subject = abs(value) if op.startswith("abs") else value
    comparisons = {
        ">=": subject >= threshold,
        "<=": subject <= threshold,
        ">": subject > threshold,
        "<": subject < threshold,
        "==": subject == threshold,
        "!=": subject != threshold,
        "abs>=": subject >= threshold,
        "abs<=": subject <= threshold,
    }
    return ConditionMatch(
        matched=comparisons[op],
        threshold=threshold,
        description=f"{subject} {op} {threshold}",
    )


def evaluate_condition(
    condition: dict[str, Any] | None,
    *,
    number: float | None = None,
    status: Severity | None = None,
    flag: bool | None = None,
) -> ConditionMatch:
    """조건이 위반됐는지 판정한다.

    조건이 비어 있으면 위반이 아니다. 값만 감시하고 알림은 만들지 않는 항목이 그렇다.
    값의 종류와 조건의 종류가 맞지 않으면 위반으로 보지 않는다. 잘못된 설정으로 거짓
    장애를 만드는 것이 더 나쁘다.
    """
    if not condition:
        return ConditionMatch(matched=False)

    if "op" in condition:
        if number is None:
            return ConditionMatch(matched=False, description="수치 값이 없다")
        return _numeric_match(condition, number)

    if "status" in condition:
        if status is None:
            return ConditionMatch(matched=False, description="상태 값이 없다")
        target = Severity(condition["status"])
        return ConditionMatch(
            matched=status is target,
            description=f"상태 {status.value} == {target.value}",
        )

    if "status_at_least" in condition:
        if status is None:
            return ConditionMatch(matched=False, description="상태 값이 없다")
        target = Severity(condition["status_at_least"])
        if status not in _SEVERITY_RANK or target not in _SEVERITY_RANK:
            return ConditionMatch(matched=False, description="비교 대상이 아닌 상태")
        return ConditionMatch(
            matched=_SEVERITY_RANK[status] >= _SEVERITY_RANK[target],
            description=f"상태 {status.value} >= {target.value}",
        )

    if "status_in" in condition:
        if status is None:
            return ConditionMatch(matched=False, description="상태 값이 없다")
        targets = {Severity(value) for value in condition["status_in"]}
        return ConditionMatch(
            matched=status in targets,
            description=f"상태 {status.value} ∈ {sorted(s.value for s in targets)}",
        )

    if "expect" in condition:
        if flag is None:
            return ConditionMatch(matched=False, description="참거짓 값이 없다")
        expected = bool(condition["expect"])
        return ConditionMatch(
            matched=flag is not expected,
            description=f"기대 {expected}, 실제 {flag}",
        )

    return ConditionMatch(matched=False, description="해석할 수 없는 조건")
