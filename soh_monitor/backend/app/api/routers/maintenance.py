"""유지보수 시간대. OPERATOR 가 열고 닫는다."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query, Request, status
from sqlalchemy import desc, select

from app.api import audit
from app.api.deps import RequireOperate, RequireRead
from app.api.presenters import iso, parse_uuid
from app.repository.postgres.collector_repo import as_utc
from app.api.schemas import MaintenanceWrite
from app.db.models import MaintenanceWindow
from app.db.session import session_scope

router = APIRouter(prefix="/api/v1", tags=["maintenance"])


def _window_payload(row: MaintenanceWindow) -> dict:
    return {
        "id": str(row.id),
        "scope": row.scope,
        "scopeId": str(row.scope_id) if row.scope_id else None,
        "startsAt": iso(row.starts_at),
        "endsAt": iso(row.ends_at),
        "reason": row.reason,
        "suppressAlerts": row.suppress_alerts,
    }


@router.get("/maintenance-windows", summary="유지보수 시간대 목록")
def list_windows(
    actor: RequireRead,
    limit: int = Query(default=50, ge=1, le=200),
    scope: str | None = None,
    scope_id: str | None = Query(default=None, alias="scopeId"),
    active: bool = False,
) -> dict:
    now = datetime.now(timezone.utc)
    with session_scope() as session:
        query = select(MaintenanceWindow)
        if scope:
            query = query.where(MaintenanceWindow.scope == scope)
        if scope_id:
            query = query.where(MaintenanceWindow.scope_id == parse_uuid(scope_id, "범위 식별자"))
        if active:
            query = query.where(
                MaintenanceWindow.starts_at <= now,
                MaintenanceWindow.ends_at >= now,
            )
        rows = session.scalars(query.order_by(desc(MaintenanceWindow.starts_at)).limit(limit)).all()
        return {"windows": [_window_payload(row) for row in rows]}


@router.post("/maintenance-windows", status_code=status.HTTP_201_CREATED, summary="유지보수 시간대 등록")
def create_window(body: MaintenanceWrite, request: Request, actor: RequireOperate) -> dict:
    if body.ends_at <= body.starts_at:
        raise HTTPException(status_code=400, detail="종료 시각이 시작 시각보다 이르다")
    if body.scope != "global" and not body.scope_id:
        raise HTTPException(status_code=400, detail="범위 대상 식별자가 필요하다")

    with session_scope() as session:
        window = MaintenanceWindow(
            scope=body.scope,
            scope_id=parse_uuid(body.scope_id, "범위 식별자") if body.scope_id else None,
            starts_at=body.starts_at,
            ends_at=body.ends_at,
            reason=body.reason,
            suppress_alerts=body.suppress_alerts,
            created_by=actor.id,
        )
        session.add(window)
        session.flush()
        audit.record(
            session,
            actor=actor,
            action="create",
            entity_type="maintenance_window",
            entity_id=str(window.id),
            after={"scope": window.scope, "reason": window.reason},
            request=request,
        )
        return {"window": _window_payload(window)}


@router.post("/maintenance-windows/{window_id}/close", summary="유지보수 시간대 종료")
def close_window(window_id: str, request: Request, actor: RequireOperate) -> dict:
    identifier = parse_uuid(window_id, "유지보수 식별자")
    now = datetime.now(timezone.utc)
    with session_scope() as session:
        window = session.get(MaintenanceWindow, identifier)
        if window is None:
            raise HTTPException(status_code=404, detail="없는 유지보수 시간대다")
        ends_at = as_utc(window.ends_at)
        starts_at = as_utc(window.starts_at)
        if ends_at is None or starts_at is None:
            raise HTTPException(status_code=409, detail="시각이 없는 유지보수 시간대다")
        if ends_at <= now:
            raise HTTPException(status_code=409, detail="이미 끝난 유지보수 시간대다")
        before = {"endsAt": iso(window.ends_at), "startsAt": iso(window.starts_at)}
        if starts_at > now:
            window.ends_at = window.starts_at
        else:
            window.ends_at = now
        audit.record(
            session,
            actor=actor,
            action="close",
            entity_type="maintenance_window",
            entity_id=str(window.id),
            before=before,
            after={"endsAt": iso(window.ends_at)},
            request=request,
        )
        return {"window": _window_payload(window)}
