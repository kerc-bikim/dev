"""지적 공부에서 쓰는 코드 → 명칭 변환표.

브이월드 국가중점데이터 API는 코드와 명칭(`...CodeNm`)을 함께 주지만,
명칭이 비어 오는 응답이 있어 코드로도 이름을 복원할 수 있게 해 둔다.
"""

from __future__ import annotations

# 지목코드 (lndcgrCode)
LAND_CATEGORY: dict[str, str] = {
    "0000": "지정되지않음",
    "0001": "전",
    "0002": "답",
    "0003": "과수원",
    "0004": "목장용지",
    "0005": "임야",
    "0006": "광천지",
    "0007": "염전",
    "0008": "대",
    "0009": "공장용지",
    "0010": "학교용지",
    "0011": "주차장",
    "0012": "주유소용지",
    "0013": "창고용지",
    "0014": "도로",
    "0015": "철도용지",
    "0016": "제방",
    "0017": "하천",
    "0018": "구거",
    "0019": "유지",
    "0020": "양어장",
    "0021": "수도용지",
    "0022": "공원",
    "0023": "체육용지",
    "0024": "유원지",
    "0025": "종교용지",
    "0026": "사적지",
    "0027": "묘지",
    "0028": "잡종지",
}

# 대장구분코드 (regstrSeCode)
# 응답에 따라 3자리(221) 또는 1자리(1)로 오기 때문에 둘 다 담는다.
REGISTER_TYPE: dict[str, str] = {
    "1": "토지대장",
    "2": "임야대장",
    "221": "토지대장",
    "222": "임야대장",
    "228": "토지대장(폐쇄)",
    "229": "임야대장(폐쇄)",
}

# 소유구분코드 (posesnSeCode)
OWNERSHIP_TYPE: dict[str, str] = {
    "3300": "일본인,창씨명",
    "3301": "개인",
    "3302": "국유지",
    "3303": "외국인,외국공공기관",
    "3304": "시.도유지",
    "3305": "군유지",
    "3306": "법인",
    "3307": "종중",
    "3308": "종교단체",
    "3309": "기타단체",
}

# 축척구분코드 (ladFrtlSc)
SCALE_TYPE: dict[str, str] = {
    "5505": "1:500",
    "5506": "1:600",
    "5510": "1:1000",
    "5512": "1:1200",
    "5524": "1:2400",
    "5530": "1:3000",
    "5560": "1:6000",
}

# 임야대장(산 번지)에 해당하는 대장구분코드
MOUNTAIN_REGISTER_CODES = frozenset({"2", "222", "229"})


def _lookup(table: dict[str, str], code: str | None, name: str | None) -> str:
    """명칭이 오면 그대로 쓰고, 없으면 코드표에서 찾는다."""
    if name and name.strip():
        return name.strip()
    if not code:
        return ""
    key = code.strip()
    if key in table:
        return table[key]
    return f"알수없음({key})"


def land_category_name(code: str | None, name: str | None = None) -> str:
    return _lookup(LAND_CATEGORY, code, name)


def register_type_name(code: str | None, name: str | None = None) -> str:
    return _lookup(REGISTER_TYPE, code, name)


def ownership_type_name(code: str | None, name: str | None = None) -> str:
    return _lookup(OWNERSHIP_TYPE, code, name)


def scale_name(code: str | None, name: str | None = None) -> str:
    return _lookup(SCALE_TYPE, code, name)


def is_mountain_register(code: str | None, name: str | None = None) -> bool:
    """임야대장 여부. 코드가 없으면 명칭에 '임야'가 있는지로 판단한다."""
    if code and code.strip() in MOUNTAIN_REGISTER_CODES:
        return True
    if code and code.strip() in REGISTER_TYPE:
        return False
    return bool(name and "임야" in name)
