"""ACME Mock Recorder 응답 파싱.

Centaur 와 다른 봉투를 쓴다. 채널 배열이 아니라 readings 객체다.

  {
    "deviceId": "MR-1001",
    "reportedAt": "...",
    "model": "MR-100",
    "readings": { "sys.health": "GOOD", "psu.millivolts": 12600, ... }
  }

파서는 값을 해석하지 않는다. 이름과 원값만 꺼낸다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


class ParseError(Exception):
    """응답을 SOH 로 해석할 수 없는 경우."""


@dataclass(frozen=True)
class Reading:
    value: Any
    units: str | None = None


@dataclass(frozen=True)
class ParsedSoh:
    device_id: str | None
    model: str | None
    reported_at: datetime | None
    readings: dict[str, Reading] = field(default_factory=dict)

    def raw(self, name: str) -> Any:
        entry = self.readings.get(name)
        return None if entry is None else entry.value

    def units(self, name: str) -> str | None:
        entry = self.readings.get(name)
        return None if entry is None else entry.units

    def has(self, name: str) -> bool:
        return name in self.readings


def parse_timestamp(raw: Any) -> datetime | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    text = raw.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _as_reading(entry: Any) -> Reading:
    if isinstance(entry, dict) and "value" in entry:
        return Reading(value=entry.get("value"), units=entry.get("units"))
    return Reading(value=entry, units=None)


def parse_soh(payload: Any) -> ParsedSoh:
    if not isinstance(payload, dict):
        raise ParseError("SOH 응답이 객체가 아니다")

    device_id = payload.get("deviceId") or payload.get("id")
    model = payload.get("model")
    reported_at = parse_timestamp(payload.get("reportedAt") or payload.get("time"))

    readings: dict[str, Reading] = {}
    raw_readings = payload.get("readings")
    if isinstance(raw_readings, dict):
        for name, entry in raw_readings.items():
            if isinstance(name, str) and name:
                readings[name] = _as_reading(entry)

    if not readings:
        raise ParseError("readings 를 하나도 찾지 못했다")

    return ParsedSoh(
        device_id=str(device_id) if device_id else None,
        model=str(model) if model else None,
        reported_at=reported_at,
        readings=readings,
    )
