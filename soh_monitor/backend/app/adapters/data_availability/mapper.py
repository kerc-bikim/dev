"""availability 구간 → 표준 acquisition Metric.

SOH 가 OK 여도 파형이 멈추면 여기 값이 커진다. 없는 채널을 0 으로 채우지 않는다.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from app.domain.enums import SupportState
from app.domain.models import MetricSample

from .parser import ChannelAvailability


def _merge_ranges(channel: ChannelAvailability) -> tuple:
    merged: list = []
    for span in channel.ranges:
        if not merged or span.start > merged[-1].end:
            merged.append(span)
            continue
        last = merged[-1]
        if span.end > last.end:
            merged[-1] = type(span)(start=last.start, end=span.end)
    return tuple(merged)


def map_channels(
    channels: tuple[ChannelAvailability, ...],
    *,
    now: datetime,
    lookback_seconds: float,
    active_age_seconds: float,
) -> list[MetricSample]:
    samples: list[MetricSample] = []
    window_start = now - timedelta(seconds=lookback_seconds)

    for channel in channels:
        merged = _merge_ranges(channel)
        in_window = [span for span in merged if span.end >= window_start]
        if not in_window:
            samples.append(
                MetricSample(
                    metric_key="acquisition.channel_active",
                    dimensions={"channel": channel.channel},
                    value_bool=False,
                    support_state=SupportState.SUPPORTED_ENABLED,
                )
            )
            samples.append(
                MetricSample(
                    metric_key="acquisition.latest_sample_age_seconds",
                    dimensions={"channel": channel.channel},
                    value_float=round(lookback_seconds, 1),
                    support_state=SupportState.SUPPORTED_ENABLED,
                )
            )
            samples.append(
                MetricSample(
                    metric_key="acquisition.gap_duration_seconds",
                    dimensions={"channel": channel.channel},
                    value_float=round(lookback_seconds, 1),
                    support_state=SupportState.SUPPORTED_ENABLED,
                )
            )
            continue

        latest = max(span.end for span in in_window)
        age = max(0.0, (now - latest).total_seconds())
        gap = 0.0
        cursor = window_start
        for span in in_window:
            start = max(span.start, window_start)
            if start > cursor:
                gap += (start - cursor).total_seconds()
            if span.end > cursor:
                cursor = span.end
        if now > cursor:
            # 마지막 샘플 이후는 경과 시간으로 따로 본다. 공백 합에 넣지 않는다.
            pass

        samples.append(
            MetricSample(
                metric_key="acquisition.latest_sample_age_seconds",
                dimensions={"channel": channel.channel},
                value_float=round(age, 1),
                support_state=SupportState.SUPPORTED_ENABLED,
            )
        )
        samples.append(
            MetricSample(
                metric_key="acquisition.gap_duration_seconds",
                dimensions={"channel": channel.channel},
                value_float=round(max(0.0, gap), 1),
                support_state=SupportState.SUPPORTED_ENABLED,
            )
        )
        samples.append(
            MetricSample(
                metric_key="acquisition.channel_active",
                dimensions={"channel": channel.channel},
                value_bool=age <= active_age_seconds,
                support_state=SupportState.SUPPORTED_ENABLED,
            )
        )
    return samples
