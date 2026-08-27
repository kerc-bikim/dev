from __future__ import annotations

from typing import NoReturn

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

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
)
from ..inventory.validator import has_errors, validate_project, xml_filename
from ..inventory.xmlbuild import InventoryError
from ..models import Project, User
from ..routers.auth import current_user

router = APIRouter(prefix="/api/projects", tags=["projects"])


def _http_inv(exc: InventoryError) -> NoReturn:
    raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


def _http_lock(exc: LockError) -> NoReturn:
    raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


def _owned(db: Session, project_id: int, user: User) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="프로젝트가 없습니다")
    return project


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


@router.get("")
def list_projects(db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict:
    rows = db.scalars(select(Project).order_by(Project.updated_at.desc())).all()
    return {"projects": [project_out(row, user, db=db) for row in rows]}


@router.post("")
def post_project(
    body: ProjectIn, db: Session = Depends(get_db), user: User = Depends(current_user)
) -> dict:
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


@router.get("/{project_id}")
def get_project(
    project_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)
) -> dict:
    project = _owned(db, project_id, user)
    return project_out(project, user, db=db)


@router.get("/{project_id}/original")
def get_original(
    project_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    project = _owned(db, project_id, user)
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
    project = _owned(db, project_id, user)
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


@router.post("/{project_id}/export/seed")
def post_export_seed(
    project_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)
) -> dict:
    project = _owned(db, project_id, user)
    row = get_draft(db, project.id, user.id)
    xml = row.xml_text if row is not None else project.xml_text
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
    raise HTTPException(
        status_code=501,
        detail="dataless SEED 변환기는 이 배포에 아직 없습니다",
    )


@router.post("/{project_id}/wizard")
def post_wizard(
    project_id: int,
    body: WizardIn,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    project = _owned(db, project_id, user)
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
    project = _owned(db, project_id, user)
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
    project = _owned(db, project_id, user)
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
    project = _owned(db, project_id, user)
    try:
        lock = acquire_lock(db, project_id=project.id, station_path=station_path, user=user)
        db.commit()
    except LockError as exc:
        db.rollback()
        _http_lock(exc)
    return lock
