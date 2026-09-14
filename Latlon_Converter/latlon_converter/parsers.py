"""브이월드 응답 파싱.

`ladfrlList`는 루트가 `fields`, 토지특성/공시지가는 루트가 `response`로
봉투 구조가 서로 다르다. 응답 형태가 조금씩 달라도 견디도록 알려진 키를
재귀로 찾아 쓴다. mock 프로바이더도 같은 파서를 거치므로 두 경로가
같은 스키마를 보증한다.
"""

from __future__ import annotations

from typing import Any

from . import codes
from .errors import AuthError, LatlonError, QuotaError
from .models import LandCharacteristics, LandLedger, Parcel

_AUTH_MARKERS = (
    "INCORRECT_KEY",
    "INVALID_KEY",
    "NOT_APPLICABLE_KEY",
    "NOT REGISTERED",
    "NOT_REGISTERED",
    "UNAUTHORIZED",
    "인증키",
    "도메인",
)
_QUOTA_MARKERS = ("OVER_QUOTA", "SERVICE_LIMIT", "LIMIT_EXCEED", "초과", "한도")


def _as_text(value: Any) -> str:
    """API가 숫자/None/중첩 dict를 섞어 보내도 문자열 한 가지로 맞춘다."""
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return ""
    return str(value).strip()


def find_records(payload: Any, key: str) -> list[dict[str, Any]]:
    """중첩 응답 어디에 있든 `key` 목록을 찾아 dict 리스트로 돌려준다."""
    if isinstance(payload, dict):
        if key in payload:
            found = payload[key]
            if isinstance(found, dict):
                return [found]
            if isinstance(found, list):
                return [item for item in found if isinstance(item, dict)]
        for value in payload.values():
            records = find_records(value, key)
            if records:
                return records
    elif isinstance(payload, list):
        for item in payload:
            records = find_records(item, key)
            if records:
                return records
    return []


def _find_value(payload: Any, key: str) -> Any:
    if isinstance(payload, dict):
        if key in payload:
            return payload[key]
        for value in payload.values():
            found = _find_value(value, key)
            if found is not None:
                return found
    elif isinstance(payload, list):
        for item in payload:
            found = _find_value(item, key)
            if found is not None:
                return found
    return None


def _error_text(payload: Any) -> str:
    """응답에서 오류 메시지를 뽑는다. 오류가 없으면 빈 문자열."""
    error = _find_value(payload, "error")
    if isinstance(error, str) and error.strip():
        return error.strip()
    if isinstance(error, dict):
        code = _as_text(error.get("code"))
        text = _as_text(error.get("text")) or _as_text(error.get("message"))
        return " ".join(part for part in (code, text) if part)

    result_code = _as_text(_find_value(payload, "resultCode"))
    if result_code and result_code not in {"00", "0", "OK", "NORMAL_SERVICE"}:
        message = _as_text(_find_value(payload, "resultMsg"))
        return " ".join(part for part in (result_code, message) if part)
    return ""


def raise_for_error(payload: Any, context: str) -> None:
    """오류 응답이면 종류에 맞는 예외를 던진다."""
    message = _error_text(payload)
    if not message:
        return
    upper = message.upper()
    if any(marker.upper() in upper for marker in _AUTH_MARKERS):
        raise AuthError(
            f"{context}: 인증키 또는 도메인이 올바르지 않습니다 ({message}). "
            "브이월드 인증키 관리의 서비스 URL과 VWORLD_DOMAIN이 같은지 확인하세요."
        )
    if any(marker.upper() in upper for marker in _QUOTA_MARKERS):
        raise QuotaError(f"{context}: 일일 호출 한도를 초과했습니다 ({message})")
    raise LatlonError(f"{context}: {message}")


def parse_cadastral(payload: Any) -> Parcel | None:
    """연속지적도(LP_PA_CBND_BUBUN) GetFeature 응답에서 필지를 읽는다."""
    raise_for_error(payload, "연속지적도 조회")
    features = find_records(payload, "features")
    if not features:
        return None
    properties = features[0].get("properties")
    if not isinstance(properties, dict):
        return None

    pnu = _as_text(properties.get("pnu"))
    if not pnu:
        return None

    address = _as_text(properties.get("addr"))
    jibun = _as_text(properties.get("jibun"))
    return Parcel(
        pnu=pnu,
        jibun_address=address,
        jibun=jibun,
        ld_code=pnu[:10],
        ld_name=_derive_ld_name(address, jibun),
        official_price=_as_text(properties.get("jiga")),
        price_year=_as_text(properties.get("gosi_year")),
        price_month=_as_text(properties.get("gosi_month")),
        source="cadastral",
    )


def _derive_ld_name(address: str, jibun: str) -> str:
    """'서울특별시 강남구 역삼동 808'에서 지번을 떼어 법정동명만 남긴다."""
    if not address:
        return ""
    parts = address.split()
    if not parts:
        return ""
    bonbun = jibun.split()[0] if jibun else ""
    if parts[-1] == bonbun or parts[-1][0].isdigit() or parts[-1].startswith("산"):
        parts = parts[:-1]
        if parts and parts[-1] == "산":
            parts = parts[:-1]
    return " ".join(parts)


def parse_geocoder(payload: Any) -> dict[str, str] | None:
    """Geocoder 2.0 getAddress 응답에서 주소와 법정동코드를 읽는다."""
    raise_for_error(payload, "지오코더 조회")
    status = _as_text(_find_value(payload, "status"))
    if status and status.upper() == "NOT_FOUND":
        return None

    results = _find_value(payload, "result")
    if isinstance(results, dict):
        results = [results]
    if not isinstance(results, list) or not results:
        return None

    parcel_entry: dict[str, Any] | None = None
    road_text = ""
    for entry in results:
        if not isinstance(entry, dict):
            continue
        entry_type = _as_text(entry.get("type")).lower()
        if entry_type == "road":
            road_text = _as_text(entry.get("text"))
            continue
        if parcel_entry is None:
            parcel_entry = entry

    if parcel_entry is None:
        return None
    structure = parcel_entry.get("structure")
    structure = structure if isinstance(structure, dict) else {}
    return {
        "text": _as_text(parcel_entry.get("text")),
        "ld_code": _as_text(structure.get("level4LC")),
        "ld_name": " ".join(
            part
            for part in (
                _as_text(structure.get("level1")),
                _as_text(structure.get("level2")),
                _as_text(structure.get("level4L")),
            )
            if part
        ),
        "jibun": _as_text(structure.get("level5")),
        "road_address": road_text,
    }


def parse_road_address(payload: Any) -> str:
    """type=BOTH 응답에서 도로명주소만 뽑는다."""
    parsed = parse_geocoder(payload)
    return parsed["road_address"] if parsed else ""


def parse_ledger(payload: Any) -> LandLedger | None:
    """토지임야정보(ladfrlList) 응답을 읽는다."""
    raise_for_error(payload, "토지임야정보 조회")
    records = find_records(payload, "ladfrlVOList")
    if not records:
        return None
    record = records[0]

    register_code = _as_text(record.get("regstrSeCode"))
    register_name = _as_text(record.get("regstrSeCodeNm"))
    jibun = _as_text(record.get("mnnmSlno"))
    if jibun.endswith("-0"):
        jibun = jibun[:-2]
    if jibun and codes.is_mountain_register(register_code, register_name):
        jibun = f"산 {jibun}"

    return LandLedger(
        pnu=_as_text(record.get("pnu")),
        ld_code=_as_text(record.get("ldCode")),
        ld_name=_as_text(record.get("ldCodeNm")),
        jibun=jibun,
        register_type=codes.register_type_name(register_code, register_name),
        land_category=codes.land_category_name(
            _as_text(record.get("lndcgrCode")), _as_text(record.get("lndcgrCodeNm"))
        ),
        area=_as_text(record.get("lndpclAr")),
        ownership_type=codes.ownership_type_name(
            _as_text(record.get("posesnSeCode")), _as_text(record.get("posesnSeCodeNm"))
        ),
        co_owner_count=_as_text(record.get("cnrsPsnCo")),
        ownership_change_reason=_as_text(record.get("posesnChgCauseCodeNm"))
        or _as_text(record.get("posesnChgCause")),
        ownership_change_date=_as_text(record.get("posesnChgDe")),
        scale=codes.scale_name(_as_text(record.get("ladFrtlSc")), _as_text(record.get("ladFrtlScNm"))),
        last_update=_as_text(record.get("lastUpdtDt")),
    )


def parse_characteristics(payload: Any, stdr_year: str = "") -> LandCharacteristics | None:
    """토지특성정보(getLandCharacteristics) 응답을 읽는다."""
    raise_for_error(payload, "토지특성정보 조회")
    records = find_records(payload, "field")
    if not records:
        records = find_records(payload, "landCharacteristicss")
    if not records:
        return None
    record = records[0]

    return LandCharacteristics(
        pnu=_as_text(record.get("pnu")),
        stdr_year=_as_text(record.get("stdrYear")) or stdr_year,
        use_area1=_as_text(record.get("prposArea1Nm")),
        use_area2=_as_text(record.get("prposArea2Nm")),
        land_use_situation=_as_text(record.get("ladUseSittnNm")),
        terrain_height=_as_text(record.get("tpgrphHgCodeNm")),
        terrain_shape=_as_text(record.get("tpgrphFrmCodeNm")),
        road_side=_as_text(record.get("roadSideCodeNm")),
        official_price=_as_text(record.get("pblntfPclnd")),
        area=_as_text(record.get("lndpclAr")),
        land_category=codes.land_category_name(
            _as_text(record.get("lndcgrCode")), _as_text(record.get("lndcgrCodeNm"))
        ),
        last_update=_as_text(record.get("lastUpdtDt")),
    )
