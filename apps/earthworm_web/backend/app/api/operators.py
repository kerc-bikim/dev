from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from ..models.schemas import OperatorCreateIn, OperatorPatchIn
from ..security import request_ip, require_admin
from ..services.auth import Actor, create_operator, list_operators, update_operator
from ..services.audit import record_audit

router = APIRouter(prefix="/api/operators", tags=["operators"], dependencies=[Depends(require_admin)])


@router.get("")
def get_operators() -> dict:
    return {"operators": list_operators()}


@router.post("")
def post_operator(body: OperatorCreateIn, request: Request, actor: Actor = Depends(require_admin)) -> dict:
    rec = create_operator(
        username=body.username,
        display_name=body.display_name,
        password=body.password,
        role=body.role,
        created_by=actor.id,
    )
    record_audit(
        action="operator_create",
        result="ok",
        actor_id=actor.id,
        actor_username=actor.username,
        actor_display_name=actor.display_name,
        target=rec["username"],
        ip=request_ip(request),
        detail={"role": rec["role"]},
    )
    return {"operator": rec, "operators": list_operators()}


@router.patch("/{op_id}")
def patch_operator(
    op_id: int, body: OperatorPatchIn, request: Request, actor: Actor = Depends(require_admin)
) -> dict:
    rec = update_operator(
        op_id,
        display_name=body.display_name,
        role=body.role,
        enabled=body.enabled,
        password=body.password,
    )
    action = "operator_disable" if body.enabled is False else "operator_update"
    record_audit(
        action=action,
        result="ok",
        actor_id=actor.id,
        actor_username=actor.username,
        actor_display_name=actor.display_name,
        target=rec["username"],
        ip=request_ip(request),
        detail={"role": rec["role"], "enabled": rec["enabled"], "password_reset": body.password is not None},
    )
    return {"operator": rec, "operators": list_operators()}
