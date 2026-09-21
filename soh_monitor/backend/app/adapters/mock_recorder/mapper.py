"""ACME 원본 읽기값 → 표준 Metric.

Centaur 와 다른 점
  * 전압은 mV, 전류는 mA, 비율은 0~1, 상태는 GOOD/WARN/BAD
  * 센서·외부 SOH·아카이브 채널이 없다. 없는 값을 0 으로 채우지 않는다.
"""
from __future__ import annotations

from typing import Any

from app.domain.enums import SupportState
from app.domain.models import MetricSample
from app.metrics.status import load_status_mappings

from .parser import ParsedSoh

ADAPTER_KEY = "acme.mock.recorder"


class MappingResult:
    def __init__(self) -> None:
        self.samples: list[MetricSample] = []
        self.unmapped_values: dict[str, str] = {}
        self.consumed: set[str] = set()

    def add(self, sample: MetricSample, *source_channels: str) -> None:
        self.samples.append(sample)
        self.consumed.update(source_channels)


def _to_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _scale(units: str | None, value: float, *, kind: str) -> float:
    """응답 단위를 우선한다. 상수로 나누면 펌웨어가 단위를 바꿀 때 조용히 틀린다."""
    normalized = (units or "").strip().lower()
    if kind == "voltage":
        if normalized in {"v", "volts"}:
            return value
        if normalized in {"uv", "microvolts"}:
            return value / 1_000_000.0
        return value / 1000.0  # 기본 mV
    if kind == "current":
        if normalized in {"a", "amps", "amperes"}:
            return value
        return value / 1000.0  # 기본 mA
    if kind == "ratio":
        if normalized in {"percent", "%", "pct"}:
            return value
        return value * 100.0  # 기본 0~1
    return value


def _status(result: MappingResult, soh: ParsedSoh, channel: str, metric_key: str) -> None:
    if not soh.has(channel):
        return
    raw = soh.raw(channel)
    resolution = load_status_mappings().resolve(ADAPTER_KEY, metric_key, raw)
    if not resolution.mapped and resolution.raw_value is not None:
        result.unmapped_values[metric_key] = resolution.raw_value
    result.add(
        MetricSample(
            metric_key=metric_key,
            value_status=resolution.severity,
            raw_value=resolution.raw_value,
            support_state=SupportState.SUPPORTED_ENABLED,
        ),
        channel,
    )


def _float(
    result: MappingResult,
    soh: ParsedSoh,
    channel: str,
    metric_key: str,
    *,
    kind: str,
    digits: int,
) -> float | None:
    if not soh.has(channel):
        return None
    raw = soh.raw(channel)
    number = _to_float(raw)
    if number is None:
        result.add(
            MetricSample(
                metric_key=metric_key,
                support_state=SupportState.UNKNOWN,
                raw_value=str(raw),
            ),
            channel,
        )
        return None
    converted = round(_scale(soh.units(channel), number, kind=kind), digits)
    result.add(
        MetricSample(
            metric_key=metric_key,
            value_float=converted,
            support_state=SupportState.SUPPORTED_ENABLED,
        ),
        channel,
    )
    return converted


def map_soh(soh: ParsedSoh) -> MappingResult:
    result = MappingResult()

    _status(result, soh, "sys.health", "device.overall_status")

    if soh.has("fw.rev"):
        result.add(
            MetricSample(metric_key="device.firmware_version", value_text=str(soh.raw("fw.rev"))),
            "fw.rev",
        )

    _float(result, soh, "temp.celsius", "device.temperature_c", kind="temperature", digits=2)

    voltage = _float(result, soh, "psu.millivolts", "power.input_voltage_v", kind="voltage", digits=3)
    current = _float(result, soh, "psu.milliamp", "power.current_a", kind="current", digits=4)
    if voltage is not None and current is not None:
        result.add(MetricSample(metric_key="power.consumption_w", value_float=round(voltage * current, 3)))

    _status(result, soh, "clk.state", "timing.status")
    _float(result, soh, "clk.quality", "timing.quality_percent", kind="ratio", digits=1)

    if soh.has("sat.count"):
        number = _to_float(soh.raw("sat.count"))
        if number is None:
            result.add(
                MetricSample(
                    metric_key="gnss.satellite_count",
                    support_state=SupportState.UNKNOWN,
                    raw_value=str(soh.raw("sat.count")),
                ),
                "sat.count",
            )
        else:
            result.add(
                MetricSample(metric_key="gnss.satellite_count", value_int=int(number)),
                "sat.count",
            )

    _float(result, soh, "disk.used_ratio", "storage.used_percent", kind="ratio", digits=1)
    _status(result, soh, "disk.record", "storage.recording_status")

    return result


def unknown_channels(soh: ParsedSoh, result: MappingResult) -> tuple[str, ...]:
    return tuple(sorted(set(soh.readings) - result.consumed))
