"""PNU(필지 고유번호) 조립·해석.

PNU는 19자리 숫자이며 다음처럼 구성된다.

    법정동코드 10 + 대장구분 1 + 본번 4 + 부번 4

대장구분은 토지대장이 `1`, 임야대장(산 번지)이 `2`다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .errors import InputError

PNU_LENGTH = 19
LD_CODE_LENGTH = 10

LAND_REGISTER = "1"
MOUNTAIN_REGISTER = "2"

# "산 12-3", "산12", "808-1", "808" 을 모두 받아들인다.
_JIBUN_RE = re.compile(r"^\s*(?P<san>산)?\s*(?P<bonbun>\d+)\s*(?:-\s*(?P<bubun>\d+))?\s*$")


@dataclass(frozen=True)
class PnuParts:
    """PNU를 구성 요소로 분해한 값."""

    ld_code: str
    register: str
    bonbun: int
    bubun: int

    @property
    def is_mountain(self) -> bool:
        return self.register == MOUNTAIN_REGISTER

    @property
    def jibun(self) -> str:
        return format_jibun(self.bonbun, self.bubun, self.is_mountain)


def parse_jibun(jibun: str) -> tuple[bool, int, int]:
    """지번 문자열을 (산 여부, 본번, 부번)으로 나눈다."""
    if not jibun or not jibun.strip():
        raise InputError("지번이 비어 있습니다")
    # 연속지적도의 jibun은 "808 대"처럼 지목이 붙어 오므로 숫자 부분만 남긴다.
    head = jibun.strip().split()
    if len(head) > 1 and not head[-1][0].isdigit() and head[-1] != "산":
        jibun = " ".join(head[:-1])
    matched = _JIBUN_RE.match(jibun)
    if not matched:
        raise InputError(f"지번 형식을 읽을 수 없습니다: {jibun}")
    bubun = matched.group("bubun")
    return (
        matched.group("san") is not None,
        int(matched.group("bonbun")),
        int(bubun) if bubun else 0,
    )


def format_jibun(bonbun: int, bubun: int, is_mountain: bool = False) -> str:
    """본번/부번을 사람이 읽는 지번 문자열로 만든다."""
    text = str(bonbun) if not bubun else f"{bonbun}-{bubun}"
    return f"산 {text}" if is_mountain else text


def build_pnu(ld_code: str, jibun: str, is_mountain: bool | None = None) -> str:
    """법정동코드와 지번으로 19자리 PNU를 만든다.

    `is_mountain`을 주면 지번의 '산' 표기보다 우선한다.
    """
    code = (ld_code or "").strip()
    if not code.isdigit() or len(code) != LD_CODE_LENGTH:
        raise InputError(f"법정동코드는 숫자 {LD_CODE_LENGTH}자리여야 합니다: {ld_code}")
    san, bonbun, bubun = parse_jibun(jibun)
    mountain = san if is_mountain is None else is_mountain
    register = MOUNTAIN_REGISTER if mountain else LAND_REGISTER
    return f"{code}{register}{bonbun:04d}{bubun:04d}"


def is_valid_pnu(pnu: str | None) -> bool:
    text = (pnu or "").strip()
    return len(text) == PNU_LENGTH and text.isdigit()


def parse_pnu(pnu: str) -> PnuParts:
    """19자리 PNU를 구성 요소로 나눈다."""
    text = (pnu or "").strip()
    if not is_valid_pnu(text):
        raise InputError(f"PNU는 숫자 {PNU_LENGTH}자리여야 합니다: {pnu}")
    return PnuParts(
        ld_code=text[:10],
        register=text[10],
        bonbun=int(text[11:15]),
        bubun=int(text[15:19]),
    )
