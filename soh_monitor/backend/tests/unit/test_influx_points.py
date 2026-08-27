"""InfluxDB 적재 형식 검증.

적재 형식이 조용히 어긋나면 Grafana 대시보드가 통째로 빈다. InfluxDB 를 띄우지 않고도
형식을 못 박아 두려는 시험이다.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.domain.enums import PollErrorCode, Severity, SupportState
from app.domain.models import MetricSample, PollResult
from app.repository.influx.points import (
    DeviceTags,
    build_points,
    poll_point,
    to_line_protocol,
)

OBSERVED_AT = datetime(2026, 8, 27, 3, 0, 0, tzinfo=timezone.utc)

TAGS = DeviceTags(
    device_id="d-1",
    station_id="s-1",
    station_code="A01",
    collection_mode="DIRECT",
    manufacturer="nanometrics",
    product_family="Centaur CTR",
    generation="ctr",
    model="CTR4-6S",
    region="R1",
)


def _result(samples: tuple[MetricSample, ...] = (), **changes) -> PollResult:
    defaults = dict(
        poll_id="poll-1",
        device_id="d-1",
        adapter_key="nanometrics.centaur.ctr",
        adapter_version="1.0",
        observed_at=OBSERVED_AT,
        success=True,
        samples=samples,
        latency_ms=42.5,
        http_status=200,
        payload_bytes=3298,
    )
    defaults.update(changes)
    return PollResult(**defaults)


def _by_measurement(points):
    return {point.measurement: point for point in points}


class Test공통Tag:
    def test_변동값은_Tag로_쓰지_않는다(self):
        """IP·펌웨어 버전을 Tag 로 쓰면 값이 바뀔 때 시계열이 둘로 갈라진다."""
        tags = TAGS.as_dict()
        assert "hostname" not in tags
        assert "ip_address" not in tags
        assert "firmware_version" not in tags

    def test_비어_있는_Tag는_붙이지_않는다(self):
        minimal = DeviceTags(
            device_id="d-2", station_id="s-2", station_code="B01", collection_mode="EDGE"
        )
        assert minimal.as_dict() == {
            "device_id": "d-2",
            "station_id": "s-2",
            "station_code": "B01",
            "collection_mode": "EDGE",
        }


class Test수집기록:
    def test_성공한_Poll(self):
        point = poll_point(_result(), TAGS, consecutive_failures=0)
        assert point.measurement == "recorder_poll"
        assert point.fields["reachable"] is True
        assert point.fields["latency_ms"] == 42.5
        assert point.fields["consecutive_failures"] == 0
        assert point.timestamp == OBSERVED_AT

    def test_실패한_Poll도_반드시_남는다(self):
        """실패를 남기지 않으면 '데이터 없음' 과 '장비 죽음' 을 구분할 수 없다."""
        result = _result(
            success=False,
            error_code=PollErrorCode.CONNECT_TIMEOUT,
            latency_ms=None,
            http_status=None,
            payload_bytes=None,
        )
        point = poll_point(result, TAGS, consecutive_failures=3)
        assert point.fields["reachable"] is False
        assert point.fields["error_code"] == "CONNECT_TIMEOUT"
        assert point.fields["consecutive_failures"] == 3
        assert "latency_ms" not in point.fields

    def test_샘플이_없어도_Poll_Point는_만든다(self):
        points = build_points(_result(success=False), TAGS)
        assert _by_measurement(points).keys() == {"recorder_poll"}


class Test값변환:
    def test_상태는_숫자와_문자열을_함께_적재한다(self):
        """숫자는 Grafana 알림·집계용, 문자열은 사람이 읽는 용도다."""
        samples = (
            MetricSample(metric_key="timing.status", value_status=Severity.WARNING),
        )
        point = _by_measurement(build_points(_result(samples), TAGS))["recorder_timing"]
        assert point.fields["status"] == 1
        assert point.fields["status_text"] == "WARNING"

    def test_실수와_정수와_참거짓(self):
        samples = (
            MetricSample(metric_key="power.input_voltage_v", value_float=12.6),
            MetricSample(metric_key="gnss.satellite_count", value_int=9),
            MetricSample(metric_key="acquisition.channel_active", value_bool=True,
                         dimensions={"channel": "HHZ"}),
        )
        points = _by_measurement(build_points(_result(samples), TAGS))
        assert points["recorder_power"].fields["input_voltage_v"] == 12.6
        assert points["recorder_gnss"].fields["satellite_count"] == 9
        assert points["recorder_acquisition"].fields["channel_active"] is True

    def test_문자열_Metric(self):
        samples = (MetricSample(metric_key="device.firmware_version", value_text="3.2.8"),)
        point = _by_measurement(build_points(_result(samples), TAGS))["recorder_device"]
        assert point.fields["firmware_version"] == "3.2.8"

    def test_시각_Metric은_epoch_초로_적재한다(self):
        moment = datetime(2026, 8, 27, 2, 59, 30, tzinfo=timezone.utc)
        samples = (MetricSample(metric_key="timing.last_lock_at", value_timestamp=moment),)
        point = _by_measurement(build_points(_result(samples), TAGS))["recorder_timing"]
        assert point.fields["last_lock_at"] == pytest.approx(moment.timestamp())


class Test차원:
    def test_차원은_Tag로_나간다(self):
        samples = (
            MetricSample(
                metric_key="sensor.mass_position_v",
                dimensions={"sensor_port": "A", "axis": "U"},
                value_float=0.31,
            ),
        )
        point = build_points(_result(samples), TAGS)[1]
        assert point.tags["sensor_port"] == "A"
        assert point.tags["axis"] == "U"

    def test_차원이_다르면_Point가_갈라진다(self):
        samples = tuple(
            MetricSample(
                metric_key="sensor.mass_position_v",
                dimensions={"sensor_port": "A", "axis": axis},
                value_float=value,
            )
            for axis, value in (("U", 0.1), ("V", 0.2), ("W", 0.3))
        )
        points = [p for p in build_points(_result(samples), TAGS) if p.measurement == "recorder_sensor"]
        assert len(points) == 3
        assert {p.tags["axis"] for p in points} == {"U", "V", "W"}

    def test_같은_measurement와_같은_Tag는_한_Point로_묶인다(self):
        """Point 수가 줄면 쓰기 비용과 저장 공간이 함께 줄어든다."""
        samples = (
            MetricSample(metric_key="power.input_voltage_v", value_float=12.6),
            MetricSample(metric_key="power.current_a", value_float=0.36),
            MetricSample(metric_key="power.consumption_w", value_float=4.54),
        )
        points = [p for p in build_points(_result(samples), TAGS) if p.measurement == "recorder_power"]
        assert len(points) == 1
        assert set(points[0].fields) == {"input_voltage_v", "current_a", "consumption_w"}


class Test값없음:
    def test_값이_없는_샘플은_적재하지_않는다(self):
        """없는 데이터를 0 으로 채우면 그래프가 거짓말을 한다."""
        samples = (
            MetricSample(
                metric_key="storage.sd_free_bytes",
                support_state=SupportState.UNKNOWN,
                raw_value="-1",
            ),
            MetricSample(
                metric_key="sensor.status",
                dimensions={"sensor_port": "B"},
                support_state=SupportState.UNSUPPORTED,
            ),
        )
        points = build_points(_result(samples), TAGS)
        assert _by_measurement(points).keys() == {"recorder_poll"}

    def test_카탈로그에_없는_Metric은_버린다(self):
        samples = (MetricSample(metric_key="power.imaginary", value_float=1.0),)
        points = build_points(_result(samples), TAGS)
        assert _by_measurement(points).keys() == {"recorder_poll"}


class Test제조사전용:
    def test_metric_key를_Tag로_둔다(self):
        samples = (
            MetricSample(
                metric_key="vendor.nanometrics.centaur.buffer_used_percent", value_float=100.0
            ),
        )
        point = _by_measurement(build_points(_result(samples), TAGS))["recorder_vendor_metric"]
        assert point.tags["metric_key"] == "vendor.nanometrics.centaur.buffer_used_percent"
        assert point.fields["value"] == 100.0

    def test_공통_measurement를_오염시키지_않는다(self):
        samples = (
            MetricSample(metric_key="power.input_voltage_v", value_float=12.6),
            MetricSample(
                metric_key="vendor.nanometrics.centaur.vco_control", value_float=32768.0
            ),
        )
        measurements = _by_measurement(build_points(_result(samples), TAGS)).keys()
        assert "recorder_vendor_metric" in measurements
        assert "recorder_power" in measurements


class TestLineProtocol:
    def test_형식(self):
        samples = (MetricSample(metric_key="power.input_voltage_v", value_float=12.6),)
        point = _by_measurement(build_points(_result(samples), TAGS))["recorder_power"]
        line = to_line_protocol(point)
        assert line.startswith("recorder_power,")
        assert "input_voltage_v=12.6" in line
        assert line.endswith(str(int(OBSERVED_AT.timestamp() * 1_000_000_000)))

    def test_정수와_참거짓과_문자열_표기(self):
        samples = (
            MetricSample(metric_key="gnss.satellite_count", value_int=9),
            MetricSample(metric_key="device.firmware_version", value_text="3.2.8"),
        )
        points = _by_measurement(build_points(_result(samples), TAGS))
        assert "satellite_count=9i" in to_line_protocol(points["recorder_gnss"])
        assert 'firmware_version="3.2.8"' in to_line_protocol(points["recorder_device"])
        assert "reachable=true" in to_line_protocol(points["recorder_poll"])


def test_관측시각을_기준으로_적재한다():
    """Edge 가 하루 뒤 올려도 원래 시각에 채워져야 한다."""
    late = datetime(2026, 8, 26, 3, 0, 0, tzinfo=timezone.utc)
    samples = (MetricSample(metric_key="power.input_voltage_v", value_float=12.1),)
    points = build_points(_result(samples, observed_at=late), TAGS)
    assert all(point.timestamp == late for point in points)
