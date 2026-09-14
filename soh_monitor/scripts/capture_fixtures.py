"""가상 서버 응답을 Fixture 로 떠 놓는다.

이 Fixture 는 **실장비 Fixture 가 아니다.** 파일명을 `synthetic-` 으로 시작해 구분한다.
실장비 응답을 확보하면 `real-` 로 시작하는 파일로 넣고(조사 항목 M-1.2), 그때부터
`test_fixture_divergence` 가 가상 서버 기준선과 실응답의 채널 집합을 대조한다.

사용법
    python scripts/capture_fixtures.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from mock.centaur_mock.devices import VirtualDevice  # noqa: E402
from mock.centaur_mock.envelope import UNITS, EnvelopeShape, render  # noqa: E402
from mock.centaur_mock.scenarios import PayloadScenario  # noqa: E402
from mock.centaur_mock.values import soh_channels  # noqa: E402

TESTDATA = ROOT / "backend" / "app" / "adapters" / "centaur_ctr" / "testdata"

# 시각을 고정해 Fixture 가 실행마다 바뀌지 않게 한다. 회귀 시험의 기준이므로 재현성이 우선이다.
FROZEN = datetime(2026, 8, 27, 3, 0, 0, tzinfo=timezone.utc)

CASES: list[tuple[str, VirtualDevice]] = [
    (
        "synthetic-ctr6-normal",
        VirtualDevice(
            instrument_id="centaur-6__0242",
            station_code="A01",
            model="CTR4-6S",
            firmware_version="3.2.8",
            serial_number="0242",
            channel_count=6,
        ),
    ),
    (
        "synthetic-ctr3-normal",
        VirtualDevice(
            instrument_id="centaur-3__0117",
            station_code="A02",
            model="CTR4-3S",
            firmware_version="3.2.8",
            serial_number="0117",
            channel_count=3,
            payload_scenario=PayloadScenario.THREE_CHANNEL,
        ),
    ),
    (
        "synthetic-ctr6-gps-unlocked",
        VirtualDevice(
            instrument_id="centaur-6__0311",
            station_code="B01",
            model="CTR4-6S",
            firmware_version="3.2.8",
            serial_number="0311",
            payload_scenario=PayloadScenario.GPS_UNLOCKED,
        ),
    ),
    (
        "synthetic-ctr6-no-sdcard",
        VirtualDevice(
            instrument_id="centaur-6__0455",
            station_code="B02",
            model="CTR4-6H",
            firmware_version="3.2.8",
            serial_number="0455",
            payload_scenario=PayloadScenario.NO_SD_CARD,
        ),
    ),
    (
        "synthetic-ctr6-store-full",
        VirtualDevice(
            instrument_id="centaur-6__0512",
            station_code="B03",
            model="CTR4-6S",
            firmware_version="3.2.8",
            serial_number="0512",
            payload_scenario=PayloadScenario.STORE_FULL,
        ),
    ),
    (
        "synthetic-ctr6-sensor-error",
        VirtualDevice(
            instrument_id="centaur-6__0613",
            station_code="B04",
            model="CTR4-6S",
            firmware_version="3.2.8",
            serial_number="0613",
            payload_scenario=PayloadScenario.SENSOR_ERROR,
        ),
    ),
    (
        "synthetic-ctr3-old-firmware-flatmap",
        VirtualDevice(
            instrument_id="centaur-3__0088",
            station_code="C01",
            model="CTR2-3",
            firmware_version="2.9.4",
            serial_number="0088",
            channel_count=3,
            has_removable_slot=False,
            external_soh_channels=0,
            payload_scenario=PayloadScenario.OLD_FIRMWARE,
            envelope_shape=EnvelopeShape.FLAT_MAP,
        ),
    ),
    (
        "synthetic-ctr6-unknown-status",
        VirtualDevice(
            instrument_id="centaur-6__0777",
            station_code="D01",
            model="CTR4-6S",
            firmware_version="3.4.0",
            serial_number="0777",
            payload_scenario=PayloadScenario.UNKNOWN_STATUS_STRING,
        ),
    ),
    (
        "synthetic-ctr6-missing-fields",
        VirtualDevice(
            instrument_id="centaur-6__0888",
            station_code="D02",
            model="CTR4-6S",
            firmware_version="3.2.8",
            serial_number="0888",
            payload_scenario=PayloadScenario.MISSING_FIELDS,
        ),
    ),
    (
        "synthetic-ctr6-no-mass-position",
        VirtualDevice(
            instrument_id="centaur-6__0999",
            station_code="D03",
            model="CTR4-6S",
            firmware_version="3.2.8",
            serial_number="0999",
            payload_scenario=PayloadScenario.NO_MASS_POSITION,
        ),
    ),
]


def main() -> int:
    TESTDATA.mkdir(parents=True, exist_ok=True)
    for name, device in CASES:
        payload = render(
            instrument_id=device.instrument_id,
            moment=FROZEN,
            channels=soh_channels(device, FROZEN),
            units=UNITS,
            shape=device.envelope_shape,
        )
        path = TESTDATA / f"{name}.json"
        path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        print(f"생성: {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
