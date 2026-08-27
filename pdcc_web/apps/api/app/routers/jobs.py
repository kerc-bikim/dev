from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..access import require_edit, require_view, visible_projects
from ..db import get_db
from ..jobs.queue import cancel_queued
from ..jobs.service import JobError, job_artifact, job_out, retry_job
from ..models import Job, User, utcnow
from ..routers.auth import current_user

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


def _visible_job(db: Session, job_id: str, user: User) -> Job:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="작업이 없습니다")
    try:
        require_view(db, job.project_id, user)
    except HTTPException:
        raise HTTPException(status_code=404, detail="작업이 없습니다") from None
    return job


@router.get("")
def list_jobs(db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict:
    project_ids = [row.id for row in visible_projects(db, user)]
    if not project_ids:
        return {"jobs": []}
    rows = db.scalars(
        select(Job)
        .where(Job.project_id.in_(project_ids))
        .order_by(Job.created_at.desc())
        .limit(50)
    ).all()
    return {"jobs": [job_out(row) for row in rows]}


@router.get("/{job_id}")
def get_job(
    job_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)
) -> dict:
    return job_out(_visible_job(db, job_id, user))


@router.get("/{job_id}/download")
def download_job(
    job_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    job = _visible_job(db, job_id, user)
    if job.kind == "dataless":
        try:
            require_edit(db, job.project_id, user)
        except HTTPException:
            raise HTTPException(status_code=403, detail="조회자는 StationXML만 받을 수 있습니다") from None
    if job.status != "succeeded":
        raise HTTPException(status_code=409, detail="아직 받을 파일이 없습니다")
    asset = job_artifact(db, job)
    if asset is None:
        raise HTTPException(status_code=404, detail="산출물이 없습니다")
    filename = asset.filename.replace('"', "")
    return Response(
        content=asset.content,
        media_type=asset.media_type or "application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-PDCC-Filename": filename,
        },
    )


@router.post("/{job_id}/retry")
def post_retry(
    job_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)
) -> dict:
    job = _visible_job(db, job_id, user)
    try:
        retry_job(db, job)
        db.commit()
        db.refresh(job)
    except JobError as exc:
        db.rollback()
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return job_out(job)


@router.post("/{job_id}/cancel")
def post_cancel(
    job_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)
) -> dict:
    job = _visible_job(db, job_id, user)
    if job.status != "queued":
        raise HTTPException(status_code=409, detail="대기 중인 작업만 취소할 수 있습니다")
    cancel_queued(job.id)
    job.status = "cancelled"
    job.message = "취소됨"
    job.finished_at = utcnow()
    db.commit()
    db.refresh(job)
    return job_out(job)
