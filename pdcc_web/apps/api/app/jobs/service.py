from __future__ import annotations

import json
import logging
import time
from typing import Any

from sqlalchemy.orm import Session

from ..export import ExportError, preview_export, render_export
from ..models import AuditLog, ExportJob, Project, User, utcnow
from .queue import enqueue_job
from .store import loads_list

log = logging.getLogger("pdcc.jobs")

ACTIVE = {"queued", "running"}


def job_out(job: ExportJob) -> dict[str, Any]:
    return {
        "id": job.id,
        "project_id": job.project_id,
        "username": job.username,
        "kind": job.kind,
        "scope": job.scope,
        "station": job.station,
        "start_time": job.start_time,
        "nslc": job.nslc,
        "status": job.status,
        "progress": job.progress,
        "message": job.message,
        "error": job.error,
        "filename": job.filename,
        "media_type": job.media_type,
        "downloadable": job.status == "completed" and bool(job.artifact_path),
        "warnings": loads_list(job.warnings_json),
        "losses": loads_list(job.losses_json),
        "drops": loads_list(job.drops_json),
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
    }


def preview_project_export(
    project: Project,
    *,
    kind: str,
    station: str | None,
    start: str | None,
    nslc: str | None,
) -> dict:
    return preview_export(
        project.xml_text,
        kind=kind,
        network=project.network_code,
        station=station,
        start=start,
        nslc=nslc,
    )


def enqueue_export(
    db: Session,
    user: User,
    project: Project,
    *,
    job_id: str,
    kind: str,
    scope: str,
    station: str | None,
    start: str | None,
    nslc: str | None,
    accept_losses: bool,
) -> ExportJob:
    preview = preview_project_export(
        project, kind=kind, station=station, start=start, nslc=nslc
    )
    if preview["errors"]:
        raise ExportError(
            f"내보낼 수 없습니다. 문제 채널 {len(preview['errors'])}개",
            400,
            errors=preview["errors"],
            losses=preview["losses"],
            drops=preview["drops"],
            code="E_EXPORT",
        )
    if preview["losses"] and not accept_losses:
        raise ExportError(
            "변환 손실이 있습니다. 목록을 확인한 뒤 다시 요청하세요",
            409,
            errors=[],
            losses=preview["losses"],
            drops=preview["drops"],
            code="E_LOSS_CONFIRM",
        )
    job = ExportJob(
        id=job_id,
        project_id=project.id,
        user_id=user.id,
        username=user.username,
        kind=kind,
        scope=scope,
        station=station,
        start_time=start,
        nslc=nslc,
        status="queued",
        progress=0,
        message="대기 중",
        warnings_json="[]",
        losses_json=json.dumps(preview["losses"], ensure_ascii=False),
        drops_json=json.dumps(preview["drops"], ensure_ascii=False),
        xml_snapshot=project.xml_text,
    )
    db.add(job)
    db.add(
        AuditLog(
            project_id=project.id,
            actor=user.username,
            action="export",
            target=f"{kind}/{scope}",
            summary=f"{kind} 내보내기 대기 ({scope})",
        )
    )
    db.flush()
    enqueue_job(job.id)
    return job


def retry_job(db: Session, job: ExportJob) -> ExportJob:
    if job.status not in {"failed", "cancelled", "completed"}:
        raise ExportError("대기·진행 중인 작업은 재시도할 수 없습니다", 409)
    job.status = "queued"
    job.progress = 0
    job.message = "재시도 대기"
    job.error = None
    job.filename = None
    job.media_type = None
    job.artifact_path = None
    job.started_at = None
    job.finished_at = None
    db.flush()
    enqueue_job(job.id)
    return job
