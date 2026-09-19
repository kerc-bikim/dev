"""가상 Centaur CTR HTTP 서버.

흉내내는 표면은 매뉴얼에 있는 것으로 한정한다. 실장비에 없는 편의 엔드포인트를 만들면
Adapter 가 그것에 의존하게 되고, 실장비를 붙일 때 드러난다.

  GET  /api/v1/instruments/soh          7.4 State of Health API
  GET  /api/v1/bands/availability.json  7.1 Data Availability API (최소 응답)
  GET  /key, POST /login, POST /logout  7.6 User Authentication API
  그 외                                  404

시험 제어용 경로는 `/_mock/` 으로 분명히 갈라 둔다. Adapter 는 이 경로를 알지 못한다.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, FastAPI, Request, Response
from fastapi.responses import JSONResponse

from .devices import DeviceRegistry, VirtualDevice, load_fleet
from .envelope import UNITS, render
from .scenarios import PayloadScenario, TransportScenario
from .values import soh_channels

SESSION_COOKIE = "nmxsid"

# TIMEOUT 시나리오에서 응답을 붙잡아 두는 시간. 수집기 Timeout 보다 길기만 하면 되고,
# 무한 대기는 두지 않는다. 시험이 멈추는 것보다 실패하는 것이 낫다.
TIMEOUT_HOLD_SECONDS = float(os.environ.get("MOCK_TIMEOUT_HOLD_SECONDS", "20"))


class MockState:
    """서버 상태. 세션과 Flapping 순번을 들고 있다."""

    def __init__(self, registry: DeviceRegistry) -> None:
        self.registry = registry
        self.session_keys: dict[str, str] = {}
        self.authenticated: set[str] = set()
        self.request_counts: dict[str, int] = {}
        self.now = lambda: datetime.now(timezone.utc)

    def next_count(self, instrument_id: str) -> int:
        count = self.request_counts.get(instrument_id, 0) + 1
        self.request_counts[instrument_id] = count
        return count


def _transport_failure(device: VirtualDevice, count: int) -> TransportScenario:
    """이번 요청에 적용할 통신 시나리오."""
    scenario = device.transport_scenario
    if scenario is TransportScenario.FLAPPING:
        # 성공/실패를 번갈아 낸다. 장애 중복 생성과 복구 알림 폭주를 잡는 시나리오다.
        return TransportScenario.OK if count % 2 == 1 else TransportScenario.HTTP_500
    return scenario


def _password_digest(password: str, key: str) -> str:
    """매뉴얼 7.6 절: MD5( MD5(password) + key )."""
    inner = hashlib.md5(password.encode("utf-8")).hexdigest()  # noqa: S324 - 장비 규격
    return hashlib.md5((inner + key).encode("utf-8")).hexdigest()  # noqa: S324


def create_app(registry: DeviceRegistry | None = None) -> FastAPI:
    state = MockState(registry or load_fleet())
    app = FastAPI(
        title="가상 Centaur CTR",
        description=(
            "시험용 가상 기록계. 응답 형태는 실장비 확보 전까지 추정이며 envelope.py 에만 있다."
        ),
        docs_url=None,
        redoc_url=None,
    )
    app.state.mock = state

    device_api = APIRouter()

    @device_api.get("/api/v1/instruments/soh")
    async def instruments_soh(request: Request) -> Response:
        instrument_id = request.query_params.get("instrumentId")
        pretty = request.query_params.get("pretty", "false").lower() == "true"

        device = state.registry.get(instrument_id)
        if device is None:
            return JSONResponse({"error": "unknown instrument"}, status_code=404)

        count = state.next_count(device.instrument_id)
        failure = _transport_failure(device, count)

        # 지연은 실패와 별개로 항상 적용한다. 느린 장비가 전체 수집을 막지 않는지 본다.
        delay_ms = device.latency_ms
        if failure is TransportScenario.SLOW_RESPONSE and delay_ms == 0:
            delay_ms = 3000
        if delay_ms:
            await asyncio.sleep(delay_ms / 1000)

        if failure is TransportScenario.TIMEOUT:
            # 응답을 붙잡아 둔다. 무한 대기로 두면 시험이 통째로 멈출 수 있어 상한을 준다.
            #
            # 주의: httpx 의 ASGI 전송은 Timeout 을 적용하지 않는다. 같은 프로세스에서 앱을
            # 직접 await 하기 때문이다. 그래서 이 시나리오는 실제 HTTP 로 붙을 때만 의미가
            # 있고, 단위 시험에서는 예외를 주입해 분류를 확인한다.
            await asyncio.sleep(TIMEOUT_HOLD_SECONDS)
            return JSONResponse({"error": "timeout"}, status_code=504)

        if failure is TransportScenario.CONNECTION_RESET:
            # 본문 없이 연결을 끊는다. httpx 에서는 읽기 오류로 나타난다.
            return Response(status_code=444)

        if failure is TransportScenario.HTTP_500:
            return JSONResponse({"error": "internal"}, status_code=500)

        if failure is TransportScenario.HTTP_401 or (
            device.requires_auth and request.cookies.get(SESSION_COOKIE) not in state.authenticated
        ):
            return JSONResponse({"error": "unauthorized"}, status_code=401)

        if failure is TransportScenario.INVALID_JSON:
            return Response(
                content='{"channels": [ {"name": "powerSupply/voltage", ',
                media_type="application/json",
            )

        moment = state.now()
        reported_id = device.instrument_id
        if failure is TransportScenario.IDENTITY_MISMATCH:
            reported_id = "centaur-6__9999"

        channels = soh_channels(device, moment)
        payload = render(
            instrument_id=reported_id,
            moment=moment,
            channels=channels,
            units=UNITS,
            shape=device.envelope_shape,
        )

        if failure is TransportScenario.HUGE_PAYLOAD:
            payload["padding"] = "x" * (12 * 1024 * 1024)

        body = json.dumps(payload, indent=2 if pretty else None, ensure_ascii=False)

        if failure is TransportScenario.TRUNCATED_BODY:
            body = body[: len(body) // 2]

        media_type = (
            "text/plain"
            if failure is TransportScenario.WRONG_CONTENT_TYPE
            else "application/json"
        )
        return Response(content=body, media_type=media_type)

    @device_api.get("/api/v1/bands/availability.json")
    async def band_availability(request: Request) -> Response:
        """데이터 연속성 검사용 최소 응답 (M2.11 에서 쓴다)."""
        device = state.registry.get(request.query_params.get("instrumentId"))
        if device is None:
            return JSONResponse({"error": "unknown instrument"}, status_code=404)

        moment = state.now()
        channel_count = 3 * len(device.sensor_ports)
        axes = ("Z", "N", "E")[: min(3, channel_count)]
        bands = []
        for axis in axes:
            if device.payload_scenario is PayloadScenario.WAVEFORM_STOPPED:
                ranges: list[dict] = []
            elif device.payload_scenario is PayloadScenario.WAVEFORM_STALE:
                end = moment - timedelta(minutes=30)
                ranges = [
                    {
                        "start": (end - timedelta(hours=5)).isoformat(),
                        "end": end.isoformat(),
                    }
                ]
            elif device.payload_scenario is PayloadScenario.WAVEFORM_GAP:
                ranges = [
                    {
                        "start": (moment - timedelta(hours=6)).isoformat(),
                        "end": (moment - timedelta(hours=3)).isoformat(),
                    },
                    {
                        "start": (moment - timedelta(hours=2)).isoformat(),
                        "end": moment.isoformat(),
                    },
                ]
            else:
                ranges = [
                    {
                        "start": (moment - timedelta(hours=6)).isoformat(),
                        "end": moment.isoformat(),
                    }
                ]
            bands.append({"channel": f"HH{axis}", "ranges": ranges})
        return JSONResponse({"instrumentId": device.instrument_id, "bands": bands})

    # ------------------------------------------------------------ 인증 (7.6 절)

    @device_api.get("/key")
    async def session_key(response: Response) -> dict[str, str]:
        session_id = secrets.token_hex(16)
        key = secrets.token_hex(8)
        state.session_keys[session_id] = key
        response.set_cookie(SESSION_COOKIE, session_id)
        return {"key": key}

    @device_api.post("/login")
    async def login(request: Request) -> Response:
        session_id = request.cookies.get(SESSION_COOKIE)
        key = state.session_keys.get(session_id or "")
        username = request.headers.get("X-NMX-USERNAME")
        password_hash = request.headers.get("X-NMX-PASSWORD")
        if not session_id or not key or not username or not password_hash:
            return JSONResponse({"error": "unauthorized"}, status_code=401)

        device = state.registry.get(None)
        if device is None or username != device.username:
            return JSONResponse({"error": "unauthorized"}, status_code=401)

        if password_hash.lower() != _password_digest(device.password, key):
            return JSONResponse({"error": "unauthorized"}, status_code=401)

        state.authenticated.add(session_id)
        return JSONResponse({"status": "ok"})

    @device_api.post("/logout")
    async def logout(request: Request) -> Response:
        session_id = request.cookies.get(SESSION_COOKIE)
        if session_id:
            state.authenticated.discard(session_id)
            state.session_keys.pop(session_id, None)
        return JSONResponse({"status": "ok"})

    app.include_router(device_api)

    from .control import build_control_router

    app.include_router(build_control_router(state))
    return app
