from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..inventory.collab import get_draft
from ..inventory.importers import load_import_warnings
from ..inventory.validator import summarize, validate_project
from ..models import AuditLog, Job, Project, ProjectVersion, User, utcnow
from .queue import enqueue_job
from .store import loads_obj

ACTIVE = {"queued", "running"}
RETRYABLE = {"failed", "cancelled"}


class JobError(Exception):
    def __init__(self, message: str, status_code: int = 409):
        super().__init__(message)
        self.status_code = status_code


def job_out(job: Job) -> dict[str, Any]:
    return {
        "id": job.id,
        "project_id": job.project_id,
        "username": job.username,
        "kind": job.kind,
        "status": job.status,
        "progress": job.progress,
        "message": job.message,
        "error": job.error,
        "version_id": job.version_id,
        "xml_source": job.xml_source,
        "result": loads_obj(job.result_json),
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
    }


def latest_version_id(db: Session, project_id: int) -> int | None:
    return db.scalars(
        select(ProjectVersion.id)
        .where(ProjectVersion.project_id == project_id)
        .order_by(ProjectVersion.number.desc(), ProjectVersion.id.desc())
    ).first()


def snapshot_xml(db: Session, project: Project, user: User) -> tuple[str, str]:
    row = get_draft(db, project.id, user.id)
    if row is not None:
        return row.xml_text, "draft"
    return project.xml_text, "project"


def enqueue_validate(
    db: Session,
    user: User,
    project: Project,
    *,
    job_id: str,
) -> Job:
    xml, source = snapshot_xml(db, project, user)
    job = Job(
        id=job_id,
        project_id=project.id,
        user_id=user.id,
        username=user.username,
        kind="validate",
        status="queued",
        progress=0,
        message="대기 중",
        version_id=latest_version_id(db, project.id),
        xml_source=source,
        xml_snapshot=xml,
        result_json="",
    )
    db.add(job)
    db.add(
        AuditLog(
            project_id=project.id,
            actor=user.username,
            action="validate",
            target=source,
            summary="공식 검증 대기",
        )
    )
    db.flush()
    enqueue_job(job.id)
    return job


def run_validate_snapshot(db: Session, job: Job, project: Project) -> dict:
    issues = load_import_warnings(db, project.id) + validate_project(
        job.xml_snapshot,
        project.network_code,
        project.id,
        mode="full",
    )
    return summarize(
        issues,
        xml_source=job.xml_source,
        mode="full",
        network=project.network_code,
    )


def retry_job(db: Session, job: Job) -> Job:
    if job.status not in RETRYABLE:
        raise JobError("대기·진행 중인 작업은 재시도할 수 없습니다", 409)
    job.status = "queued"
    job.progress = 0
    job.message = "재시도 대기"
    job.error = None
    job.result_json = ""
    job.started_at = None
    job.finished_at = None
    db.flush()
    enqueue_job(job.id)
    return job
