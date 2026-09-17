"""조회 결과 자료구조."""

from __future__ import annotations

from dataclasses import dataclass, field

# 소유자 성명은 어떤 공개 API로도 받을 수 없다. 등기사항증명서로 안내한다.
REGISTRY_URL = "https://www.iros.go.kr/"
OWNER_NAME_NOTICE = "소유자 성명은 공개 API 미제공 — 등기사항증명서 확인 필요"

OUTPUT_COLUMNS: tuple[str, ...] = (
    "입력위도",
    "입력경도",
    "지번주소",
    "도로명주소",
    "PNU",
    "법정동코드",
    "법정동명",
    "대장구분",
    "지목",
    "면적(㎡)",
    "소유구분",
    "국가기관구분",
    "거주지구분",
    "공유인수",
    "소유권변동원인",
    "소유권변동일자",
    "개별공시지가(원/㎡)",
    "공시기준연도",
    "용도지역1",
    "용도지역2",
    "토지이용상황",
    "등기열람URL",
    "비고",
)


@dataclass
class ParcelCandidate:
    """같은 지점 또는 주변에서 함께 조회된 필지."""

    pnu: str
    jibun_address: str = ""
    jibun: str = ""
    contains_point: bool | None = None
    approx_area_m2: float | None = None
    distance_m: float | None = None
    lat: float | None = None
    lon: float | None = None

    def describe(self) -> str:
        parts = [self.jibun_address or self.jibun or self.pnu]
        if self.pnu and self.jibun_address:
            parts.append(f"PNU {self.pnu}")
        if self.approx_area_m2:
            parts.append(f"약 {round(self.approx_area_m2):,}㎡")
        if self.contains_point is True:
            parts.append("점 포함")
        if self.distance_m is not None:
            if self.contains_point is True:
                parts.append(f"경계 {self.distance_m:.0f}m")
            else:
                parts.append(f"{self.distance_m:.0f}m")
        if self.lat is not None and self.lon is not None:
            parts.append(f"{self.lat:.6f}, {self.lon:.6f}")
        return " · ".join(parts)


@dataclass
class Parcel:
    """좌표로 찾은 필지의 기본 정보."""

    pnu: str
    jibun_address: str = ""
    jibun: str = ""
    ld_code: str = ""
    ld_name: str = ""
    road_address: str = ""
    official_price: str = ""
    price_year: str = ""
    price_month: str = ""
    source: str = "cadastral"
    contains_point: bool | None = None
    distance_m: float | None = None
    alternatives: list[ParcelCandidate] = field(default_factory=list)


@dataclass
class LandLedger:
    """토지(임야)대장 속성. 소유자 성명은 포함되지 않는다."""

    pnu: str = ""
    ld_code: str = ""
    ld_name: str = ""
    jibun: str = ""
    register_type: str = ""
    land_category: str = ""
    area: str = ""
    ownership_type: str = ""
    ownership_agency: str = ""
    residence_type: str = ""
    co_owner_count: str = ""
    ownership_change_reason: str = ""
    ownership_change_date: str = ""
    scale: str = ""
    last_update: str = ""


@dataclass
class LandCharacteristics:
    """토지특성정보(용도지역, 이용상황, 공시지가)."""

    pnu: str = ""
    stdr_year: str = ""
    use_area1: str = ""
    use_area2: str = ""
    land_use_situation: str = ""
    terrain_height: str = ""
    terrain_shape: str = ""
    road_side: str = ""
    official_price: str = ""
    area: str = ""
    land_category: str = ""
    last_update: str = ""


@dataclass
class LookupResult:
    """좌표 한 건에 대한 조회 결과."""

    lat: float | None = None
    lon: float | None = None
    parcel: Parcel | None = None
    ledger: LandLedger | None = None
    characteristics: LandCharacteristics | None = None
    nearby: list[ParcelCandidate] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def found(self) -> bool:
        return self.parcel is not None

    @property
    def registry_url(self) -> str:
        return REGISTRY_URL if self.parcel else ""

    def to_row(self) -> dict[str, str]:
        """CSV 한 행으로 펼친다."""
        parcel = self.parcel
        ledger = self.ledger
        chars = self.characteristics

        price = ""
        price_year = ""
        if chars and chars.official_price:
            price = chars.official_price
            price_year = chars.stdr_year
        elif parcel and parcel.official_price:
            price = parcel.official_price
            price_year = parcel.price_year

        return {
            "입력위도": f"{self.lat:.6f}" if self.lat is not None else "",
            "입력경도": f"{self.lon:.6f}" if self.lon is not None else "",
            "지번주소": parcel.jibun_address if parcel else "",
            "도로명주소": parcel.road_address if parcel else "",
            "PNU": parcel.pnu if parcel else "",
            "법정동코드": (ledger.ld_code if ledger and ledger.ld_code else (parcel.ld_code if parcel else "")),
            "법정동명": (ledger.ld_name if ledger and ledger.ld_name else (parcel.ld_name if parcel else "")),
            "대장구분": ledger.register_type if ledger else "",
            "지목": (ledger.land_category if ledger and ledger.land_category else (chars.land_category if chars else "")),
            "면적(㎡)": (ledger.area if ledger and ledger.area else (chars.area if chars else "")),
            "소유구분": ledger.ownership_type if ledger else "",
            "국가기관구분": ledger.ownership_agency if ledger else "",
            "거주지구분": ledger.residence_type if ledger else "",
            "공유인수": ledger.co_owner_count if ledger else "",
            "소유권변동원인": ledger.ownership_change_reason if ledger else "",
            "소유권변동일자": ledger.ownership_change_date if ledger else "",
            "개별공시지가(원/㎡)": price,
            "공시기준연도": price_year,
            "용도지역1": chars.use_area1 if chars else "",
            "용도지역2": chars.use_area2 if chars else "",
            "토지이용상황": chars.land_use_situation if chars else "",
            "등기열람URL": self.registry_url,
            "비고": " / ".join(self.warnings),
        }
