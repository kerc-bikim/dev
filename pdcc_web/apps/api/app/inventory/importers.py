"""StationXML 가져오기. 원문은 FileAsset 에 보관하고 편집 XML 과 덮어쓰지 않습니다."""

from __future__ import annotations

from lxml import etree

from ..config import settings
from .xmlbuild import NETWORK_CODE_RE, InventoryError, list_inventory
from .xmlutil import local, parse_root, qname


def inspect_stationxml(raw: bytes) -> dict:
    if not raw or not raw.strip():
        raise InventoryError("파일이 비어 있습니다", 400, "E_IMPORT")
    if len(raw) > settings.max_upload_bytes:
        raise InventoryError("파일이 너무 큽니다", 400, "E_IMPORT")
    if raw[:2] == b"PK":
        raise InventoryError("zip은 아직 열 수 없습니다. StationXML을 선택하세요", 400, "E_IMPORT")
    stripped = raw.lstrip(b"\xef\xbb\xbf \t\r\n")
    if not stripped.startswith(b"<"):
        raise InventoryError("StationXML이 아닙니다. dataless SEED 가져오기는 아직 없습니다", 400, "E_IMPORT")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise InventoryError("UTF-8 StationXML만 열 수 있습니다", 400, "E_IMPORT") from exc
    try:
        root = parse_root(text)
    except etree.XMLSyntaxError as exc:
        raise InventoryError("XML 구조가 표준과 다릅니다", 400, "XSD") from exc
    if local(root.tag) != "FDSNStationXML":
        raise InventoryError("FDSN StationXML이 아닙니다", 400, "XSD")
    version = root.get("schemaVersion") or ""
    if version != "1.2":
        raise InventoryError("schemaVersion 은 1.2 여야 합니다", 400, "XSD")
    nets = [node for node in root.findall(qname("Network")) if node.get("code")]
    if not nets:
        raise InventoryError("Network가 없습니다", 400, "E_CODE_NET")
    if len(nets) > 1:
        raise InventoryError("파일에 네트워크가 여러 개입니다. 하나만 있는 StationXML을 여세요", 400, "E_CODE_NET")
    code = (nets[0].get("code") or "").strip().upper()
    if not NETWORK_CODE_RE.match(code):
        raise InventoryError("네트워크 코드가 올바르지 않습니다", 400, "E_CODE_NET")
    stations = list_inventory(text, code, 0)
    return {
        "network_code": code,
        "xml_text": text,
        "station_count": len(stations),
        "channel_count": sum(len(sta["channels"]) for sta in stations),
    }
