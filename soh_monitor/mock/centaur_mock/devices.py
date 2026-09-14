"""가상 장비 레지스트리.

한 프로세스가 여러 대를 흉내낸다. 다만 기록계마다 IP 가 다르다는 점이 등록·수집 경로의
핵심이므로, 개발 Compose 에서는 장비마다 네트워크 별칭을 따로 주어 서로 다른 주소로
접근하게 한다. 이 파일은 그 뒤에서 "어떤 장비인가" 만 들고 있다.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path

import yaml

from .envelope import EnvelopeShape
from .scenarios import PayloadScenario, TransportScenario

PROFILE_DIR = Path(__file__).resolve().parent / "profiles"


@dataclass(frozen=True)
class VirtualDevice:
    instrument_id: str
    station_code: str
    model: str
    firmware_version: str
    serial_number: str
    channel_count: int = 6
    has_removable_slot: bool = True
    external_soh_channels: int = 3
    has_gnss: bool = True
    payload_scenario: PayloadScenario = PayloadScenario.NORMAL
    transport_scenario: TransportScenario = TransportScenario.OK
    envelope_shape: EnvelopeShape = EnvelopeShape.CHANNEL_LIST
    latency_ms: int = 0
    requires_auth: bool = False
    password: str = "centaur"
    username: str = "admin"
    value_overrides: dict[str, object] = field(default_factory=dict)

    @property
    def sensor_ports(self) -> tuple[int, ...]:
        """장비가 실제로 가진 센서 포트 번호. 3채널 모델은 포트 0 뿐이다."""
        if self.payload_scenario is PayloadScenario.THREE_CHANNEL or self.channel_count <= 3:
            return (0,)
        return (0, 1)

    @property
    def effective_removable_slot(self) -> bool:
        if self.payload_scenario is PayloadScenario.SLOT_ABSENT:
            return False
        return self.has_removable_slot

    @property
    def effective_external_soh_channels(self) -> int:
        if self.payload_scenario is PayloadScenario.NO_EXTERNAL_SOH:
            return 0
        return self.external_soh_channels

    @property
    def reports_mass_position(self) -> bool:
        return self.payload_scenario is not PayloadScenario.NO_MASS_POSITION


class DeviceRegistry:
    def __init__(self, devices: list[VirtualDevice] | None = None) -> None:
        self._devices: dict[str, VirtualDevice] = {}
        self._initial: dict[str, VirtualDevice] = {}
        self._default_id: str | None = None
        for device in devices or []:
            self.add(device)

    def add(self, device: VirtualDevice) -> None:
        self._devices[device.instrument_id] = device
        self._initial[device.instrument_id] = device
        if self._default_id is None:
            self._default_id = device.instrument_id

    def get(self, instrument_id: str | None) -> VirtualDevice | None:
        """instrumentId 미지정이면 자기 자신을 보고한다 (매뉴얼 7.4 절 동작)."""
        if instrument_id is None or instrument_id == "":
            if self._default_id is None:
                return None
            return self._devices[self._default_id]
        return self._devices.get(instrument_id)

    def all(self) -> tuple[VirtualDevice, ...]:
        return tuple(self._devices.values())

    def update(self, instrument_id: str, **changes: object) -> VirtualDevice:
        device = self._devices[instrument_id]
        updated = replace(device, **changes)  # type: ignore[arg-type]
        self._devices[instrument_id] = updated
        return updated

    def reset(self) -> None:
        self._devices = dict(self._initial)

    def __len__(self) -> int:
        return len(self._devices)


def _device_from_entry(entry: dict) -> VirtualDevice:
    return VirtualDevice(
        instrument_id=entry["instrumentId"],
        station_code=entry.get("stationCode", entry["instrumentId"]),
        model=entry.get("model", "CTR4-6S"),
        firmware_version=entry.get("firmware", "3.2.8"),
        serial_number=entry.get("serial", entry["instrumentId"].split("_")[-1]),
        channel_count=int(entry.get("channelCount", 6)),
        has_removable_slot=bool(entry.get("removableSlot", True)),
        external_soh_channels=int(entry.get("externalSohChannels", 3)),
        has_gnss=bool(entry.get("gnss", True)),
        payload_scenario=PayloadScenario(entry.get("payloadScenario", "NORMAL")),
        transport_scenario=TransportScenario(entry.get("transportScenario", "OK")),
        envelope_shape=EnvelopeShape(entry.get("envelopeShape", "channel_list")),
        latency_ms=int(entry.get("latencyMs", 0)),
        requires_auth=bool(entry.get("requiresAuth", False)),
        password=entry.get("password", "centaur"),
        username=entry.get("username", "admin"),
    )


def load_fleet(name: str = "fleet") -> DeviceRegistry:
    """가상 관측소 묶음을 파일에서 읽는다.

    개발용 소수와 부하 시험용 다수를 같은 정의 형식으로 쓴다.
    """
    path = PROFILE_DIR / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"가상 관측소 묶음 파일이 없다: {path}")

    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    devices = [_device_from_entry(entry) for entry in raw.get("devices", [])]
    if not devices:
        raise ValueError(f"{path} 에 장비가 하나도 없다")
    return DeviceRegistry(devices)


def generated_fleet(
    count: int,
    *,
    slow_ratio: float = 0.0,
    prefix: str = "centaur-6__",
) -> DeviceRegistry:
    """부하 시험용 장비를 즉석에서 만든다 (M10.3).

    `slow_ratio` 만큼을 느린 장비로 만든다. 느린 장비가 전체 수집을 지연시키지 않는지
    확인하는 것이 목적이다.
    """
    devices: list[VirtualDevice] = []
    slow_every = int(1 / slow_ratio) if slow_ratio > 0 else 0
    for index in range(1, count + 1):
        slow = slow_every > 0 and index % slow_every == 0
        devices.append(
            VirtualDevice(
                instrument_id=f"{prefix}{index:04d}",
                station_code=f"L{index:03d}",
                model="CTR4-6S" if index % 3 else "CTR4-3S",
                firmware_version="3.2.8",
                serial_number=f"{index:04d}",
                channel_count=6 if index % 3 else 3,
                payload_scenario=(
                    PayloadScenario.THREE_CHANNEL if index % 3 == 0 else PayloadScenario.NORMAL
                ),
                transport_scenario=(
                    TransportScenario.SLOW_RESPONSE if slow else TransportScenario.OK
                ),
                latency_ms=3000 if slow else 0,
            )
        )
    return DeviceRegistry(devices)
