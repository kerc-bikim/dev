"""데이터 연속성 응답 파싱.

SOH 와 다른 봉투를 받는다. 아래 세 형태를 모두 읽는다.

  1) Centaur bands : {"bands": [{"channel": "HHZ", "ranges": [{"start","end"}]}]}
  2) FDSNWS JSON   : {"datasources": [{"chan": "HHZ", "timespans": [[start,end]]}]}
  3) 평평한 목록   : {"channels": [{"channel": "HHZ", "end": "...", "gaps": [...]}]}

파서는 경과·공백을 계산하지 않는다. 채널과 구간만 꺼낸다.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


class AvailabilityParseError(Exception):
    """availability 응답을 해석할 수 없는 경우."""


@dataclass(frozen=True)
class TimeRange:
    start: datetime
    end: datetime


@dataclass(frozen=True)
class ChannelAvailability:
    channel: str
    ranges: tuple[TimeRange, ...]


def parse_timestamp(raw: Any) -> datetime | None:
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        # FDSN 이 UNIX 초로 줄 수 있다.
        return datetime.fromtimestamp(float(raw), tz=timezone.utc)
    if not isinstance(raw, str) or not raw.strip():
        return None
    text = raw.strip().replace("Z", "+00:00")
    # SeedLink INFO XML 은 `YYYY-MM-DD HH:MM:SS` 를 쓴다.
    if "T" not in text and text.count(" ") == 1 and ":" in text:
        text = text.replace(" ", "T", 1)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _range(start_raw: Any, end_raw: Any) -> TimeRange | None:
    start = parse_timestamp(start_raw)
    end = parse_timestamp(end_raw)
    if start is None or end is None or end < start:
        return None
    return TimeRange(start=start, end=end)


def _channel_name(entry: dict[str, Any]) -> str | None:
    for key in ("channel", "chan", "code", "name"):
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    loc = entry.get("location")
    cha = entry.get("cha") or entry.get("channelCode")
    if isinstance(cha, str) and cha.strip():
        if isinstance(loc, str) and loc.strip() and loc.strip() != "--":
            return f"{loc.strip()}.{cha.strip()}"
        return cha.strip()
    return None


def parse_availability(payload: Any) -> tuple[ChannelAvailability, ...]:
    if not isinstance(payload, dict):
        raise AvailabilityParseError("availability 응답이 객체가 아니다")

    channels: dict[str, list[TimeRange]] = {}

    bands = payload.get("bands")
    if isinstance(bands, list):
        for item in bands:
            if not isinstance(item, dict):
                continue
            name = _channel_name(item)
            if not name:
                continue
            channels.setdefault(name, [])
            for raw in item.get("ranges") or []:
                if not isinstance(raw, dict):
                    continue
                span = _range(raw.get("start") or raw.get("begin"), raw.get("end"))
                if span:
                    channels[name].append(span)

    sources = payload.get("datasources") or payload.get("data")
    if isinstance(sources, list):
        for item in sources:
            if not isinstance(item, dict):
                continue
            name = _channel_name(item)
            if not name:
                continue
            channels.setdefault(name, [])
            for raw in item.get("timespans") or item.get("ranges") or []:
                if isinstance(raw, (list, tuple)) and len(raw) >= 2:
                    span = _range(raw[0], raw[1])
                elif isinstance(raw, dict):
                    span = _range(raw.get("start") or raw.get("earliest"), raw.get("end") or raw.get("latest"))
                else:
                    continue
                if span:
                    channels[name].append(span)

    listed = payload.get("channels")
    if isinstance(listed, list):
        for item in listed:
            if not isinstance(item, dict):
                continue
            name = _channel_name(item)
            if not name:
                continue
            latest = parse_timestamp(item.get("end") or item.get("latest"))
            earliest = parse_timestamp(item.get("start") or item.get("earliest"))
            if latest is not None:
                channels.setdefault(name, []).append(
                    TimeRange(start=earliest or latest, end=latest)
                )
            else:
                channels.setdefault(name, [])

    if not channels:
        raise AvailabilityParseError("채널 availability 를 하나도 찾지 못했다")

    result: list[ChannelAvailability] = []
    for name, ranges in channels.items():
        ordered = tuple(sorted(ranges, key=lambda item: item.start))
        result.append(ChannelAvailability(channel=name, ranges=ordered))
    return tuple(sorted(result, key=lambda item: item.channel))
