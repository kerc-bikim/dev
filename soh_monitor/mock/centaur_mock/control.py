"""시험 제어 API.

실장비에 없는 경로이므로 `/_mock/` 으로 분명히 갈라 둔다. Adapter 가 실수로 이 경로에
의존하면 실장비에서 곧바로 드러나게 하려는 것이다.

E2E 에서 시나리오를 도중에 바꾸는 데 쓴다. 기동 시 기본 시나리오는 환경변수로 준다.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .envelope import EnvelopeShape
from .scenarios import PayloadScenario, TransportScenario

if TYPE_CHECKING:
    from .server import MockState


class ScenarioRequest(BaseModel):
    payloadScenario: PayloadScenario | None = None
    transportScenario: TransportScenario | None = None
    envelopeShape: EnvelopeShape | None = None
    latencyMs: int | None = None
    requiresAuth: bool | None = None


class ValueOverrideRequest(BaseModel):
    """특정 채널 값을 고정한다. 임계값 경계 시험에 쓴다."""

    values: dict[str, Any]
    replace: bool = False


def build_control_router(state: "MockState") -> APIRouter:
    router = APIRouter(prefix="/_mock", tags=["mock-control"])

    @router.get("/devices")
    async def list_devices() -> dict[str, Any]:
        return {
            "devices": [
                {
                    "instrumentId": device.instrument_id,
                    "stationCode": device.station_code,
                    "model": device.model,
                    "firmware": device.firmware_version,
                    "channelCount": device.channel_count,
                    "sensorPorts": list(device.sensor_ports),
                    "removableSlot": device.effective_removable_slot,
                    "externalSohChannels": device.effective_external_soh_channels,
                    "reportsMassPosition": device.reports_mass_position,
                    "payloadScenario": device.payload_scenario.value,
                    "transportScenario": device.transport_scenario.value,
                    "envelopeShape": device.envelope_shape.value,
                    "latencyMs": device.latency_ms,
                    "requiresAuth": device.requires_auth,
                    "requestCount": state.request_counts.get(device.instrument_id, 0),
                }
                for device in state.registry.all()
            ]
        }

    @router.post("/devices/{instrument_id}/scenario")
    async def set_scenario(instrument_id: str, request: ScenarioRequest) -> JSONResponse:
        if state.registry.get(instrument_id) is None:
            return JSONResponse({"error": "unknown instrument"}, status_code=404)

        changes: dict[str, Any] = {}
        if request.payloadScenario is not None:
            changes["payload_scenario"] = request.payloadScenario
        if request.transportScenario is not None:
            changes["transport_scenario"] = request.transportScenario
        if request.envelopeShape is not None:
            changes["envelope_shape"] = request.envelopeShape
        if request.latencyMs is not None:
            changes["latency_ms"] = request.latencyMs
        if request.requiresAuth is not None:
            changes["requires_auth"] = request.requiresAuth

        device = state.registry.update(instrument_id, **changes)
        return JSONResponse(
            {
                "instrumentId": device.instrument_id,
                "payloadScenario": device.payload_scenario.value,
                "transportScenario": device.transport_scenario.value,
                "envelopeShape": device.envelope_shape.value,
                "latencyMs": device.latency_ms,
            }
        )

    @router.post("/devices/{instrument_id}/values")
    async def set_values(instrument_id: str, request: ValueOverrideRequest) -> JSONResponse:
        device = state.registry.get(instrument_id)
        if device is None:
            return JSONResponse({"error": "unknown instrument"}, status_code=404)

        overrides = dict({} if request.replace else device.value_overrides)
        overrides.update(request.values)
        updated = state.registry.update(instrument_id, value_overrides=overrides)
        return JSONResponse({"instrumentId": instrument_id, "overrides": updated.value_overrides})

    @router.post("/reset")
    async def reset() -> JSONResponse:
        state.registry.reset()
        state.request_counts.clear()
        state.authenticated.clear()
        state.session_keys.clear()
        return JSONResponse({"status": "reset", "devices": len(state.registry)})

    @router.get("/scenarios")
    async def scenarios() -> dict[str, list[str]]:
        return {
            "payload": [scenario.value for scenario in PayloadScenario],
            "transport": [scenario.value for scenario in TransportScenario],
        }

    return router
