"""필지 경계 판정과 면적 근사 검증."""

from __future__ import annotations

import pytest

from latlon_converter import geometry

# 한 변이 약 0.001도인 사각형.
SQUARE = [[0.0, 0.0], [0.001, 0.0], [0.001, 0.001], [0.0, 0.001], [0.0, 0.0]]
POLYGON = {"type": "Polygon", "coordinates": [SQUARE]}
MULTI = {"type": "MultiPolygon", "coordinates": [[SQUARE]]}

# 가운데가 뚫린 사각형.
HOLE = [[0.0003, 0.0003], [0.0007, 0.0003], [0.0007, 0.0007], [0.0003, 0.0007], [0.0003, 0.0003]]
DONUT = {"type": "Polygon", "coordinates": [SQUARE, HOLE]}


@pytest.mark.parametrize("shape", [POLYGON, MULTI])
def test_point_inside_and_outside(shape):
    assert geometry.point_in_geometry(0.0005, 0.0005, shape) is True
    assert geometry.point_in_geometry(0.002, 0.0005, shape) is False
    assert geometry.point_in_geometry(0.0005, -0.001, shape) is False


def test_hole_is_excluded():
    assert geometry.point_in_geometry(0.0005, 0.0005, DONUT) is False
    assert geometry.point_in_geometry(0.0001, 0.0001, DONUT) is True


@pytest.mark.parametrize("shape", [None, {}, {"type": "Point", "coordinates": [0, 0]}, "없음"])
def test_missing_geometry_is_undecidable(shape):
    assert geometry.point_in_geometry(0.0, 0.0, shape) is None
    assert geometry.approx_area_m2(shape, 37.5) is None


def test_degenerate_ring_is_not_inside():
    assert geometry.point_in_ring(0.0, 0.0, [[0.0, 0.0], [1.0, 1.0]]) is False


def test_area_matches_hand_calculation():
    # 위도 0에서 0.001도 사각형은 약 111.32m x 110.54m.
    area = geometry.approx_area_m2(POLYGON, 0.0)
    assert area == pytest.approx(111.32 * 110.54, rel=0.01)


def test_area_shrinks_with_latitude():
    at_equator = geometry.approx_area_m2(POLYGON, 0.0)
    at_korea = geometry.approx_area_m2(POLYGON, 37.97)
    assert at_korea < at_equator
    assert at_korea == pytest.approx(at_equator * 0.788, rel=0.02)


def test_hole_area_is_subtracted():
    assert geometry.approx_area_m2(DONUT, 0.0) < geometry.approx_area_m2(POLYGON, 0.0)


def test_centroid_and_distance():
    center = geometry.centroid(POLYGON)
    assert center is not None
    assert center[0] == pytest.approx(0.0005, abs=1e-4)
    assert center[1] == pytest.approx(0.0005, abs=1e-4)
    assert geometry.centroid({"type": "Point", "coordinates": [0, 0]}) is None


def test_distance_uses_local_scale():
    # 위도 37.97에서 경도 0.001도는 약 88m.
    assert geometry.distance_m(124.0, 37.97, 124.001, 37.97) == pytest.approx(88, abs=2)
    # 위도 0.001도는 위치와 무관하게 약 110m.
    assert geometry.distance_m(124.0, 37.97, 124.0, 37.971) == pytest.approx(110.5, abs=1)
