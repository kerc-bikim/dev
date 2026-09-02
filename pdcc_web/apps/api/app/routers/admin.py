from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..access import (
    add_member,
    member_out,
    normalize_role,
    org_of,
    require_admin,
    user_out,
)
from ..config import settings
from ..dashboard import backup_status, build_dashboard
from ..db import get_db
from ..inventory.locks import LockError, all_live_locks, lock_snapshot, release_lock
from ..inventory.service import write_audit
from ..jobs.queue import cancel_queued
from ..jobs.service import job_out
from ..models import (
    AuditLog,
    Job,
    NrlAlias,
    NrlExcluded,
    Organization,
    Project,
    ProjectMember,
    User,
    hash_password,
    utcnow,
)
from ..notices import push_notice
from ..nrl.client import nrl_mode
from ..routers.auth import current_user

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _admin(user: User = Depends(current_user)) -> User:
    return require_admin(user)


class OrgIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)


class UserIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)
    role: str = Field(min_length=1, max_length=32)
    display_name: str | None = Field(default=None, max_length=128)
    org_id: int | None = None


class PasswordIn(BaseModel):
    password: str = Field(min_length=1, max_length=128)


class RoleIn(BaseModel):
    role: str = Field(min_length=1, max_length=32)


class MemberIn(BaseModel):
    user_id: int
    role: str = Field(min_length=1, max_length=32)
    project_id: int


class NrlAliasIn(BaseModel):
    query: str = Field(min_length=1, max_length=64)
    manufacturer: str = Field(min_length=1, max_length=128)
    model: str = Field(default="", max_length=128)


class NrlExcludedIn(BaseModel):
    query: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=512)


class UnlockIn(BaseModel):
    station_path: str = Field(min_length=1, max_length=160)
    reason: str = Field(min_length=1, max_length=512)


def _required(value: str, label: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise HTTPException(status_code=400, detail=f"{label}을(를) 입력하세요")
    return cleaned


def _query(value: str) -> str:
    return _required(value, "검색어").lower()


def _alias_out(row: NrlAlias) -> dict:
    return {
        "id": row.id,
        "query": row.query,
        "manufacturer": row.manufacturer,
        "model": row.model,
    }


def _excluded_out(row: NrlExcluded) -> dict:
    return {
        "id": row.id,
        "query": row.query,
        "name": row.name,
        "message": row.message,
    }


def _audit_out(row: AuditLog, project_name: str | None) -> dict:
    return {
        "id": row.id,
        "project_id": row.project_id,
        "project_name": project_name,
        "actor": row.actor,
        "action": row.action,
        "target": row.target,
        "summary": row.summary,
        "details": row.details or "",
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _org_or_404(db: Session, org_id: int | None) -> Organization:
    if org_id is None:
        org = db.scalar(select(Organization).order_by(Organization.id.asc()))
        if org is None:
            raise HTTPException(status_code=400, detail="기관이 없습니다")
        return org
    org = db.get(Organization, org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="기관이 없습니다")
    return org


@router.get("/dashboard")
def admin_dashboard(db: Session = Depends(get_db), _admin: User = Depends(_admin)) -> dict:
    return build_dashboard(db)


@router.get("/audit-logs")
def list_audit_logs(
    project_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    _admin: User = Depends(_admin),
) -> dict:
    filters = [AuditLog.project_id == project_id] if project_id is not None else []
    total = db.scalar(select(func.count(AuditLog.id)).where(*filters)) or 0
    rows = db.execute(
        select(AuditLog, Project.name)
        .outerjoin(Project, Project.id == AuditLog.project_id)
        .where(*filters)
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .limit(limit)
    ).all()
    return {
        "audit_logs": [_audit_out(row, project_name) for row, project_name in rows],
        "total": total,
    }


@router.get("/nrl/aliases")
def list_nrl_aliases(db: Session = Depends(get_db), _admin: User = Depends(_admin)) -> dict:
    rows = db.scalars(select(NrlAlias).order_by(NrlAlias.query, NrlAlias.id)).all()
    return {"aliases": [_alias_out(row) for row in rows]}


@router.post("/nrl/aliases")
def create_nrl_alias(
    body: NrlAliasIn, db: Session = Depends(get_db), admin: User = Depends(_admin)
) -> dict:
    query = _query(body.query)
    if db.scalar(select(NrlAlias).where(NrlAlias.query == query)) is not None:
        raise HTTPException(status_code=409, detail="같은 별칭 검색어가 있습니다")
    row = NrlAlias(
        query=query,
        manufacturer=_required(body.manufacturer, "제조사"),
        model=body.model.strip(),
    )
    db.add(row)
    db.flush()
    write_audit(
        db,
        project_id=None,
        actor=admin.username,
        action="nrl_alias_create",
        target=query,
        summary=f"NRL 별칭 생성 {query}",
    )
    db.commit()
    db.refresh(row)
    return _alias_out(row)


@router.put("/nrl/aliases/{alias_id}")
def update_nrl_alias(
    alias_id: int,
    body: NrlAliasIn,
    db: Session = Depends(get_db),
    admin: User = Depends(_admin),
) -> dict:
    row = db.get(NrlAlias, alias_id)
    if row is None:
        raise HTTPException(status_code=404, detail="별칭이 없습니다")
    query = _query(body.query)
    duplicate = db.scalar(
        select(NrlAlias).where(NrlAlias.query == query, NrlAlias.id != alias_id)
    )
    if duplicate is not None:
        raise HTTPException(status_code=409, detail="같은 별칭 검색어가 있습니다")
    before = row.query
    row.query = query
    row.manufacturer = _required(body.manufacturer, "제조사")
    row.model = body.model.strip()
    write_audit(
        db,
        project_id=None,
        actor=admin.username,
        action="nrl_alias_update",
        target=query,
        summary=f"NRL 별칭 수정 {before} → {query}",
    )
    db.commit()
    db.refresh(row)
    return _alias_out(row)


@router.delete("/nrl/aliases/{alias_id}")
def delete_nrl_alias(
    alias_id: int, db: Session = Depends(get_db), admin: User = Depends(_admin)
) -> dict:
    row = db.get(NrlAlias, alias_id)
    if row is None:
        raise HTTPException(status_code=404, detail="별칭이 없습니다")
    query = row.query
    db.delete(row)
    write_audit(
        db,
        project_id=None,
        actor=admin.username,
        action="nrl_alias_delete",
        target=query,
        summary=f"NRL 별칭 삭제 {query}",
    )
    db.commit()
    return {"ok": True, "query": query}


@router.get("/nrl/excluded")
def list_nrl_excluded(db: Session = Depends(get_db), _admin: User = Depends(_admin)) -> dict:
    rows = db.scalars(select(NrlExcluded).order_by(NrlExcluded.query, NrlExcluded.id)).all()
    return {"excluded": [_excluded_out(row) for row in rows]}


@router.post("/nrl/excluded")
def create_nrl_excluded(
    body: NrlExcludedIn, db: Session = Depends(get_db), admin: User = Depends(_admin)
) -> dict:
    query = _query(body.query)
    if db.scalar(select(NrlExcluded).where(NrlExcluded.query == query)) is not None:
        raise HTTPException(status_code=409, detail="같은 제외 장비 검색어가 있습니다")
    row = NrlExcluded(
        query=query,
        name=_required(body.name, "장비명"),
        message=_required(body.message, "안내"),
    )
    db.add(row)
    db.flush()
    write_audit(
        db,
        project_id=None,
        actor=admin.username,
        action="nrl_excluded_create",
        target=query,
        summary=f"NRL 제외 장비 생성 {query}",
    )
    db.commit()
    db.refresh(row)
    return _excluded_out(row)


@router.put("/nrl/excluded/{excluded_id}")
def update_nrl_excluded(
    excluded_id: int,
    body: NrlExcludedIn,
    db: Session = Depends(get_db),
    admin: User = Depends(_admin),
) -> dict:
    row = db.get(NrlExcluded, excluded_id)
    if row is None:
        raise HTTPException(status_code=404, detail="제외 장비가 없습니다")
    query = _query(body.query)
    duplicate = db.scalar(
        select(NrlExcluded).where(
            NrlExcluded.query == query,
            NrlExcluded.id != excluded_id,
        )
    )
    if duplicate is not None:
        raise HTTPException(status_code=409, detail="같은 제외 장비 검색어가 있습니다")
    before = row.query
    row.query = query
    row.name = _required(body.name, "장비명")
    row.message = _required(body.message, "안내")
    write_audit(
        db,
        project_id=None,
        actor=admin.username,
        action="nrl_excluded_update",
        target=query,
        summary=f"NRL 제외 장비 수정 {before} → {query}",
    )
    db.commit()
    db.refresh(row)
    return _excluded_out(row)


@router.delete("/nrl/excluded/{excluded_id}")
def delete_nrl_excluded(
    excluded_id: int, db: Session = Depends(get_db), admin: User = Depends(_admin)
) -> dict:
    row = db.get(NrlExcluded, excluded_id)
    if row is None:
        raise HTTPException(status_code=404, detail="제외 장비가 없습니다")
    query = row.query
    db.delete(row)
    write_audit(
        db,
        project_id=None,
        actor=admin.username,
        action="nrl_excluded_delete",
        target=query,
        summary=f"NRL 제외 장비 삭제 {query}",
    )
    db.commit()
    return {"ok": True, "query": query}


@router.get("/orgs")
def list_orgs(db: Session = Depends(get_db), _admin: User = Depends(_admin)) -> dict:
    rows = db.scalars(select(Organization).order_by(Organization.name)).all()
    out = []
    for org in rows:
        users = db.scalars(select(User).where(User.org_id == org.id)).all()
        out.append(
            {
                "id": org.id,
                "name": org.name,
                "user_count": len(users),
                "created_at": org.created_at.isoformat() if org.created_at else None,
            }
        )
    return {"orgs": out}


@router.post("/orgs")
def create_org(
    body: OrgIn, db: Session = Depends(get_db), admin: User = Depends(_admin)
) -> dict:
    name = body.name.strip()
    if db.scalar(select(Organization).where(Organization.name == name)) is not None:
        raise HTTPException(status_code=409, detail="같은 이름의 기관이 있습니다")
    org = Organization(name=name)
    db.add(org)
    db.flush()
    write_audit(
        db,
        project_id=None,
        actor=admin.username,
        action="org_create",
        target=name,
        summary=f"기관 생성 {name}",
    )
    db.commit()
    db.refresh(org)
    return {
        "id": org.id,
        "name": org.name,
        "user_count": 0,
        "created_at": org.created_at.isoformat() if org.created_at else None,
    }


@router.get("/users")
def list_users(db: Session = Depends(get_db), _admin: User = Depends(_admin)) -> dict:
    rows = db.scalars(select(User).order_by(User.username)).all()
    orgs = {org.id: org for org in db.scalars(select(Organization)).all()}
    return {"users": [user_out(row, orgs.get(row.org_id) if row.org_id else None) for row in rows]}


@router.post("/users")
def create_user(
    body: UserIn, db: Session = Depends(get_db), admin: User = Depends(_admin)
) -> dict:
    username = body.username.strip()
    if db.scalar(select(User).where(User.username == username)) is not None:
        raise HTTPException(status_code=409, detail="같은 아이디가 있습니다")
    role = normalize_role(body.role)
    org = _org_or_404(db, body.org_id)
    user = User(
        username=username,
        display_name=(body.display_name or "").strip() or username,
        password_hash=hash_password(body.password),
        role=role,
        active=True,
        org_id=org.id,
    )
    db.add(user)
    db.flush()
    write_audit(
        db,
        project_id=None,
        actor=admin.username,
        action="user_create",
        target=username,
        summary=f"{username} {role} 생성",
    )
    db.commit()
    db.refresh(user)
    return user_out(user, org)


@router.post("/users/{user_id}/deactivate")
def deactivate_user(
    user_id: int, db: Session = Depends(get_db), admin: User = Depends(_admin)
) -> dict:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="사용자가 없습니다")
    if user.id == admin.id:
        raise HTTPException(status_code=400, detail="자기 자신은 비활성할 수 없습니다")
    user.active = False
    write_audit(
        db,
        project_id=None,
        actor=admin.username,
        action="user_deactivate",
        target=user.username,
        summary=f"{user.username} 비활성",
    )
    db.commit()
    db.refresh(user)
    return user_out(user, org_of(db, user))


@router.post("/users/{user_id}/activate")
def activate_user(
    user_id: int, db: Session = Depends(get_db), admin: User = Depends(_admin)
) -> dict:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="사용자가 없습니다")
    user.active = True
    write_audit(
        db,
        project_id=None,
        actor=admin.username,
        action="user_activate",
        target=user.username,
        summary=f"{user.username} 활성",
    )
    db.commit()
    db.refresh(user)
    return user_out(user, org_of(db, user))


@router.post("/users/{user_id}/password")
def reset_password(
    user_id: int,
    body: PasswordIn,
    db: Session = Depends(get_db),
    admin: User = Depends(_admin),
) -> dict:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="사용자가 없습니다")
    user.password_hash = hash_password(body.password)
    write_audit(
        db,
        project_id=None,
        actor=admin.username,
        action="user_password",
        target=user.username,
        summary=f"{user.username} 비밀번호 재설정",
    )
    db.commit()
    return {"ok": True, "username": user.username}


@router.post("/users/{user_id}/role")
def set_role(
    user_id: int,
    body: RoleIn,
    db: Session = Depends(get_db),
    admin: User = Depends(_admin),
) -> dict:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="사용자가 없습니다")
    user.role = normalize_role(body.role)
    write_audit(
        db,
        project_id=None,
        actor=admin.username,
        action="user_role",
        target=user.username,
        summary=f"{user.username} 역할 {user.role}",
    )
    db.commit()
    db.refresh(user)
    return user_out(user, org_of(db, user))


@router.get("/projects/{project_id}/members")
def admin_list_members(
    project_id: int, db: Session = Depends(get_db), _admin: User = Depends(_admin)
) -> dict:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="프로젝트가 없습니다")
    rows = db.scalars(
        select(ProjectMember).where(ProjectMember.project_id == project.id)
    ).all()
    users = {row.id: row for row in db.scalars(select(User)).all()}
    return {
        "project_id": project.id,
        "members": [member_out(row, users[row.user_id]) for row in rows if row.user_id in users],
    }


@router.put("/members")
def admin_put_member(
    body: MemberIn, db: Session = Depends(get_db), admin: User = Depends(_admin)
) -> dict:
    project = db.get(Project, body.project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="프로젝트가 없습니다")
    user = db.get(User, body.user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="사용자가 없습니다")
    row = add_member(db, project, user, body.role)
    write_audit(
        db,
        project_id=project.id,
        actor=admin.username,
        action="member",
        target=user.username,
        summary=f"{user.username} 멤버 {row.role}",
    )
    db.commit()
    return member_out(row, user)


def _admin_job(db: Session, job: Job) -> dict:
    data = job_out(job)
    project = db.get(Project, job.project_id)
    data["project_name"] = project.name if project else None
    data["network_code"] = project.network_code if project else None
    return data


@router.get("/jobs")
def admin_list_jobs(
    project_id: int | None = Query(default=None),
    kind: str | None = Query(default=None),
    status: str | None = Query(default=None),
    db: Session = Depends(get_db),
    _admin: User = Depends(_admin),
) -> dict:
    stmt = select(Job).order_by(Job.created_at.desc()).limit(200)
    if project_id is not None:
        stmt = stmt.where(Job.project_id == project_id)
    if kind:
        stmt = stmt.where(Job.kind == kind.strip())
    if status:
        stmt = stmt.where(Job.status == status.strip())
    rows = db.scalars(stmt).all()
    return {"jobs": [_admin_job(db, row) for row in rows]}


@router.get("/jobs/{job_id}/log")
def admin_job_log(
    job_id: str, db: Session = Depends(get_db), _admin: User = Depends(_admin)
):
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="작업이 없습니다")
    lines = [
        f"id={job.id}",
        f"project_id={job.project_id}",
        f"kind={job.kind}",
        f"status={job.status}",
        f"username={job.username}",
        f"message={job.message or ''}",
        f"error={job.error or ''}",
        f"created_at={job.created_at.isoformat() if job.created_at else ''}",
        f"finished_at={job.finished_at.isoformat() if job.finished_at else ''}",
        f"result={job.result_json or ''}",
    ]
    body = "\n".join(lines) + "\n"
    filename = f"job-{job.id}.log"
    return Response(
        content=body.encode("utf-8"),
        media_type="text/plain; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-PDCC-Filename": filename,
        },
    )


@router.post("/jobs/{job_id}/cancel")
def admin_cancel_job(
    job_id: str, db: Session = Depends(get_db), admin: User = Depends(_admin)
) -> dict:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="작업이 없습니다")
    if job.status != "queued":
        raise HTTPException(status_code=409, detail="대기 중인 작업만 취소할 수 있습니다")
    cancel_queued(job.id)
    job.status = "cancelled"
    job.message = "관리자가 취소함"
    job.finished_at = utcnow()
    write_audit(
        db,
        project_id=job.project_id,
        actor=admin.username,
        action="job_cancel",
        target=job.id,
        summary=f"{job.kind} 작업 취소",
    )
    db.commit()
    db.refresh(job)
    return _admin_job(db, job)


@router.get("/locks")
def admin_list_locks(db: Session = Depends(get_db), _admin: User = Depends(_admin)) -> dict:
    return {"locks": all_live_locks(db)}


@router.post("/locks/unlock")
def admin_force_unlock(
    body: UnlockIn, db: Session = Depends(get_db), admin: User = Depends(_admin)
) -> dict:
    reason = body.reason.strip()
    if not reason:
        raise HTTPException(status_code=400, detail="강제 해제 사유를 입력하세요")
    current = lock_snapshot(body.station_path)
    if current is None:
        raise HTTPException(status_code=404, detail="잠금이 없습니다")
    holder_id = int(current["user_id"])
    holder_name = str(current.get("username") or "")
    project_id = int(current.get("project_id") or 0) or None
    try:
        release_lock(db, body.station_path, admin, force=True)
    except LockError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    write_audit(
        db,
        project_id=project_id,
        actor=admin.username,
        action="unlock",
        target=body.station_path,
        summary="잠금 강제 해제",
        details=reason,
    )
    if holder_id != admin.id:
        push_notice(holder_id, "관리자가 잠금을 해제했습니다", kind="unlock")
    db.commit()
    return {
        "ok": True,
        "station_path": body.station_path,
        "holder": holder_name,
        "draft_kept": True,
    }


@router.get("/system")
def admin_system(_admin: User = Depends(_admin)) -> dict:
    return {
        "upload": {
            "max_upload_bytes": settings.max_upload_bytes,
            "max_zip_bytes": settings.max_zip_bytes,
            "max_zip_uncompressed_bytes": settings.max_zip_uncompressed_bytes,
            "max_zip_members": settings.max_zip_members,
        },
        "timeouts": {
            "nrl_sec": settings.nrl_timeout_sec,
            "library_sec": settings.nrl_library_timeout_sec,
            "converter_sec": settings.converter_timeout_sec,
            "validator_sec": settings.validator_timeout_sec,
        },
        "seed": {
            "organization": settings.seed_organization or "",
            "label": settings.seed_label or "",
        },
        "session_ttl_sec": settings.session_ttl_sec,
        "lock_ttl_sec": settings.lock_ttl_sec,
        "nrl_mode": nrl_mode(),
        "backup": backup_status(),
        "citations": [
            {
                "name": "NRL",
                "text": "Templeton (2017)",
                "doi": "10.17611/S7159Q",
            },
            {
                "name": "StationXML",
                "text": "FDSN 표준",
                "doi": "",
            },
            {
                "name": "변환기/검증기",
                "text": "IRIS/EarthScope 도구",
                "doi": "",
            },
            {
                "name": "코드",
                "text": "PDCC Web 대체 구현. 배포 라이선스는 저장소 NOTICE를 따릅니다.",
                "doi": "",
            },
        ],
    }
