"""키 없이 동작하는 mock 제공자.

`fixtures/`에 담아 둔 실제 스키마의 응답을 좌표로 찾아 재생하고,
등록되지 않은 좌표는 좌표 해시로 결정론적인 가짜 필지를 만들어 낸다.
어느 쪽이든 실제 API와 동일한 파서를 거치므로 두 경로가 같은 스키마를 본다.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .. import parsers
from ..config import FIXTURES_DIR
from ..models import LandCharacteristics, LandLedger, Parcel
from ..pnu import build_pnu, format_jibun, parse_pnu

# 국내를 대강 감싸는 사각 범위. 해상도 들어가는 근사치라 mock 안에서만 쓴다.
# 이 밖이면 필지가 없는 것으로 본다.
KOREA_BBOX = (33.0, 38.7, 124.5, 131.9)

# fixtures에 없는 좌표를 만들어 냈다는 표시. 결과에 경고로 남는다.
SYNTHESIZED_SOURCE = "mock-synth"

# 합성 주소는 실제 지번으로 오해하기 쉬우므로 실재하지 않는 이름과
# 쓰이지 않는 법정동코드(9999…)를 써서 한눈에 구분되게 한다.
MOCK_LABEL = "[모의]"

_SAMPLE_DONG: tuple[tuple[str, str], ...] = (
    ("9999900001", f"{MOCK_LABEL} 가상시 가상구 가동"),
    ("9999900002", f"{MOCK_LABEL} 가상시 가상구 나동"),
    ("9999900003", f"{MOCK_LABEL} 가상시 가상구 다동"),
    ("9999900004", f"{MOCK_LABEL} 가상군 가상면 라리"),
    ("9999900005", f"{MOCK_LABEL} 가상군 가상면 마리"),
)

_SAMPLE_OWNERSHIP: tuple[tuple[str, str], ...] = (
    ("3301", "개인"),
    ("3302", "국유지"),
    ("3304", "시.도유지"),
    ("3306", "법인"),
)

_SAMPLE_CATEGORY: tuple[tuple[str, str], ...] = (
    ("0001", "전"),
    ("0005", "임야"),
    ("0008", "대"),
    ("0014", "도로"),
    ("0028", "잡종지"),
)

_SAMPLE_USE_AREA: tuple[str, ...] = (
    "제1종일반주거지역",
    "계획관리지역",
    "보전관리지역",
    "농림지역",
    "자연녹지지역",
)


def _seed(*parts: Any) -> int:
    raw = "|".join(str(part) for part in parts)
    return int(hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12], 16)


class MockProvider:
    """fixtures 기반 오프라인 제공자."""

    name = "mock"

    def __init__(self, fixtures_dir: Path | None = None) -> None:
        self.fixtures_dir = Path(fixtures_dir or FIXTURES_DIR)
        index_path = self.fixtures_dir / "index.json"
        index = json.loads(index_path.read_text(encoding="utf-8")) if index_path.is_file() else {}
        self.tolerance = float(index.get("match_tolerance_deg", 0.001))
        self.points: list[dict[str, Any]] = list(index.get("points", []))
        self._payloads: dict[str, dict] = {}
        self._by_pnu: dict[str, dict[str, Any]] | None = None

    # --- fixtures ---------------------------------------------------------

    def _payload(self, filename: str) -> dict:
        if filename not in self._payloads:
            path = self.fixtures_dir / filename
            self._payloads[filename] = json.loads(path.read_text(encoding="utf-8"))
        return self._payloads[filename]

    def _entry_for_point(self, lat: float, lon: float) -> dict[str, Any] | None:
        for entry in self.points:
            if (
                abs(float(entry["lat"]) - lat) <= self.tolerance
                and abs(float(entry["lon"]) - lon) <= self.tolerance
            ):
                return entry
        return None

    def _entry_for_pnu(self, pnu: str) -> dict[str, Any] | None:
        if self._by_pnu is None:
            self._by_pnu = {}
            for entry in self.points:
                cadastral = entry.get("cadastral")
                if not cadastral:
                    continue
                parcel = parsers.parse_cadastral(self._payload(cadastral))
                if parcel:
                    self._by_pnu[parcel.pnu] = entry
        return self._by_pnu.get(pnu)

    # --- 조회 -------------------------------------------------------------

    def get_parcel(self, lat: float, lon: float, with_road: bool = False) -> Parcel | None:
        entry = self._entry_for_point(lat, lon)
        if entry is not None:
            parcel = parsers.parse_cadastral(self._payload(entry["cadastral"]))
            if parcel and with_road and entry.get("geocoder"):
                parcel.road_address = parsers.parse_road_address(self._payload(entry["geocoder"]))
            return parcel

        lat_min, lat_max, lon_min, lon_max = KOREA_BBOX
        if not (lat_min <= lat <= lat_max and lon_min <= lon <= lon_max):
            return None
        parcel = parsers.parse_cadastral(_synth_cadastral(lat, lon))
        if parcel:
            parcel.source = SYNTHESIZED_SOURCE
        return parcel

    def get_ledger(self, pnu: str) -> LandLedger | None:
        entry = self._entry_for_pnu(pnu)
        if entry is not None:
            if not entry.get("ledger"):
                return None
            return parsers.parse_ledger(self._payload(entry["ledger"]))
        return parsers.parse_ledger(_synth_ledger(pnu))

    def get_characteristics(self, pnu: str, stdr_year: int) -> LandCharacteristics | None:
        entry = self._entry_for_pnu(pnu)
        if entry is not None:
            if not entry.get("characteristics"):
                return None
            return parsers.parse_characteristics(
                self._payload(entry["characteristics"]), str(stdr_year)
            )
        return parsers.parse_characteristics(_synth_characteristics(pnu, stdr_year), str(stdr_year))


# --- 결정론적 합성 응답 --------------------------------------------------


def _synth_cadastral(lat: float, lon: float) -> dict:
    seed = _seed(round(lat, 5), round(lon, 5))
    ld_code, ld_name = _SAMPLE_DONG[seed % len(_SAMPLE_DONG)]
    mountain = seed % 5 == 0
    bonbun = seed // 7 % 900 + 1
    bubun = seed // 13 % 5
    jibun = format_jibun(bonbun, bubun, mountain)
    return {
        "response": {
            "status": "OK",
            "record": {"total": "1", "current": "1"},
            "result": {
                "featureCollection": {
                    "type": "FeatureCollection",
                    "features": [
                        {
                            "type": "Feature",
                            "geometry": None,
                            "properties": {
                                "pnu": build_pnu(ld_code, jibun),
                                "jibun": jibun,
                                "bonbun": str(bonbun),
                                "bubun": str(bubun) if bubun else "",
                                "addr": f"{ld_name} {jibun}",
                                "gosi_year": "2025",
                                "gosi_month": "01",
                                "jiga": str(10000 + seed % 2000000),
                            },
                        }
                    ],
                }
            },
        }
    }


def _ld_name_for(ld_code: str) -> str:
    for code, name in _SAMPLE_DONG:
        if code == ld_code:
            return name
    return f"{MOCK_LABEL} 가상 법정동"


def _synth_ledger(pnu: str) -> dict:
    parts = parse_pnu(pnu)
    seed = _seed(pnu)
    ownership_code, ownership_name = _SAMPLE_OWNERSHIP[seed % len(_SAMPLE_OWNERSHIP)]
    category_code, category_name = (
        ("0005", "임야") if parts.is_mountain else _SAMPLE_CATEGORY[seed % len(_SAMPLE_CATEGORY)]
    )
    return {
        "fields": {
            "totalCount": "1",
            "ladfrlVOList": [
                {
                    "pnu": pnu,
                    "ldCode": parts.ld_code,
                    "ldCodeNm": _ld_name_for(parts.ld_code),
                    "regstrSeCode": "2" if parts.is_mountain else "1",
                    "regstrSeCodeNm": "임야대장" if parts.is_mountain else "토지대장",
                    "mnnmSlno": format_jibun(parts.bonbun, parts.bubun),
                    "lndcgrCode": category_code,
                    "lndcgrCodeNm": category_name,
                    "lndpclAr": str(100 + seed % 90000),
                    "posesnSeCode": ownership_code,
                    "posesnSeCodeNm": ownership_name,
                    "cnrsPsnCo": str(1 + seed % 3),
                    "posesnChgCauseCodeNm": "매매" if ownership_code == "3301" else "소유권보존",
                    "posesnChgDe": f"20{10 + seed % 15:02d}{1 + seed % 12:02d}{1 + seed % 28:02d}",
                    "ladFrtlSc": "5512",
                    "ladFrtlScNm": "1:1200",
                    "lastUpdtDt": "2025-08-31",
                }
            ],
        }
    }


def _synth_characteristics(pnu: str, stdr_year: int) -> dict:
    parts = parse_pnu(pnu)
    seed = _seed(pnu, stdr_year)
    return {
        "landCharacteristicss": {
            "totalCount": "1",
            "field": [
                {
                    "pnu": pnu,
                    "ldCodeNm": _ld_name_for(parts.ld_code),
                    "mnnmSlno": parts.jibun,
                    "stdrYear": str(stdr_year),
                    "lndcgrCode": "0005" if parts.is_mountain else "0008",
                    "lndcgrCodeNm": "임야" if parts.is_mountain else "대",
                    "lndpclAr": str(100 + _seed(pnu) % 90000),
                    "prposArea1Nm": _SAMPLE_USE_AREA[seed % len(_SAMPLE_USE_AREA)],
                    "prposArea2Nm": "지정되지않음",
                    "ladUseSittnNm": "자연림" if parts.is_mountain else "단독주택",
                    "tpgrphHgCodeNm": "고지" if parts.is_mountain else "평지",
                    "tpgrphFrmCodeNm": "부정형",
                    "roadSideCodeNm": "맹지" if parts.is_mountain else "세로한면",
                    "pblntfPclnd": str(1000 + seed % 500000),
                    "lastUpdtDt": "2025-05-31",
                }
            ],
        }
    }
