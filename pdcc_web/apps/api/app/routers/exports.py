from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..export import ExportError
from ..jobs.queue import cancel_queued
from ..jobs.service import job_out, retry_job
from ..jobs.store import artifact_bytes
from ..models import ExportJob, User, utcnow
from ..routers.auth import current_user

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


def _job(db: Session, job_id: str, user: User) -> ExportJob:
    job = db.get(ExportJob, job_id)
    if job is None or job.user_id != user.id:
        raise HTTPException(status_code=404, detail="작업이 없습니다")
    return job


@router.get("")
def list_jobs(db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict:
    rows = db.scalars(
        select(ExportJob)
        .where(ExportJob.user_id == user.id)
        .order_by(ExportJob.created_at.desc())
        .limit(50)
    ).all()
    return {"jobs": [job_out(row) for row in rows]}


@router.get("/{job_id}")
def get_job(
    job_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)
) -> dict:
    return job_out(_job(db, job_id, user))


@router.get("/{job_id}/download")
def download_job(
    job_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    job = _job(db, job_id, user)
    if job.status != "completed" or not job.artifact_path:
        raise HTTPException(status_code=409, detail="아직 받을 파일이 없습니다")
    try:
        data = artifact_bytes(job)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="산출물이 없습니다") from None
    headers = {
        "Content-Disposition": f'attachment; filename="{job.filename or "export.bin"}"'
    }
    return Response(
        content=data,
        media_type=job.media_type or "application/octet-stream",
        headers=headers,
    )


@router.post("/{job_id}/retry")
def post_retry(
    job_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)
) -> dict:
    job = _job(db, job_id, user)
    try:
        retry_job(db, job)
        db.commit()
        db.refresh(job)
    except ExportError as exc:
        db.rollback()
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return job_out(job)


@router.post("/{job_id}/cancel")
def post_cancel(
    job_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)
) -> dict:
    job = _job(db, job_id, user)
    if job.status != "queued":
        raise HTTPException(status_code=409, detail="대기 중인 작업만 취소할 수 있습니다")
    cancel_queued(job.id)
    job.status = "cancelled"
    job.message = "취소됨"
    job.finished_at = utcnow()
    db.commit()
    db.refresh(job)
    return job_out(job)
