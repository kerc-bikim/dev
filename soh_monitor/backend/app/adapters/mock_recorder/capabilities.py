"""ACME Mock Recorder 기능 탐지.

이 가상 제조사는 센서·외장 SD·외부 SOH·아카이브가 없다.
없는 기능을 UNKNOWN 으로 두면 화면이 빈 탭을 장애처럼 보여 준다. 그래서
채널이 없으면 UNSUPPORTED 로 못 박는다.
"""
from __future__ import annotations

from app.domain.enums import SupportState
from app.domain.models import CapabilityReport

from .parser import ParsedSoh

_PRESENT: dict[str, tuple[str, ...]] = {
    "device.overall_status": ("sys.health",),
    "device.firmware_status": ("fw.rev",),
    "device.temperature": ("temp.celsius",),
    "power.input_voltage": ("psu.millivolts",),
    "power.current": ("psu.milliamp",),
    "timing.status": ("clk.state",),
    "timing.quality": ("clk.quality",),
    "gnss.receiver": ("sat.count",),
    "storage.internal": ("disk.used_ratio", "disk.record"),
}

_ABSENT = (
    "device.configuration_status",
    "sensor.status",
    "sensor.control_lines",
    "sensor.mass_position",
    "storage.removable",
    "archive.continuous",
    "archive.event",
    "external_soh.analog",
    "environment.weather_station",
)


def detect(soh: ParsedSoh) -> CapabilityReport:
    states: dict[str, SupportState] = {}
    for capability_key, channels in _PRESENT.items():
        states[capability_key] = (
            SupportState.SUPPORTED_ENABLED
            if any(soh.has(channel) for channel in channels)
            else SupportState.UNSUPPORTED
        )
    for capability_key in _ABSENT:
        states[capability_key] = SupportState.UNSUPPORTED
    # 파형 연속성은 기록계 기능이 아니다.
    states["acquisition.data_check"] = SupportState.UNKNOWN
    return CapabilityReport(states=states)
