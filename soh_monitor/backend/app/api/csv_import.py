"""관측소 CSV 일괄 등록.

오류 행만 실패하고 나머지는 등록한다. 스프레드시트 수식 주입(=, +, @ 등)은
저장하지 않는다. 저장된 값이 나중에 내보내져 열렸을 때 수식으로 실행되면
운영자 환경이 위험해진다.
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from typing import Any

FORMULA_PREFIXES = ("=", "+", "@", "\t", "\r", "\n")
STATION_CODE_RE = re.compile(r"^[A-Za-z0-9_]{1,16}$")
NETWORK_CODE_RE = re.compile(r"^[A-Za-z0-9]{1,8}$")

HEADER_ALIASES = {
    "networkcode": "network_code",
    "network_code": "network_code",
    "stationcode": "station_code",
    "station_code": "station_code",
    "name": "name",
    "latitude": "latitude",
    "longitude": "longitude",
    "elevationm": "elevation_m",
    "elevation_m": "elevation_m",
    "regioncode": "region_code",
    "region_code": "region_code",
    "timezone": "timezone",
    "hostname": "hostname",
    "port": "port",
    "adapterkey": "adapter_key",
    "adapter_key": "adapter_key",
    "credentialreference": "credential_reference",
    "credential_reference": "credential_reference",
    "instrumentid": "instrument_id",
    "instrument_id": "instrument_id",
    "serialnumber": "serial_number",
    "serial_number": "serial_number",
    "scheme": "scheme",
    "datasourceuri": "data_source_uri",
    "data_source_uri": "data_source_uri",
}


@dataclass
class CsvRowError:
    row: int
    field: str | None
    message: str


@dataclass
class ParsedStationRow:
    row_number: int
    network_code: str
    station_code: str
    name: str
    latitude: float | None = None
    longitude: float | None = None
    elevation_m: float | None = None
    region_code: str | None = None
    timezone: str = "Asia/Seoul"
    hostname: str | None = None
    port: int | None = None
    adapter_key: str = "nanometrics.centaur.ctr"
    credential_reference: str | None = None
    instrument_id: str | None = None
    serial_number: str | None = None
    scheme: str = "http"
    data_source_uri: str | None = None


@dataclass
class CsvImportResult:
    rows: list[ParsedStationRow] = field(default_factory=list)
    errors: list[CsvRowError] = field(default_factory=list)

    @property
    def has_rows(self) -> bool:
        return bool(self.rows)


def _normalize_header(raw: str) -> str:
    return HEADER_ALIASES.get(raw.strip().lstrip("\ufeff").lower().replace("-", ""), "")


def looks_like_formula(value: str) -> bool:
    text = value.lstrip()
    if not text:
        return False
    if text[0] in FORMULA_PREFIXES:
        return True
    if text[0] == "-" and not _is_number(text):
        return True
    return False


def _is_number(value: str) -> bool:
    try:
        float(value)
    except ValueError:
        return False
    return True


def _cell(row: dict[str, str], key: str) -> str:
    return (row.get(key) or "").strip()


def _optional_float(row_number: int, field: str, raw: str) -> tuple[float | None, CsvRowError | None]:
    if not raw:
        return None, None
    try:
        return float(raw), None
    except ValueError:
        return None, CsvRowError(row_number, field, f"{field} 는 숫자여야 한다")


def parse_stations_csv(content: str) -> CsvImportResult:
    result = CsvImportResult()
    if not content or not content.strip():
        result.errors.append(CsvRowError(0, None, "CSV 내용이 비어 있다"))
        return result

    reader = csv.DictReader(io.StringIO(content))
    if reader.fieldnames is None:
        result.errors.append(CsvRowError(0, None, "헤더 행이 없다"))
        return result

    mapping: dict[str, str] = {}
    for raw in reader.fieldnames:
        if raw is None:
            continue
        key = _normalize_header(raw)
        if key:
            mapping[raw] = key

    required = {"network_code", "station_code", "name"}
    if required - set(mapping.values()):
        result.errors.append(
            CsvRowError(0, None, "필수 열(networkCode, stationCode, name)이 없다")
        )
        return result

    seen: set[tuple[str, str]] = set()
    for index, raw_row in enumerate(reader, start=2):
        normalized = {mapping[src]: (value or "").strip() for src, value in raw_row.items() if src in mapping}

        formula_field = next(
            (field for field, value in normalized.items() if value and looks_like_formula(value)),
            None,
        )
        if formula_field:
            result.errors.append(
                CsvRowError(index, formula_field, "스프레드시트 수식으로 보이는 값은 받을 수 없다")
            )
            continue

        network = _cell(normalized, "network_code").upper()
        station = _cell(normalized, "station_code").upper()
        name = _cell(normalized, "name")
        if not NETWORK_CODE_RE.match(network):
            result.errors.append(CsvRowError(index, "networkCode", "네트워크 코드 형식이 잘못됐다"))
            continue
        if not STATION_CODE_RE.match(station):
            result.errors.append(CsvRowError(index, "stationCode", "관측소 코드 형식이 잘못됐다"))
            continue
        if not name:
            result.errors.append(CsvRowError(index, "name", "이름이 비어 있다"))
            continue

        key = (network, station)
        if key in seen:
            result.errors.append(CsvRowError(index, "stationCode", "파일 안에서 관측소가 중복됐다"))
            continue
        seen.add(key)

        latitude, lat_error = _optional_float(index, "latitude", _cell(normalized, "latitude"))
        if lat_error:
            result.errors.append(lat_error)
            continue
        longitude, lon_error = _optional_float(index, "longitude", _cell(normalized, "longitude"))
        if lon_error:
            result.errors.append(lon_error)
            continue
        elevation, el_error = _optional_float(index, "elevationM", _cell(normalized, "elevation_m"))
        if el_error:
            result.errors.append(el_error)
            continue

        port_raw = _cell(normalized, "port")
        port: int | None = None
        if port_raw:
            try:
                port = int(port_raw)
            except ValueError:
                result.errors.append(CsvRowError(index, "port", "포트는 정수여야 한다"))
                continue
            if not 1 <= port <= 65535:
                result.errors.append(CsvRowError(index, "port", "포트는 1~65535 범위여야 한다"))
                continue

        scheme = (_cell(normalized, "scheme") or "http").lower()
        if scheme not in {"http", "https"}:
            result.errors.append(CsvRowError(index, "scheme", "scheme 은 http 또는 https 여야 한다"))
            continue

        credential = _cell(normalized, "credential_reference") or None
        if credential and ":" not in credential:
            result.errors.append(
                CsvRowError(index, "credentialReference", "인증정보 참조는 env: 또는 file: 형식이어야 한다")
            )
            continue
        if credential and looks_like_password_literal(credential):
            result.errors.append(
                CsvRowError(index, "credentialReference", "비밀번호 평문을 넣을 수 없다")
            )
            continue

        result.rows.append(
            ParsedStationRow(
                row_number=index,
                network_code=network,
                station_code=station,
                name=name,
                latitude=latitude,
                longitude=longitude,
                elevation_m=elevation,
                region_code=_cell(normalized, "region_code").upper() or None,
                timezone=_cell(normalized, "timezone") or "Asia/Seoul",
                hostname=_cell(normalized, "hostname") or None,
                port=port,
                adapter_key=_cell(normalized, "adapter_key") or "nanometrics.centaur.ctr",
                credential_reference=credential,
                instrument_id=_cell(normalized, "instrument_id") or None,
                serial_number=_cell(normalized, "serial_number") or None,
                scheme=scheme,
                data_source_uri=_cell(normalized, "data_source_uri") or None,
            )
        )

    return result


def looks_like_password_literal(value: str) -> bool:
    scheme, _, _ = value.partition(":")
    return scheme.lower() not in {"env", "file"}


def row_to_dict(row: ParsedStationRow) -> dict[str, Any]:
    return {
        "networkCode": row.network_code,
        "stationCode": row.station_code,
        "name": row.name,
        "hostname": row.hostname,
        "adapterKey": row.adapter_key,
    }
