"""장비 한 대를 수집하는 절차.

한 장비의 문제가 다른 장비에 번지지 않게 하는 것이 이 파일의 목적이다.
예외는 여기서 멈추고, 결과는 항상 PollResult 로 정리된다.
"""
from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass

from app.adapters.contract import DeviceContext, RecorderAdapter
from app.adapters.data_availability import attach_availability
from app.adapters.registry import AdapterRegistrationError, AdapterRegistry
from app.auth.credentials import CredentialResolver
from app.collector.retry import RetryPolicy
from app.domain.enums import PollErrorCode
from app.domain.models import PollResult, utcnow
from app.observability.logging import get_logger
from app.repository.postgres.collector_repo import DueDevice

logger = get_logger("app.collector.runner", role="collector")


@dataclass
class PollOutcome:
    device: DueDevice
    result: PollResult
    attempts: int


def build_context(
    device: DueDevice, resolver: CredentialResolver, *, sleepless: bool = False
) -> DeviceContext:
    return DeviceContext(
        device_id=str(device.device_id),
        station_code=device.station_code,
        connection=device.connection,
        credential=resolver.resolve(device.credential_reference),
        connect_timeout_ms=device.connect_timeout_ms,
        request_timeout_ms=device.request_timeout_ms,
        options={"sleepless": sleepless} if sleepless else None,
    )


def _failure(device: DueDevice, adapter_key: str, code: PollErrorCode, message: str) -> PollResult:
    return PollResult(
        poll_id=str(uuid.uuid4()),
        device_id=str(device.device_id),
        adapter_key=adapter_key,
        adapter_version="unknown",
        observed_at=utcnow(),
        success=False,
        error_code=code,
        error_message=message,
    )


async def poll_device(
    device: DueDevice,
    registry: AdapterRegistry,
    resolver: CredentialResolver,
    policy: RetryPolicy,
    *,
    sleep=asyncio.sleep,
) -> PollOutcome:
    """재시도까지 포함한 한 장비의 수집."""
    try:
        adapter: RecorderAdapter = registry.get(device.adapter_key)
    except AdapterRegistrationError as exc:
        # 등록되지 않은 Adapter 를 요구하는 장비. 수집할 방법이 없으므로 즉시 실패로 남긴다.
        logger.error(
            "등록되지 않은 Adapter",
            extra={"device_id": str(device.device_id), "adapter_key": device.adapter_key},
        )
        return PollOutcome(
            device=device,
            result=_failure(device, device.adapter_key, PollErrorCode.ADAPTER_ERROR, str(exc)),
            attempts=0,
        )

    context = build_context(device, resolver)
    attempts = 0
    result: PollResult | None = None

    while True:
        attempts += 1
        try:
            result = await adapter.collect(context)
        except Exception as exc:  # noqa: BLE001 - Adapter 가 계약을 어겨도 루프는 살아야 한다
            logger.exception(
                "Adapter 가 예외를 던졌다",
                extra={"device_id": str(device.device_id), "adapter_key": device.adapter_key},
            )
            result = _failure(device, device.adapter_key, PollErrorCode.ADAPTER_ERROR, str(exc))

        if result.success:
            break
        if not policy.should_retry(result.error_code, attempts):
            break

        delay = policy.delay_for(attempts)
        logger.info(
            "수집 재시도",
            extra={
                "device_id": str(device.device_id),
                "poll_id": result.poll_id,
                "attempt": attempts,
                "error_code": result.error_code.value if result.error_code else None,
                "delay_seconds": delay,
            },
        )
        await sleep(delay)

    result = await attach_availability(
        result,
        context,
        data_source_uri=device.data_source_uri,
        poll_interval_minutes=device.poll_interval_minutes,
        httpx_transport=getattr(adapter, "_transport", None),
    )

    logger.info(
        "수집 완료" if result.success else "수집 실패",
        extra={
            "device_id": str(device.device_id),
            "station_code": device.station_code,
            "poll_id": result.poll_id,
            "success": result.success,
            "attempts": attempts,
            "samples": len(result.samples),
            "latency_ms": result.latency_ms,
            "error_code": result.error_code.value if result.error_code else None,
        },
    )
    return PollOutcome(device=device, result=result, attempts=attempts)
