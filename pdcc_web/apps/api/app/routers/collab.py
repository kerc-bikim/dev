from __future__ import annotations

import json
from typing import NoReturn

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..inventory.collab import (
    conflict_fields,
    draft_conflict,
    get_draft,
    latest_undo,
    record_edit,
    require_no_foreign_lock,
    upsert_draft,
    version_out,
)
from ..inventory.service import project_out, write_audit
from ..inventory.validator import summarize, validate_project
from ..inventory.xmlbuild import (
    InventoryError,
    apply_field_choices,
    diff_fields,
    field_snapshot,
    list_inventory,
    update_channel,
    update_station,
)
from ..models import EquipmentSet, Project, ProjectVersion, User, utcnow
from ..nrl.client import get_nrl_client, validate_instconfig
from ..routers.auth import current_user


def _owned(db: Session, project_id: int, user: User) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="프로젝트가 없습니다")
    return project

router = APIRouter(tags=["collab"])


def _http_inv(exc: InventoryError) -> NoReturn:
    raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


class EquipmentIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    notes: str = ""
    sensor_instconfig: str = Field(min_length=1, max_length=256)
    datalogger_instconfig: str = ""
    channels: list[str] = Field(default_factory=lambda: ["BHZ", "BHN", "BHE"])


class DraftIn(BaseModel):
    station: str
    start_time: str
    latitude: float | None = None
    longitude: float | None = None
    elevation: float | None = None
    site_name: str | None = None
    end: str | None = None
    set_end: bool = False
    propagate: bool = True
    channel: str | None = None
    location: str | None = None
    new_code: str | None = None
    new_location: str | None = None
    depth: float | None = None
    azimuth: float | None = None
    dip: float | None = None
    sample_rate: float | None = None
    sensitivity: float | None = None


class MergeIn(BaseModel):
    choices: dict[str, str]


class RestoreIn(BaseModel):
    pass


def _set_out(row: EquipmentSet, fingerprint: str) -> dict:
    stale = bool(row.nrl_version) and row.nrl_version != fingerprint
    return {
        "id": row.id,
        "name": row.name,
        "notes": row.notes,
        "sensor_instconfig": row.sensor_instconfig,
        "datalogger_instconfig": row.datalogger_instconfig,
        "channels": json.loads(row.channels_json),
        "nrl_version": row.nrl_version,
        "stale": stale,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


@router.get("/api/equipment-sets")
def list_sets(db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict:
    fingerprint = get_nrl_client().catalog_fingerprint()
    rows = db.scalars(
        select(EquipmentSet).where(EquipmentSet.user_id == user.id).order_by(EquipmentSet.id.desc())
    ).all()
    return {"sets": [_set_out(row, fingerprint) for row in rows], "nrl_version": fingerprint}


@router.post("/api/equipment-sets")
def post_set(
    body: EquipmentIn, db: Session = Depends(get_db), user: User = Depends(current_user)
) -> dict:
    sensor = validate_instconfig(body.sensor_instconfig)
    logger = validate_instconfig(body.datalogger_instconfig) if body.datalogger_instconfig else ""
    fingerprint = get_nrl_client().catalog_fingerprint()
    row = EquipmentSet(
        user_id=user.id,
        name=body.name.strip(),
        notes=(body.notes or "").strip(),
        sensor_instconfig=sensor,
        datalogger_instconfig=logger,
        channels_json=json.dumps([c.strip().upper() for c in body.channels if c.strip()]),
        nrl_version=fingerprint,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _set_out(row, fingerprint)


@router.delete("/api/equipment-sets/{set_id}")
def delete_set(
    set_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)
) -> dict:
    row = db.get(EquipmentSet, set_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(status_code=404, detail="장비 세트가 없습니다")
    db.delete(row)
    db.commit()
    return {"ok": True}


@router.get("/api/projects/{project_id}/versions")
def list_versions(
    project_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)
) -> dict:
    _owned(db, project_id, user)
    rows = db.scalars(
        select(ProjectVersion)
        .where(ProjectVersion.project_id == project_id)
        .order_by(ProjectVersion.number.desc())
    ).all()
    return {"versions": [version_out(row) for row in rows]}


@router.get("/api/projects/{project_id}/versions/{left}/diff/{right}")
def diff_versions(
    project_id: int,
    left: int,
    right: int,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    project = _owned(db, project_id, user)
    a = db.get(ProjectVersion, left)
    b = db.get(ProjectVersion, right)
    if a is None or b is None or a.project_id != project.id or b.project_id != project.id:
        raise HTTPException(status_code=404, detail="버전이 없습니다")
    fields = diff_fields(
        field_snapshot(a.xml_text, project.network_code, project.id),
        field_snapshot(b.xml_text, project.network_code, project.id),
    )
    return {"a": version_out(a), "b": version_out(b), "fields": fields}


@router.post("/api/projects/{project_id}/versions/{version_id}/restore")
def restore_version(
    project_id: int,
    version_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    project = _owned(db, project_id, user)
    row = db.get(ProjectVersion, version_id)
    if row is None or row.project_id != project.id:
        raise HTTPException(status_code=404, detail="버전이 없습니다")
    try:
        require_no_foreign_lock(project, user)
    except InventoryError as exc:
        _http_inv(exc)
    before = project.xml_text
    project.xml_text = row.xml_text
    project.updated_at = utcnow()
    record_edit(
        db,
        project,
        user,
        before=before,
        after=row.xml_text,
        action="restore",
        summary=f"버전 {row.number} 복원",
    )
    write_audit(
        db,
        project_id=project.id,
        actor=user.username,
        action="restore",
        target=str(row.number),
        summary=f"버전 {row.number} 복원",
    )
    db.commit()
    db.refresh(project)
    return {"project": project_out(project, user, db=db), "restored": version_out(row)}


@router.put("/api/projects/{project_id}/draft")
def put_draft(
    project_id: int,
    body: DraftIn,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    project = _owned(db, project_id, user)
    source = get_draft(db, project.id, user.id)
    xml = source.xml_text if source is not None else project.xml_text
    try:
        if body.channel:
            xml = update_channel(
                xml,
                network=project.network_code,
                station=body.station.strip().upper(),
                start=body.start_time,
                location=body.location or "",
                channel=body.channel.strip().upper(),
                new_location=body.new_location,
                new_code=body.new_code,
                depth=body.depth,
                azimuth=body.azimuth,
                dip=body.dip,
                sample_rate=body.sample_rate,
                sensitivity=body.sensitivity,
                latitude=body.latitude,
                longitude=body.longitude,
                elevation=body.elevation,
                end=body.end,
                set_end=body.set_end,
            )
        else:
            xml = update_station(
                xml,
                network=project.network_code,
                station=body.station.strip().upper(),
                start=body.start_time,
                latitude=body.latitude,
                longitude=body.longitude,
                elevation=body.elevation,
                site_name=body.site_name,
                end=body.end,
                set_end=body.set_end,
                propagate=body.propagate,
            )
    except InventoryError as exc:
        _http_inv(exc)
    row = upsert_draft(db, project, user, xml)
    db.commit()
    return {
        "draft": {
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            "base_updated_at": row.base_updated_at,
            "conflict": draft_conflict(project, row),
        }
    }


@router.get("/api/projects/{project_id}/draft")
def read_draft(
    project_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)
) -> dict:
    project = _owned(db, project_id, user)
    row = get_draft(db, project.id, user.id)
    if row is None:
        return {"draft": None}
    stations = list_inventory(row.xml_text, project.network_code, project.id)
    return {
        "draft": {
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            "base_updated_at": row.base_updated_at,
            "conflict": draft_conflict(project, row),
            "stations": stations,
            "xml_text": row.xml_text,
        }
    }


@router.get("/api/projects/{project_id}/issues")
def list_issues(
    project_id: int,
    mode: str = Query(default="quick"),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    project = _owned(db, project_id, user)
    row = get_draft(db, project.id, user.id)
    xml = row.xml_text if row is not None else project.xml_text
    try:
        issues = validate_project(xml, project.network_code, project.id, mode=mode)
    except InventoryError as exc:
        _http_inv(exc)
    return summarize(
        issues,
        xml_source="draft" if row is not None else "project",
        mode=mode,
        network=project.network_code,
    )


@router.post("/api/projects/{project_id}/validate")
def post_validate(
    project_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)
) -> dict:
    project = _owned(db, project_id, user)
    row = get_draft(db, project.id, user.id)
    xml = row.xml_text if row is not None else project.xml_text
    issues = validate_project(xml, project.network_code, project.id, mode="full")
    return summarize(
        issues,
        xml_source="draft" if row is not None else "project",
        mode="full",
        network=project.network_code,
    )


@router.post("/api/projects/{project_id}/draft/discard")
def discard_draft(
    project_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)
) -> dict:
    project = _owned(db, project_id, user)
    row = get_draft(db, project.id, user.id)
    if row is not None:
        db.delete(row)
        db.commit()
    return {"ok": True, "project": project_out(project, user, db=db)}


@router.post("/api/projects/{project_id}/draft/commit")
def commit_draft(
    project_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)
) -> dict:
    project = _owned(db, project_id, user)
    row = get_draft(db, project.id, user.id)
    if row is None:
        raise HTTPException(status_code=404, detail="초안이 없습니다")
    if draft_conflict(project, row):
        raise HTTPException(
            status_code=409,
            detail={
                "message": "서버 값이 바뀌었습니다. 필드마다 선택하세요",
                "code": "E_DRAFT_CONFLICT",
                "fields": conflict_fields(project, row),
            },
        )
    try:
        require_no_foreign_lock(project, user)
    except InventoryError as exc:
        _http_inv(exc)
    before = project.xml_text
    project.xml_text = row.xml_text
    project.updated_at = utcnow()
    record_edit(db, project, user, before=before, after=row.xml_text, action="save", summary="초안 저장")
    write_audit(
        db,
        project_id=project.id,
        actor=user.username,
        action="save",
        target=project.network_code,
        summary="초안 저장",
    )
    db.delete(row)
    db.commit()
    db.refresh(project)
    return {"project": project_out(project, user, db=db)}


@router.post("/api/projects/{project_id}/draft/merge")
def merge_draft(
    project_id: int,
    body: MergeIn,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    project = _owned(db, project_id, user)
    row = get_draft(db, project.id, user.id)
    if row is None:
        raise HTTPException(status_code=404, detail="초안이 없습니다")
    try:
        require_no_foreign_lock(project, user)
        xml = apply_field_choices(
            project.xml_text,
            row.xml_text,
            network=project.network_code,
            choices=body.choices,
        )
    except InventoryError as exc:
        _http_inv(exc)
    before = project.xml_text
    project.xml_text = xml
    project.updated_at = utcnow()
    record_edit(db, project, user, before=before, after=xml, action="merge", summary="초안 머지")
    write_audit(
        db,
        project_id=project.id,
        actor=user.username,
        action="merge",
        target=project.network_code,
        summary="초안 머지",
    )
    db.delete(row)
    db.commit()
    db.refresh(project)
    return {"project": project_out(project, user, db=db)}


@router.post("/api/projects/{project_id}/undo")
def post_undo(
    project_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)
) -> dict:
    project = _owned(db, project_id, user)
    row = latest_undo(db, project.id, user.id)
    if row is None:
        raise HTTPException(status_code=404, detail="취소할 편집이 없습니다")
    try:
        require_no_foreign_lock(project, user)
    except InventoryError as exc:
        _http_inv(exc)
    project.xml_text = row.before_xml
    project.updated_at = utcnow()
    version = record_edit(
        db,
        project,
        user,
        before=row.after_xml,
        after=row.before_xml,
        action="undo",
        summary=f"실행 취소: {row.summary}",
        undo=False,
    )
    write_audit(
        db,
        project_id=project.id,
        actor=user.username,
        action="undo",
        target=row.action,
        summary=f"실행 취소: {row.summary}",
    )
    db.delete(row)
    db.commit()
    db.refresh(project)
    return {"project": project_out(project, user, db=db), "undone": version_out(version)}
