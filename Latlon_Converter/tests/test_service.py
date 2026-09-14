"""조회 오케스트레이션 검증."""

from __future__ import annotations

import pytest

from latlon_converter.errors import AuthError, InputError, LatlonError, QuotaError
from latlon_converter.models import LandCharacteristics, LandLedger, Parcel
from latlon_converter.providers.mock import MockProvider
from latlon_converter.service import LandLookupService, LookupOptions, current_year


class StubProvider:
    """호출 내역을 기록하는 시험용 제공자."""

    name = "stub"

    def __init__(self, parcel=None, ledger=None, characteristics=None, ledger_error=None, chars_error=None):
        self._parcel = parcel
        self._ledger = ledger
        self._characteristics = characteristics
        self._ledger_error = ledger_error
        self._chars_error = chars_error
        self.requested_years: list[int] = []

    def get_parcel(self, lat, lon, with_road=False):
        return self._parcel

    def get_ledger(self, pnu):
        if self._ledger_error:
            raise self._ledger_error
        return self._ledger

    def get_characteristics(self, pnu, stdr_year):
        self.requested_years.append(stdr_year)
        if self._chars_error:
            raise self._chars_error
        if callable(self._characteristics):
            return self._characteristics(stdr_year)
        return self._characteristics


def make_parcel() -> Parcel:
    return Parcel(
        pnu="1168010100108080000",
        jibun_address="서울특별시 강남구 역삼동 808",
        jibun="808",
        ld_code="1168010100",
        ld_name="서울특별시 강남구 역삼동",
    )


def test_no_parcel_returns_early_with_warning():
    service = LandLookupService(StubProvider(parcel=None))
    result = service.lookup_point(36.0, 130.5)
    assert result.found is False
    assert result.ledger is None
    assert "필지를 찾지 못했습니다" in result.warnings[0]


def test_ledger_failure_keeps_other_fields():
    provider = StubProvider(
        parcel=make_parcel(),
        ledger_error=LatlonError("토지임야정보 조회: 일시적 오류"),
        characteristics=LandCharacteristics(use_area1="일반상업지역"),
    )
    result = LandLookupService(provider).lookup_point(37.5, 127.0)
    assert result.found is True
    assert result.ledger is None
    assert result.characteristics is not None
    assert any("일시적 오류" in warning for warning in result.warnings)


def test_year_fallback_walks_back_and_notes_it():
    this_year = current_year()
    oldest = this_year - 2

    def characteristics_for(year: int):
        return LandCharacteristics(stdr_year=str(year)) if year == oldest else None

    provider = StubProvider(
        parcel=make_parcel(),
        ledger=LandLedger(ownership_type="개인"),
        characteristics=characteristics_for,
    )
    result = LandLookupService(provider).lookup_point(37.5, 127.0, LookupOptions(stdr_year=None))
    assert provider.requested_years == [this_year, this_year - 1, oldest]
    assert result.characteristics is not None
    assert result.characteristics.stdr_year == str(oldest)
    assert any(f"{oldest}년 자료를 사용했습니다" in warning for warning in result.warnings)


def test_year_fallback_stops_after_configured_attempts():
    provider = StubProvider(parcel=make_parcel(), ledger=LandLedger(), characteristics=None)
    result = LandLookupService(provider).lookup_point(
        37.5, 127.0, LookupOptions(year_attempts=2)
    )
    assert len(provider.requested_years) == 2
    assert result.characteristics is None


def test_explicit_year_is_tried_once():
    provider = StubProvider(parcel=make_parcel(), ledger=LandLedger(), characteristics=None)
    result = LandLookupService(provider).lookup_point(37.5, 127.0, LookupOptions(stdr_year=2020))
    assert provider.requested_years == [2020]
    assert any("토지특성정보가 조회되지 않았습니다" in warning for warning in result.warnings)


@pytest.mark.parametrize("error", [AuthError("키 오류"), QuotaError("한도 초과")])
def test_auth_and_quota_errors_propagate(error):
    provider = StubProvider(parcel=make_parcel(), ledger_error=error)
    with pytest.raises(type(error)):
        LandLookupService(provider).lookup_point(37.5, 127.0)


@pytest.mark.parametrize(("lat", "lon"), [(95.0, 127.0), (37.5, 200.0)])
def test_coordinate_range_is_validated(lat, lon):
    with pytest.raises(InputError):
        LandLookupService(StubProvider()).lookup_point(lat, lon)


def test_lookup_pnu_builds_parcel_from_ledger():
    service = LandLookupService(MockProvider())
    result = service.lookup_pnu("4215038023200120003")
    assert result.parcel is not None
    assert result.parcel.jibun == "산 12-3"
    assert result.parcel.jibun_address == "강원특별자치도 강릉시 왕산면 대기리 산 12-3"
    assert result.ledger is not None and result.ledger.ownership_type == "국유지"


def test_lookup_pnu_rejects_bad_pnu():
    with pytest.raises(InputError):
        LandLookupService(MockProvider()).lookup_pnu("12345")


def test_mock_synthesized_result_is_flagged():
    service = LandLookupService(MockProvider())
    result = service.lookup_point(35.1802, 128.1076)
    assert result.found is True
    assert any("합성 데이터" in warning for warning in result.warnings)


def test_mock_fixture_result_is_not_flagged():
    service = LandLookupService(MockProvider())
    result = service.lookup_point(37.50435, 127.02505)
    assert result.parcel is not None and result.parcel.pnu == "1168010100108080000"
    assert not any("합성 데이터" in warning for warning in result.warnings)
