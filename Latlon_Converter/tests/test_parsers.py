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
from latlon_converter.models import Parcel


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


def test_parse_possession_personal_residence():
    possession = parsers.parse_possession(load("possession_yeoksam.json"))
    assert possession is not None
    assert possession.ownership_type == "개인"
    assert possession.residence_type == "시도내"
    assert possession.ownership_agency == ""
    assert possession.ownership_change_reason == "주소경정"


def test_parse_possession_national_agency():
    possession = parsers.parse_possession(load("possession_mountain.json"))
    assert possession is not None
    assert possession.ownership_type == "국유지"
    assert possession.ownership_agency == "중앙부처"
    assert possession.residence_type == ""


def test_merge_fills_blank_ownership_detail():
    ledger = parsers.parse_ledger(load("ladfrl_yeoksam.json"))
    possession = parsers.parse_possession(load("possession_yeoksam.json"))
    merged = parsers.merge_ledger_possession(ledger, possession)
    assert merged is not None
    assert merged.ownership_type == "개인"
    assert merged.residence_type == "시도내"
    assert merged.ownership_agency == ""
    assert merged.co_owner_count == "1"
    assert merged.ownership_change_reason == "매매"


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


def test_find_records_unwraps_same_key_envelope():
    payload = {
        "ladfrlVOList": {
            "pageNo": "1",
            "totalCount": "1",
            "ladfrlVOList": [
                {
                    "pnu": "2872033023108530000",
                    "posesnSeCode": "02",
                    "posesnSeCodeNm": "국유지",
                    "regstrSeCode": "1",
                    "regstrSeCodeNm": "토지대장",
                    "ldCode": "2872033023",
                    "ldCodeNm": "인천광역시 옹진군 백령면 가을리",
                    "mnnmSlno": "853",
                    "lndcgrCode": "28",
                    "lndcgrCodeNm": "잡종지",
                    "lndpclAr": "7618",
                }
            ],
        }
    }
    records = parsers.find_records(payload, "ladfrlVOList")
    assert len(records) == 1
    assert records[0]["pnu"] == "2872033023108530000"
    ledger = parsers.parse_ledger(payload)
    assert ledger is not None
    assert ledger.ownership_type == "국유지"
    assert ledger.land_category == "잡종지"
    assert ledger.register_type == "토지대장"


def _square(lon: float, lat: float, half: float) -> dict:
    return {
        "type": "Polygon",
        "coordinates": [
            [
                [lon - half, lat - half],
                [lon + half, lat - half],
                [lon + half, lat + half],
                [lon - half, lat + half],
                [lon - half, lat - half],
            ]
        ],
    }


def test_select_parcel_prefers_smallest_containing_feature():
    big = parsers.CadastralFeature(
        parcel=Parcel(pnu="1", jibun_address="큰필지"),
        geometry=_square(127.0, 37.5, 0.01),
    )
    small = parsers.CadastralFeature(
        parcel=Parcel(pnu="2", jibun_address="작은필지"),
        geometry=_square(127.0, 37.5, 0.001),
    )
    chosen = parsers.select_parcel([big, small], 37.5, 127.0)
    assert chosen is not None
    assert chosen.pnu == "2"
    assert chosen.contains_point is True
    assert chosen.alternatives[0].pnu == "1"
    assert chosen.alternatives[0].contains_point is True


def test_parse_search_items_reads_point_and_parcel():
    payload = {
        "response": {
            "status": "OK",
            "result": {
                "items": [
                    {
                        "id": "2872033023108530000",
                        "title": "인천광역시 옹진군 백령면 가을리 853",
                        "point": {"x": "124.648201", "y": "37.968579"},
                        "address": {"parcel": "인천광역시 옹진군 백령면 가을리 853"},
                    }
                ]
            },
        }
    }
    hits = parsers.parse_search_items(payload)
    assert len(hits) == 1
    assert hits[0].pnu == "2872033023108530000"
    assert hits[0].lat == 37.968579
    assert hits[0].lon == 124.648201
