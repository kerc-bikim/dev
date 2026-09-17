"""필지 경계 다루기.

좌표는 GeoJSON 순서(경도, 위도)를 쓴다. 거리 계산은 한 필지 크기 안에서만
쓰므로 위도에 따른 단순 축척으로 충분하다.
"""

from __future__ import annotations

import math
from typing import Any, Sequence

METERS_PER_DEGREE_LAT = 110_540.0
METERS_PER_DEGREE_LON = 111_320.0

Ring = Sequence[Sequence[float]]


def meters_per_degree_lon(lat: float) -> float:
    return METERS_PER_DEGREE_LON * math.cos(math.radians(lat))


def point_in_ring(lon: float, lat: float, ring: Ring) -> bool:
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
    if not rings:
        return False
    if not point_in_ring(lon, lat, rings[0]):
        return False
    return not any(point_in_ring(lon, lat, hole) for hole in rings[1:])


def point_in_geometry(lon: float, lat: float, geometry: Any) -> bool | None:
    polygons = _polygons(geometry)
    if polygons is None:
        return None
    return any(point_in_polygon(lon, lat, rings) for rings in polygons)


def _ring_area_deg2(ring: Ring) -> float:
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
    dx = (lon2 - lon1) * meters_per_degree_lon((lat1 + lat2) / 2)
    dy = (lat2 - lat1) * METERS_PER_DEGREE_LAT
    return math.hypot(dx, dy)


def min_edge_distance_m(lon: float, lat: float, geometry: Any) -> float | None:
    """점과 필지 외곽선 사이 최단 거리(m). 점이 안이어도 경계까지 거리를 준다."""
    polygons = _polygons(geometry)
    if polygons is None:
        return None
    mx = meters_per_degree_lon(lat)
    my = METERS_PER_DEGREE_LAT
    px, py = lon * mx, lat * my
    best: float | None = None
    for rings in polygons:
        if not rings:
            continue
        ring = rings[0]
        count = len(ring)
        if count < 2:
            continue
        for index in range(count):
            x1, y1 = ring[index][0] * mx, ring[index][1] * my
            x2, y2 = ring[(index + 1) % count][0] * mx, ring[(index + 1) % count][1] * my
            distance = _point_to_segment_m(px, py, x1, y1, x2, y2)
            if best is None or distance < best:
                best = distance
    return best


def _point_to_segment_m(px: float, py: float, x1: float, y1: float, x2: float, y2: float) -> float:
    dx, dy = x2 - x1, y2 - y1
    if dx == 0 and dy == 0:
        return math.hypot(px - x1, py - y1)
    span = dx * dx + dy * dy
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / span))
    return math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))


def _polygons(geometry: Any) -> list[Sequence[Ring]] | None:
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
