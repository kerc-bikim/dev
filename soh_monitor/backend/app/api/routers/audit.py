"""감사 로그 조회. 설정 변경 이력은 ADMIN 만 본다."""
from __future__ import annotations

from fastapi import APIRouter, Query

from app.api import audit
from app.api.deps import RequireAdmin
from app.api.presenters import iso
from app.db.session import session_scope

router = APIRouter(prefix="/api/v1", tags=["audit"])


@router.get("/audit-logs", summary="감사 로그")
def list_audit_logs(
    actor: RequireAdmin,
    limit: int = Query(default=100, ge=1, le=500),
    entity_type: str | None = None,
) -> dict:
    with session_scope() as session:
        rows = audit.list_logs(session, limit=limit, entity_type=entity_type)
        return {
            "logs": [
                {
                    "id": str(row.id),
                    "occurredAt": iso(row.occurred_at),
                    "actorId": str(row.actor_id) if row.actor_id else None,
                    "actorName": row.actor_name,
                    "action": row.action,
                    "entityType": row.entity_type,
                    "entityId": row.entity_id,
                    "before": row.before_value,
                    "after": row.after_value,
                    "sourceIp": row.source_ip,
                }
                for row in rows
            ]
        }
