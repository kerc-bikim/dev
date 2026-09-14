"""PNU 조립/해석 검증."""

from __future__ import annotations

import pytest

from latlon_converter.errors import InputError
from latlon_converter.pnu import (
    build_pnu,
    format_jibun,
    is_valid_pnu,
    parse_jibun,
    parse_pnu,
)


@pytest.mark.parametrize(
    ("jibun", "expected"),
    [
        ("808", (False, 808, 0)),
        ("808-1", (False, 808, 1)),
        ("산 12-3", (True, 12, 3)),
        ("산12", (True, 12, 0)),
        (" 12 - 3 ", (False, 12, 3)),
        ("808 대", (False, 808, 0)),
        ("산 12-3 임", (True, 12, 3)),
    ],
)
def test_parse_jibun(jibun, expected):
    assert parse_jibun(jibun) == expected


def test_parse_jibun_rejects_garbage():
    with pytest.raises(InputError):
        parse_jibun("지번없음")
    with pytest.raises(InputError):
        parse_jibun("")


@pytest.mark.parametrize(
    ("bonbun", "bubun", "mountain", "expected"),
    [
        (808, 0, False, "808"),
        (808, 1, False, "808-1"),
        (12, 3, True, "산 12-3"),
        (12, 0, True, "산 12"),
    ],
)
def test_format_jibun(bonbun, bubun, mountain, expected):
    assert format_jibun(bonbun, bubun, mountain) == expected


def test_build_pnu_land_and_mountain():
    assert build_pnu("1168010100", "808") == "1168010100108080000"
    assert build_pnu("4215038023", "산 12-3") == "4215038023200120003"


def test_build_pnu_explicit_mountain_flag_wins():
    assert build_pnu("1168010100", "808", is_mountain=True) == "1168010100208080000"


def test_build_pnu_rejects_bad_ld_code():
    with pytest.raises(InputError):
        build_pnu("11680101", "808")
    with pytest.raises(InputError):
        build_pnu("서울1168010", "808")


@pytest.mark.parametrize("pnu", ["1168010100108080000", "4215038023200120003"])
def test_parse_pnu_roundtrip(pnu):
    parts = parse_pnu(pnu)
    assert build_pnu(parts.ld_code, parts.jibun) == pnu


def test_parse_pnu_parts():
    parts = parse_pnu("4215038023200120003")
    assert parts.ld_code == "4215038023"
    assert parts.is_mountain is True
    assert (parts.bonbun, parts.bubun) == (12, 3)
    assert parts.jibun == "산 12-3"


@pytest.mark.parametrize("pnu", ["", "116801010010808000", "11680101001080800000", "abcdefghijklmnopqrs"])
def test_is_valid_pnu_rejects(pnu):
    assert is_valid_pnu(pnu) is False
    with pytest.raises(InputError):
        parse_pnu(pnu)
