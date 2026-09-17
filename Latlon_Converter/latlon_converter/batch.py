"""CSV 일괄 조회."""

from __future__ import annotations

import csv
import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import Callable, Iterable, Sequence

from .errors import AuthError, InputError, LatlonError, QuotaError
from .models import LookupResult
from .service import LandLookupService, LookupOptions

LAT_ALIASES: tuple[str, ...] = ("위도", "latitude", "lat", "Latitude", "LAT")
LON_ALIASES: tuple[str, ...] = ("경도", "longitude", "lon", "lng", "Longitude", "LON")
CRS_ALIASES: tuple[str, ...] = ("좌표계", "crs", "datum", "CRS", "좌표기준")

_WGS84_MARKERS = {"wgs84", "wgs", "gps", "세계", "세계측지계", "위경도"}
_TOKYO_MARKERS = {"tokyo", "bessel", "동경", "동경측지계", "지적", "구지적"}


def detect_column(fieldnames: Sequence[str], explicit: str | None, aliases: Iterable[str], kind: str) -> str:
    """헤더에서 좌표 컬럼을 찾는다."""
    names = [name for name in fieldnames if name]
    if explicit:
        if explicit not in names:
            raise InputError(f"입력 CSV에 '{explicit}' 컬럼이 없습니다. 헤더: {', '.join(names)}")
        return explicit

    lowered = {name.strip().lower(): name for name in names}
    for alias in aliases:
        if alias in names:
            return alias
        if alias.lower() in lowered:
            return lowered[alias.lower()]
    raise InputError(f"{kind} 컬럼을 찾지 못했습니다. --lat-col/--lon-col로 지정하세요. 헤더: {', '.join(names)}")


def detect_optional_column(
    fieldnames: Sequence[str],
    explicit: str | None,
    aliases: Iterable[str],
    kind: str,
) -> str | None:
    """있으면 쓰고, 없으면 None. 이름을 지정했는데 없을 때만 오류."""
    if explicit:
        return detect_column(fieldnames, explicit, aliases, kind)
    try:
        return detect_column(fieldnames, None, aliases, kind)
    except InputError:
        return None


def parse_crs(value: str | None, default: str, line: int | None = None) -> str:
    """행의 좌표계 값을 wgs84/tokyo로 맞춘다. 비어 있으면 default."""
    text = (value or "").strip()
    if not text:
        return default
    key = text.replace(" ", "").replace("_", "").lower()
    if key in _WGS84_MARKERS:
        return "wgs84"
    if key in _TOKYO_MARKERS:
        return "tokyo"
    where = f"{line}행: " if line is not None else ""
    raise InputError(f"{where}알 수 없는 좌표계입니다: {text} (wgs84 또는 tokyo)")


def read_rows(path: str | Path) -> tuple[list[str], list[dict[str, str]]]:
    """입력 CSV를 읽는다. BOM이 붙은 엑셀 저장본도 그대로 읽힌다."""
    csv_path = Path(path)
    if not csv_path.is_file():
        raise InputError(f"입력 파일을 찾을 수 없습니다: {csv_path}")
    with csv_path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        rows = [dict(row) for row in reader]
    if not fieldnames:
        raise InputError(f"입력 CSV에 헤더가 없습니다: {csv_path}")
    return fieldnames, rows


def _parse_coord(value: str | None, kind: str, line: int) -> float:
    text = (value or "").strip()
    if not text:
        raise InputError(f"{line}행: {kind} 값이 비어 있습니다")
    try:
        return float(text)
    except ValueError as exc:
        raise InputError(f"{line}행: {kind} 값이 숫자가 아닙니다: {text}") from exc


def run_batch(
    service: LandLookupService,
    rows: list[dict[str, str]],
    lat_col: str,
    lon_col: str,
    options: LookupOptions | None = None,
    sleep: float = 0.0,
    limit: int | None = None,
    progress: Callable[[str], None] | None = None,
    crs_col: str | None = None,
) -> list[tuple[dict[str, str], LookupResult]]:
    """행마다 조회한다. 인증/한도 오류가 아니면 실패 행을 기록하고 계속한다."""
    options = options or LookupOptions()
    report = progress or (lambda message: print(message, file=sys.stderr))
    target = rows[:limit] if limit else rows
    total = len(target)
    results: list[tuple[dict[str, str], LookupResult]] = []
    skip_cols = {lat_col, lon_col}

    for index, row in enumerate(target, start=1):
        passthrough = {name: value for name, value in row.items() if name not in skip_cols}
        try:
            lat = _parse_coord(row.get(lat_col), "위도", index + 1)
            lon = _parse_coord(row.get(lon_col), "경도", index + 1)
            crs = parse_crs(row.get(crs_col) if crs_col else None, options.crs, index + 1)
        except InputError as exc:
            result = LookupResult()
            result.warnings.append(f"[오류] {exc}")
            results.append((passthrough, result))
            report(f"[{index}/{total}] 건너뜀 — {exc}")
            continue

        row_options = replace(options, crs=crs)
        try:
            result = service.lookup_point(lat, lon, row_options)
        except (AuthError, QuotaError):
            raise
        except LatlonError as exc:
            result = LookupResult(lat=lat, lon=lon)
            result.warnings.append(f"[오류] {exc}")
            report(f"[{index}/{total}] 실패 — {exc}")
        else:
            label = result.parcel.jibun_address if result.parcel else "필지 없음"
            report(f"[{index}/{total}] {lat:.5f}, {lon:.5f} ({crs}) → {label}")

        results.append((passthrough, result))
        if sleep and index < total:
            time.sleep(sleep)

    return results
