"""가상 Centaur CTR 서버 실행점.

    python -m mock.centaur_mock
    MOCK_FLEET_SIZE=100 MOCK_SLOW_RATIO=0.2 python -m mock.centaur_mock   # 부하 시험용

환경변수
    MOCK_PORT          기본 8090
    MOCK_FLEET         묶음 파일 이름 (기본 fleet)
    MOCK_FLEET_SIZE    지정하면 파일 대신 그 수만큼 즉석 생성
    MOCK_SLOW_RATIO    생성 시 느린 장비 비율 (0.0~1.0)
    MOCK_SCENARIO      전 장비에 적용할 기본 본문 시나리오
    MOCK_ENVELOPE      channel_list | flat_map
"""
from __future__ import annotations

import os

import uvicorn

from .devices import DeviceRegistry, generated_fleet, load_fleet
from .envelope import EnvelopeShape
from .scenarios import PayloadScenario
from .server import create_app


def build_registry() -> DeviceRegistry:
    size = os.environ.get("MOCK_FLEET_SIZE")
    if size:
        registry = generated_fleet(
            int(size), slow_ratio=float(os.environ.get("MOCK_SLOW_RATIO", "0"))
        )
    else:
        registry = load_fleet(os.environ.get("MOCK_FLEET", "fleet"))

    scenario = os.environ.get("MOCK_SCENARIO")
    envelope = os.environ.get("MOCK_ENVELOPE")
    if scenario or envelope:
        changes: dict[str, object] = {}
        if scenario:
            changes["payload_scenario"] = PayloadScenario(scenario)
        if envelope:
            changes["envelope_shape"] = EnvelopeShape(envelope)
        for device in registry.all():
            registry.update(device.instrument_id, **changes)

    return registry


def main() -> None:
    registry = build_registry()
    print(f"[가상 Centaur] 장비 {len(registry)}대")
    for device in registry.all():
        print(
            f"  {device.instrument_id:20s} {device.station_code:5s} {device.model:10s} "
            f"본문={device.payload_scenario.value:22s} 통신={device.transport_scenario.value}"
        )
    uvicorn.run(
        create_app(registry),
        host="0.0.0.0",
        port=int(os.environ.get("MOCK_PORT", "8090")),
        log_level="info",
    )


if __name__ == "__main__":
    main()
