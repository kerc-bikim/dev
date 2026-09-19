"""데이터 연속성 검사.

기록계 SOH 와 독립이다. 센서 상태가 OK 여도 파형이 멈추면 여기서 잡는다.
데이터 서버 URI 가 없으면 기능을 UNSUPPORTED 로 표시하고 값을 채우지 않는다.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx

from app.adapters.contract import DeviceContext
from app.domain.enums import SupportState
from app.domain.models import CapabilityReport, MetricSample, PollResult

from .client import HttpAvailabilityTransport, SeedLinkStubTransport, normalize_uri
from .mapper import map_channels
from .parser import AvailabilityParseError, parse_availability

LOOKBACK_SECONDS = 6 * 3600
DEFAULT_ACTIVE_AGE_SECONDS = 120


class DataAvailabilityChecker:
    def __init__(self, *, httpx_transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._http = HttpAvailabilityTransport(httpx_transport=httpx_transport)
        self._seedlink = SeedLinkStubTransport()

    async def collect(
        self,
        context: DeviceContext,
        *,
        data_source_uri: str | None,
        now: datetime | None = None,
        poll_interval_minutes: int = 5,
    ) -> tuple[tuple[MetricSample, ...], CapabilityReport]:
        if not (data_source_uri or "").strip():
            return (), CapabilityReport(states={"acquisition.data_check": SupportState.UNSUPPORTED})

        now = now or datetime.now(timezone.utc)
        active_age = max(DEFAULT_ACTIVE_AGE_SECONDS, poll_interval_minutes * 60 * 2)
        try:
            kind, target = normalize_uri(data_source_uri)
        except ValueError:
            return (), CapabilityReport(states={"acquisition.data_check": SupportState.ERROR})

        if kind == "seedlink":
            fetched = await self._seedlink.fetch(
                target,
                connect_timeout_ms=context.connect_timeout_ms,
                request_timeout_ms=context.request_timeout_ms,
            )
        else:
            fetched = await self._http.fetch(
                target,
                connect_timeout_ms=context.connect_timeout_ms,
                request_timeout_ms=context.request_timeout_ms,
            )

        if not fetched.success:
            return (), CapabilityReport(states={"acquisition.data_check": SupportState.ERROR})

        try:
            channels = parse_availability(fetched.payload)
        except AvailabilityParseError:
            return (), CapabilityReport(states={"acquisition.data_check": SupportState.ERROR})

        samples = map_channels(
            channels,
            now=now,
            lookback_seconds=LOOKBACK_SECONDS,
            active_age_seconds=active_age,
        )
        return tuple(samples), CapabilityReport(
            states={"acquisition.data_check": SupportState.SUPPORTED_ENABLED}
        )


def merge_availability(result: PollResult, samples: tuple[MetricSample, ...], report: CapabilityReport) -> PollResult:
    """SOH 성공/실패와 관계없이 acquisition 샘플·capability 를 붙인다."""
    states = dict(result.capabilities.states)
    states.update(report.states)
    return result.model_copy(
        update={
            "samples": tuple(result.samples) + samples,
            "capabilities": CapabilityReport(states=states),
        }
    )


async def attach_availability(
    result: PollResult,
    context: DeviceContext,
    *,
    data_source_uri: str | None,
    poll_interval_minutes: int,
    httpx_transport: Any = None,
) -> PollResult:
    try:
        checker = DataAvailabilityChecker(httpx_transport=httpx_transport)
        samples, report = await checker.collect(
            context,
            data_source_uri=data_source_uri,
            now=result.observed_at,
            poll_interval_minutes=poll_interval_minutes,
        )
    except Exception as exc:  # noqa: BLE001 - 데이터 검사가 SOH 수집을 뒤집지 않는다
        samples, report = (), CapabilityReport(
            states={"acquisition.data_check": SupportState.ERROR}
        )
        del exc
    return merge_availability(result, samples, report)
