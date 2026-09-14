"""브이월드 응답 파서 검증.

mock 제공자가 재생하는 fixtures를 그대로 써서, 실제 응답 스키마가 바뀌면
mock과 실 API 경로가 함께 깨지도록 한다.
"""

from __future__ import annotations

import json

import pytest

from latlon_converter import parsers
from latlon_converter.config import FIXTURES_DIR
from latlon_converter.errors import AuthError, LatlonError, QuotaError


def load(name: str) -> dict:
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


def test_parse_cadastral_reads_parcel():
    parcel = parsers.parse_cadastral(load("cadastral_yeoksam.json"))
    assert parcel is not None
    assert parcel.pnu == "1168010100108080000"
    assert parcel.jibun_address == "서울특별시 강남구 역삼동 808"
    assert parcel.ld_code == "1168010100"
    assert parcel.ld_name == "서울특별시 강남구 역삼동"
    assert parcel.official_price == "73680000"


def test_parse_cadastral_strips_jibun_from_ld_name_for_mountain():
    parcel = parsers.parse_cadastral(load("cadastral_mountain.json"))
    assert parcel is not None
    assert parcel.pnu == "4215038023200120003"
    assert parcel.ld_name == "강원특별자치도 강릉시 왕산면 대기리"


def test_parse_cadastral_returns_none_when_empty():
    assert parsers.parse_cadastral(load("cadastral_empty.json")) is None


def test_parse_geocoder_reads_structure_and_road():
    parsed = parsers.parse_geocoder(load("geocoder_yeoksam.json"))
    assert parsed is not None
    assert parsed["ld_code"] == "1168010100"
    assert parsed["jibun"] == "808"
    assert parsed["text"] == "서울특별시 강남구 역삼동 808"
    assert parsed["road_address"] == "서울특별시 강남구 테헤란로 305"
    assert parsers.parse_road_address(load("geocoder_yeoksam.json")) == "서울특별시 강남구 테헤란로 305"


def test_parse_ledger_fields_root_envelope():
    ledger = parsers.parse_ledger(load("ladfrl_yeoksam.json"))
    assert ledger is not None
    assert ledger.register_type == "토지대장"
    assert ledger.land_category == "대"
    assert ledger.ownership_type == "개인"
    assert ledger.co_owner_count == "1"
    assert ledger.jibun == "808"


def test_parse_ledger_marks_mountain_jibun():
    ledger = parsers.parse_ledger(load("ladfrl_mountain.json"))
    assert ledger is not None
    assert ledger.jibun == "산 12-3"
    assert ledger.register_type == "임야대장"
    assert ledger.ownership_type == "국유지"


def test_parse_characteristics_handles_both_envelopes():
    # landchar_yeoksam은 루트가 landCharacteristicss, mountain은 루트가 response다.
    seoul = parsers.parse_characteristics(load("landchar_yeoksam.json"))
    mountain = parsers.parse_characteristics(load("landchar_mountain.json"))
    assert seoul is not None and mountain is not None
    assert seoul.use_area1 == "일반상업지역"
    assert seoul.official_price == "73680000"
    assert mountain.use_area1 == "보전관리지역"
    assert mountain.land_use_situation == "자연림"


def test_error_responses_map_to_exceptions():
    with pytest.raises(AuthError):
        parsers.parse_cadastral(load("error_incorrect_key.json"))
    with pytest.raises(QuotaError):
        parsers.parse_cadastral(load("error_over_quota.json"))


def test_ned_result_code_errors():
    payload = {"response": {"resultCode": "30", "resultMsg": "SERVICE KEY IS NOT REGISTERED ERROR"}}
    with pytest.raises(AuthError):
        parsers.parse_characteristics(payload)

    payload = {"response": {"resultCode": "99", "resultMsg": "UNKNOWN ERROR"}}
    with pytest.raises(LatlonError):
        parsers.parse_characteristics(payload)


def test_find_records_searches_nested_payload():
    payload = {"a": {"b": {"ladfrlVOList": {"pnu": "1"}}}}
    assert parsers.find_records(payload, "ladfrlVOList") == [{"pnu": "1"}]
    assert parsers.find_records({"a": []}, "ladfrlVOList") == []
