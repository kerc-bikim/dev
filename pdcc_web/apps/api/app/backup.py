from __future__ import annotations

import io
import json
import re
import zipfile
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .inventory.service import write_audit
from .inventory.xmlbuild import NETWORK_CODE_RE, InventoryError
from .inventory.xmlutil import local, parse_root, qname
from .models import Project, User, utcnow

BACKUP_FORMAT = "pdcc-stationxml-backup-v1"
_UNSAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


def _safe_part(value: str, fallback: str) -> str:
    cleaned = _UNSAFE_NAME.sub("_", value.strip())[:80].strip("._")
    return cleaned or fallback


def _network_from_xml(xml_text: str) -> str:
    try:
        root = parse_root(xml_text)
    except Exception as exc:
        raise InventoryError("StationXML을 읽을 수 없습니다", 400, "E_XML") from exc
    if local(root.tag) != "FDSNStationXML":
        raise InventoryError("FDSNStationXML 문서가 아닙니다", 400, "E_XML")
    network = root.find(qname("Network"))
    code = (network.get("code") if network is not None else "") or ""
    code = code.strip().upper()
    if not NETWORK_CODE_RE.match(code):
        raise InventoryError("네트워크 코드가 올바르지 않습니다", 400, "E_CODE_NET")
    return code


def _xml_filename(project: Project) -> str:
    name = _safe_part(project.name, project.network_code)
    return f"projects/{project.id}-{project.network_code}-{name}.xml"


def build_backup_zip(db: Session, user: User) -> tuple[bytes, str, dict[str, Any]]:
    projects = db.scalars(select(Project).order_by(Project.id.asc())).all()
    created = datetime.now(timezone.utc)
    stamp = created.strftime("%Y%m%dT%H%M%SZ")
    entries: list[dict[str, Any]] = []
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for project in projects:
            xml_name = _xml_filename(project)
            zf.writestr(xml_name, project.xml_text or "")
            entries.append(
                {
                    "id": project.id,
                    "name": project.name,
                    "network_code": project.network_code,
                    "operator": project.operator,
                    "status": project.status,
                    "updated_at": project.updated_at.isoformat() if project.updated_at else None,
                    "xml_file": xml_name,
                }
            )
        manifest = {
            "format": BACKUP_FORMAT,
            "created_at": created.isoformat(),
            "created_by": user.username,
            "project_count": len(entries),
            "projects": entries,
        }
        zf.writestr(
            "manifest.json",
            json.dumps(manifest, ensure_ascii=False, indent=2),
        )
        zf.writestr(
            "README.txt",
            "PDCC Web StationXML 스냅샷입니다. SEED/RESP 내보내기(M3)와 다릅니다.\n"
            "복원: POST /api/ops/restore (application/zip).\n"
            "DB 전체 복구는 infra/runbook.md 의 pg_dump 절차를 따릅니다.\n",
        )
    write_audit(
        db,
        project_id=None,
        actor=user.username,
        action="backup",
        target="projects",
        summary=f"StationXML 스냅샷 {len(entries)}개",
    )
    filename = f"pdcc-stationxml-{stamp}.zip"
    return buf.getvalue(), filename, manifest


def _member_ok(name: str) -> bool:
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts:
        return False
    return True


def _load_zip_items(payload: bytes) -> list[tuple[dict[str, Any], str]]:
    try:
        zf = zipfile.ZipFile(io.BytesIO(payload))
    except zipfile.BadZipFile as exc:
        raise InventoryError("ZIP 파일이 아닙니다", 400, "E_ZIP") from exc
    names = [name for name in zf.namelist() if _member_ok(name) and not name.endswith("/")]
    manifest: dict[str, Any] = {}
    if "manifest.json" in names:
        try:
            manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise InventoryError("manifest.json 을 읽을 수 없습니다", 400, "E_ZIP") from exc
    by_file = {
        str(item.get("xml_file")): item
        for item in manifest.get("projects") or []
        if isinstance(item, dict) and item.get("xml_file")
    }
    items: list[tuple[dict[str, Any], str]] = []
    xml_names = [
        name
        for name in names
        if name.endswith(".xml") and (name.startswith("projects/") or "/" not in name)
    ]
    if not xml_names:
        raise InventoryError("ZIP에 StationXML이 없습니다", 400, "E_ZIP")
    for name in xml_names:
        xml_text = zf.read(name).decode("utf-8")
        meta = dict(by_file.get(name) or {})
        if not meta.get("name"):
            meta["name"] = PurePosixPath(name).stem
        items.append((meta, xml_text))
    return items


def restore_snapshot(
    db: Session,
    user: User,
    payload: bytes,
    *,
    content_type: str,
    replace: bool,
) -> dict[str, Any]:
    ctype = (content_type or "").split(";")[0].strip().lower()
    if payload[:2] == b"PK" or "zip" in ctype:
        pairs = _load_zip_items(payload)
    else:
        xml_text = payload.decode("utf-8")
        pairs = [({"name": "복원된 프로젝트"}, xml_text)]

    created: list[dict[str, Any]] = []
    replaced: list[dict[str, Any]] = []
    for meta, xml_text in pairs:
        network = _network_from_xml(xml_text)
        title = (meta.get("name") or "").strip() or f"{network} 복원"
        original_id = meta.get("id")
        project: Project | None = None
        if replace and original_id is not None:
            project = db.get(Project, int(original_id))
            if project is not None and project.owner_id != user.id and user.role != "admin":
                raise InventoryError("다른 사용자의 프로젝트를 덮어쓸 수 없습니다", 403, "E_OWNER")
        if project is None:
            project = Project(
                name=title,
                network_code=network,
                operator=(meta.get("operator") or None),
                status=str(meta.get("status") or "draft"),
                xml_text=xml_text,
                owner_id=user.id,
            )
            db.add(project)
            db.flush()
            created.append({"id": project.id, "name": project.name, "network_code": network})
            action = "restore"
            summary = "스냅샷에서 프로젝트 생성"
        else:
            project.name = title
            project.network_code = network
            project.operator = meta.get("operator") or project.operator
            project.xml_text = xml_text
            project.updated_at = utcnow()
            replaced.append({"id": project.id, "name": project.name, "network_code": network})
            action = "restore"
            summary = "스냅샷으로 프로젝트 원문 교체"
        write_audit(
            db,
            project_id=project.id,
            actor=user.username,
            action=action,
            target=network,
            summary=summary,
        )
    return {
        "created": created,
        "replaced": replaced,
        "count": len(created) + len(replaced),
    }
