from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..access import EDITOR_ROLE, ROLES, add_member, project_role, can_edit_role
from ..models import AuditLog, FileAsset, Project, User, utcnow
from .collab import get_draft, latest_undo, record_edit
from .importers import inspect_upload, original_kind_of, store_import_warnings
from ..nrl.client import get_nrl_client, validate_instconfig
from ..nrl.curve import sample_rate_from_instconfig
from .locks import acquire_lock, lock_snapshot, require_lock
from .xmlbuild import (
    InventoryError,
    NETWORK_CODE_RE,
    add_station,
    apply_response,
    clone_stations,
    empty_inventory,
    list_inventory,
    parse_clone_paste,
    station_path,
)
from .xmlutil import local
from lxml import etree


def write_audit(
    db: Session,
    *,
    project_id: int | None,
    actor: str,
    action: str,
    target: str,
    summary: str,
) -> None:
    db.add(
        AuditLog(
            project_id=project_id,
            actor=actor,
            action=action,
            target=target,
            summary=summary,
        )
    )


def _with_mine(lock: dict, user: User) -> dict:
    data = dict(lock)
    data["mine"] = int(data.get("user_id") or 0) == user.id
    return data


def project_out(
    project: Project, user: User, lock: dict | None = None, db: Session | None = None
) -> dict[str, Any]:
    stations = (
        list_inventory(project.xml_text, project.network_code, project.id) if project.xml_text else []
    )
    top_lock = _with_mine(lock, user) if lock is not None else None
    for sta in stations:
        snap = lock_snapshot(sta["station_path"])
        if snap:
            sta["lock"] = _with_mine(snap, user)
            if top_lock is None:
                top_lock = sta["lock"]
    data = {
        "id": project.id,
        "name": project.name,
        "network_code": project.network_code,
        "operator": project.operator,
        "status": project.status,
        "updated_at": project.updated_at.isoformat() if project.updated_at else None,
        "station_count": len(stations),
        "channel_count": sum(len(sta["channels"]) for sta in stations),
        "stations": stations,
        "nrl_applied": any(
            ch["has_response"] for sta in stations for ch in sta["channels"]
        ),
        "can_undo": False,
        "draft": None,
        "has_original": False,
        "original_kind": None,
        "original_filename": None,
    }
    if db is not None:
        data["can_undo"] = latest_undo(db, project.id, user.id) is not None
        draft = get_draft(db, project.id, user.id)
        if draft is not None:
            data["draft"] = {
                "updated_at": draft.updated_at.isoformat() if draft.updated_at else None,
                "base_updated_at": draft.base_updated_at,
                "conflict": draft.base_updated_at != data["updated_at"],
            }
        asset = original_asset(db, project.id)
        data["has_original"] = asset is not None
        data["original_kind"] = original_kind_of(asset)
        data["original_filename"] = asset.filename if asset is not None else None
        role = project_role(db, project, user)
        data["my_role"] = role
        data["can_edit"] = can_edit_role(role)
    else:
        data["my_role"] = None
        data["can_edit"] = False
    if top_lock is not None:
        data["lock"] = top_lock
    return data


def create_project(db: Session, user: User, *, name: str, network_code: str, operator: str | None) -> Project:
    code = network_code.strip().upper()
    if not NETWORK_CODE_RE.match(code):
        raise InventoryError("네트워크 코드가 올바르지 않습니다", 400, "E_CODE_NET")
    title = name.strip() or f"{code} 네트워크"
    project = Project(
        name=title,
        network_code=code,
        operator=(operator or "").strip() or None,
        xml_text=empty_inventory(code, operator=operator),
        owner_id=user.id,
        status="draft",
    )
    db.add(project)
    db.flush()
    owner_role = user.role if user.role in ROLES else EDITOR_ROLE
    add_member(db, project, user, owner_role)
    write_audit(
        db,
        project_id=project.id,
        actor=user.username,
        action="create",
        target=code,
        summary="프로젝트 생성",
    )
    return project


def import_project(
    db: Session,
    user: User,
    *,
    filename: str,
    raw: bytes,
    name: str | None = None,
    operator: str | None = None,
) -> Project:
    info = inspect_upload(raw, filename)
    code = info["network_code"]
    title = (name or "").strip() or f"{code} 가져오기"
    project = Project(
        name=title,
        network_code=code,
        operator=(operator or "").strip() or None,
        xml_text=info["xml_text"],
        owner_id=user.id,
        status="draft",
    )
    db.add(project)
    db.flush()
    owner_role = user.role if user.role in ROLES else EDITOR_ROLE
    add_member(db, project, user, owner_role)
    db.add(
        FileAsset(
            project_id=project.id,
            kind="original",
            filename=(filename or "station.xml")[:256],
            media_type=info.get("media_type") or "application/xml",
            content=raw,
        )
    )
    if info.get("warnings"):
        store_import_warnings(db, project.id, info["warnings"])
    record_edit(
        db,
        project,
        user,
        before=info["xml_text"],
        after=info["xml_text"],
        action="import",
        summary=f"{filename} 가져오기",
        undo=False,
    )
    write_audit(
        db,
        project_id=project.id,
        actor=user.username,
        action="import",
        target=code,
        summary=f"{filename} 가져오기",
    )
    return project


def original_asset(db: Session, project_id: int) -> FileAsset | None:
    return db.scalars(
        select(FileAsset)
        .where(FileAsset.project_id == project_id, FileAsset.kind == "original")
        .order_by(FileAsset.id.desc())
    ).first()


def _response_element(instconfig: str) -> tuple[etree._Element, bytes]:
    payload, _ct = get_nrl_client().combine(validate_instconfig(instconfig), "stationxml-resp")
    root = etree.fromstring(payload)
    if local(root.tag) != "Response":
        raise InventoryError("NRL combine이 StationXML-Response가 아닙니다", 502)
    return root, payload


def run_wizard(
    db: Session,
    user: User,
    project: Project,
    body: dict[str, Any],
) -> dict[str, Any]:
    station = str(body.get("station") or "").strip().upper()
    site_name = str(body.get("site_name") or "").strip()
    start = str(body.get("start_time") or "").strip()
    current = bool(body.get("current_operation", True))
    end = None if current else (str(body.get("end_time") or "").strip() or None)
    if not site_name:
        raise InventoryError("사이트명이 필요합니다", 400, "E_REQ")
    if not start:
        raise InventoryError("시작 시각이 필요합니다", 400, "E_REQ")
    channels = body.get("channels") or ["BHZ", "BHN", "BHE"]
    channels = [str(c).strip().upper() for c in channels]
    location = str(body.get("location") if body.get("location") is not None else "00")
    sensor = (body.get("sensor_instconfig") or "").strip() or None
    datalogger = (body.get("datalogger_instconfig") or "").strip() or None
    nrl_later = bool(body.get("nrl_later"))
    if sensor:
        sensor = validate_instconfig(sensor)
    if datalogger:
        datalogger = validate_instconfig(datalogger)

    comments: list[str] = []
    cascade = None
    response_el = None
    sample_rate = float(body.get("sample_rate") or 0) or None
    if not nrl_later and (sensor or datalogger):
        cascade = ":".join(part for part in [sensor, datalogger] if part)
        response_el, _payload = _response_element(cascade)
        comments = [f"NRL v2 {part}" for part in [sensor, datalogger] if part]
        sample_rate = sample_rate or sample_rate_from_instconfig(cascade) or 20.0
    sample_rate = sample_rate or 20.0

    path = station_path(project.network_code, station, start, project.id)
    before = project.xml_text
    xml = add_station(
        project.xml_text,
        network=project.network_code,
        station=station,
        site_name=site_name,
        start=start,
        end=end,
        latitude=float(body["latitude"]),
        longitude=float(body["longitude"]),
        elevation=float(body.get("elevation") or 0),
        depth=float(body.get("depth") or 0),
        channels=channels,
        location=location,
        sample_rate=sample_rate,
        operator=body.get("operator") or project.operator,
        response_el=response_el,
        comments=comments,
        sensor_desc=sensor,
        datalogger_desc=datalogger,
    )
    project.xml_text = xml
    project.updated_at = utcnow()
    lock = acquire_lock(db, project_id=project.id, station_path=path, user=user)
    record_edit(
        db,
        project,
        user,
        before=before,
        after=xml,
        action="create",
        summary=f"위저드로 관측소 생성 ({', '.join(channels)})",
    )
    write_audit(
        db,
        project_id=project.id,
        actor=user.username,
        action="create",
        target=f"{project.network_code}/{station}",
        summary=f"위저드로 관측소 생성 ({', '.join(channels)})",
    )
    db.flush()
    return {"project": project_out(project, user, lock, db), "station_path": path, "lock": lock}


def run_clone(
    db: Session,
    user: User,
    project: Project,
    body: dict[str, Any],
) -> dict[str, Any]:
    source_station = str(body.get("source_station") or "").strip().upper()
    source_start = str(body.get("source_start") or "").strip()
    if not source_station or not source_start:
        raise InventoryError("원본 관측소와 시작 시각이 필요합니다", 400, "E_REQ")
    rows = [row for row in (body.get("rows") or [])]
    paste = str(body.get("paste") or "")
    if paste and not any(str(row.get("code") or "").strip() for row in rows):
        rows = parse_clone_paste(paste)
    before = project.xml_text
    xml, created, skipped = clone_stations(
        project.xml_text,
        network=project.network_code,
        source_station=source_station,
        source_start=source_start,
        rows=rows,
    )
    if not created:
        raise InventoryError("코드가 있는 행이 없습니다", 400, "E_REQ")
    project.xml_text = xml
    project.updated_at = utcnow()
    codes = [row["code"] for row in created]
    lock = None
    for row in created:
        path = station_path(project.network_code, row["code"], row["start"], project.id)
        lock = acquire_lock(db, project_id=project.id, station_path=path, user=user)
    record_edit(
        db,
        project,
        user,
        before=before,
        after=xml,
        action="clone",
        summary=f"관측소 복제 {', '.join(codes)}",
    )
    write_audit(
        db,
        project_id=project.id,
        actor=user.username,
        action="clone",
        target=f"{project.network_code}/{source_station}",
        summary=f"관측소 복제 {', '.join(codes)} (빈 코드 {sum(1 for row in skipped if row.get('reason') == 'empty_code')}개 무시)",
    )
    db.flush()
    return {
        "project": project_out(project, user, lock, db),
        "created": created,
        "skipped": skipped,
    }


def apply_nrl(
    db: Session,
    user: User,
    project: Project,
    body: dict[str, Any],
) -> dict[str, Any]:
    station = str(body.get("station") or "").strip().upper()
    start = str(body.get("start_time") or "").strip()
    if not station or not start:
        raise InventoryError("관측소와 시작 시각이 필요합니다", 400, "E_REQ")
    path = station_path(project.network_code, station, start, project.id)
    require_lock(path, user)
    sensor = (body.get("sensor_instconfig") or "").strip() or None
    datalogger = (body.get("datalogger_instconfig") or "").strip() or None
    if not sensor and not datalogger:
        raise InventoryError("센서 또는 기록계 instconfig가 필요합니다", 400)
    if sensor:
        sensor = validate_instconfig(sensor)
    if datalogger:
        datalogger = validate_instconfig(datalogger)
    cascade = ":".join(part for part in [sensor, datalogger] if part)
    _el, payload = _response_element(cascade)
    comments = [f"NRL v2 {part}" for part in [sensor, datalogger] if part]
    sample_rate = sample_rate_from_instconfig(cascade)
    replace_existing = bool(body.get("replace_existing", True))
    raw_channels = body.get("channels") or []
    if not raw_channels:
        raise InventoryError("적용할 채널이 필요합니다", 400)
    xml = project.xml_text
    before = xml
    applied: list[str] = []
    errors: list[dict] = []
    for item in raw_channels:
        text = str(item)
        if "." in text:
            location, channel = text.split(".", 1)
        else:
            location, channel = "00", text
        try:
            xml = apply_response(
                xml,
                network=project.network_code,
                station=station,
                start=start,
                location=location,
                channel=channel.upper(),
                response_xml=payload,
                comments=comments,
                sample_rate=sample_rate,
                replace_existing=replace_existing,
            )
            applied.append(f"{location}.{channel.upper()}")
        except InventoryError as exc:
            errors.append({"channel": text, "reason": str(exc)})
    if not applied and errors:
        raise InventoryError(errors[0]["reason"], getattr(errors[0], "status_code", 400))
    project.xml_text = xml
    project.updated_at = utcnow()
    record_edit(
        db,
        project,
        user,
        before=before,
        after=xml,
        action="nrl",
        summary=f"NRL 적용 {', '.join(applied)}",
    )
    write_audit(
        db,
        project_id=project.id,
        actor=user.username,
        action="nrl",
        target=f"{project.network_code}/{station}",
        summary=f"NRL 적용 {', '.join(applied)}",
    )
    db.flush()
    return {
        "applied": applied,
        "errors": errors,
        "instconfig": cascade,
        "project": project_out(project, user, require_lock(path, user), db),
    }
