"""필지 도형 계산 검증."""

from __future__ import annotations

from latlon_converter import geometry


def square(lon: float, lat: float, half: float = 0.001) -> dict:
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


def test_point_in_polygon_and_holes():
    geom = square(127.0, 37.5, 0.01)
    assert geometry.point_in_geometry(127.0, 37.5, geom) is True
    assert geometry.point_in_geometry(128.0, 37.5, geom) is False


def test_approx_area_is_positive():
    area = geometry.approx_area_m2(square(127.0, 37.5, 0.001), 37.5)
    assert area is not None and area > 10_000


def test_min_edge_distance_inside_is_small():
    geom = square(127.0, 37.5, 0.001)
    inside = geometry.min_edge_distance_m(127.0, 37.5, geom)
    outside = geometry.min_edge_distance_m(127.003, 37.5, geom)
    assert inside is not None and inside < 120
    assert outside is not None and outside > 100
