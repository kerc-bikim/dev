"""겹친 필지 중 어느 것을 고르는지 검증.

연속지적도는 지적도와 임야도를 따로 이어 붙여 만들기 때문에 한 점에
토지대장 필지와 임야대장 필지가 함께 걸릴 수 있다. 보고된 사례
(37.968352, 124.645289 → 가을리 853 대신 가을리 산 306)를 픽스처로 재현한다.
"""

from __future__ import annotations

import json

import pytest

from latlon_converter import parsers
from latlon_converter.config import FIXTURES_DIR, Settings
from latlon_converter.parsers import CadastralFeature, parse_cadastral_features, select_parcel
from latlon_converter.models import Parcel
from latlon_converter.providers.vworld import VWorldProvider
from latlon_converter.service import LandLookupService

# 보고된 좌표.
LAT, LON = 37.968352, 124.645289

LAND_PNU = "2872025022108530000"
MOUNTAIN_PNU = "2872025022203060000"


def load(name: str) -> dict:
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


class StubSession:
    """연속지적도 요청에만 정해진 응답을 주는 세션."""

    verify = True

    def __init__(self, payload: dict):
        self.payload = payload
        self.calls: list[dict] = []

    def get(self, url, params=None, timeout=None):
        self.calls.append(dict(params or {}))
        return _Response(self.payload)


class _Response:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def make_provider(payload: dict) -> tuple[VWorldProvider, StubSession]:
    session = StubSession(payload)
    settings = Settings(provider="vworld", api_key="KEY", domain="http://localhost", retries=1)
    return VWorldProvider(settings, session=session), session


# --- 선택 규칙 ------------------------------------------------------------


def test_overlapping_parcels_pick_the_one_containing_the_point():
    features = parse_cadastral_features(load("cadastral_overlap.json"))
    assert len(features) == 2

    parcel = select_parcel(features, LAT, LON)

    assert parcel is not None
    assert parcel.pnu == LAND_PNU
    assert parcel.jibun_address == "인천광역시 옹진군 백령면 가을리 853"
    assert parcel.contains_point is True


def test_the_other_parcel_is_reported_as_an_alternative():
    parcel = select_parcel(parse_cadastral_features(load("cadastral_overlap.json")), LAT, LON)

    assert parcel is not None
    assert [candidate.pnu for candidate in parcel.alternatives] == [MOUNTAIN_PNU]
    described = parcel.alternatives[0].describe()
    assert "산 306" in described
    assert "점 포함" in described


def test_response_order_does_not_decide_the_result():
    """응답 순서를 뒤집어도 같은 필지를 고른다."""
    payload = load("cadastral_overlap.json")
    features = payload["response"]["result"]["featureCollection"]["features"]
    payload["response"]["result"]["featureCollection"]["features"] = list(reversed(features))

    parcel = select_parcel(parse_cadastral_features(payload), LAT, LON)
    assert parcel is not None and parcel.pnu == LAND_PNU


def test_point_outside_every_parcel_is_flagged():
    # 두 필지 모두에서 벗어난 점.
    parcel = select_parcel(parse_cadastral_features(load("cadastral_overlap.json")), 37.9, 124.5)

    assert parcel is not None
    assert parcel.contains_point is False
    assert parcel.alternatives


def test_without_geometry_the_first_feature_wins():
    """도형이 없는 응답(mock 픽스처 등)에서는 기존처럼 첫 필지를 쓴다."""
    features = parse_cadastral_features(load("cadastral_yeoksam.json"))
    parcel = select_parcel(features, 37.50435, 127.02505)

    assert parcel is not None
    assert parcel.pnu == "1168010100108080000"
    assert parcel.contains_point is None
    assert parcel.alternatives == []


def test_empty_response_selects_nothing():
    assert select_parcel([], LAT, LON) is None
    assert select_parcel(parse_cadastral_features(load("cadastral_empty.json")), LAT, LON) is None


def test_containing_parcel_beats_a_smaller_one_that_misses_the_point():
    """점을 품지 않는 필지는 아무리 작아도 고르지 않는다."""
    small_but_elsewhere = CadastralFeature(
        parcel=Parcel(pnu="3" * 19),
        geometry={
            "type": "Polygon",
            "coordinates": [[[9.0, 9.0], [9.001, 9.0], [9.001, 9.001], [9.0, 9.001], [9.0, 9.0]]],
        },
    )
    big_but_containing = CadastralFeature(
        parcel=Parcel(pnu="4" * 19),
        geometry={"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]},
    )

    parcel = select_parcel([small_but_elsewhere, big_but_containing], 0.5, 0.5)

    assert parcel is not None and parcel.pnu == "4" * 19
    assert parcel.contains_point is True


def test_smallest_containing_parcel_wins_even_if_listed_last():
    big = CadastralFeature(
        parcel=Parcel(pnu="1" * 19),
        geometry={"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]},
    )
    small = CadastralFeature(
        parcel=Parcel(pnu="2" * 19),
        geometry={
            "type": "Polygon",
            "coordinates": [[[0.4, 0.4], [0.6, 0.4], [0.6, 0.6], [0.4, 0.6], [0.4, 0.4]]],
        },
    )
    parcel = select_parcel([big, small], 0.5, 0.5)
    assert parcel is not None and parcel.pnu == "2" * 19


# --- 제공자 동작 ----------------------------------------------------------


def test_provider_requests_geometry_and_multiple_candidates():
    provider, session = make_provider(load("cadastral_overlap.json"))

    parcel = provider.get_parcel(LAT, LON)

    assert parcel is not None and parcel.pnu == LAND_PNU
    params = session.calls[0]
    assert params["geometry"] == "true"
    assert int(params["size"]) > 1
    assert params["geomFilter"] == f"POINT({LON} {LAT})"


def test_service_warns_about_the_overlapping_parcel():
    provider, _ = make_provider(load("cadastral_overlap.json"))

    result = LandLookupService(provider).lookup_point(LAT, LON)

    assert result.parcel is not None and result.parcel.pnu == LAND_PNU
    overlap = [warning for warning in result.warnings if "겹치는 필지" in warning]
    assert overlap and "산 306" in overlap[0]
    assert "산 306" in result.to_row()["비고"]


def test_service_warns_when_point_is_outside_the_parcel():
    provider, _ = make_provider(load("cadastral_overlap.json"))

    result = LandLookupService(provider).lookup_point(37.9, 124.5)

    assert any("경계 안에 들어가지 않습니다" in warning for warning in result.warnings)


# --- 주변 필지 조회 -------------------------------------------------------


def test_find_nearby_orders_by_containment_then_distance():
    provider, session = make_provider(load("cadastral_overlap.json"))

    candidates = provider.find_nearby(LAT, LON, 100)

    assert [candidate.pnu for candidate in candidates] == [LAND_PNU, MOUNTAIN_PNU]
    assert candidates[0].contains_point is True
    assert candidates[0].approx_area_m2 == pytest.approx(30 * 31, rel=0.2)
    assert candidates[1].distance_m is not None

    box = session.calls[0]["geomFilter"]
    assert box.startswith("BOX(")
    # 100m는 위도로 0.0009도쯤이므로 점 주변이 제대로 감싸여야 한다.
    min_lon, min_lat, max_lon, max_lat = (float(v) for v in box[4:-1].split(","))
    assert min_lon < LON < max_lon
    assert min_lat < LAT < max_lat
    assert (max_lat - min_lat) == pytest.approx(2 * 100 / 110540, rel=0.01)


def test_find_nearby_handles_empty_area():
    provider, _ = make_provider(load("cadastral_empty.json"))
    assert provider.find_nearby(LAT, LON, 50) == []


def test_mock_provider_supports_nearby():
    from latlon_converter.providers.mock import MockProvider

    candidates = MockProvider().find_nearby(37.50435, 127.02505, 50)
    assert len(candidates) == 1
    assert candidates[0].pnu == "1168010100108080000"

    assert MockProvider().find_nearby(36.0, 130.5, 50) == []


# --- 출력 -----------------------------------------------------------------


def test_json_output_lists_alternatives(capsys):
    from latlon_converter import report

    provider, _ = make_provider(load("cadastral_overlap.json"))
    result = LandLookupService(provider).lookup_point(LAT, LON)

    payload = json.loads(report.render_json(result))
    assert [item["pnu"] for item in payload["alternatives"]] == [MOUNTAIN_PNU]
    assert payload["parcel"]["contains_point"] is True


def test_parse_cadastral_still_returns_the_first_parcel():
    """기존 호출부(mock 등)가 쓰는 단일 반환도 그대로 동작한다."""
    parcel = parsers.parse_cadastral(load("cadastral_overlap.json"))
    assert parcel is not None and parcel.pnu == MOUNTAIN_PNU
