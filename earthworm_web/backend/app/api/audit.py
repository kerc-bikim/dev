from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from fastapi.responses import PlainTextResponse

from ..security import require_actor, require_operator
from ..services.audit import export_csv, list_audit

router = APIRouter(prefix="/api/audit", tags=["audit"])


@router.get("")
def get_audit(
    _: None = Depends(require_actor),
    since: str | None = Query(default=None, alias="from"),
    until: str | None = Query(default=None, alias="to"),
    actor: str | None = Query(default=None),
    action: str | None = Query(default=None),
    result: str | None = Query(default=None),
    q: str | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict:
    return list_audit(
        since=since,
        until=until,
        actor=actor,
        action=action,
        result=result,
        q=q,
        offset=offset,
        limit=limit,
    )


@router.get("/export")
def get_audit_export(
    _: None = Depends(require_operator),
    since: str | None = Query(default=None, alias="from"),
    until: str | None = Query(default=None, alias="to"),
    actor: str | None = Query(default=None),
    action: str | None = Query(default=None),
    result: str | None = Query(default=None),
    q: str | None = Query(default=None),
) -> PlainTextResponse:
    csv = export_csv(since=since, until=until, actor=actor, action=action, result=result, q=q)
    return PlainTextResponse(csv, media_type="text/csv")
