"""StationXML·dataless SEED·RESP 가져오기. 원문은 FileAsset 에 보관하고 편집 XML 과 덮어쓰지 않습니다."""

from __future__ import annotations

import json

from lxml import etree
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import FileAsset
from .resp_convert import convert_resp_to_xml
from .seed_convert import (
    SEED_MEDIA,
    convert_dataless_to_xml,
    looks_like_resp,
    looks_like_seed,
)
from .xmlbuild import NETWORK_CODE_RE, InventoryError, list_inventory
from .xmlutil import local, parse_root, qname

WARNINGS_KIND = "import_warnings"
ALLOWED_UPLOAD_SUFFIXES = (".xml", ".seed", ".dataless", ".resp")


def validate_upload_filename(filename: str) -> str:
    name = (filename or "").strip()
    lowered = name.lower()
    if (
        not name
        or "\x00" in name
        or "/" in name
        or "\\" in name
        or ":" in name
        or (
            not lowered.endswith(ALLOWED_UPLOAD_SUFFIXES)
            and not (lowered.startswith("resp.") and len(name) > len("resp."))
        )
    ):
        raise InventoryError(
            "허용된 확장자는 .xml, .seed, .dataless, .resp 입니다",
            400,
            "E_UPLOAD_EXTENSION",
        )
    return name


def inspect_stationxml(raw: bytes) -> dict:
    if not raw or not raw.strip():
        raise InventoryError("파일이 비어 있습니다", 400, "E_IMPORT")
    if len(raw) > settings.max_upload_bytes:
        raise InventoryError("파일이 너무 큽니다", 413, "E_UPLOAD_SIZE")
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
        "kind": "stationxml",
        "network_code": code,
        "xml_text": text,
        "station_count": len(stations),
        "channel_count": sum(len(sta["channels"]) for sta in stations),
        "media_type": "application/xml",
        "warnings": [],
    }


def inspect_upload(raw: bytes, filename: str = "") -> dict:
    if not raw or not raw.strip():
        raise InventoryError("파일이 비어 있습니다", 400, "E_IMPORT")
    if len(raw) > settings.max_upload_bytes:
        raise InventoryError("파일이 너무 큽니다", 413, "E_UPLOAD_SIZE")
    if raw[:2] == b"PK":
        raise InventoryError("zip은 아직 열 수 없습니다. StationXML, dataless SEED 또는 RESP를 선택하세요", 400, "E_IMPORT")
    if (filename or "").lower().endswith(".mseed"):
        raise InventoryError(
            "파형 MiniSEED는 열 수 없습니다. dataless SEED를 선택하세요",
            400,
            "E_IMPORT",
        )
    validate_upload_filename(filename)
    stripped = raw.lstrip(b"\xef\xbb\xbf \t\r\n")
    name = (filename or "").lower()
    seed_name = name.endswith(".seed") or name.endswith(".dataless")
    resp_name = name.endswith(".resp")
    if stripped.startswith(b"<"):
        info = inspect_stationxml(raw)
        return info
    if looks_like_resp(raw) or resp_name:
        if looks_like_seed(raw) and seed_name:
            pass
        else:
            xml, notes = convert_resp_to_xml(raw)
            info = inspect_stationxml(xml.encode("utf-8"))
            info["kind"] = "resp"
            info["media_type"] = "text/x-seed-resp"
            info["warnings"] = notes
            return info
    if looks_like_seed(raw) or seed_name:
        xml, notes = convert_dataless_to_xml(raw)
        info = inspect_stationxml(xml.encode("utf-8"))
        info["kind"] = "dataless"
        info["media_type"] = SEED_MEDIA
        info["warnings"] = notes
        return info
    raise InventoryError(
        "StationXML이 아닙니다. dataless SEED, RESP 또는 StationXML을 선택하세요",
        400,
        "E_IMPORT",
    )


def original_kind_of(asset: FileAsset | None) -> str | None:
    if asset is None:
        return None
    media = (asset.media_type or "").lower()
    name = (asset.filename or "").lower()
    if "resp" in media or name.endswith(".resp") or name.startswith("resp."):
        return "resp"
    if "seed" in media or name.endswith(".seed") or name.endswith(".dataless"):
        return "dataless"
    return "stationxml"


def store_import_warnings(db: Session, project_id: int, warnings: list[dict]) -> None:
    payload = json.dumps(warnings, ensure_ascii=False).encode("utf-8")
    db.add(
        FileAsset(
            project_id=project_id,
            kind=WARNINGS_KIND,
            filename="import-warnings.json",
            media_type="application/json",
            content=payload,
        )
    )


def load_import_warnings(db: Session, project_id: int) -> list[dict]:
    row = db.scalars(
        select(FileAsset)
        .where(FileAsset.project_id == project_id, FileAsset.kind == WARNINGS_KIND)
        .order_by(FileAsset.id.desc())
    ).first()
    if row is None:
        return []
    try:
        data = json.loads(row.content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []
