from __future__ import annotations

from typing import NoReturn
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..access import (
    add_member,
    member_out,
    require_creator,
    require_edit,
    require_manage_members,
    require_view,
    visible_projects,
)
from ..db import get_db
from ..inventory.collab import get_draft
from ..inventory.locks import LockError, acquire_lock
from ..inventory.service import (
    apply_nrl,
    create_project,
    import_project,
    original_asset,
    project_out,
    run_clone,
    run_wizard,
    write_audit,
)
from ..inventory.seed_loss import loss_ack_token, seed_loss_report
from ..inventory.validator import has_errors, validate_project, xml_filename
from ..inventory.xmlbuild import InventoryError
from ..jobs.service import enqueue_resp_export, enqueue_seed_export, job_out
from ..inventory.xmlslice import slice_stationxml
from ..models import ProjectMember, User
from ..routers.auth import current_user

router = APIRouter(prefix="/api/projects", tags=["projects"])


def _http_inv(exc: InventoryError) -> NoReturn:
    raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


def _http_lock(exc: LockError) -> NoReturn:
    raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    network_code: str = Field(min_length=1, max_length=8)
    operator: str | None = Field(default=None, max_length=128)


class WizardIn(BaseModel):
    station: str = Field(min_length=1, max_length=5)
    site_name: str = Field(min_length=1, max_length=128)
    operator: str | None = None
    start_time: str = Field(min_length=1, max_length=40)
    end_time: str | None = None
    current_operation: bool = True
    latitude: float
    longitude: float
    elevation: float = 0
    depth: float = 0
    location: str = "00"
    channels: list[str] = Field(default_factory=lambda: ["BHZ", "BHN", "BHE"])
    sensor_instconfig: str | None = None
    datalogger_instconfig: str | None = None
    nrl_later: bool = False
    sample_rate: float | None = None


class ApplyIn(BaseModel):
    station: str
    start_time: str
    channels: list[str]
    sensor_instconfig: str | None = None
    datalogger_instconfig: str | None = None
    replace_existing: bool = True


class ImportIn(BaseModel):
    filename: str = Field(min_length=1, max_length=256)
    xml_text: str = Field(min_length=1)
    name: str | None = Field(default=None, max_length=128)
    operator: str | None = Field(default=None, max_length=128)


class CloneRowIn(BaseModel):
    code: str | None = None
    site_name: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    elevation: float | None = None
    start: str | None = None
    end: str | None = None
    comment: str | None = None
    serial: str | None = None


class CloneIn(BaseModel):
    source_station: str = Field(min_length=1, max_length=5)
    source_start: str = Field(min_length=1, max_length=40)
    rows: list[CloneRowIn] = Field(default_factory=list)
    paste: str | None = None


class MemberIn(BaseModel):
    user_id: int
    role: str = Field(min_length=1, max_length=32)


@router.get("")
def list_projects(db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict:
    rows = visible_projects(db, user)
    return {"projects": [project_out(row, user, db=db) for row in rows]}


@router.post("")
def post_project(
    body: ProjectIn, db: Session = Depends(get_db), user: User = Depends(current_user)
) -> dict:
    require_creator(user)
    try:
        project = create_project(
            db,
            user,
            name=body.name,
            network_code=body.network_code,
            operator=body.operator,
        )
        db.commit()
        db.refresh(project)
    except InventoryError as exc:
        db.rollback()
        _http_inv(exc)
    return project_out(project, user, db=db)


@router.post("/import")
def post_import(
    body: ImportIn, db: Session = Depends(get_db), user: User = Depends(current_user)
) -> dict:
    require_creator(user)
    try:
        project = import_project(
            db,
            user,
            filename=body.filename,
            raw=body.xml_text.encode("utf-8"),
            name=body.name,
            operator=body.operator,
        )
        db.commit()
        db.refresh(project)
    except InventoryError as exc:
        db.rollback()
        _http_inv(exc)
    return project_out(project, user, db=db)


@router.post("/import-file")
def post_import_file(
    file: UploadFile = File(...),
    name: str | None = Form(default=None),
    operator: str | None = Form(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    require_creator(user)
    raw = file.file.read()
    filename = file.filename or "upload.bin"
    try:
        project = import_project(
            db,
            user,
            filename=filename,
            raw=raw,
            name=name,
            operator=operator,
        )
        db.commit()
        db.refresh(project)
    except InventoryError as exc:
        db.rollback()
        _http_inv(exc)
    return project_out(project, user, db=db)


@router.get("/{project_id}")
def get_project(
    project_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)
) -> dict:
    project = require_view(db, project_id, user)
    return project_out(project, user, db=db)


@router.get("/{project_id}/original")
def get_original(
    project_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    project = require_view(db, project_id, user)
    asset = original_asset(db, project.id)
    if asset is None:
        raise HTTPException(status_code=404, detail="원본 파일이 없습니다")
    filename = asset.filename.replace('"', "")
    return Response(
        content=asset.content,
        media_type=asset.media_type or "application/xml",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{project_id}/xml")
def get_project_xml(
    project_id: int,
    source: str = Query(default="project"),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    project = require_view(db, project_id, user)
    row = get_draft(db, project.id, user.id)
    use_draft = source == "draft" and row is not None
    xml = row.xml_text if use_draft else project.xml_text
    issues = validate_project(xml, project.network_code, project.id, mode="full")
    filename = xml_filename(project.network_code, issues)
    return Response(
        content=xml,
        media_type="application/xml",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-PDCC-Filename": filename,
            "X-PDCC-Error-Count": str(sum(1 for row in issues if row.get("level") == "error")),
        },
    )


def _project_xml(db: Session, project, user: User) -> str:
    row = get_draft(db, project.id, user.id)
    return row.xml_text if row is not None else project.xml_text


@router.get("/{project_id}/export/seed-loss")
def get_export_seed_loss(
    project_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)
) -> dict:
    project = require_view(db, project_id, user)
    xml = _project_xml(db, project, user)
    return seed_loss_report(xml, project.network_code, project.id)


@router.post("/{project_id}/export/seed")
def post_export_seed(
    project_id: int,
    loss_ack: str | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    project = require_edit(db, project_id, user)
    xml = _project_xml(db, project, user)
    issues = validate_project(xml, project.network_code, project.id, mode="full")
    if has_errors(issues):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "E_UNVALIDATED",
                "message": "검증 오류가 있어 dataless SEED를 만들 수 없습니다",
                "error_count": sum(1 for row in issues if row.get("level") == "error"),
            },
        )
    report = seed_loss_report(xml, project.network_code, project.id)
    if (loss_ack or "") != loss_ack_token(xml):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "E_LOSS_ACK",
                "message": "손실 목록을 본 뒤에만 dataless SEED를 만들 수 있습니다",
                "notices": report["notices"],
                "rows": report["rows"],
                "trunc_count": report["trunc_count"],
                "drop_count": report["drop_count"],
                "ack": report["ack"],
            },
        )
    job = enqueue_seed_export(
        db,
        user,
        project,
        job_id=str(uuid.uuid4()),
        xml=xml,
    )
    db.commit()
    db.refresh(job)
    return job_out(job)


@router.post("/{project_id}/export/resp")
def post_export_resp(
    project_id: int,
    station: str | None = Query(default=None),
    start: str | None = Query(default=None),
    nslc: str | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    project = require_edit(db, project_id, user)
    xml = _project_xml(db, project, user)
    issues = validate_project(xml, project.network_code, project.id, mode="full")
    if has_errors(issues):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "E_UNVALIDATED",
                "message": "검증 오류가 있어 RESP를 만들 수 없습니다",
                "error_count": sum(1 for row in issues if row.get("level") == "error"),
            },
        )
    try:
        snapshot = slice_stationxml(
            xml,
            network=project.network_code,
            station=station,
            start=start,
            nslc=nslc,
        )
    except InventoryError as exc:
        _http_inv(exc)
    target = nslc or station or project.network_code
    job = enqueue_resp_export(
        db,
        user,
        project,
        job_id=str(uuid.uuid4()),
        xml=xml,
        snapshot=snapshot,
        target=target,
    )
    db.commit()
    db.refresh(job)
    return job_out(job)


@router.post("/{project_id}/wizard")
def post_wizard(
    project_id: int,
    body: WizardIn,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    project = require_edit(db, project_id, user)
    try:
        result = run_wizard(db, user, project, body.model_dump())
        db.commit()
    except InventoryError as exc:
        db.rollback()
        _http_inv(exc)
    except LockError as exc:
        db.rollback()
        _http_lock(exc)
    return result


@router.post("/{project_id}/clone-stations")
def post_clone_stations(
    project_id: int,
    body: CloneIn,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    project = require_edit(db, project_id, user)
    try:
        result = run_clone(db, user, project, body.model_dump())
        db.commit()
    except InventoryError as exc:
        db.rollback()
        _http_inv(exc)
    except LockError as exc:
        db.rollback()
        _http_lock(exc)
    return result


@router.post("/{project_id}/apply-nrl")
def post_apply_nrl(
    project_id: int,
    body: ApplyIn,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    project = require_edit(db, project_id, user)
    try:
        result = apply_nrl(db, user, project, body.model_dump())
        db.commit()
    except InventoryError as exc:
        db.rollback()
        _http_inv(exc)
    except LockError as exc:
        db.rollback()
        _http_lock(exc)
    return result


@router.post("/{project_id}/lock")
def post_project_lock(
    project_id: int,
    station_path: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    project = require_edit(db, project_id, user)
    try:
        lock = acquire_lock(db, project_id=project.id, station_path=station_path, user=user)
        db.commit()
    except LockError as exc:
        db.rollback()
        _http_lock(exc)
    return lock


@router.get("/{project_id}/members")
def list_members(
    project_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)
) -> dict:
    project = require_view(db, project_id, user)
    rows = db.scalars(
        select(ProjectMember).where(ProjectMember.project_id == project.id)
    ).all()
    users = {row.id: row for row in db.scalars(select(User)).all()}
    return {
        "project_id": project.id,
        "members": [member_out(row, users[row.user_id]) for row in rows if row.user_id in users],
    }


@router.put("/{project_id}/members")
def put_member(
    project_id: int,
    body: MemberIn,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    project = require_manage_members(db, project_id, user)
    member = db.get(User, body.user_id)
    if member is None:
        raise HTTPException(status_code=404, detail="사용자가 없습니다")
    row = add_member(db, project, member, body.role)
    write_audit(
        db,
        project_id=project.id,
        actor=user.username,
        action="member",
        target=member.username,
        summary=f"{member.username} 멤버 {row.role}",
    )
    db.commit()
    return member_out(row, member)


@router.delete("/{project_id}/members/{user_id}")
def delete_member(
    project_id: int,
    user_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    project = require_manage_members(db, project_id, user)
    row = db.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == project.id,
            ProjectMember.user_id == user_id,
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="멤버가 없습니다")
    member = db.get(User, user_id)
    name = member.username if member is not None else str(user_id)
    db.delete(row)
    write_audit(
        db,
        project_id=project.id,
        actor=user.username,
        action="member_remove",
        target=name,
        summary=f"{name} 멤버 해제",
    )
    db.commit()
    return {"ok": True}
