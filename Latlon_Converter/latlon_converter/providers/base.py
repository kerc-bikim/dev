"""제공자 인터페이스.

`service.py`는 이 프로토콜에만 의존하므로 mock과 실제 API를 같은 코드로 다룬다.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..models import LandCharacteristics, LandLedger, Parcel, ParcelCandidate


@runtime_checkable
class LandDataProvider(Protocol):
    """좌표/PNU로 토지 정보를 가져오는 제공자."""

    name: str

    def get_parcel(self, lat: float, lon: float, with_road: bool = False) -> Parcel | None:
        """좌표가 속한 필지를 찾는다. 없으면 None."""

    def find_nearby(self, lat: float, lon: float, meters: float) -> list[ParcelCandidate]:
        """점 주변 필지를 가까운 순으로 돌려준다. 지번 확인용."""

    def get_ledger(self, pnu: str) -> LandLedger | None:
        """토지(임야)대장 속성을 가져온다."""

    def get_characteristics(self, pnu: str, stdr_year: int) -> LandCharacteristics | None:
        """해당 기준연도의 토지특성정보를 가져온다."""
