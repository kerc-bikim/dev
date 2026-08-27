from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from ..models import AuditLog, Project, User, utcnow
from ..nrl.client import get_nrl_client, validate_instconfig
from ..nrl.curve import sample_rate_from_instconfig
from .locks import acquire_lock, lock_snapshot, require_lock
from .xmlbuild import (
    InventoryError,
    NETWORK_CODE_RE,
    add_station,
    apply_response,
    empty_inventory,
    list_inventory,
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


def project_out(project: Project, user: User, lock: dict | None = None) -> dict[str, Any]:
    stations = list_inventory(project.xml_text, project.network_code) if project.xml_text else []
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
    }
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
    write_audit(
        db,
        project_id=project.id,
        actor=user.username,
        action="create",
        target=code,
        summary="프로젝트 생성",
    )
    return project


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
    path = station_path(project.network_code, station, start)
    lock = acquire_lock(db, project_id=project.id, station_path=path, user=user)
    write_audit(
        db,
        project_id=project.id,
        actor=user.username,
        action="create",
        target=f"{project.network_code}/{station}",
        summary=f"위저드로 관측소 생성 ({', '.join(channels)})",
    )
    db.flush()
    return {"project": project_out(project, user, lock), "station_path": path, "lock": lock}


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
    path = station_path(project.network_code, station, start)
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
        "project": project_out(project, user, require_lock(path, user)),
    }
