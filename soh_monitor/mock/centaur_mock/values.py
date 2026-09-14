"""가상 장비의 SOH 채널 값 생성.

Fixture 를 그대로 재생하면 모든 값이 고정되어 임계값·Hysteresis·다운샘플링을 시험할 수
없다. 그래서 기준선 위에 시간에 따른 변화를 얹는다.

난수를 쓰지 않고 장비 ID 와 시각의 결정적 함수로 만든다. 같은 장비·같은 초에는 항상 같은
값이 나와야 테스트가 재현된다.

값의 단위는 실장비 그대로다. 외부 SOH 와 Mass Position 은 마이크로볼트, 여유 공간은
바이트, 온도는 섭씨다. 단위 변환은 Adapter 의 책임이며 여기서 미리 다듬지 않는다.
"""
from __future__ import annotations

import hashlib
import math
from datetime import datetime, timedelta, timezone
from typing import Any

from .devices import VirtualDevice
from .scenarios import PayloadScenario

_GIGABYTE = 1024**3


def _seed(instrument_id: str) -> int:
    digest = hashlib.sha256(instrument_id.encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big")


def _wave(seed: int, moment: datetime, period_seconds: float, amplitude: float) -> float:
    """장비별로 위상이 다른 결정적 진동."""
    phase = (seed % 1000) / 1000 * 2 * math.pi
    elapsed = moment.timestamp()
    return amplitude * math.sin(2 * math.pi * elapsed / period_seconds + phase)


def _iso(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def soh_channels(device: VirtualDevice, moment: datetime) -> dict[str, Any]:
    """SOH 채널 이름 → 원값.

    채널 이름의 근거는 Centaur User Guide 17935R10 7.4 절 SOH channels 표다.
    massPosition 채널 이름만 추정이며 M-1.3 에서 확정한다 (envelope.py 주석 참고).
    """
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    seed = _seed(device.instrument_id)
    scenario = device.payload_scenario

    channels: dict[str, Any] = {}

    # ---------------------------------------------------------------- 장비
    channels["instrumentStatus"] = "ok"
    channels["config/commitState"] = "committed"
    channels["instrument/systemInfo/firmwareStatus"] = "ok"
    channels["systemSoftwareVersion"] = device.firmware_version

    # 내부 온도. 일주기 변동을 준다.
    channels["temperature"] = round(28.0 + _wave(seed, moment, 86400, 5.0), 2)

    # ---------------------------------------------------------------- 전원
    # 배터리 소모를 흉내내 아주 완만히 내려간다. 주의→장애 전이를 만들 수 있게 한다.
    hours = (moment - moment.replace(hour=0, minute=0, second=0, microsecond=0)).total_seconds() / 3600
    channels["powerSupply/voltage"] = round(12.9 - hours * 0.02 + _wave(seed, moment, 900, 0.05), 3)
    channels["system/current"] = round(0.36 + _wave(seed, moment, 600, 0.02), 4)

    # ---------------------------------------------------------------- 시각·GNSS
    channels["timeStatus"] = "time ok"
    channels["timing/phaseLock"] = "fine lock"
    channels["timing/timeQuality"] = 100
    channels["timing/timeError"] = int(400 + _wave(seed, moment, 300, 250))
    channels["timing/timeUncertainty"] = int(1200 + _wave(seed, moment, 1800, 400))
    channels["timing/lastLockTime"] = _iso(moment - timedelta(seconds=30))

    if device.has_gnss:
        # Duty cycle 운용을 흉내내 주기적으로 위성 수가 줄어드는 구간을 만든다.
        # 이 구간만으로 장애를 만들지 않는 판정을 시험할 수 있다.
        channels["gps/numberOfSatellites"] = max(0, int(9 + _wave(seed, moment, 3600, 3)))
        channels["instrument/earthLocation"] = {
            "latitude": round(37.56 + (seed % 100) / 1000, 5),
            "longitude": round(126.98 + (seed % 97) / 1000, 5),
            "elevation": round(45.0 + (seed % 40), 1),
        }

    # ---------------------------------------------------------------- 저장소
    # 사용률이 올라가다 wrapping 되는 순환.
    channels["controller/store/storePercentageUsed"] = round(
        40 + (moment.timestamp() % 86400) / 86400 * 30, 1
    )
    channels["controller/store/storeRecordingStatus"] = "recording"
    channels["dataArchive/status"] = "ok"
    channels["dataArchive/status/events"] = "ok"

    if device.effective_removable_slot:
        channels["media/status/removableSD"] = "ok"
        channels["media/freeSpace/removableSD"] = int(24 * _GIGABYTE - (seed % 1000) * 1024)

    # ---------------------------------------------------------------- 센서
    for port in device.sensor_ports:
        channels[f"digitizer/sensor/status#_{port}"] = "ok"
        channels[f"sensor/controlLines/state#_{port}"] = "expected"
        if not device.reports_mass_position:
            continue
        for axis in (1, 2, 3):
            # Mass Position 은 매우 느리게 드리프트한다. 갑자기 기울어도 한동안 정상으로
            # 보이는 실제 특성을 반영한다.
            drift = _wave(seed + port * 7 + axis, moment, 21600, 0.35)
            channels[f"digitizer/sensor/massPosition#_{port}_{axis}"] = int(drift * 1_000_000)

    # ---------------------------------------------------------------- 외부 SOH
    for channel in range(1, device.effective_external_soh_channels + 1):
        base = 1.2 + channel * 0.4
        value = base + _wave(seed + channel, moment, 1200, 0.08)
        channels[f"externalSoh/voltage#_{channel}"] = int(value * 1_000_000)

    _apply_payload_scenario(channels, device, scenario, moment, seed)
    channels.update(device.value_overrides)
    return channels


def _apply_payload_scenario(
    channels: dict[str, Any],
    device: VirtualDevice,
    scenario: PayloadScenario,
    moment: datetime,
    seed: int,
) -> None:
    """장비가 이상을 보고하는 상황을 얹는다."""
    if scenario is PayloadScenario.GPS_UNLOCKED:
        channels["timeStatus"] = "free running"
        channels["timing/phaseLock"] = "no lock"
        channels["timing/timeQuality"] = 45
        channels["timing/timeError"] = 0
        channels["timing/timeUncertainty"] = 850_000
        channels["gps/numberOfSatellites"] = 0
        channels["timing/lastLockTime"] = _iso(moment - timedelta(hours=6))
        channels["instrumentStatus"] = "warning"

    elif scenario is PayloadScenario.LOW_VOLTAGE:
        channels["powerSupply/voltage"] = round(11.1 + _wave(seed, moment, 900, 0.08), 3)
        channels["system/current"] = 0.31
        channels["instrumentStatus"] = "warning"

    elif scenario is PayloadScenario.SENSOR_ERROR:
        port = device.sensor_ports[0]
        channels[f"digitizer/sensor/status#_{port}"] = "error"
        channels["instrumentStatus"] = "error"
        if device.reports_mass_position:
            channels[f"digitizer/sensor/massPosition#_{port}_1"] = 3_800_000
            channels[f"digitizer/sensor/massPosition#_{port}_2"] = -4_100_000

    elif scenario is PayloadScenario.STORE_FULL:
        channels["controller/store/storePercentageUsed"] = 97.4
        channels["controller/store/storeRecordingStatus"] = "not enough space"
        channels["dataArchive/status"] = "media full"
        channels["instrumentStatus"] = "error"

    elif scenario is PayloadScenario.NO_SD_CARD:
        # 슬롯은 있으나 카드가 없다. 매뉴얼 7.4 절: 미장착이면 여유 공간이 -1 이다.
        channels["media/status/removableSD"] = "not present"
        channels["media/freeSpace/removableSD"] = -1
        channels["dataArchive/status"] = "media not present"
        channels["instrumentStatus"] = "warning"

    elif scenario is PayloadScenario.UNCOMMITTED_CONFIG:
        channels["config/commitState"] = "uncommitted"
        channels["instrumentStatus"] = "warning"

    elif scenario is PayloadScenario.TESTCODE_FIRMWARE:
        channels["instrument/systemInfo/firmwareStatus"] = "testcode"
        channels["instrumentStatus"] = "warning"

    elif scenario is PayloadScenario.UNKNOWN_STATUS_STRING:
        # 새 펌웨어가 새 문자열을 내보내는 상황. 정상으로 오인하면 장애를 놓친다.
        channels["timeStatus"] = "quantum drift compensating"
        channels["controller/store/storeRecordingStatus"] = "defragmenting"
        channels["instrumentStatus"] = "nominal"

    elif scenario is PayloadScenario.MISSING_FIELDS:
        for name in (
            "temperature",
            "controller/store/storePercentageUsed",
            "timing/timeUncertainty",
            "digitizer/sensor/status#_1",
        ):
            channels.pop(name, None)

    elif scenario is PayloadScenario.OLD_FIRMWARE:
        # 예전 형태: 상태를 수치 코드로 준다 (8.2 절 GST/GPL/GAN 코드계).
        channels["systemSoftwareVersion"] = "2.9.4"
        channels["timeStatus"] = 2
        channels["timing/phaseLock"] = 2
        channels["gnss/antennaStatus"] = 0
