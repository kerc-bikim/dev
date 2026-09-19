"""시나리오 정의.

두 종류를 분명히 나눈다.

  본문 시나리오(PayloadScenario)  : 장비가 이상을 **보고**하는 상황.
                                    Adapter 의 Mapping·단위 변환·Capability 판정을 압박한다.
  통신 시나리오(TransportScenario): 회선·장비가 **오작동**하는 상황.
                                    Collector 의 재시도·실패 분류·Offline 판정을 압박한다.

두 계층은 처리 주체가 다르므로 섞으면 무엇을 시험하는지 모르게 된다.
"""
from __future__ import annotations

from enum import Enum


class PayloadScenario(str, Enum):
    NORMAL = "NORMAL"

    # 모델 차이
    THREE_CHANNEL = "THREE_CHANNEL"          # Sensor B 없음 → UNSUPPORTED 판정 확인
    SLOT_ABSENT = "SLOT_ABSENT"              # SD 슬롯 자체가 없는 모델
    NO_EXTERNAL_SOH = "NO_EXTERNAL_SOH"      # 외부 SOH 입력 없는 모델
    NO_MASS_POSITION = "NO_MASS_POSITION"    # SOH API 로 축별 값이 오지 않는 경우 (M-1.3 미확정 대비)

    # 장비 이상
    GPS_UNLOCKED = "GPS_UNLOCKED"
    LOW_VOLTAGE = "LOW_VOLTAGE"
    SENSOR_ERROR = "SENSOR_ERROR"
    STORE_FULL = "STORE_FULL"
    NO_SD_CARD = "NO_SD_CARD"                # 슬롯은 있으나 카드 미장착 (여유 공간 -1)
    UNCOMMITTED_CONFIG = "UNCOMMITTED_CONFIG"
    TESTCODE_FIRMWARE = "TESTCODE_FIRMWARE"

    # 파서 압박
    UNKNOWN_STATUS_STRING = "UNKNOWN_STATUS_STRING"  # 모르는 값이 OK 로 오인되지 않는지
    MISSING_FIELDS = "MISSING_FIELDS"                # 채널 누락에도 부분 결과를 내는지
    OLD_FIRMWARE = "OLD_FIRMWARE"                    # 수치 코드로 상태를 주는 예전 형태

    # 데이터 연속성 (SOH 와 독립. availability 응답만 바뀐다)
    WAVEFORM_STALE = "WAVEFORM_STALE"
    WAVEFORM_GAP = "WAVEFORM_GAP"
    WAVEFORM_STOPPED = "WAVEFORM_STOPPED"


class TransportScenario(str, Enum):
    OK = "OK"
    SLOW_RESPONSE = "SLOW_RESPONSE"
    TIMEOUT = "TIMEOUT"
    CONNECTION_RESET = "CONNECTION_RESET"
    HTTP_500 = "HTTP_500"
    HTTP_401 = "HTTP_401"
    INVALID_JSON = "INVALID_JSON"
    TRUNCATED_BODY = "TRUNCATED_BODY"
    WRONG_CONTENT_TYPE = "WRONG_CONTENT_TYPE"
    HUGE_PAYLOAD = "HUGE_PAYLOAD"
    IDENTITY_MISMATCH = "IDENTITY_MISMATCH"
    FLAPPING = "FLAPPING"  # 성공/실패 반복. 장애 중복 생성과 복구 알림 폭주를 잡는다


# 본문 시나리오가 장비 구성 자체를 바꾸는 경우. 값이 아니라 "없음"을 만든다.
CONFIGURATION_SCENARIOS = frozenset(
    {
        PayloadScenario.THREE_CHANNEL,
        PayloadScenario.SLOT_ABSENT,
        PayloadScenario.NO_EXTERNAL_SOH,
        PayloadScenario.NO_MASS_POSITION,
    }
)
