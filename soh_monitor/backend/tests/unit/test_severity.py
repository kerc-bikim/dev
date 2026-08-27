"""상태 집계 규칙 검증.

미지원·확인불가를 정상으로 접지 않는 것이 이 모듈의 존재 이유다.
"""
from __future__ import annotations

import pytest

from app.domain.enums import Severity, SupportState
from app.domain.models import CapabilityReport


@pytest.mark.parametrize(
    ("severity", "code"),
    [
        (Severity.OK, 0),
        (Severity.WARNING, 1),
        (Severity.CRITICAL, 2),
        (Severity.UNKNOWN, 3),
        (Severity.DISABLED, 4),
        (Severity.MAINTENANCE, 5),
    ],
)
def test_severity_코드는_카탈로그_설명과_일치한다(severity, code):
    assert severity.code == code
    assert Severity.from_code(code) is severity


def test_가장_나쁜_상태를_고른다():
    assert Severity.worst([Severity.OK, Severity.WARNING]) is Severity.WARNING
    assert Severity.worst([Severity.WARNING, Severity.CRITICAL]) is Severity.CRITICAL
    assert Severity.worst([Severity.OK, Severity.OK]) is Severity.OK


def test_확인불가는_정상보다_나쁘게_본다():
    """수집이 안 된 항목이 있으면 그 관측소를 정상으로 표시하지 않는다."""
    assert Severity.worst([Severity.OK, Severity.UNKNOWN]) is Severity.UNKNOWN


def test_확인불가보다_경고가_우선한다():
    assert Severity.worst([Severity.UNKNOWN, Severity.WARNING]) is Severity.WARNING


def test_미지원과_유지보수는_집계에서_빠진다():
    assert Severity.worst([Severity.OK, Severity.DISABLED]) is Severity.OK
    assert Severity.worst([Severity.OK, Severity.MAINTENANCE]) is Severity.OK


def test_판정_대상이_하나도_없으면_확인불가다():
    assert Severity.worst([Severity.DISABLED, Severity.MAINTENANCE]) is Severity.DISABLED
    assert Severity.worst([]) is Severity.UNKNOWN


class Test기능지원상태:
    def test_활성_기능만_값을_기대한다(self):
        assert SupportState.SUPPORTED_ENABLED.expects_value is True
        for state in (
            SupportState.SUPPORTED_DISABLED,
            SupportState.UNSUPPORTED,
            SupportState.UNKNOWN,
            SupportState.ERROR,
        ):
            assert state.expects_value is False

    def test_활성_기능만_장애_판정한다(self):
        assert SupportState.SUPPORTED_ENABLED.evaluable is True
        assert SupportState.UNSUPPORTED.evaluable is False
        assert SupportState.UNKNOWN.evaluable is False

    def test_capability가_없는_Metric은_항상_판정한다(self):
        report = CapabilityReport()
        assert report.evaluable(None) is True

    def test_미지원_기능은_판정에서_제외된다(self):
        report = CapabilityReport(states={"storage.removable": SupportState.UNSUPPORTED})
        assert report.evaluable("storage.removable") is False

    def test_탐지되지_않은_기능은_확인불가다(self):
        report = CapabilityReport()
        assert report.state_of("storage.removable") is SupportState.UNKNOWN
        assert report.evaluable("storage.removable") is False
