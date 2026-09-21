"""SOH 응답의 JSON 형태를 만드는 유일한 자리.

★ 중요 ★
Centaur User Guide 17935R10 의 7.4 State of Health API 절은 URI·파라미터·SOH 채널
이름까지는 명시하지만 **응답 본문 예시를 담고 있지 않다.** 따라서 채널 이름이 JSON 에서
어떻게 감싸여 오는지는 실장비 응답으로만 확정된다 (조사 항목 M-1.2).

그 미확정 부분을 이 파일 하나에 가둔다. 실장비 응답을 확보하면 여기와 Adapter 의
parser.py 만 고치면 되고, 시나리오·값 모델·제어면은 그대로 쓴다.

위험을 더 줄이기 위해 여러 형태를 낼 수 있게 했다. Adapter 는 관용적으로 읽는다.

  channel_list    : {"channels": [{"name": ..., "value": ...}, ...]}
  flat_map        : {"soh": {"<name>": {"value": ...}, ...}}
  instrument_map  : {"<instrumentId>": {"<name>": {"value": ..., "time": ..., "units": ...}}}
                    firmware 4.9.2 Centaur-6 실응답.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any


class EnvelopeShape(str, Enum):
    CHANNEL_LIST = "channel_list"
    FLAT_MAP = "flat_map"
    INSTRUMENT_MAP = "instrument_map"


def _iso(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def render(
    *,
    instrument_id: str,
    moment: datetime,
    channels: dict[str, Any],
    units: dict[str, str] | None = None,
    shape: EnvelopeShape = EnvelopeShape.CHANNEL_LIST,
) -> dict[str, Any]:
    """SOH 응답 본문을 만든다.

    `channels` 는 {SOH 채널 이름: 원값} 이다. 원값은 실장비 단위 그대로다.
    예를 들어 외부 SOH 는 마이크로볼트, 온도는 섭씨, 여유 공간은 바이트다.
    단위 변환은 Adapter 의 책임이며 여기서 미리 다듬지 않는다.
    """
    units = units or {}
    timestamp = _iso(moment)

    if shape is EnvelopeShape.INSTRUMENT_MAP:
        return {
            instrument_id: {
                name: {
                    "value": value,
                    "time": timestamp,
                    "units": units.get(name),
                }
                for name, value in channels.items()
            }
        }

    if shape is EnvelopeShape.FLAT_MAP:
        return {
            "instrumentId": instrument_id,
            "timestamp": timestamp,
            "soh": {
                name: {"value": value, "units": units.get(name)}
                for name, value in channels.items()
            },
        }

    return {
        "instrumentId": instrument_id,
        "timestamp": timestamp,
        "channels": [
            {
                "name": name,
                "value": value,
                "units": units.get(name),
                "timestamp": timestamp,
            }
            for name, value in channels.items()
        ],
    }


# massPosition 추정 이름은 쓰지 않는다. 실응답 4.9.2 는 digitizer/sensor/soh/voltage#_n 이다.
UNITS: dict[str, str] = {
    "powerSupply/voltage": "V",
    "system/current": "A",
    "temperature": "degreesCelsius",
    "timing/timeError": "nanoseconds",
    "timing/timeQuality": "percentage",
    "timing/timeUncertainty": "nanoseconds",
    "externalSoh/voltage#_1": "microVolts",
    "externalSoh/voltage#_2": "microVolts",
    "externalSoh/voltage#_3": "microVolts",
    "controller/store/storePercentageUsed": "percentage",
    "media/freeSpace/removableSD": "bytes",
    "digitizer/sensor/soh/voltage#_1": "microVolts",
    "digitizer/sensor/soh/voltage#_2": "microVolts",
    "digitizer/sensor/soh/voltage#_3": "microVolts",
    "digitizer/sensor/soh/voltage#_4": "microVolts",
    "digitizer/sensor/soh/voltage#_5": "microVolts",
    "digitizer/sensor/soh/voltage#_6": "microVolts",
}
