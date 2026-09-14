from __future__ import annotations

import uuid
from typing import NoReturn

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import get_db
from ..export import ExportError
from ..export.slice import KINDS, SCOPES
from ..jobs.service import enqueue_export, job_out, preview_project_export
from ..models import Project, User
from ..routers.auth import current_user
from ..routers.projects import _owned

router = APIRouter(prefix="/api/projects", tags=["export"])


def _http_export(exc: ExportError) -> NoReturn:
    detail: dict = {"message": str(exc)}
    if exc.code:
        detail["code"] = exc.code
    if exc.errors:
        detail["errors"] = exc.errors
    if exc.losses:
        detail["losses"] = exc.losses
    if exc.drops:
        detail["drops"] = exc.drops
    raise HTTPException(status_code=exc.status_code, detail=detail) from exc


class ExportIn(BaseModel):
    kind: str = Field(pattern="^(resp|dataless)$")
    scope: str = Field(default="project", pattern="^(project|station|channel)$")
    station: str | None = Field(default=None, max_length=8)
    start_time: str | None = Field(default=None, max_length=40)
    nslc: str | None = Field(default=None, max_length=32)
    accept_losses: bool = False
    preview: bool = False


def _scope_fields(body: ExportIn) -> tuple[str | None, str | None, str | None]:
    station = body.station
    start = body.start_time
    nslc = body.nslc
    if body.scope == "project":
        return None, None, None
    if body.scope == "station":
        if not station:
            raise HTTPException(status_code=400, detail="관측소가 필요합니다")
        return station, start, None
    if not station or not nslc:
        raise HTTPException(status_code=400, detail="관측소와 채널이 필요합니다")
    return station, start, nslc


@router.post("/{project_id}/export")
def post_export(
    project_id: int,
    body: ExportIn,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    if body.kind not in KINDS or body.scope not in SCOPES:
        raise HTTPException(status_code=400, detail="kind 또는 scope가 올바르지 않습니다")
    project = _owned(db, project_id, user)
    station, start, nslc = _scope_fields(body)
    if body.preview:
        try:
            preview = preview_project_export(
                project,
                kind=body.kind,
                station=station,
                start=start,
                nslc=nslc,
            )
        except ExportError as exc:
            _http_export(exc)
        return preview
    try:
        job = enqueue_export(
            db,
            user,
            project,
            job_id=str(uuid.uuid4()),
            kind=body.kind,
            scope=body.scope,
            station=station,
            start=start,
            nslc=nslc,
            accept_losses=body.accept_losses,
        )
        db.commit()
        db.refresh(job)
    except ExportError as exc:
        db.rollback()
        _http_export(exc)
    return job_out(job)
