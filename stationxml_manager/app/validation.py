"""공통 값 검사."""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any

from obspy import UTCDateTime

from .errors import ValidationError


def is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    return isinstance(value, str) and not value.strip()


def as_str(value: Any, default: str = "") -> str:
    if is_blank(value):
        return default
    if isinstance(value, datetime):
        return UTCDateTime(value).isoformat()
    text = str(value).strip()
    if text.endswith(".0") and text.replace(".", "", 1).isdigit():
        return text[:-2]
    return text


def parse_float(value: Any, field: str, row: int | None = None) -> float | None:
    if is_blank(value):
        return None
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(_row_msg(row, f"{field} 값이 숫자가 아닙니다: {value}")) from exc


def parse_time(value: Any, field: str, row: int | None = None) -> UTCDateTime | None:
    if is_blank(value):
        return None
    if isinstance(value, UTCDateTime):
        return value
    try:
        if isinstance(value, datetime):
            return UTCDateTime(value)
        return UTCDateTime(str(value).strip())
    except Exception as exc:
        raise ValidationError(
            _row_msg(row, f"{field} 시간 형식을 읽을 수 없습니다: {value}")
        ) from exc


def canonical_time(value: Any, field: str, row: int | None = None) -> str | None:
    """시간 값을 DB/비교용 UTC 문자열 한 형식으로 정규화한다."""
    parsed = parse_time(value, field, row)
    return str(parsed) if parsed is not None else None


def infer_az_dip(channel_code: str) -> tuple[float, float]:
    last = channel_code[-1].upper() if channel_code else ""
    if last == "Z":
        return 0.0, -90.0
    if last in ("N", "1"):
        return 0.0, 0.0
    if last in ("E", "2"):
        return 90.0, 0.0
    return 0.0, 0.0


def validate_lat_lon(lat: float, lon: float, row: int | None = None) -> None:
    if not -90.0 <= lat <= 90.0:
        raise ValidationError(_row_msg(row, f"위도는 -90~90 범위여야 합니다: {lat}"))
    if not -180.0 <= lon <= 180.0:
        raise ValidationError(_row_msg(row, f"경도는 -180~180 범위여야 합니다: {lon}"))


def validate_time_order(
    start: UTCDateTime | None,
    end: UTCDateTime | None,
    start_name: str,
    end_name: str,
    row: int | None = None,
) -> None:
    if start is not None and end is not None and not start < end:
        raise ValidationError(
            _row_msg(row, f"{end_name}은 {start_name}보다 이후여야 합니다")
        )


def validate_sample_rate(rate: float, row: int | None = None) -> None:
    if rate <= 0:
        raise ValidationError(_row_msg(row, f"샘플링레이트는 0보다 커야 합니다: {rate}"))


def sample_rates_match(channel_rate: float, catalog_rate: float | None) -> bool:
    if catalog_rate is None:
        return True
    return abs(float(channel_rate) - float(catalog_rate)) < 1e-3


def _row_msg(row: int | None, message: str) -> str:
    if row is None:
        return message
    return f"{row}행: {message}"
