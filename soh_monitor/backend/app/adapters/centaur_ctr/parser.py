"""Centaur CTR SOH 응답 파싱.

응답 본문 형태는 매뉴얼(17935R10 7.4절)에 예시가 없어 실장비로만 확정된다(조사 M-1.3/M-1.2).
파서는 아래 네 형태를 모두 읽는다.

  1) {"channels": [{"name": ..., "value": ..., "units": ...}, ...]}
  2) {"soh": {"<name>": {"value": ..., "units": ...}, ...}}
  3) {"<name>": <value>, ...}                      (평평한 형태)
  4) {"<instrumentId>": {"<name>": {"value": ..., "time": ..., "units": ...}, ...}}
     firmware 4.9.2 Centaur-6 실응답.

실제 형태가 이 중 하나면 그대로 동작하고, 변형이면 이 파일만 고친다.
파서는 값을 해석하지 않는다. 이름과 원값을 꺼내는 일까지만 한다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

# 채널이 아니라 응답 자체의 속성인 키. 평평한 형태를 읽을 때 채널로 오인하지 않는다.
_ENVELOPE_KEYS = frozenset(
    {"instrumentid", "timestamp", "channels", "soh", "time", "error", "padding"}
)
_FRACTION_TRIM = re.compile(r"\.(\d{6})\d+")


class ParseError(Exception):
    """응답을 SOH 로 해석할 수 없는 경우. 통신 성공과 별개로 본문 오류로 분류한다."""


@dataclass(frozen=True)
class ChannelValue:
    value: Any
    units: str | None = None


@dataclass(frozen=True)
class ParsedSoh:
    instrument_id: str | None
    reported_at: datetime | None
    channels: dict[str, ChannelValue] = field(default_factory=dict)

    def raw(self, name: str) -> Any:
        entry = self.channels.get(name)
        return None if entry is None else entry.value

    def units(self, name: str) -> str | None:
        entry = self.channels.get(name)
        return None if entry is None else entry.units

    def has(self, name: str) -> bool:
        return name in self.channels

    def names_with_prefix(self, prefix: str) -> tuple[str, ...]:
        return tuple(sorted(name for name in self.channels if name.startswith(prefix)))


def parse_timestamp(raw: Any) -> datetime | None:
    """장비가 준 시각. 해석하지 못하면 None 이며, 그때는 수집 시각을 쓴다.

    실응답은 나노초 소수와 공백 구분(`2026-09-21 00:00:00.000000000`)을 쓴다.
    """
    if not isinstance(raw, str) or not raw.strip():
        return None
    text = raw.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    text = _FRACTION_TRIM.sub(r".\1", text)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _entry_to_channel(entry: Any) -> ChannelValue:
    """값이 스칼라로 오는 경우와 {"value":..,"units":..} 로 오는 경우를 함께 받는다."""
    if isinstance(entry, dict) and "value" in entry:
        return ChannelValue(value=entry.get("value"), units=entry.get("units"))
    return ChannelValue(value=entry, units=None)


def _looks_like_channel_entry(entry: Any) -> bool:
    return isinstance(entry, dict) and "value" in entry


def _instrument_map(payload: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    """펌웨어 4.9.2 실응답: 최상위 키가 Instrument ID 이고 값이 채널 맵이다."""
    if len(payload) != 1:
        return None
    key, inner = next(iter(payload.items()))
    if not isinstance(key, str) or key.lower() in _ENVELOPE_KEYS:
        return None
    if not isinstance(inner, dict) or not inner:
        return None
    hits = sum(1 for entry in inner.values() if _looks_like_channel_entry(entry))
    if hits < max(1, (len(inner) + 1) // 2):
        return None
    return key, inner


def _ingest_map(channels: dict[str, ChannelValue], raw_map: dict[str, Any]) -> None:
    for name, entry in raw_map.items():
        if isinstance(name, str) and name:
            channels[name] = _entry_to_channel(entry)


def parse_soh(payload: Any) -> ParsedSoh:
    if not isinstance(payload, dict):
        raise ParseError("SOH 응답이 객체가 아니다")

    instrument_id = payload.get("instrumentId") or payload.get("instrumentID")
    reported_at = parse_timestamp(payload.get("timestamp") or payload.get("time"))

    channels: dict[str, ChannelValue] = {}

    wrapped = _instrument_map(payload)
    if wrapped is not None:
        instrument_id = instrument_id or wrapped[0]
        _ingest_map(channels, wrapped[1])
        if reported_at is None:
            times = [
                parse_timestamp(entry.get("time"))
                for entry in wrapped[1].values()
                if isinstance(entry, dict)
            ]
            present = [item for item in times if item is not None]
            if present:
                reported_at = max(present)

    raw_channels = payload.get("channels")
    if isinstance(raw_channels, list):
        for item in raw_channels:
            if not isinstance(item, dict):
                continue
            name = item.get("name") or item.get("channel")
            if not isinstance(name, str) or not name:
                continue
            channels[name] = ChannelValue(value=item.get("value"), units=item.get("units"))

    raw_map = payload.get("soh")
    if isinstance(raw_map, dict):
        _ingest_map(channels, raw_map)

    if not channels:
        # 평평한 형태. 응답 자체의 속성은 제외한다.
        for name, entry in payload.items():
            if not isinstance(name, str) or name.lower() in _ENVELOPE_KEYS:
                continue
            channels[name] = _entry_to_channel(entry)

    if not channels:
        raise ParseError("SOH 채널을 하나도 찾지 못했다")

    return ParsedSoh(instrument_id=instrument_id, reported_at=reported_at, channels=channels)
