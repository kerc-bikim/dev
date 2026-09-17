"""브이월드(국토교통부) 오픈API 제공자.

좌표 한 건당 호출은 다음 3~4회다.

1. `req/data` 연속지적도 — PNU, 지번, 주소, 공시지가를 한 번에 준다.
2. `ned/data/ladfrlList` — 지목, 면적, 대장구분, 소유구분, 공유인수.
3. `ned/data/getPossessionAttr` — 국가기관구분, 거주지구분, 소유권변동원인·일자.
4. `ned/data/getLandCharacteristics` — 용도지역, 토지이용상황, 공시지가.

연속지적도에서 필지를 못 찾으면 Geocoder(`req/address`)로 한 번 더 시도한다.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import requests

from .. import geometry, parsers
from ..cache import NullCache
from ..config import Settings
from ..errors import AuthError, NetworkError, QuotaError, TlsError
from ..logutil import redact, safe_params
from ..models import LandCharacteristics, LandLedger, Parcel, ParcelCandidate
from ..pnu import build_pnu
from ..tls import build_session, tls_error_message

logger = logging.getLogger(__name__)

DATA_URL = "https://api.vworld.kr/req/data"
ADDRESS_URL = "https://api.vworld.kr/req/address"
SEARCH_URL = "https://api.vworld.kr/req/search"
LADFRL_URL = "https://api.vworld.kr/ned/data/ladfrlList"
POSSESSION_URL = "https://api.vworld.kr/ned/data/getPossessionAttr"
LANDCHAR_URL = "https://api.vworld.kr/ned/data/getLandCharacteristics"

CADASTRAL_LAYER = "LP_PA_CBND_BUBUN"
DEFAULT_CRS = "EPSG:4326"


class VWorldProvider:
    """실제 브이월드 API를 호출하는 제공자."""

    name = "vworld"

    def __init__(
        self,
        settings: Settings,
        cache: Any | None = None,
        session: Any | None = None,
    ) -> None:
        if not settings.api_key:
            raise AuthError(
                "VWORLD_API_KEY가 설정되지 않았습니다. "
                "Latlon_Converter/.env 에 키를 넣거나 --provider mock 으로 실행하세요."
            )
        self.settings = settings
        self.cache = cache or NullCache()
        # LATLON_CA_BUNDLE이 있으면 그 인증서로 서버를 검증한다.
        self.session = build_session(settings, session)

    # --- HTTP ------------------------------------------------------------

    def _auth_params(self, with_domain: bool = True) -> dict[str, str]:
        params = {"key": self.settings.api_key}
        # 2D데이터/국가중점 API는 domain이 발급 시 서비스 URL과 같아야 한다.
        if with_domain and self.settings.domain:
            params["domain"] = self.settings.domain
        return params

    def _get(self, url: str, params: dict[str, Any], context: str) -> dict:
        cached = self.cache.get(self.name, url, params)
        if cached is not None:
            logger.info("%s 캐시 사용", context)
            logger.debug("%s 캐시 키 params=%s", context, safe_params(params))
            return cached

        last_error: Exception | None = None
        for attempt in range(1, max(self.settings.retries, 1) + 1):
            logger.info("%s 요청 %s (%d회차)", context, url, attempt)
            logger.debug("%s params=%s", context, safe_params(params))
            started = time.perf_counter()
            try:
                response = self.session.get(url, params=params, timeout=self.settings.timeout)
            except requests.exceptions.SSLError as exc:
                # 인증서 문제는 다시 시도해도 같은 결과이므로 바로 알린다.
                raise TlsError(f"{context}: {tls_error_message(self.session.verify, exc)}") from exc
            except Exception as exc:  # requests의 모든 전송 오류
                last_error = exc
                logger.warning(
                    "%s 요청 실패(%d회차, %.2fs): %s",
                    context,
                    attempt,
                    time.perf_counter() - started,
                    redact(str(exc), self.settings.api_key),
                )
            else:
                elapsed = time.perf_counter() - started
                logger.info("%s HTTP %s (%.2fs)", context, response.status_code, elapsed)
                if response.status_code >= 500:
                    last_error = NetworkError(f"{context}: 서버 오류 {response.status_code}")
                    logger.warning("%s 서버 오류(%d회차): %s", context, attempt, response.status_code)
                elif response.status_code >= 400:
                    raise NetworkError(f"{context}: HTTP {response.status_code}")
                else:
                    payload = _decode(response, context)
                    logger.debug("%s 응답 %s", context, _payload_summary(payload))
                    self.cache.set(self.name, url, params, payload)
                    return payload
            if attempt < max(self.settings.retries, 1):
                time.sleep(min(2 ** (attempt - 1), 8))

        raise NetworkError(
            f"{context}: 요청에 실패했습니다 ({redact(str(last_error), self.settings.api_key)})"
        )

    # --- 조회 -------------------------------------------------------------

    def get_parcel(self, lat: float, lon: float, with_road: bool = False) -> Parcel | None:
        parcel = self._get_parcel_from_cadastral(lat, lon)
        if parcel is None:
            parcel = self._get_parcel_from_geocoder(lat, lon)
        if parcel is None:
            return None
        if with_road and not parcel.road_address:
            parcel.road_address = self._get_road_address(lat, lon)
        return parcel

    def _get_parcel_from_cadastral(self, lat: float, lon: float) -> Parcel | None:
        payload = self._cadastral_get(
            geom_filter=f"POINT({lon} {lat})",
            size=10,
            with_geometry=True,
        )
        return parsers.select_parcel(parsers.parse_cadastral_features(payload), lat, lon)

    def find_nearby(
        self,
        lat: float,
        lon: float,
        radius_m: float = 300,
        size: int = 50,
    ) -> list[ParcelCandidate]:
        """좌표 주변 BOX로 필지를 모아 가까운 순으로 돌려준다."""
        radius_m = max(float(radius_m), 1.0)
        dlat = radius_m / geometry.METERS_PER_DEGREE_LAT
        dlon = radius_m / geometry.meters_per_degree_lon(lat)
        payload = self._cadastral_get(
            geom_filter=f"BOX({lon - dlon},{lat - dlat},{lon + dlon},{lat + dlat})",
            size=max(int(size), 1),
            with_geometry=True,
        )
        hits: list[ParcelCandidate] = []
        for feature in parsers.parse_cadastral_features(payload):
            center = geometry.centroid(feature.geometry)
            edge_m = geometry.min_edge_distance_m(lon, lat, feature.geometry)
            if edge_m is None and center is not None:
                edge_m = geometry.distance_m(lon, lat, center[0], center[1])
            hits.append(
                ParcelCandidate(
                    pnu=feature.parcel.pnu,
                    jibun_address=feature.parcel.jibun_address,
                    jibun=feature.parcel.jibun,
                    contains_point=geometry.point_in_geometry(lon, lat, feature.geometry),
                    approx_area_m2=geometry.approx_area_m2(feature.geometry, lat),
                    distance_m=edge_m,
                    lat=center[1] if center else None,
                    lon=center[0] if center else None,
                )
            )
        hits.sort(key=lambda item: (item.contains_point is not True, item.distance_m if item.distance_m is not None else 9e9))
        return hits

    def search_address(self, query: str) -> list[ParcelCandidate]:
        """지번 주소로 좌표를 찾는다. 지적 조회와 대조할 때 쓴다."""
        params = {
            "service": "search",
            "version": "2.0",
            "request": "search",
            "type": "address",
            "category": "parcel",
            "format": "json",
            "crs": DEFAULT_CRS,
            "query": query,
            "size": "10",
            "page": "1",
            **self._auth_params(with_domain=False),
        }
        return parsers.parse_search_items(self._get(SEARCH_URL, params, "주소 검색"))

    def _cadastral_get(self, geom_filter: str, size: int, with_geometry: bool) -> dict:
        params = {
            "service": "data",
            "version": "2.0",
            "request": "GetFeature",
            "data": CADASTRAL_LAYER,
            "format": "json",
            "crs": DEFAULT_CRS,
            "geomFilter": geom_filter,
            "geometry": "true" if with_geometry else "false",
            "attribute": "true",
            "size": str(size),
            "page": "1",
            **self._auth_params(),
        }
        return self._get(DATA_URL, params, "연속지적도 조회")

    def _address_params(self, lat: float, lon: float, address_type: str) -> dict[str, str]:
        return {
            "service": "address",
            "version": "2.0",
            "request": "getAddress",
            "type": address_type,
            "crs": DEFAULT_CRS,
            "point": f"{lon},{lat}",
            "format": "json",
            "simple": "false",
            **self._auth_params(with_domain=False),
        }

    def _get_parcel_from_geocoder(self, lat: float, lon: float) -> Parcel | None:
        payload = self._get(ADDRESS_URL, self._address_params(lat, lon, "PARCEL"), "지오코더 조회")
        parsed = parsers.parse_geocoder(payload)
        if not parsed or not parsed["ld_code"] or not parsed["jibun"]:
            return None
        return Parcel(
            pnu=build_pnu(parsed["ld_code"], parsed["jibun"]),
            jibun_address=parsed["text"],
            jibun=parsed["jibun"],
            ld_code=parsed["ld_code"],
            ld_name=parsed["ld_name"],
            road_address=parsed["road_address"],
            source="geocoder",
        )

    def _get_road_address(self, lat: float, lon: float) -> str:
        try:
            payload = self._get(ADDRESS_URL, self._address_params(lat, lon, "BOTH"), "도로명주소 조회")
            return parsers.parse_road_address(payload)
        except (AuthError, QuotaError):
            raise
        except Exception as exc:
            logger.debug("도로명주소 조회 실패: %s", exc)
            return ""

    def get_ledger(self, pnu: str) -> LandLedger | None:
        params = {
            "pnu": pnu,
            "format": "json",
            "numOfRows": "10",
            "pageNo": "1",
            **self._auth_params(),
        }
        ledger = parsers.parse_ledger(self._get(LADFRL_URL, params, "토지임야정보 조회"))
        try:
            possession = parsers.parse_possession(
                self._get(POSSESSION_URL, params, "토지소유정보 조회")
            )
        except (AuthError, QuotaError):
            raise
        except Exception as exc:
            logger.info("토지소유정보 조회 실패: %s", redact(str(exc), self.settings.api_key))
            possession = None
        return parsers.merge_ledger_possession(ledger, possession)

    def get_characteristics(self, pnu: str, stdr_year: int) -> LandCharacteristics | None:
        params = {
            "pnu": pnu,
            "stdrYear": str(stdr_year),
            "format": "json",
            "numOfRows": "10",
            "pageNo": "1",
            **self._auth_params(),
        }
        payload = self._get(LANDCHAR_URL, params, "토지특성정보 조회")
        return parsers.parse_characteristics(payload, str(stdr_year))


def _decode(response: Any, context: str) -> dict:
    try:
        payload = response.json()
    except ValueError as exc:
        raise NetworkError(f"{context}: JSON 응답이 아닙니다") from exc
    if not isinstance(payload, dict):
        raise NetworkError(f"{context}: 예상과 다른 응답 형식입니다")
    return payload


def _payload_summary(payload: dict) -> str:
    keys = ", ".join(str(key) for key in payload)
    return f"keys=[{keys}]"
