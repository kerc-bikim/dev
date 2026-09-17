"""동경측지계 → WGS84 변환 검증."""

from __future__ import annotations

from latlon_converter.datum import tokyo_to_wgs84
from latlon_converter.geometry import distance_m


def test_tokyo_to_wgs84_shifts_korea_eastward_a_few_hundred_meters():
    lat, lon = 37.968352, 124.645289
    wgs_lat, wgs_lon = tokyo_to_wgs84(lat, lon)
    shift = distance_m(lon, lat, wgs_lon, wgs_lat)
    # 지적 간이변환은 경도 +10.405″ (이 위도에서 약 250m 동쪽).
    assert wgs_lat == lat
    assert abs((wgs_lon - lon) * 3600 - 10.405) < 1e-9
    assert 200 < shift < 300
    assert wgs_lon > lon
