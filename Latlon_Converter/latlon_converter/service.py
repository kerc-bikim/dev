"""조회 오케스트레이션.

필지를 찾는 1단계는 필수지만, 대장·토지특성 조회가 실패해도 나머지 정보는
살려서 돌려준다. 인증 오류와 한도 초과만 위로 던진다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from .errors import AuthError, InputError, LatlonError, QuotaError
from .models import LookupResult, Parcel
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
        parcel = self.provider.get_parcel(lat, lon, options.with_road)
        if parcel is None:
            result.warnings.append(NO_PARCEL_MESSAGE)
            return result

        result.parcel = parcel
        if parcel.source.startswith("mock"):
            result.warnings.append(SYNTHESIZED_MESSAGE)
        self._fill_details(result, parcel.pnu, options)
        return result

    def lookup_pnu(self, pnu: str, options: LookupOptions | None = None) -> LookupResult:
        options = options or LookupOptions()
        if not is_valid_pnu(pnu):
            raise InputError(f"PNU는 숫자 19자리여야 합니다: {pnu}")

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

    def _fill_details(self, result: LookupResult, pnu: str, options: LookupOptions) -> None:
        try:
            result.ledger = self.provider.get_ledger(pnu)
            if result.ledger is None:
                result.warnings.append("토지임야정보가 조회되지 않았습니다")
        except (AuthError, QuotaError):
            raise
        except LatlonError as exc:
            logger.debug("토지임야정보 조회 실패: %s", exc)
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
                logger.debug("토지특성정보 조회 실패(%d년): %s", year, exc)
                result.warnings.append(str(exc))
                return None
            if characteristics is not None:
                if offset:
                    result.warnings.append(f"{base_year}년 토지특성 자료가 없어 {year}년 자료를 사용했습니다")
                return characteristics

        result.warnings.append("토지특성정보가 조회되지 않았습니다")
        return None


def _validate_coords(lat: float, lon: float) -> None:
    if not -90.0 <= lat <= 90.0:
        raise InputError(f"위도는 -90~90 범위여야 합니다: {lat}")
    if not -180.0 <= lon <= 180.0:
        raise InputError(f"경도는 -180~180 범위여야 합니다: {lon}")
