"""필지 경계 다루기.

연속지적도는 지적도(1:1200 등)와 임야도(1:6000)를 각각 이어 붙여 만들기
때문에, 같은 지점에 토지대장 필지와 임야대장 필지가 겹쳐 등록되어 있는
경우가 있다. 한 점으로 조회하면 두 필지가 모두 돌아오므로, 점이 실제로
어느 경계 안에 있는지 따져서 골라야 한다.

좌표는 GeoJSON 순서(경도, 위도)를 쓴다. 거리 계산은 한 필지 크기 안에서만
쓰므로 위도에 따른 단순 축척으로 충분하다.
"""

from __future__ import annotations

import math
from typing import Any, Sequence

# 위도 1도당 미터. 경도는 위도에 따라 줄어든다.
METERS_PER_DEGREE_LAT = 110_540.0
METERS_PER_DEGREE_LON = 111_320.0

Ring = Sequence[Sequence[float]]


def meters_per_degree_lon(lat: float) -> float:
    return METERS_PER_DEGREE_LON * math.cos(math.radians(lat))


def point_in_ring(lon: float, lat: float, ring: Ring) -> bool:
    """전통적인 레이 캐스팅. 경계선 위의 점은 판정이 갈릴 수 있다."""
    inside = False
    count = len(ring)
    if count < 3:
        return False

    previous_lon, previous_lat = ring[-1][0], ring[-1][1]
    for point in ring:
        current_lon, current_lat = point[0], point[1]
        intersects = (current_lat > lat) != (previous_lat > lat)
        if intersects:
            span = previous_lat - current_lat
            if span != 0:
                crossing = (previous_lon - current_lon) * (lat - current_lat) / span + current_lon
                if lon < crossing:
                    inside = not inside
        previous_lon, previous_lat = current_lon, current_lat
    return inside


def point_in_polygon(lon: float, lat: float, rings: Sequence[Ring]) -> bool:
    """첫 고리는 바깥 경계, 나머지는 구멍으로 본다."""
    if not rings:
        return False
    if not point_in_ring(lon, lat, rings[0]):
        return False
    return not any(point_in_ring(lon, lat, hole) for hole in rings[1:])


def point_in_geometry(lon: float, lat: float, geometry: Any) -> bool | None:
    """경계 안에 있는지 판정한다. 도형이 없으면 판단할 수 없어 None."""
    polygons = _polygons(geometry)
    if polygons is None:
        return None
    return any(point_in_polygon(lon, lat, rings) for rings in polygons)


def _ring_area_deg2(ring: Ring) -> float:
    """신발끈 공식. 단위는 도²이므로 비교용으로만 쓴다."""
    total = 0.0
    count = len(ring)
    if count < 3:
        return 0.0
    for index in range(count):
        x1, y1 = ring[index][0], ring[index][1]
        x2, y2 = ring[(index + 1) % count][0], ring[(index + 1) % count][1]
        total += x1 * y2 - x2 * y1
    return abs(total) / 2.0


def approx_area_m2(geometry: Any, lat: float) -> float | None:
    """필지 면적의 근삿값. 구멍은 빼고 센다."""
    polygons = _polygons(geometry)
    if polygons is None:
        return None
    scale = meters_per_degree_lon(lat) * METERS_PER_DEGREE_LAT
    total = 0.0
    for rings in polygons:
        if not rings:
            continue
        total += _ring_area_deg2(rings[0])
        total -= sum(_ring_area_deg2(hole) for hole in rings[1:])
    return max(total, 0.0) * scale


def centroid(geometry: Any) -> tuple[float, float] | None:
    """바깥 고리 꼭짓점의 평균. 대표점이 필요할 때만 쓴다."""
    polygons = _polygons(geometry)
    if not polygons:
        return None
    points = [point for rings in polygons if rings for point in rings[0]]
    if not points:
        return None
    return (
        sum(point[0] for point in points) / len(points),
        sum(point[1] for point in points) / len(points),
    )


def distance_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """짧은 거리용 평면 근사."""
    dx = (lon2 - lon1) * meters_per_degree_lon((lat1 + lat2) / 2)
    dy = (lat2 - lat1) * METERS_PER_DEGREE_LAT
    return math.hypot(dx, dy)


def _polygons(geometry: Any) -> list[Sequence[Ring]] | None:
    """Polygon / MultiPolygon을 고리 목록의 목록으로 통일한다."""
    if not isinstance(geometry, dict):
        return None
    coordinates = geometry.get("coordinates")
    if not isinstance(coordinates, list) or not coordinates:
        return None

    kind = str(geometry.get("type", "")).lower()
    if kind == "polygon":
        return [coordinates]
    if kind == "multipolygon":
        return [polygon for polygon in coordinates if isinstance(polygon, list)]
    return None
