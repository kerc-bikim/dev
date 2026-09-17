"""조회 오케스트레이션.

필지를 찾는 1단계는 필수지만, 대장·토지특성 조회가 실패해도 나머지 정보는
살려서 돌려준다. 인증 오류와 한도 초과만 위로 던진다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from .datum import tokyo_to_wgs84
from .errors import AuthError, InputError, LatlonError, QuotaError
from . import geometry
from .models import LookupResult, Parcel, ParcelCandidate
from .pnu import is_valid_pnu, parse_pnu
from .providers.base import LandDataProvider

logger = logging.getLogger(__name__)

NO_PARCEL_MESSAGE = "해당 좌표에서 필지를 찾지 못했습니다 (해상·국외·미등록 지역일 수 있음)"
SYNTHESIZED_MESSAGE = (
    "mock 제공자가 만들어 낸 합성 데이터입니다 (실제 지번 아님). "
    "실제 주소가 필요하면 VWORLD_API_KEY를 설정하고 --provider vworld 로 실행하세요."
)


@dataclass
class LookupOptions:
    """조회 세부 설정."""

    stdr_year: int | None = None
    with_road: bool = False
    # 올해 자료가 아직 고시되지 않았을 수 있어 연도를 낮춰 가며 재시도한다.
    year_attempts: int = 3
    nearby_m: float | None = None
    crs: str = "wgs84"


def current_year() -> int:
    return datetime.now(timezone.utc).year


class LandLookupService:
    """제공자를 감싸 한 좌표에 대한 완성된 결과를 만든다."""

    def __init__(self, provider: LandDataProvider) -> None:
        self.provider = provider

    def lookup_point(self, lat: float, lon: float, options: LookupOptions | None = None) -> LookupResult:
        options = options or LookupOptions()
        _validate_coords(lat, lon)

        result = LookupResult(lat=lat, lon=lon)
        query_lat, query_lon = lat, lon
        logger.info(
            "좌표 조회 lat=%s lon=%s crs=%s provider=%s",
            lat,
            lon,
            options.crs,
            getattr(self.provider, "name", type(self.provider).__name__),
        )
        if options.crs == "tokyo":
            query_lat, query_lon = tokyo_to_wgs84(lat, lon)
            shift = geometry.distance_m(lon, lat, query_lon, query_lat)
            logger.info("동경측지계 → WGS84 %s, %s (약 %.0fm)", f"{query_lat:.6f}", f"{query_lon:.6f}", shift)
            result.warnings.append(
                f"동경측지계(Bessel) 입력을 WGS84로 변환했습니다 → "
                f"{query_lat:.6f}, {query_lon:.6f} (약 {shift:.0f}m)"
            )

        parcel = self.provider.get_parcel(query_lat, query_lon, options.with_road)
        if parcel is None:
            logger.info("필지를 찾지 못했습니다")
            result.warnings.append(NO_PARCEL_MESSAGE)
            self._attach_nearby(result, query_lat, query_lon, options, None)
            return result

        result.parcel = parcel
        logger.info(
            "필지 %s PNU %s source=%s",
            parcel.jibun_address or parcel.jibun,
            parcel.pnu,
            parcel.source,
        )
        if parcel.source.startswith("mock"):
            result.warnings.append(SYNTHESIZED_MESSAGE)
        if parcel.contains_point is False:
            result.warnings.append(
                "입력한 점이 필지 경계 안에 들어가지 않습니다. "
                "연속지적도와 위치 오차이거나 좌표가 경계에 걸쳤을 수 있습니다"
            )
        if parcel.alternatives:
            shown = ", ".join(item.describe() for item in parcel.alternatives[:5])
            result.warnings.append(f"같은 지점에 겹치는 필지가 더 있습니다: {shown}")
            logger.info("같은 점의 다른 필지 %d건: %s", len(parcel.alternatives), shown)
        self._attach_nearby(result, query_lat, query_lon, options, parcel)
        self._fill_details(result, parcel.pnu, options)
        return result

    def search_address(
        self,
        query: str,
        lat: float | None = None,
        lon: float | None = None,
    ) -> list[ParcelCandidate]:
        query = query.strip()
        if not query:
            raise InputError("검색어를 입력하세요")
        searcher = getattr(self.provider, "search_address", None)
        if searcher is None:
            raise InputError("이 제공자는 주소 검색을 지원하지 않습니다")
        hits = list(searcher(query))
        logger.info("주소 검색 %r → %d건", query, len(hits))
        if lat is not None and lon is not None:
            _validate_coords(lat, lon)
            for hit in hits:
                if hit.lat is not None and hit.lon is not None:
                    hit.distance_m = geometry.distance_m(lon, lat, hit.lon, hit.lat)
        return hits

    def lookup_pnu(self, pnu: str, options: LookupOptions | None = None) -> LookupResult:
        options = options or LookupOptions()
        if not is_valid_pnu(pnu):
            raise InputError(f"PNU는 숫자 19자리여야 합니다: {pnu}")

        logger.info("PNU 조회 %s provider=%s", pnu, getattr(self.provider, "name", type(self.provider).__name__))
        result = LookupResult()
        self._fill_details(result, pnu, options)

        ledger = result.ledger
        parts = parse_pnu(pnu)
        address = " ".join(part for part in ((ledger.ld_name if ledger else ""), parts.jibun) if part)
        result.parcel = Parcel(
            pnu=pnu,
            jibun_address=address,
            jibun=parts.jibun,
            ld_code=parts.ld_code,
            ld_name=ledger.ld_name if ledger else "",
            source="pnu",
        )
        return result

    # --- 내부 -------------------------------------------------------------

    def _attach_nearby(
        self,
        result: LookupResult,
        lat: float,
        lon: float,
        options: LookupOptions,
        parcel: Parcel | None,
    ) -> None:
        if not options.nearby_m:
            return
        finder = getattr(self.provider, "find_nearby", None)
        if finder is None:
            return
        nearby = [
            item
            for item in finder(lat, lon, radius_m=options.nearby_m)
            if parcel is None or item.pnu != parcel.pnu
        ]
        result.nearby = nearby
        if nearby:
            shown = ", ".join(item.describe() for item in nearby[:8])
            result.warnings.append(f"주변 {options.nearby_m:.0f}m 필지: {shown}")
            logger.info("주변 %.0fm 필지 %d건", options.nearby_m, len(nearby))

    def _fill_details(self, result: LookupResult, pnu: str, options: LookupOptions) -> None:
        try:
            result.ledger = self.provider.get_ledger(pnu)
            if result.ledger is None:
                result.warnings.append("토지임야정보가 조회되지 않았습니다")
                logger.info("토지임야정보 없음 PNU %s", pnu)
            else:
                logger.info(
                    "토지임야정보 소유구분=%s 국가기관구분=%s 거주지구분=%s 지목=%s 면적=%s 대장=%s",
                    result.ledger.ownership_type or "-",
                    result.ledger.ownership_agency or "-",
                    result.ledger.residence_type or "-",
                    result.ledger.land_category or "-",
                    result.ledger.area or "-",
                    result.ledger.register_type or "-",
                )
        except (AuthError, QuotaError):
            raise
        except LatlonError as exc:
            logger.info("토지임야정보 조회 실패: %s", exc)
            result.warnings.append(str(exc))

        result.characteristics = self._get_characteristics(result, pnu, options)

    def _get_characteristics(self, result: LookupResult, pnu: str, options: LookupOptions):
        base_year = options.stdr_year or current_year()
        attempts = max(options.year_attempts, 1) if options.stdr_year is None else 1

        for offset in range(attempts):
            year = base_year - offset
            try:
                characteristics = self.provider.get_characteristics(pnu, year)
            except (AuthError, QuotaError):
                raise
            except LatlonError as exc:
                logger.info("토지특성정보 조회 실패(%d년): %s", year, exc)
                result.warnings.append(str(exc))
                return None
            if characteristics is not None:
                if offset:
                    result.warnings.append(f"{base_year}년 토지특성 자료가 없어 {year}년 자료를 사용했습니다")
                logger.info(
                    "토지특성 %s년 용도지역=%s 이용상황=%s",
                    characteristics.stdr_year or year,
                    characteristics.use_area1 or "-",
                    characteristics.land_use_situation or "-",
                )
                return characteristics

        result.warnings.append("토지특성정보가 조회되지 않았습니다")
        return None


def _validate_coords(lat: float, lon: float) -> None:
    if not -90.0 <= lat <= 90.0:
        raise InputError(f"위도는 -90~90 범위여야 합니다: {lat}")
    if not -180.0 <= lon <= 180.0:
        raise InputError(f"경도는 -180~180 범위여야 합니다: {lon}")
