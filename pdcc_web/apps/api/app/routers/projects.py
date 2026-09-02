from __future__ import annotations

from typing import NoReturn

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..inventory.locks import LockError, acquire_lock
from ..inventory.service import apply_nrl, create_project, project_out, run_wizard
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


@router.get("")
def list_projects(db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict:
    rows = db.scalars(select(Project).order_by(Project.updated_at.desc())).all()
    return {"projects": [project_out(row, user) for row in rows]}


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
    return project_out(project, user)


@router.get("/{project_id}")
def get_project(
    project_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)
) -> dict:
    project = _owned(db, project_id, user)
    return project_out(project, user)


@router.get("/{project_id}/xml")
def get_project_xml(
    project_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    project = _owned(db, project_id, user)
    return Response(content=project.xml_text, media_type="application/xml")


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
