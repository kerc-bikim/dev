"""코드표 변환 검증."""

from __future__ import annotations

from latlon_converter import codes


def test_names_from_code():
    assert codes.land_category_name("0008") == "대"
    assert codes.register_type_name("222") == "임야대장"
    assert codes.ownership_type_name("3302") == "국유지"
    assert codes.ownership_type_name("02") == "국유지"
    assert codes.land_category_name("28") == "잡종지"
    assert codes.scale_name("12") == "1:1200"
    assert codes.scale_name("5505") == "1:500"


def test_response_name_wins_over_table():
    assert codes.land_category_name("0008", "대지") == "대지"


def test_unknown_code_is_marked():
    assert codes.ownership_type_name("9999") == "알수없음(9999)"
    assert codes.land_category_name(None) == ""


def test_agency_and_residence_skip_placeholders():
    assert codes.agency_name("01", "중앙부처") == "중앙부처"
    assert codes.agency_name("01") == "중앙부처"
    assert codes.agency_name("ZZ", "구분없음") == ""
    assert codes.residence_name("02", "시도내") == "시도내"
    assert codes.residence_name("ZZ") == ""
    assert codes.public_label("구분없음") == ""


def test_mountain_register_detection():
    assert codes.is_mountain_register("2") is True
    assert codes.is_mountain_register("222") is True
    assert codes.is_mountain_register("1") is False
    assert codes.is_mountain_register("221") is False
    # 코드가 없으면 명칭으로 판단한다.
    assert codes.is_mountain_register("", "임야대장") is True
    assert codes.is_mountain_register(None, "토지대장") is False
