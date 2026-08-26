"""ADR 0002: ObsPy 왕복에서 의미 동등을 검사할 StationXML 필드.

XPath는 기본 네임스페이스를 ``fsx`` 접두어로 둔다.
반복 노드(Comment, Identifier, Equipment, Channel)는 트리 순회로 수집한다.
"""

from __future__ import annotations

from typing import Final

FDSN_NS: Final = "http://www.fdsn.org/xml/station/1"
NSMAP: Final = {"fsx": FDSN_NS}
SCHEMA_VERSION: Final = "1.2"

# 숫자 비교 상대 오차 (ADR 0002)
DECIMAL_REL_TOL: Final = 1e-9

DOCUMENT_TEXT_FIELDS: Final = (
    "Source",
    "Sender",
    "Module",
    "ModuleURI",
    "Created",
)

BASE_NODE_ATTRS: Final = (
    "code",
    "startDate",
    "endDate",
    "restrictedStatus",
    "alternateCode",
    "historicalCode",
    "sourceID",
)

UNCERTAIN_DOUBLE_ATTRS: Final = (
    "unit",
    "plusError",
    "minusError",
    "datum",
    "measurementMethod",
)

STATION_TEXT_FIELDS: Final = (
    "Description",
    "CreationDate",
    "TerminationDate",
    "Vault",
    "Geology",
)

STATION_GEO_FIELDS: Final = (
    "Latitude",
    "Longitude",
    "Elevation",
    "WaterLevel",
)

SITE_TEXT_FIELDS: Final = (
    "Name",
    "Description",
    "Town",
    "County",
    "Region",
    "Country",
)

CHANNEL_TEXT_FIELDS: Final = (
    "Description",
)

CHANNEL_GEO_FIELDS: Final = (
    "Latitude",
    "Longitude",
    "Elevation",
    "Depth",
    "Azimuth",
    "Dip",
    "WaterLevel",
)

CHANNEL_SCALAR_FIELDS: Final = (
    "SampleRate",
    "ClockDrift",
)

EQUIPMENT_TEXT_FIELDS: Final = (
    "Type",
    "Description",
    "Manufacturer",
    "Vendor",
    "Model",
    "SerialNumber",
    "InstallationDate",
    "RemovalDate",
    "CalibrationDate",
)

CHANNEL_EQUIPMENT_TAGS: Final = (
    "Sensor",
    "PreAmplifier",
    "DataLogger",
    "Equipment",
)

# 값이 달라도 오류가 아닌 필드 (ADR: 의도적 차이)
INTENTIONAL_DIFF_FIELDS: Final = frozenset(
    {
        "Created",  # 신규 스냅샷 시각. 원문 패치 경로에서는 유지한다.
        "TotalNumberChannels",
        "SelectedNumberChannels",
    }
)

# ObsPy Inventory.write()가 삼키거나 깨뜨리는 것으로 확인된 항목
OBSPY_WRITE_KNOWN_LOSS: Final = (
    "Operator extra Agency beyond the first",
    "XML comments",
    "Processing instructions",
    "Channel/StorageFormat",
    "Document Source/Sender/Module overwritten by Inventory defaults",
    "Custom namespace extra nodes may move or drop depending on ObsPy version",
)


def fqn(tag: str) -> str:
    """FDSN 네임스페이스 Clark 표기."""
    return f"{{{FDSN_NS}}}{tag}"
