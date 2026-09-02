"""상태 문자열 변환 검증.

가장 중요한 규칙은 "모르는 값은 OK 가 아니다" 다. 새 펌웨어가 새 문자열을 내보낼 때
정상으로 오인하면 장애를 놓친다.
"""
from __future__ import annotations

import pytest

from app.domain.enums import Severity
from app.metrics.status import load_status_mappings

CTR = "nanometrics.centaur.ctr"


@pytest.fixture(scope="module")
def mappings():
    return load_status_mappings()


@pytest.mark.parametrize(
    ("metric_key", "raw", "expected"),
    [
        ("device.overall_status", "ok", Severity.OK),
        ("device.overall_status", "warning", Severity.WARNING),
        ("device.overall_status", "error", Severity.CRITICAL),
        ("device.configuration_status", "uncommitted", Severity.WARNING),
        ("device.firmware_status", "testcode", Severity.WARNING),
        ("timing.status", "time ok", Severity.OK),
        ("timing.status", "free running", Severity.WARNING),
        ("timing.status", "antenna short", Severity.CRITICAL),
        ("timing.phase_lock", "fine lock", Severity.OK),
        ("timing.phase_lock", "coarse lock", Severity.WARNING),
        ("timing.phase_lock", "no lock", Severity.CRITICAL),
        ("sensor.status", "error", Severity.CRITICAL),
        ("sensor.control_state", "unexpected", Severity.WARNING),
        ("storage.recording_status", "recording", Severity.OK),
        ("storage.recording_status", "wrapping", Severity.OK),
        ("storage.recording_status", "not enough space", Severity.CRITICAL),
        ("storage.sd_status", "not present", Severity.WARNING),
        ("storage.sd_status", "error", Severity.CRITICAL),
        ("archive.continuous_status", "disabled", Severity.DISABLED),
        ("archive.continuous_status", "media full", Severity.CRITICAL),
    ],
)
def test_CTR_상태문자열_변환(mappings, metric_key, raw, expected):
    result = mappings.resolve(CTR, metric_key, raw)
    assert result.severity is expected
    assert result.mapped is True


@pytest.mark.parametrize("raw", ["OK", " ok ", "Ok", "oK"])
def test_대소문자와_공백은_무시한다(mappings, raw):
    assert mappings.resolve(CTR, "device.overall_status", raw).severity is Severity.OK


def test_공백이_섞인_문자열도_정규화한다(mappings):
    assert mappings.resolve(CTR, "timing.status", "time   ok").severity is Severity.OK


def test_모르는_문자열은_UNKNOWN이며_원문을_남긴다(mappings):
    result = mappings.resolve(CTR, "timing.status", "quantum drift")
    assert result.severity is Severity.UNKNOWN
    assert result.mapped is False
    assert result.raw_value == "quantum drift"


def test_값이_없으면_UNKNOWN이다(mappings):
    result = mappings.resolve(CTR, "timing.status", None)
    assert result.severity is Severity.UNKNOWN
    assert result.mapped is False


def test_등록되지_않은_Adapter는_UNKNOWN으로_떨어진다(mappings):
    result = mappings.resolve("vendor.unknown.recorder", "timing.status", "ok")
    assert result.severity is Severity.UNKNOWN
    assert result.mapped is False


@pytest.mark.parametrize(
    ("metric_key", "code", "expected"),
    [
        ("timing.phase_lock", 0, Severity.CRITICAL),
        ("timing.phase_lock", 1, Severity.WARNING),
        ("timing.phase_lock", 2, Severity.OK),
        ("timing.phase_lock", 3, Severity.WARNING),
        ("gnss.antenna_status", 0, Severity.OK),
        ("gnss.antenna_status", 1, Severity.CRITICAL),
        ("timing.status", 0, Severity.DISABLED),
        ("timing.status", 2, Severity.OK),
    ],
)
def test_수치_코드_변환(mappings, metric_key, code, expected):
    result = mappings.resolve(CTR, metric_key, code)
    assert result.severity is expected
    assert result.mapped is True


def test_모르는_수치코드는_UNKNOWN이다(mappings):
    result = mappings.resolve(CTR, "timing.phase_lock", 99)
    assert result.severity is Severity.UNKNOWN
    assert result.mapped is False


def test_참거짓_상태는_Adapter가_직접_변환해야_한다(mappings):
    """장비가 상태를 true/false 로 주면 의미가 모호하다. 암묵 변환을 허용하지 않는다."""
    result = mappings.resolve(CTR, "timing.status", True)
    assert result.severity is Severity.UNKNOWN
    assert result.mapped is False
