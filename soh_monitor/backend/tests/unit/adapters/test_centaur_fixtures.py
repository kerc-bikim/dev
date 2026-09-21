"""Fixture 회귀 시험.

`testdata/` 의 응답을 모두 파싱·변환해 카탈로그 검증을 통과하는지 본다. 응답 형식이
바뀌거나 Mapping 이 깨지면 여기서 걸린다.

`real-` 접두 Fixture(실장비 응답)가 하나라도 들어오면 `test_실응답과_가상서버_기준선이_어긋나지_않는다`
가 켜진다. 가상 서버가 조용히 현실에서 멀어지는 것을 막는 장치다.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.adapters.centaur_ctr.mapper import (
    is_acknowledged_unmapped,
    map_soh,
    unknown_channels,
)
from app.adapters.centaur_ctr.parser import parse_soh
from app.adapters.centaur_ctr import capabilities as capability_detector
from app.domain.enums import Severity, SupportState
from app.metrics.catalog import validate_sample

TESTDATA = (
    Path(__file__).resolve().parents[3]
    / "app"
    / "adapters"
    / "centaur_ctr"
    / "testdata"
)

SYNTHETIC = sorted(TESTDATA.glob("synthetic-*.json"))
REAL = sorted(TESTDATA.glob("real-*.json"))
ALL_FIXTURES = SYNTHETIC + REAL


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_Fixture가_존재한다():
    assert SYNTHETIC, "python scripts/capture_fixtures.py 로 생성한다"


@pytest.mark.parametrize("path", ALL_FIXTURES, ids=lambda p: p.stem)
def test_모든_Fixture를_파싱하고_변환한다(path: Path):
    soh = parse_soh(_load(path))
    assert soh.channels

    result = map_soh(soh)
    assert result.samples

    for sample in result.samples:
        validate_sample(sample)


@pytest.mark.parametrize("path", ALL_FIXTURES, ids=lambda p: p.stem)
def test_옮기지_못한_채널이_없다(path: Path):
    """새 채널이 조용히 버려지는 것을 막는다. 실장비 Fixture 를 넣었을 때
    여기서 실패하면 Mapping 을 보강해야 한다는 신호다."""
    soh = parse_soh(_load(path))
    leftover = unknown_channels(soh, map_soh(soh))
    assert leftover == (), f"{path.name}: 표준 Metric 으로 옮기지 못한 채널 {leftover}"


@pytest.mark.parametrize("path", ALL_FIXTURES, ids=lambda p: p.stem)
def test_기능_탐지가_예외_없이_끝난다(path: Path):
    soh = parse_soh(_load(path))
    report = capability_detector.detect(soh)
    assert report.states


def test_3채널_Fixture는_SensorB를_미지원으로_판정한다():
    path = TESTDATA / "synthetic-ctr3-normal.json"
    soh = parse_soh(_load(path))
    report = capability_detector.detect(soh, expected_channel_count=3)
    assert report.state_of("sensor.status", "B") is SupportState.UNSUPPORTED


def test_모르는_상태_Fixture는_보강_대상을_남긴다():
    path = TESTDATA / "synthetic-ctr6-unknown-status.json"
    result = map_soh(parse_soh(_load(path)))
    assert result.unmapped_values, "모르는 상태 문자열이 UNKNOWN 으로 떨어지며 원문을 남겨야 한다"


def _health_channels(names: set[str]) -> set[str]:
    """표준 Metric 감시 대상만 남긴다. 패킷 스트림 등 운영 채널은 대조에서 뺀다."""
    return {name for name in names if not is_acknowledged_unmapped(name)}


# 6채널 가상 장비는 Sensor B Mass Position(voltage#_4..6) 을 낸다.
# 실응답 4.9.2 Centaur-6 는 status#_1 이 있어도 voltage#_4..6 이 없다.
_MOCK_ONLY_ALLOWED = frozenset(
    {
        "digitizer/sensor/soh/voltage#_4",
        "digitizer/sensor/soh/voltage#_5",
        "digitizer/sensor/soh/voltage#_6",
    }
)


@pytest.mark.skipif(not REAL, reason="실장비 Fixture 가 아직 없다 (조사 항목 M-1.2)")
def test_실응답과_가상서버_기준선이_어긋나지_않는다():
    """가상 서버가 상상 속 형식으로 굳는 것을 막는 장치.

    실장비 Fixture 가 들어오면 켜진다. 가상 서버 기준선에 없는 건강 채널이 실응답에
    있으면 가상 서버를 고쳐야 하고, 반대면 우리가 만들어 낸 채널이라는 뜻이다.
    """
    baseline = _health_channels(
        set(parse_soh(_load(TESTDATA / "synthetic-ctr6-normal.json")).channels)
    )

    for path in REAL:
        actual = _health_channels(set(parse_soh(_load(path)).channels))
        missing_in_mock = actual - baseline
        invented_by_mock = baseline - actual - _MOCK_ONLY_ALLOWED
        assert not missing_in_mock, (
            f"{path.name}: 실장비에 있으나 가상 서버가 내지 않는 채널 {sorted(missing_in_mock)}"
        )
        assert not invented_by_mock, (
            f"{path.name}: 가상 서버만 내는 채널 {sorted(invented_by_mock)}. "
            "우리가 만들어 낸 채널이라는 뜻이다"
        )


def test_실응답_야간은_Mass_Position과_전원을_옮긴다():
    path = TESTDATA / "real-ctr6-normal.json"
    if not path.exists():
        pytest.skip("실장비 Fixture 가 아직 없다")
    soh = parse_soh(_load(path))
    assert soh.instrument_id == "centaur-6__0000"
    result = map_soh(soh)
    samples = {(s.metric_key, tuple(sorted(s.dimensions.items()))): s for s in result.samples}
    assert samples[("sensor.mass_position_v", (("axis", "W"), ("sensor_port", "A")))].value_float == pytest.approx(0.2971)
    assert samples[("sensor.mass_position_v", (("axis", "V"), ("sensor_port", "A")))].value_float == pytest.approx(0.1617)
    assert samples[("sensor.mass_position_v", (("axis", "U"), ("sensor_port", "A")))].value_float == pytest.approx(-0.3091)
    assert samples[("power.input_voltage_v", ())].value_float == pytest.approx(14.204, abs=0.001)
    assert samples[("device.temperature_c", ())].value_float == pytest.approx(34.34, abs=0.01)
    assert samples[("timing.status", ())].value_status is Severity.OK
    assert samples[("gnss.satellite_count", ())].value_int == 9
    assert "gnss.antenna_status" not in {s.metric_key for s in result.samples}
    assert unknown_channels(soh, result) == ()


def test_실응답_Sensor_B는_상태만_있고_질량은_확인_불가():
    """status#_1 은 ok 인데 voltage#_4..6 이 없다. 없는 기능으로 단정하지 않는다."""
    path = TESTDATA / "real-ctr6-normal.json"
    if not path.exists():
        pytest.skip("실장비 Fixture 가 아직 없다")
    soh = parse_soh(_load(path))
    report = capability_detector.detect(soh, expected_channel_count=6)
    assert report.state_of("sensor.status", "B") is SupportState.SUPPORTED_ENABLED
    assert report.state_of("sensor.mass_position", "A") is SupportState.SUPPORTED_ENABLED
    assert report.state_of("sensor.mass_position", "B") is SupportState.UNKNOWN
