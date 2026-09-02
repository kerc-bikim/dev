"""상태 전이 규칙.

순간적으로 임계값을 넘었다고 곧바로 장애를 만들지 않는다. 그렇게 하면 회선이 한 번
흔들릴 때마다 알림이 오고, 결국 운영자가 알림을 무시하게 된다. 알림을 무시하기 시작하면
감시 체계는 없는 것과 같다.

그래서 두 방향에 각각 지연을 둔다.
  * 나빠질 때  : 지속시간(hold)과 연속 위반 횟수를 함께 요구한다
  * 좋아질 때  : 회복 지속시간(recovery)을 요구한다 — Hysteresis

지연을 넘기기 전의 상태는 '보류' 로 관리하고, 화면에는 이전 확정 상태를 보인다.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.domain.enums import Severity

# 나쁜 정도 비교. 값이 클수록 나쁘다.
_RANK = {Severity.OK: 0, Severity.UNKNOWN: 1, Severity.WARNING: 2, Severity.CRITICAL: 3}

# 지연 없이 곧바로 반영하는 상태. 판정 대상이 아니라는 사실은 미룰 이유가 없다.
_IMMEDIATE = {Severity.DISABLED, Severity.MAINTENANCE}


@dataclass
class PendingState:
    """확정되지 않은 전이. health_states.detail 에 그대로 담긴다."""

    severity: Severity | None = None
    since: datetime | None = None
    violations: int = 0

    def to_json(self) -> dict[str, Any]:
        return {
            "pending_severity": self.severity.value if self.severity else None,
            "pending_since": self.since.isoformat() if self.since else None,
            "pending_violations": self.violations,
        }

    @classmethod
    def from_json(cls, detail: dict[str, Any] | None) -> "PendingState":
        detail = detail or {}
        raw_severity = detail.get("pending_severity")
        raw_since = detail.get("pending_since")
        since: datetime | None = None
        if isinstance(raw_since, str):
            try:
                since = datetime.fromisoformat(raw_since)
            except ValueError:
                since = None
        return cls(
            severity=Severity(raw_severity) if raw_severity else None,
            since=since,
            violations=int(detail.get("pending_violations") or 0),
        )


@dataclass(frozen=True)
class Transition:
    """전이 결과."""

    severity: Severity
    changed: bool
    pending: PendingState
    reason: str = ""

    @property
    def escalated(self) -> bool:
        return self.changed and self.severity in {Severity.WARNING, Severity.CRITICAL}

    @property
    def recovered(self) -> bool:
        return self.changed and self.severity is Severity.OK


def _is_worse(candidate: Severity, current: Severity) -> bool:
    return _RANK.get(candidate, -1) > _RANK.get(current, -1)


def advance(
    current: Severity,
    candidate: Severity,
    pending: PendingState,
    *,
    now: datetime,
    hold_seconds: int = 0,
    recovery_seconds: int = 0,
    required_violations: int = 1,
    first_observation: bool = False,
) -> Transition:
    """현재 상태와 새 판정으로부터 다음 상태를 정한다."""
    if first_observation and not _is_worse(candidate, current):
        # 처음 판정하는 항목이 정상이면 지연 없이 확정한다. 회복 지연(Hysteresis)은 확정된
        # 상태 사이의 진동을 막는 장치이고, 되돌아갈 이전 상태가 없는 첫 관측에는 해당하지
        # 않는다. 이것을 미루면 새로 등록한 관측소가 첫 회복 구간 동안 '확인 불가' 로 보인다.
        #
        # 반대로 첫 판정이 나쁜 값이면 지속시간을 그대로 요구한다. 등록 직후 한 샘플로
        # 장애를 만들면, 설치 중 흔들리는 값이 곧바로 알림이 된다.
        return Transition(
            severity=candidate,
            changed=candidate is not current,
            pending=PendingState(),
            reason="첫 판정",
        )

    if candidate in _IMMEDIATE or current in _IMMEDIATE:
        # 감시 제외·유지보수는 지연 없이 반영하고, 그 상태에서 빠져나올 때도 즉시 반영한다.
        return Transition(
            severity=candidate,
            changed=candidate is not current,
            pending=PendingState(),
            reason="지연 없이 반영",
        )

    if candidate is current:
        # 같은 상태가 이어지면 보류를 비운다. 흔들리다 제자리로 온 경우다.
        return Transition(severity=current, changed=False, pending=PendingState(), reason="유지")

    if pending.severity is candidate and pending.since is not None:
        elapsed = (now - pending.since).total_seconds()
        violations = pending.violations + 1
    else:
        elapsed = 0.0
        violations = 1
        pending = PendingState(severity=candidate, since=now, violations=0)

    worse = _is_worse(candidate, current)
    required_seconds = hold_seconds if worse else recovery_seconds

    if elapsed >= required_seconds and violations >= (required_violations if worse else 1):
        return Transition(
            severity=candidate,
            changed=True,
            pending=PendingState(),
            reason=(
                f"{'악화' if worse else '회복'} 조건 충족 "
                f"(경과 {elapsed:.0f}s ≥ {required_seconds}s, 위반 {violations}회)"
            ),
        )

    return Transition(
        severity=current,
        changed=False,
        pending=PendingState(severity=candidate, since=pending.since or now, violations=violations),
        reason=(
            f"{'악화' if worse else '회복'} 보류 "
            f"(경과 {elapsed:.0f}s < {required_seconds}s 또는 위반 {violations}/{required_violations})"
        ),
    )


def rollup(severities: list[Severity]) -> Severity:
    """분류·장비 단위 집계.

    판정 대상이 하나도 없으면 정상이라고 하지 않는다. 미지원·유지보수만 있는 분류는
    그 사실을 그대로 표시한다.
    """
    actionable = [s for s in severities if s in _RANK]
    if actionable:
        return max(actionable, key=lambda s: _RANK[s])
    if not severities:
        return Severity.UNKNOWN
    if all(s is Severity.MAINTENANCE for s in severities):
        return Severity.MAINTENANCE
    if all(s in _IMMEDIATE for s in severities):
        return Severity.DISABLED
    return Severity.UNKNOWN
