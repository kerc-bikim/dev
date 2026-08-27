"""Centaur CTR 기능 탐지.

목적은 하나다. "장비에 그 기능이 없다"와 "수집에 실패해서 모른다"를 구분해, 없는 기능이
장애로 집계되지 않게 하는 것.

판정 근거는 응답에 그 채널이 있는지와 장비 식별정보(3채널/6채널)다. 모델명은 SOH API 가
주지 않으므로 채널 존재 여부를 우선한다.
"""
from __future__ import annotations

from app.domain.enums import SupportState
from app.domain.models import CapabilityReport, dimensioned_capability

from .mapper import PORT_NAMES
from .parser import ParsedSoh

# 채널이 있으면 그 기능이 활성이라고 본다.
_CHANNEL_CAPABILITIES: dict[str, tuple[str, ...]] = {
    "device.overall_status": ("instrumentStatus",),
    "device.configuration_status": ("config/commitState",),
    "device.firmware_status": ("instrument/systemInfo/firmwareStatus", "systemSoftwareVersion"),
    "device.temperature": ("temperature",),
    "power.input_voltage": ("powerSupply/voltage",),
    "power.current": ("system/current",),
    "timing.status": ("timeStatus", "timing/phaseLock"),
    "timing.quality": ("timing/timeQuality", "timing/timeError", "timing/timeUncertainty"),
    "gnss.receiver": ("gps/numberOfSatellites", "instrument/earthLocation"),
    "storage.internal": ("controller/store/storePercentageUsed", "controller/store/storeRecordingStatus"),
    "storage.removable": ("media/status/removableSD", "media/freeSpace/removableSD"),
    "archive.continuous": ("dataArchive/status",),
    "archive.event": ("dataArchive/status/events",),
}


def detect(soh: ParsedSoh, *, expected_channel_count: int | None = None) -> CapabilityReport:
    states: dict[str, SupportState] = {}

    for capability_key, channels in _CHANNEL_CAPABILITIES.items():
        present = any(soh.has(channel) for channel in channels)
        states[capability_key] = (
            SupportState.SUPPORTED_ENABLED if present else SupportState.UNSUPPORTED
        )

    # 외부 SOH. CTR2 이상만 갖고 있으며, 채널 수도 모델에 따라 다르다.
    external_channels = soh.names_with_prefix("externalSoh/voltage#_")
    states["external_soh.analog"] = (
        SupportState.SUPPORTED_ENABLED if external_channels else SupportState.UNSUPPORTED
    )
    for channel_number in (1, 2, 3):
        key = dimensioned_capability("external_soh.analog", f"EX{channel_number}")
        states[key] = (
            SupportState.SUPPORTED_ENABLED
            if soh.has(f"externalSoh/voltage#_{channel_number}")
            else SupportState.UNSUPPORTED
        )

    # 센서 포트. 3채널 모델은 Sensor B 가 아예 없다. 그것을 장애로 세면 안 된다.
    #
    # 판정을 두 단계로 한다.
    #   1) 포트 자체가 있는가 — 채널이 하나라도 오면 있다고 본다.
    #   2) 포트가 있는데 특정 채널만 없다면 그것은 '미지원' 이 아니라 '확인 불가' 다.
    #      펌웨어가 그 채널을 빼거나 응답이 일부 누락된 상황이므로, 없는 기능으로 단정하면
    #      실제 이상을 감시에서 빼 버린다.
    for port, port_name in PORT_NAMES.items():
        has_status = soh.has(f"digitizer/sensor/status#_{port}")
        has_mass = any(
            soh.has(f"digitizer/sensor/massPosition#_{port}_{axis}") for axis in (1, 2, 3)
        )
        has_control = soh.has(f"sensor/controlLines/state#_{port}")
        port_exists = has_status or has_mass or has_control

        if port_exists:
            missing_state = SupportState.UNKNOWN
        elif expected_channel_count is not None and expected_channel_count > 3 and port == 1:
            # 장비가 6채널이라고 알려 왔는데 포트 정보가 통째로 없다.
            # '없는 것' 이 아니라 '모르는 것' 이다.
            missing_state = SupportState.UNKNOWN
        else:
            missing_state = SupportState.UNSUPPORTED

        for capability_key, present in (
            ("sensor.status", has_status),
            ("sensor.control_lines", has_control),
            ("sensor.mass_position", has_mass),
        ):
            states[dimensioned_capability(capability_key, port_name)] = (
                SupportState.SUPPORTED_ENABLED if present else missing_state
            )

    for capability_key in ("sensor.status", "sensor.control_lines", "sensor.mass_position"):
        any_port = any(
            states.get(dimensioned_capability(capability_key, port_name))
            is SupportState.SUPPORTED_ENABLED
            for port_name in PORT_NAMES.values()
        )
        states[capability_key] = (
            SupportState.SUPPORTED_ENABLED if any_port else SupportState.UNSUPPORTED
        )

    # 기상 센서 연동은 SOH API 채널로 확인되지 않는다. 확정할 수 없으면 UNKNOWN 이다.
    states["environment.weather_station"] = SupportState.UNKNOWN

    # 데이터 연속성 검사는 기록계 기능이 아니라 데이터 서버 설정에 달려 있다.
    states["acquisition.data_check"] = SupportState.UNKNOWN

    states["vendor.nanometrics.centaur"] = SupportState.SUPPORTED_ENABLED

    return CapabilityReport(states=states)
