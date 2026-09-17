"""구 지적·종이 지도에서 쓰는 동경측지계를 WGS84로 바꾼다.

브이월드 연속지적도는 EPSG:4326(WGS84)이다. GPS·스마트폰 좌표는 변환 없이
넣으면 된다. 예전 지적 성과를 WGS84인 것처럼 넣으면 한반도에서 경도가
약 10.4초(200~300m) 서쪽으로 치우친다.

여기서는 국토·지적 실무에서 쓰는 평균 경도 원점 차이(10.405″)를 더한다.
위도는 지역 편차가 커서 그대로 둔다.
"""

from __future__ import annotations

# 동경측지계 경도 + 10.405″ ≈ 세계측지계 경도 (지적 간이변환)
_KOREA_BESSEL_LON_SHIFT_DEG = 10.405 / 3600.0


def tokyo_to_wgs84(lat: float, lon: float, height: float = 0.0) -> tuple[float, float]:
    """동경측지계 위경도를 WGS84 위경도로 변환한다."""
    del height
    return lat, lon + _KOREA_BESSEL_LON_SHIFT_DEG
