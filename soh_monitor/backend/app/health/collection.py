"""수집 활성 여부에 따른 상태 표시.

수집을 끄면 다음 Tick 이 오지 않는다. 마지막 정상·장애 값을 그대로 두면
꺼진 장비가 살아 있는 것처럼 보인다. 읽기 쪽에서 DISABLED 로 덮는다.
저장된 판정 행은 그대로 두어, 다시 켜면 직전 값이 보인다.
"""
from __future__ import annotations

from app.domain.enums import Severity


def collected_severity(enabled: bool, severity: Severity | str | None) -> str:
    if not enabled:
        return Severity.DISABLED.value
    if severity is None:
        return Severity.UNKNOWN.value
    return severity.value if isinstance(severity, Severity) else severity
