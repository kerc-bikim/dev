"""Centaur CTR 원본 채널 → 표준 Metric 변환.

이 파일이 제조사 고유 지식이 존재하는 유일한 자리다(파서·클라이언트와 함께).
여기서 나간 결과는 어느 제조사에서 왔는지 알 수 없어야 한다.

원칙
  * 모르는 상태 문자열은 OK 가 아니라 UNKNOWN 으로 떨어지고 원문을 남긴다.
  * 값이 없으면 0 으로 채우지 않고 UNSUPPORTED / UNKNOWN 으로 표시한다.
  * 단위 변환은 응답이 알려 준 단위를 우선하고, 없으면 매뉴얼 기준 단위를 쓴다.

근거: Centaur User Guide 17935R10 — 7.4 State of Health API(SOH channels 표),
8.2 SOH channels in Steim compressed formats(단위·수치 코드).
"""
from __future__ import annotations

from typing import Any

from app.domain.enums import Severity, SupportState
from app.domain.models import MetricSample
from app.metrics.status import load_status_mappings

from .parser import ParsedSoh, parse_timestamp

ADAPTER_KEY = "nanometrics.centaur.ctr"

# 센서 포트 번호 → 표준 포트 이름.
PORT_NAMES = {0: "A", 1: "B"}

# Mass Position 축 순서. 매뉴얼 8.2절: Nanometrics 지진계는 VM1=W, VM2=V, VM3=U 다.
# SOH API 의 축 인덱스도 같은 순서를 따른다고 보고 매핑하며, M-1.3 에서 확인한다.
AXIS_NAMES = {1: "W", 2: "V", 3: "U"}

# 마이크로 단위로 오는 채널. 매뉴얼 표기(microVolts)를 기준으로 한다.
_MICRO = 1_000_000.0


class MappingResult:
    """변환 결과 묶음."""

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


def _to_int(value: Any) -> int | None:
    number = _to_float(value)
    return None if number is None else int(number)


def _scale_for(units: str | None, default_divisor: float) -> float:
    """응답이 알려 준 단위를 우선해 나눗수를 정한다.

    같은 채널이 펌웨어에 따라 V 또는 mV 로 올 수 있다. 단위를 무시하고 상수로 나누면
    1000배 틀린 값이 조용히 적재된다.
    """
    if not units:
        return default_divisor
    normalized = units.strip().lower()
    if normalized in {"microvolts", "uv", "µv", "micro_volts"}:
        return _MICRO
    if normalized in {"millivolts", "mv"}:
        return 1000.0
    if normalized in {"volts", "v"}:
        return 1.0
    if normalized in {"milliamps", "ma"}:
        return 1000.0
    if normalized in {"amperes", "amps", "a"}:
        return 1.0
    if normalized in {"millidegreescelsius", "mdegc", "m°c"}:
        return 1000.0
    if normalized in {"degreescelsius", "degc", "°c", "c"}:
        return 1.0
    return default_divisor


def _status_sample(
    result: MappingResult,
    soh: ParsedSoh,
    channel: str,
    metric_key: str,
    *,
    dimensions: dict[str, str] | None = None,
) -> None:
    """상태 문자열·수치 코드를 표준 상태로 옮긴다."""
    if not soh.has(channel):
        return

    raw = soh.raw(channel)
    resolution = load_status_mappings().resolve(ADAPTER_KEY, metric_key, raw)
    if not resolution.mapped and resolution.raw_value is not None:
        # 새 펌웨어가 새 문자열을 내보낸 신호. 정상으로 오인하지 않고 보강 대상으로 남긴다.
        result.unmapped_values[metric_key] = resolution.raw_value

    result.add(
        MetricSample(
            metric_key=metric_key,
            dimensions=dimensions or {},
            value_status=resolution.severity,
            raw_value=resolution.raw_value,
            support_state=SupportState.SUPPORTED_ENABLED,
        ),
        channel,
    )


def _float_sample(
    result: MappingResult,
    soh: ParsedSoh,
    channel: str,
    metric_key: str,
    *,
    divisor: float = 1.0,
    unit_aware: bool = False,
    dimensions: dict[str, str] | None = None,
    digits: int | None = 4,
) -> float | None:
    if not soh.has(channel):
        return None

    raw = soh.raw(channel)
    number = _to_float(raw)
    if number is None:
        result.add(
            MetricSample(
                metric_key=metric_key,
                dimensions=dimensions or {},
                support_state=SupportState.UNKNOWN,
                raw_value=str(raw),
            ),
            channel,
        )
        return None

    effective = _scale_for(soh.units(channel), divisor) if unit_aware else divisor
    converted = number / effective
    if digits is not None:
        converted = round(converted, digits)

    result.add(
        MetricSample(
            metric_key=metric_key,
            dimensions=dimensions or {},
            value_float=converted,
            support_state=SupportState.SUPPORTED_ENABLED,
        ),
        channel,
    )
    return converted


def _int_sample(
    result: MappingResult,
    soh: ParsedSoh,
    channel: str,
    metric_key: str,
    *,
    dimensions: dict[str, str] | None = None,
    treat_negative_as_missing: bool = False,
) -> None:
    if not soh.has(channel):
        return

    raw = soh.raw(channel)
    number = _to_int(raw)
    if number is None:
        result.add(
            MetricSample(
                metric_key=metric_key,
                dimensions=dimensions or {},
                support_state=SupportState.UNKNOWN,
                raw_value=str(raw),
            ),
            channel,
        )
        return

    if treat_negative_as_missing and number < 0:
        # 매뉴얼 7.4절: 외장 SD 가 마운트되지 않으면 여유 공간이 -1 이다.
        # 슬롯은 있으므로 UNSUPPORTED 가 아니라 '값을 알 수 없음' 이다.
        result.add(
            MetricSample(
                metric_key=metric_key,
                dimensions=dimensions or {},
                support_state=SupportState.UNKNOWN,
                raw_value=str(raw),
            ),
            channel,
        )
        return

    result.add(
        MetricSample(
            metric_key=metric_key,
            dimensions=dimensions or {},
            value_int=number,
            support_state=SupportState.SUPPORTED_ENABLED,
        ),
        channel,
    )


def map_soh(soh: ParsedSoh) -> MappingResult:
    """파싱된 SOH 를 표준 Metric 샘플로 옮긴다."""
    result = MappingResult()

    # ---------------------------------------------------------------- 장비
    _status_sample(result, soh, "instrumentStatus", "device.overall_status")
    _status_sample(result, soh, "config/commitState", "device.configuration_status")
    _status_sample(
        result, soh, "instrument/systemInfo/firmwareStatus", "device.firmware_status"
    )

    if soh.has("systemSoftwareVersion"):
        result.add(
            MetricSample(
                metric_key="device.firmware_version",
                value_text=str(soh.raw("systemSoftwareVersion")),
            ),
            "systemSoftwareVersion",
        )

    _float_sample(
        result, soh, "temperature", "device.temperature_c", unit_aware=True, digits=2
    )

    # ---------------------------------------------------------------- 전원
    voltage = _float_sample(
        result, soh, "powerSupply/voltage", "power.input_voltage_v", unit_aware=True, digits=3
    )
    current = _float_sample(
        result, soh, "system/current", "power.current_a", unit_aware=True, digits=4
    )
    if voltage is not None and current is not None:
        result.add(
            MetricSample(
                metric_key="power.consumption_w",
                value_float=round(voltage * current, 3),
            )
        )

    # ---------------------------------------------------------------- 시각
    _status_sample(result, soh, "timeStatus", "timing.status")
    _status_sample(result, soh, "timing/phaseLock", "timing.phase_lock")
    _float_sample(result, soh, "timing/timeQuality", "timing.quality_percent", digits=1)
    _float_sample(result, soh, "timing/timeError", "timing.error_ns", digits=0)
    _float_sample(result, soh, "timing/timeUncertainty", "timing.uncertainty_ns", digits=0)

    if soh.has("timing/lastLockTime"):
        moment = parse_timestamp(soh.raw("timing/lastLockTime"))
        if moment is None:
            result.add(
                MetricSample(
                    metric_key="timing.last_lock_at",
                    support_state=SupportState.UNKNOWN,
                    raw_value=str(soh.raw("timing/lastLockTime")),
                ),
                "timing/lastLockTime",
            )
        else:
            result.add(
                MetricSample(metric_key="timing.last_lock_at", value_timestamp=moment),
                "timing/lastLockTime",
            )

    # ---------------------------------------------------------------- GNSS
    _int_sample(result, soh, "gps/numberOfSatellites", "gnss.satellite_count")
    _status_sample(result, soh, "gnss/antennaStatus", "gnss.antenna_status")

    location = soh.raw("instrument/earthLocation")
    if isinstance(location, dict):
        for key, metric_key, digits in (
            ("latitude", "gnss.latitude", 6),
            ("longitude", "gnss.longitude", 6),
            ("elevation", "gnss.elevation_m", 2),
        ):
            number = _to_float(location.get(key))
            if number is None:
                continue
            result.add(
                MetricSample(metric_key=metric_key, value_float=round(number, digits)),
                "instrument/earthLocation",
            )
        result.consumed.add("instrument/earthLocation")

    # ---------------------------------------------------------------- 센서
    for port, port_name in PORT_NAMES.items():
        _status_sample(
            result,
            soh,
            f"digitizer/sensor/status#_{port}",
            "sensor.status",
            dimensions={"sensor_port": port_name},
        )
        _status_sample(
            result,
            soh,
            f"sensor/controlLines/state#_{port}",
            "sensor.control_state",
            dimensions={"sensor_port": port_name},
        )
        for axis_index, axis_name in AXIS_NAMES.items():
            _float_sample(
                result,
                soh,
                f"digitizer/sensor/massPosition#_{port}_{axis_index}",
                "sensor.mass_position_v",
                divisor=_MICRO,
                unit_aware=True,
                dimensions={"sensor_port": port_name, "axis": axis_name},
                digits=4,
            )

    # ---------------------------------------------------------------- 저장소
    _float_sample(
        result,
        soh,
        "controller/store/storePercentageUsed",
        "storage.used_percent",
        digits=1,
    )
    _status_sample(
        result, soh, "controller/store/storeRecordingStatus", "storage.recording_status"
    )
    _status_sample(result, soh, "media/status/removableSD", "storage.sd_status")
    _int_sample(
        result,
        soh,
        "media/freeSpace/removableSD",
        "storage.sd_free_bytes",
        treat_negative_as_missing=True,
    )

    # ---------------------------------------------------------------- 아카이브
    _status_sample(result, soh, "dataArchive/status", "archive.continuous_status")
    _status_sample(result, soh, "dataArchive/status/events", "archive.event_status")

    # ---------------------------------------------------------------- 외부 SOH
    for channel_number in (1, 2, 3):
        _float_sample(
            result,
            soh,
            f"externalSoh/voltage#_{channel_number}",
            "external_soh.value",
            divisor=_MICRO,
            unit_aware=True,
            dimensions={"channel": f"EX{channel_number}"},
            digits=6,
        )

    return result


def unknown_channels(soh: ParsedSoh, result: MappingResult) -> tuple[str, ...]:
    """표준 Metric 으로 옮기지 못한 채널 이름.

    새 펌웨어가 채널을 추가했다는 신호다. 조용히 버리면 그 사실을 알 수 없다.
    """
    return tuple(sorted(set(soh.channels) - result.consumed))


def status_of(samples: list[MetricSample], metric_key: str) -> Severity | None:
    for sample in samples:
        if sample.metric_key == metric_key:
            return sample.value_status
    return None
