"""엑셀 읽기/쓰기와 템플릿 생성."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Any

import pandas as pd
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.utils.dataframe import dataframe_to_rows
from openpyxl.worksheet.datavalidation import DataValidation
from sqlalchemy.orm import Session

from .catalog import catalog_map
from .columns import (
    ALIAS_TO_CANONICAL,
    CANONICAL_FIELDS,
    CHANNEL_FIELDS,
    EXCEL_SHEET_CHANNELS,
    EXCEL_SHEET_DATALOGGERS,
    EXCEL_SHEET_SENSORS,
    FIELDS,
    KOREAN_HEADERS,
    NETWORK_FIELDS,
    REQUIRED_CHANNEL_FIELDS,
    STATION_FIELDS,
    normalize_header,
    resolve_header,
)
from .errors import ValidationError
from .models import Channel, EquipmentCatalog, Network, Station
from .validation import (
    as_str,
    infer_az_dip,
    is_blank,
    parse_float,
    parse_time,
    validate_lat_lon,
    validate_sample_rate,
    validate_time_order,
)


def _normalize_headers(columns: list[Any]) -> list[str]:
    resolved: list[str] = []
    unknown: list[str] = []
    seen: set[str] = set()
    for raw in columns:
        name = str(raw).strip()
        if not name or name.startswith("Unnamed"):
            continue
        canonical = resolve_header(name)
        if canonical is None:
            unknown.append(name)
            continue
        if canonical in seen:
            raise ValidationError(f"엑셀 헤더가 중복됩니다: {name} ({canonical})")
        seen.add(canonical)
        resolved.append(canonical)
    if unknown:
        raise ValidationError(
            "알 수 없는 엑셀 열입니다: "
            + ", ".join(unknown)
            + ". 템플릿 헤더만 사용하세요."
        )
    return resolved


def _row_to_dict(raw: dict[str, Any], excel_row: int) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for spec in FIELDS:
        out[spec.canonical] = raw.get(spec.canonical)
    missing = [KOREAN_HEADERS[f] for f in REQUIRED_CHANNEL_FIELDS if is_blank(out.get(f))]
    if missing:
        raise ValidationError(f"{excel_row}행: 필수 열이 비어 있습니다: {', '.join(missing)}")
    return out


def parse_channel_sheet(df: pd.DataFrame) -> list[dict[str, Any]]:
    if df.empty:
        raise ValidationError("채널 시트가 비어 있습니다")
    df = df.rename(columns=lambda c: resolve_header(str(c)) or str(c))
    _normalize_headers(list(df.columns))
    rows: list[dict[str, Any]] = []
    for idx, series in df.iterrows():
        excel_row = int(idx) + 2
        raw = series.to_dict()
        if all(is_blank(v) for v in raw.values()):
            continue
        rows.append(_row_to_dict(raw, excel_row) | {"_excel_row": excel_row})
    if not rows:
        raise ValidationError("유효한 채널 행이 없습니다")
    return rows


def parse_catalog_sheet(df: pd.DataFrame, kind: str) -> list[dict[str, Any]]:
    if df is None or df.empty:
        return []
    rename = {}
    for col in df.columns:
        key = normalize_header(str(col))
        mapping = {
            "id": "code",
            "code": "code",
            "장비id": "code",
            "manufacturer": "manufacturer",
            "제조사": "manufacturer",
            "model": "model",
            "모델": "model",
            "sample_rate": "sample_rate",
            "샘플링레이트": "sample_rate",
            "nrl_keys": "nrl_keys",
            "nrl키": "nrl_keys",
        }
        if key not in mapping:
            raise ValidationError(f"카탈로그 시트의 알 수 없는 열: {col}")
        rename[col] = mapping[key]
    df = df.rename(columns=rename)
    items: list[dict[str, Any]] = []
    for _, series in df.iterrows():
        code = as_str(series.get("code"))
        if not code:
            continue
        items.append(
            {
                "kind": kind,
                "code": code,
                "manufacturer": as_str(series.get("manufacturer")),
                "model": as_str(series.get("model")),
                "sample_rate": parse_float(series.get("sample_rate"), "sample_rate")
                if kind == "datalogger"
                else None,
                "nrl_keys": as_str(series.get("nrl_keys")) or None,
            }
        )
    return items


def rows_to_hierarchy(rows: list[dict[str, Any]]) -> dict[str, Any]:
    networks: dict[str, dict[str, Any]] = {}
    for raw in rows:
        excel_row = raw["_excel_row"]
        net_code = as_str(raw["network"])
        sta_code = as_str(raw["station"])
        net = networks.setdefault(
            net_code,
            {
                "code": net_code,
                "description": as_str(raw.get("network_description")) or None,
                "operator_agency": as_str(raw.get("operator_agency")) or None,
                "restricted_status": as_str(raw.get("restricted_status")) or None,
                "stations": {},
                "_rows": {excel_row},
            },
        )
        _assert_same(net, "description", raw.get("network_description"), "네트워크설명", excel_row)
        _assert_same(net, "operator_agency", raw.get("operator_agency"), "운영기관", excel_row)
        _assert_same(net, "restricted_status", raw.get("restricted_status"), "공개제한", excel_row)

        lat = parse_float(raw["latitude"], "위도", excel_row)
        lon = parse_float(raw["longitude"], "경도", excel_row)
        if lat is None or lon is None:
            raise ValidationError(f"{excel_row}행: 위도/경도는 필수입니다")
        validate_lat_lon(lat, lon, excel_row)
        elev = parse_float(raw.get("elevation"), "고도", excel_row)
        elevation_warning = elev is None or elev == 0
        if elev is None:
            elev = 0.0

        sta = net["stations"].setdefault(
            sta_code,
            {
                "code": sta_code,
                "latitude": lat,
                "longitude": lon,
                "elevation": elev,
                "site_name": as_str(raw.get("site_name")) or None,
                "site_description": as_str(raw.get("site_description")) or None,
                "site_town": as_str(raw.get("site_town")) or None,
                "site_region": as_str(raw.get("site_region")) or None,
                "site_country": as_str(raw.get("site_country")) or None,
                "vault": as_str(raw.get("vault")) or None,
                "geology": as_str(raw.get("geology")) or None,
                "description": as_str(raw.get("station_description")) or None,
                "creation_date": _time_str(raw.get("creation_date"), "설치일", excel_row),
                "termination_date": _time_str(raw.get("termination_date"), "철거일", excel_row),
                "channels": [],
                "elevation_warning": elevation_warning,
            },
        )
        for key, field, label in [
            ("latitude", lat, "위도"),
            ("longitude", lon, "경도"),
            ("elevation", elev, "고도"),
            ("site_name", as_str(raw.get("site_name")) or None, "관측소명"),
            ("site_description", as_str(raw.get("site_description")) or None, "위치설명"),
            ("site_town", as_str(raw.get("site_town")) or None, "시군구"),
            ("site_region", as_str(raw.get("site_region")) or None, "지역"),
            ("site_country", as_str(raw.get("site_country")) or None, "국가"),
            ("vault", as_str(raw.get("vault")) or None, "설치환경"),
            ("geology", as_str(raw.get("geology")) or None, "지질"),
            ("description", as_str(raw.get("station_description")) or None, "관측소설명"),
            ("creation_date", _time_str(raw.get("creation_date"), "설치일", excel_row), "설치일"),
            (
                "termination_date",
                _time_str(raw.get("termination_date"), "철거일", excel_row),
                "철거일",
            ),
        ]:
            if sta[key] != field:
                raise ValidationError(
                    f"{excel_row}행: 같은 관측소 {net_code}.{sta_code}의 {label} 값이 다른 행과 다릅니다"
                )

        start = parse_time(raw["start_time"], "시작시간", excel_row)
        end = parse_time(raw.get("end_time"), "끝시간", excel_row)
        if start is None:
            raise ValidationError(f"{excel_row}행: 시작시간은 필수입니다")
        validate_time_order(start, end, "시작시간", "끝시간", excel_row)
        creation = parse_time(raw.get("creation_date"), "설치일", excel_row)
        termination = parse_time(raw.get("termination_date"), "철거일", excel_row)
        validate_time_order(creation, termination, "설치일", "철거일", excel_row)

        rate = parse_float(raw["sample_rate"], "샘플링레이트", excel_row)
        if rate is None:
            raise ValidationError(f"{excel_row}행: 샘플링레이트는 필수입니다")
        validate_sample_rate(rate, excel_row)

        channel_code = as_str(raw["channel"])
        az = parse_float(raw.get("azimuth"), "방위각", excel_row)
        dip = parse_float(raw.get("dip"), "경사", excel_row)
        if az is None or dip is None:
            inf_az, inf_dip = infer_az_dip(channel_code)
            az = inf_az if az is None else az
            dip = inf_dip if dip is None else dip

        sta["channels"].append(
            {
                "location": as_str(raw.get("location")),
                "channel": channel_code,
                "start_time": start.isoformat(),
                "end_time": end.isoformat() if end else None,
                "sample_rate": rate,
                "depth": parse_float(raw.get("depth"), "심도", excel_row) or 0.0,
                "azimuth": az,
                "dip": dip,
                "description": as_str(raw.get("channel_description")) or None,
                "comment": as_str(raw.get("comment")) or None,
                "channel_types": as_str(raw.get("channel_types")) or None,
                "clock_drift": parse_float(raw.get("clock_drift"), "시각오차", excel_row),
                "latitude": parse_float(raw.get("channel_latitude"), "채널위도", excel_row),
                "longitude": parse_float(raw.get("channel_longitude"), "채널경도", excel_row),
                "elevation": parse_float(raw.get("channel_elevation"), "채널고도", excel_row),
                "sensor_id": as_str(raw.get("sensor_id")) or None,
                "sensor_serial": as_str(raw.get("sensor_serial")) or None,
                "sensor_type": as_str(raw.get("sensor_type")) or None,
                "sensor_install_date": _time_str(raw.get("sensor_install_date"), "센서설치일", excel_row),
                "sensor_remove_date": _time_str(raw.get("sensor_remove_date"), "센서철거일", excel_row),
                "datalogger_id": as_str(raw.get("datalogger_id")) or None,
                "datalogger_serial": as_str(raw.get("datalogger_serial")) or None,
                "datalogger_type": as_str(raw.get("datalogger_type")) or None,
                "datalogger_install_date": _time_str(
                    raw.get("datalogger_install_date"), "기록계설치일", excel_row
                ),
                "datalogger_remove_date": _time_str(
                    raw.get("datalogger_remove_date"), "기록계철거일", excel_row
                ),
                "_excel_row": excel_row,
            }
        )
    return {"networks": networks}


def _assert_same(store: dict[str, Any], key: str, value: Any, label: str, excel_row: int) -> None:
    normalized = as_str(value) or None
    current = store.get(key)
    if current in (None, "") and normalized:
        store[key] = normalized
        return
    if normalized in (None, "") or current == normalized:
        return
    raise ValidationError(
        f"{excel_row}행: 같은 네트워크의 {label} 값이 다른 행과 다릅니다 ({current} vs {normalized})"
    )


def _time_str(value: Any, field: str, excel_row: int) -> str | None:
    parsed = parse_time(value, field, excel_row)
    return parsed.isoformat() if parsed else None


def read_excel(path_or_buf) -> dict[str, Any]:
    xls = pd.ExcelFile(path_or_buf, engine="openpyxl")
    if EXCEL_SHEET_CHANNELS not in xls.sheet_names and "Sheet1" not in xls.sheet_names:
        # first sheet as channels if named differently but has headers
        sheet = xls.sheet_names[0]
    else:
        sheet = EXCEL_SHEET_CHANNELS if EXCEL_SHEET_CHANNELS in xls.sheet_names else xls.sheet_names[0]
    channels_df = pd.read_excel(xls, sheet_name=sheet)
    hierarchy = rows_to_hierarchy(parse_channel_sheet(channels_df))
    sensors = []
    dataloggers = []
    if EXCEL_SHEET_SENSORS in xls.sheet_names:
        sensors = parse_catalog_sheet(pd.read_excel(xls, sheet_name=EXCEL_SHEET_SENSORS), "sensor")
    if EXCEL_SHEET_DATALOGGERS in xls.sheet_names:
        dataloggers = parse_catalog_sheet(
            pd.read_excel(xls, sheet_name=EXCEL_SHEET_DATALOGGERS), "datalogger"
        )
    hierarchy["catalog"] = {"sensors": sensors, "dataloggers": dataloggers}
    return hierarchy


def write_excel(session: Session) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = EXCEL_SHEET_CHANNELS
    headers = [KOREAN_HEADERS[s.canonical] for s in FIELDS]
    ws.append(headers)
    header_fill = PatternFill("solid", fgColor="1F4E79")
    header_font = Font(color="FFFFFF", bold=True)
    for cell in ws[1]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(wrap_text=True)

    q = (
        session.query(Channel)
        .join(Station)
        .join(Network)
        .order_by(Network.code, Station.code, Channel.location, Channel.channel, Channel.start_time)
    )
    for ch in q.all():
        sta = ch.station
        net = sta.network
        row = {
            "network": net.code,
            "network_description": net.description,
            "operator_agency": net.operator_agency,
            "restricted_status": net.restricted_status,
            "station": sta.code,
            "latitude": sta.latitude,
            "longitude": sta.longitude,
            "elevation": sta.elevation,
            "site_name": sta.site_name,
            "site_description": sta.site_description,
            "site_town": sta.site_town,
            "site_region": sta.site_region,
            "site_country": sta.site_country,
            "vault": sta.vault,
            "geology": sta.geology,
            "station_description": sta.description,
            "creation_date": sta.creation_date,
            "termination_date": sta.termination_date,
            "channel": ch.channel,
            "start_time": ch.start_time,
            "sample_rate": ch.sample_rate,
            "location": ch.location,
            "depth": ch.depth,
            "end_time": ch.end_time,
            "azimuth": ch.azimuth,
            "dip": ch.dip,
            "channel_description": ch.description,
            "comment": ch.comment,
            "channel_types": ch.channel_types,
            "clock_drift": ch.clock_drift,
            "channel_latitude": ch.latitude,
            "channel_longitude": ch.longitude,
            "channel_elevation": ch.elevation,
            "sensor_id": ch.sensor_id,
            "sensor_serial": ch.sensor_serial,
            "sensor_type": ch.sensor_type,
            "sensor_install_date": ch.sensor_install_date,
            "sensor_remove_date": ch.sensor_remove_date,
            "datalogger_id": ch.datalogger_id,
            "datalogger_serial": ch.datalogger_serial,
            "datalogger_type": ch.datalogger_type,
            "datalogger_install_date": ch.datalogger_install_date,
            "datalogger_remove_date": ch.datalogger_remove_date,
        }
        ws.append([row.get(spec.canonical) for spec in FIELDS])

    _write_catalog_sheet(
        wb,
        EXCEL_SHEET_SENSORS,
        session.query(EquipmentCatalog).filter_by(kind="sensor").all(),
        False,
    )
    _write_catalog_sheet(
        wb,
        EXCEL_SHEET_DATALOGGERS,
        session.query(EquipmentCatalog).filter_by(kind="datalogger").all(),
        True,
    )

    sensor_codes = [
        r.code for r in session.query(EquipmentCatalog).filter_by(kind="sensor").all()
    ]
    logger_codes = [
        r.code for r in session.query(EquipmentCatalog).filter_by(kind="datalogger").all()
    ]
    _add_dropdown(ws, "센서ID", sensor_codes, EXCEL_SHEET_SENSORS)
    _add_dropdown(ws, "기록계ID", logger_codes, EXCEL_SHEET_DATALOGGERS)

    for idx, _ in enumerate(headers, start=1):
        ws.column_dimensions[get_column_letter(idx)].width = 16
    ws.auto_filter.ref = ws.dimensions
    ws.freeze_panes = "A2"

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def write_template(session: Session | None = None) -> bytes:
    if session is not None:
        return write_excel(session)
    # catalog-only template with example row
    wb = Workbook()
    ws = wb.active
    ws.title = EXCEL_SHEET_CHANNELS
    headers = [KOREAN_HEADERS[s.canonical] for s in FIELDS]
    ws.append(headers)
    example = {s.canonical: "" for s in FIELDS}
    example.update(
        {
            "network": "XX",
            "station": "TEST",
            "latitude": 37.5,
            "longitude": 127.0,
            "elevation": 80,
            "site_name": "예시 관측소",
            "channel": "HHZ",
            "start_time": "2020-01-01",
            "sample_rate": 100,
            "location": "",
            "sensor_id": "Guralp_CMG-3T",
            "datalogger_id": "REFTEK_RT130_100sps",
        }
    )
    ws.append([example.get(s.canonical) for s in FIELDS])
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _write_catalog_sheet(wb: Workbook, title: str, rows: list[EquipmentCatalog], with_rate: bool) -> None:
    ws = wb.create_sheet(title)
    headers = ["id", "manufacturer", "model"]
    if with_rate:
        headers.append("sample_rate")
    headers.append("nrl_keys")
    ws.append(headers)
    for row in rows:
        values = [row.code, row.manufacturer, row.model]
        if with_rate:
            values.append(row.sample_rate)
        values.append(row.nrl_keys)
        ws.append(values)


def _add_dropdown(ws, header_name: str, codes: list[str], sheet: str) -> None:
    if not codes:
        return
    col_idx = None
    for cell in ws[1]:
        if cell.value == header_name:
            col_idx = cell.column
            break
    if col_idx is None:
        return
    letter = get_column_letter(col_idx)
    formula = f"={sheet}!$A$2:$A$200"
    dv = DataValidation(type="list", formula1=formula, allow_blank=True)
    dv.error = "카탈로그에 있는 장비 ID만 선택할 수 있습니다"
    dv.errorTitle = "잘못된 장비 ID"
    dv.prompt = "카탈로그에서 선택하세요"
    dv.promptTitle = header_name
    ws.add_data_validation(dv)
    dv.add(f"{letter}2:{letter}2000")


def write_template_file(path: Path, session: Session | None = None) -> None:
    path.write_bytes(write_excel(session) if session is not None else _full_seed_template())


def _full_seed_template() -> bytes:
    from .catalog import load_seed_yaml
    from .db import SessionLocal, init_db
    from .models import EquipmentCatalog

    init_db()
    session = SessionLocal()
    try:
        if session.query(EquipmentCatalog).first() is None:
            data = load_seed_yaml()
            for item in data["sensors"]:
                session.add(
                    EquipmentCatalog(
                        kind="sensor",
                        code=item["id"],
                        manufacturer=item["manufacturer"],
                        model=item["model"],
                        nrl_keys=item.get("nrl_keys") or None,
                    )
                )
            for item in data["dataloggers"]:
                session.add(
                    EquipmentCatalog(
                        kind="datalogger",
                        code=item["id"],
                        manufacturer=item["manufacturer"],
                        model=item["model"],
                        sample_rate=item.get("sample_rate"),
                        nrl_keys=item.get("nrl_keys") or None,
                    )
                )
            session.commit()
        return write_excel(session)
    finally:
        session.close()
