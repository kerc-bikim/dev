"""SOH 응답의 JSON 형태를 만드는 유일한 자리.

★ 중요 ★
Centaur User Guide 17935R10 의 7.4 State of Health API 절은 URI·파라미터·SOH 채널
이름까지는 명시하지만 **응답 본문 예시를 담고 있지 않다.** 따라서 채널 이름이 JSON 에서
어떻게 감싸여 오는지는 실장비 응답으로만 확정된다 (조사 항목 M-1.2).

그 미확정 부분을 이 파일 하나에 가둔다. 실장비 응답을 확보하면 여기와 Adapter 의
parser.py 만 고치면 되고, 시나리오·값 모델·제어면은 그대로 쓴다.

위험을 더 줄이기 위해 두 가지 형태를 모두 낼 수 있게 했다. Adapter 는 두 형태를 모두
읽어야 하며, 그래서 실제 형태가 어느 쪽이든(혹은 그 변형이든) 파서가 이미 관용적이다.

  channel_list : {"channels": [{"name": ..., "value": ...}, ...]}
  flat_map     : {"soh": {"<name>": {"value": ...}, ...}}
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any


class EnvelopeShape(str, Enum):
    CHANNEL_LIST = "channel_list"
    FLAT_MAP = "flat_map"


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


# SOH 채널 이름과 원 단위. 근거: Centaur User Guide 17935R10 7.4 절 SOH channels 표.
#
# massPosition 채널 이름만은 매뉴얼에 없다. 7.4 절 표에는 포트 단위 상태
# (digitizer/sensor/status#_0) 만 있고 축별 값의 키가 나오지 않는다. VM1~VM6 은
# Steim/SeedLink 채널 코드(8.2 절)이므로 SOH API 의 키가 아니다.
# 아래 이름은 externalSoh/voltage#_n 의 표기 관례를 따른 추정이며, M-1.3 에서 확정한다.
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
    "digitizer/sensor/massPosition#_0_1": "microVolts",
    "digitizer/sensor/massPosition#_0_2": "microVolts",
    "digitizer/sensor/massPosition#_0_3": "microVolts",
    "digitizer/sensor/massPosition#_1_1": "microVolts",
    "digitizer/sensor/massPosition#_1_2": "microVolts",
    "digitizer/sensor/massPosition#_1_3": "microVolts",
}
