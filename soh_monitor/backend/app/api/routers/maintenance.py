"""유지보수 시간대. OPERATOR 가 열고 닫는다."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request, status
from sqlalchemy import desc, select

from app.api import audit
from app.api.deps import RequireOperate, RequireRead
from app.api.presenters import iso, parse_uuid
from app.api.schemas import MaintenanceWrite
from app.db.models import MaintenanceWindow
from app.db.session import session_scope

router = APIRouter(prefix="/api/v1", tags=["maintenance"])


@router.get("/maintenance-windows", summary="유지보수 시간대 목록")
def list_windows(actor: RequireRead, limit: int = Query(default=50, ge=1, le=200)) -> dict:
    with session_scope() as session:
        rows = session.scalars(
            select(MaintenanceWindow).order_by(desc(MaintenanceWindow.starts_at)).limit(limit)
        ).all()
        return {
            "windows": [
                {
                    "id": str(row.id),
                    "scope": row.scope,
                    "scopeId": str(row.scope_id) if row.scope_id else None,
                    "startsAt": iso(row.starts_at),
                    "endsAt": iso(row.ends_at),
                    "reason": row.reason,
                    "suppressAlerts": row.suppress_alerts,
                }
                for row in rows
            ]
        }


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
        return {
            "window": {
                "id": str(window.id),
                "scope": window.scope,
                "scopeId": str(window.scope_id) if window.scope_id else None,
                "startsAt": iso(window.starts_at),
                "endsAt": iso(window.ends_at),
                "reason": window.reason,
                "suppressAlerts": window.suppress_alerts,
            }
        }
