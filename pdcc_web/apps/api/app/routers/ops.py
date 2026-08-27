from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..backup import build_backup_zip, restore_snapshot
from ..config import INSECURE_SECRET, settings
from ..db import get_db
from ..inventory.service import write_audit
from ..inventory.xmlbuild import InventoryError
from ..models import ADMIN_ROLE, AuditLog, User, hash_password
from ..runtime import (
    cookie_samesite,
    cookie_secure,
    is_production,
    stub_login_allowed,
)
from ..routers.auth import current_user

router = APIRouter(prefix="/api/ops", tags=["ops"])


def _http_inv(exc: InventoryError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


def _user_count(db: Session) -> int:
    return int(db.scalar(select(func.count()).select_from(User)) or 0)


@router.get("/bootstrap")
def bootstrap_status(db: Session = Depends(get_db)) -> dict:
    return {"available": _user_count(db) == 0}


class BootstrapIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=8, max_length=128)


@router.post("/bootstrap")
def bootstrap_user(body: BootstrapIn, db: Session = Depends(get_db)) -> dict:
    if _user_count(db) > 0:
        raise HTTPException(status_code=409, detail="이미 사용자가 있어 최초 부트스트랩을 할 수 없습니다")
    if body.username.lower() in {"stub", "stub2", "admin"}:
        raise HTTPException(status_code=400, detail="예약된 아이디는 쓸 수 없습니다")
    user = User(
        username=body.username.strip(),
        password_hash=hash_password(body.password),
        role=ADMIN_ROLE,
    )
    db.add(user)
    db.flush()
    write_audit(
        db,
        project_id=None,
        actor=user.username,
        action="bootstrap",
        target=user.username,
        summary="최초 관리자 생성",
    )
    db.commit()
    return {"ok": True, "username": user.username, "role": user.role}


@router.get("/status")
def ops_status(user: User = Depends(current_user)) -> dict:
    return {
        "env": settings.app_env,
        "allow_stub_login": stub_login_allowed(),
        "dev_bootstrap_admin": bool(settings.dev_bootstrap_admin),
        "session_cookie_secure": cookie_secure(),
        "session_cookie_samesite": cookie_samesite(),
        "audit_retention_days": settings.audit_retention_days,
        "app_secret_is_default": settings.app_secret == INSECURE_SECRET,
        "username": user.username,
        "role": user.role,
        "production": is_production(),
    }


@router.get("/audit")
def list_audit(
    project_id: int | None = None,
    actor: str | None = None,
    action: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    stmt = select(AuditLog)
    count_stmt = select(func.count()).select_from(AuditLog)
    if project_id is not None:
        stmt = stmt.where(AuditLog.project_id == project_id)
        count_stmt = count_stmt.where(AuditLog.project_id == project_id)
    if actor:
        stmt = stmt.where(AuditLog.actor == actor)
        count_stmt = count_stmt.where(AuditLog.actor == actor)
    if action:
        stmt = stmt.where(AuditLog.action == action)
        count_stmt = count_stmt.where(AuditLog.action == action)
    total = int(db.scalar(count_stmt) or 0)
    rows = db.scalars(
        stmt.order_by(AuditLog.id.desc()).offset(offset).limit(limit)
    ).all()
    return {
        "items": [
            {
                "id": row.id,
                "project_id": row.project_id,
                "actor": row.actor,
                "action": row.action,
                "target": row.target,
                "summary": row.summary,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
        "retention_days": settings.audit_retention_days,
        "viewer": user.username,
    }


def purge_expired_audit(db: Session) -> int:
    days = max(int(settings.audit_retention_days), 0)
    if days <= 0:
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    result = db.execute(delete(AuditLog).where(AuditLog.created_at < cutoff))
    return int(result.rowcount or 0)


@router.post("/audit/purge")
def purge_audit(
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    if user.role != ADMIN_ROLE:
        raise HTTPException(status_code=403, detail="관리자만 감사 로그를 정리할 수 있습니다")
    deleted = purge_expired_audit(db)
    write_audit(
        db,
        project_id=None,
        actor=user.username,
        action="purge",
        target="audit_logs",
        summary=f"보관기간 {settings.audit_retention_days}일 이전 {deleted}건 삭제",
    )
    db.commit()
    return {"ok": True, "deleted": deleted, "retention_days": settings.audit_retention_days}


@router.get("/backup")
def download_backup(
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> Response:
    payload, filename, _manifest = build_backup_zip(db, user)
    db.commit()
    return Response(
        content=payload,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/restore")
async def restore_backup(
    request: Request,
    replace: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    payload = await request.body()
    if not payload:
        raise HTTPException(status_code=400, detail="복원할 ZIP 또는 StationXML이 없습니다")
    if replace and user.role != ADMIN_ROLE:
        raise HTTPException(status_code=403, detail="덮어쓰기 복원은 관리자만 할 수 있습니다")
    try:
        result = restore_snapshot(
            db,
            user,
            payload,
            content_type=request.headers.get("content-type") or "",
            replace=replace,
        )
        db.commit()
    except InventoryError as exc:
        db.rollback()
        _http_inv(exc)
        raise
    return result
