"""설정 변경 감사 기록.

주체·대상·전후 값을 남긴다. 비밀번호·토큰은 저장하지 않는다. 감사 로그가
비밀값의 두 번째 저장소가 되면 안 된다.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import Request
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.api.deps import Actor
from app.db.models import AuditLog

_SECRET_MARKERS = ("password", "secret", "token", "credential", "hash", "apikey", "api_key")


def redact_value(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            lowered = str(key).lower().replace("-", "_")
            if any(marker in lowered for marker in _SECRET_MARKERS):
                cleaned[key] = "***"
            else:
                cleaned[key] = redact_value(item)
        return cleaned
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    return value


def record(
    session: Session,
    *,
    actor: Actor | None,
    action: str,
    entity_type: str,
    entity_id: str | None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    request: Request | None = None,
) -> AuditLog:
    client_ip = None
    request_id = None
    if request is not None:
        forwarded = request.headers.get("x-forwarded-for")
        client_ip = (forwarded.split(",")[0].strip() if forwarded else None) or (
            request.client.host if request.client else None
        )
        request_id = request.headers.get("x-request-id")

    entry = AuditLog(
        occurred_at=datetime.now(timezone.utc),
        actor_id=actor.id if actor else None,
        actor_name=actor.username if actor else None,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        before_value=redact_value(before) if before is not None else None,
        after_value=redact_value(after) if after is not None else None,
        request_id=request_id,
        source_ip=client_ip,
    )
    session.add(entry)
    return entry


def list_logs(
    session: Session,
    *,
    limit: int = 100,
    entity_type: str | None = None,
    actor_name: str | None = None,
) -> list[AuditLog]:
    query = select(AuditLog).order_by(desc(AuditLog.occurred_at)).limit(limit)
    if entity_type:
        query = query.where(AuditLog.entity_type == entity_type)
    if actor_name:
        query = query.where(AuditLog.actor_name == actor_name)
    return list(session.scalars(query))
