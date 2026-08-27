"""엑셀 헤더 별칭과 필드 수준(네트워크/관측소/채널) 정의."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FieldSpec:
    canonical: str
    aliases: tuple[str, ...]
    level: str  # network | station | channel
    required: bool = False


FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec("network", ("network", "네트워크", "net"), "network", True),
    FieldSpec(
        "network_description",
        ("network_description", "네트워크설명", "network_desc"),
        "network",
    ),
    FieldSpec(
        "operator_agency",
        ("operator_agency", "운영기관", "operator", "agency"),
        "network",
    ),
    FieldSpec(
        "restricted_status",
        ("restricted_status", "공개제한"),
        "network",
    ),
    FieldSpec("station", ("station", "관측소", "sta"), "station", True),
    FieldSpec("latitude", ("latitude", "위도", "lat"), "station", True),
    FieldSpec("longitude", ("longitude", "경도", "lon", "lng"), "station", True),
    FieldSpec("elevation", ("elevation", "고도", "elev"), "station"),
    FieldSpec("site_name", ("site_name", "관측소명", "sitename"), "station"),
    FieldSpec(
        "site_description",
        ("site_description", "위치설명"),
        "station",
    ),
    FieldSpec("site_town", ("site_town", "시군구", "town"), "station"),
    FieldSpec("site_region", ("site_region", "지역", "region"), "station"),
    FieldSpec("site_country", ("site_country", "국가", "country"), "station"),
    FieldSpec("vault", ("vault", "설치환경"), "station"),
    FieldSpec("geology", ("geology", "지질"), "station"),
    FieldSpec(
        "station_description",
        ("station_description", "관측소설명"),
        "station",
    ),
    FieldSpec("creation_date", ("creation_date", "설치일"), "station"),
    FieldSpec("termination_date", ("termination_date", "철거일"), "station"),
    FieldSpec("channel", ("channel", "채널", "cha"), "channel", True),
    FieldSpec("start_time", ("start_time", "시작시간", "start"), "channel", True),
    FieldSpec(
        "sample_rate",
        ("sample_rate", "샘플링레이트", "sampling_rate", "sps"),
        "channel",
        True,
    ),
    FieldSpec("location", ("location", "위치코드", "loc", "location_code"), "channel"),
    FieldSpec("depth", ("depth", "심도"), "channel"),
    FieldSpec("end_time", ("end_time", "끝시간", "end"), "channel"),
    FieldSpec("azimuth", ("azimuth", "방위각", "az"), "channel"),
    FieldSpec("dip", ("dip", "경사"), "channel"),
    FieldSpec(
        "channel_description",
        ("channel_description", "채널설명"),
        "channel",
    ),
    FieldSpec("comment", ("comment", "비고", "comments"), "channel"),
    FieldSpec(
        "channel_types",
        ("channel_types", "채널유형", "types"),
        "channel",
    ),
    FieldSpec("clock_drift", ("clock_drift", "시각오차"), "channel"),
    FieldSpec(
        "channel_latitude",
        ("channel_latitude", "채널위도"),
        "channel",
    ),
    FieldSpec(
        "channel_longitude",
        ("channel_longitude", "채널경도"),
        "channel",
    ),
    FieldSpec(
        "channel_elevation",
        ("channel_elevation", "채널고도"),
        "channel",
    ),
    FieldSpec("sensor_id", ("sensor_id", "센서ID", "sensor"), "channel"),
    FieldSpec(
        "sensor_serial",
        ("sensor_serial", "센서일련번호"),
        "channel",
    ),
    FieldSpec("sensor_type", ("sensor_type", "센서유형"), "channel"),
    FieldSpec(
        "sensor_install_date",
        ("sensor_install_date", "센서설치일"),
        "channel",
    ),
    FieldSpec(
        "sensor_remove_date",
        ("sensor_remove_date", "센서철거일"),
        "channel",
    ),
    FieldSpec(
        "datalogger_id",
        ("datalogger_id", "기록계ID", "datalogger", "logger_id"),
        "channel",
    ),
    FieldSpec(
        "datalogger_serial",
        ("datalogger_serial", "기록계일련번호"),
        "channel",
    ),
    FieldSpec(
        "datalogger_type",
        ("datalogger_type", "기록계유형"),
        "channel",
    ),
    FieldSpec(
        "datalogger_install_date",
        ("datalogger_install_date", "기록계설치일"),
        "channel",
    ),
    FieldSpec(
        "datalogger_remove_date",
        ("datalogger_remove_date", "기록계철거일"),
        "channel",
    ),
)

ALIAS_TO_CANONICAL: dict[str, str] = {}
for _spec in FIELDS:
    for _alias in _spec.aliases:
        ALIAS_TO_CANONICAL[_alias.strip().lower()] = _spec.canonical

CANONICAL_FIELDS: dict[str, FieldSpec] = {s.canonical: s for s in FIELDS}

REQUIRED_CHANNEL_FIELDS = tuple(s.canonical for s in FIELDS if s.required)

NETWORK_FIELDS = tuple(s.canonical for s in FIELDS if s.level == "network")
STATION_FIELDS = tuple(s.canonical for s in FIELDS if s.level == "station")
CHANNEL_FIELDS = tuple(s.canonical for s in FIELDS if s.level == "channel")

EXCEL_SHEET_CHANNELS = "channels"
EXCEL_SHEET_SENSORS = "catalog_sensors"
EXCEL_SHEET_DATALOGGERS = "catalog_dataloggers"

KOREAN_HEADERS: dict[str, str] = {
    "network": "네트워크",
    "network_description": "네트워크설명",
    "operator_agency": "운영기관",
    "restricted_status": "공개제한",
    "station": "관측소",
    "latitude": "위도",
    "longitude": "경도",
    "elevation": "고도",
    "site_name": "관측소명",
    "site_description": "위치설명",
    "site_town": "시군구",
    "site_region": "지역",
    "site_country": "국가",
    "vault": "설치환경",
    "geology": "지질",
    "station_description": "관측소설명",
    "creation_date": "설치일",
    "termination_date": "철거일",
    "channel": "채널",
    "start_time": "시작시간",
    "sample_rate": "샘플링레이트",
    "location": "위치코드",
    "depth": "심도",
    "end_time": "끝시간",
    "azimuth": "방위각",
    "dip": "경사",
    "channel_description": "채널설명",
    "comment": "비고",
    "channel_types": "채널유형",
    "clock_drift": "시각오차",
    "channel_latitude": "채널위도",
    "channel_longitude": "채널경도",
    "channel_elevation": "채널고도",
    "sensor_id": "센서ID",
    "sensor_serial": "센서일련번호",
    "sensor_type": "센서유형",
    "sensor_install_date": "센서설치일",
    "sensor_remove_date": "센서철거일",
    "datalogger_id": "기록계ID",
    "datalogger_serial": "기록계일련번호",
    "datalogger_type": "기록계유형",
    "datalogger_install_date": "기록계설치일",
    "datalogger_remove_date": "기록계철거일",
}


def normalize_header(raw: str) -> str:
    return str(raw).strip().lower().replace(" ", "_")


def resolve_header(raw: str) -> str | None:
    return ALIAS_TO_CANONICAL.get(normalize_header(raw))
