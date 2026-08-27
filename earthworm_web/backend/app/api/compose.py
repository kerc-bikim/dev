from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from ..models.schemas import ComposeBoardIn, ComposeSuggestIn
from ..security import request_ip, require_actor, require_operator
from ..services.app_store import load_app
from ..services.audit import record_audit
from ..services.auth import Actor
from ..services.compose import ComposeError, apply_board_async, get_compose, suggest, validate_board

router = APIRouter(prefix="/api/compose", tags=["compose"])


def require_setup() -> None:
    if not load_app().setup_complete:
        raise HTTPException(409, "초기 설정을 먼저 완료하세요")


def _board_dict(body: ComposeBoardIn) -> dict:
    return {
        "site": body.site.model_dump(),
        "instances": [i.model_dump() for i in body.instances],
    }


@router.get("")
def get_board(_: None = Depends(require_setup), __: Actor = Depends(require_actor)) -> dict:
    return get_compose()


@router.post("/validate")
def post_validate(body: ComposeBoardIn, _: None = Depends(require_setup), __: Actor = Depends(require_actor)) -> dict:
    issues = validate_board(_board_dict(body))
    errors = [i for i in issues if i.get("level") != "warning"]
    return {"ok": not errors, "issues": issues}


@router.post("/suggest")
def post_suggest(body: ComposeSuggestIn, _: None = Depends(require_setup), __: Actor = Depends(require_actor)) -> dict:
    try:
        return suggest(body.family, body.board)
    except ComposeError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/apply")
async def post_apply(
    body: ComposeBoardIn,
    request: Request,
    _: None = Depends(require_setup),
    actor: Actor = Depends(require_operator),
) -> dict:
    if not actor or not actor.username:
        raise HTTPException(500, "작업자가 없습니다")
    board = _board_dict(body)
    try:
        result = await apply_board_async(board, reconfigure=body.reconfigure, actor_username=actor.username)
    except ComposeError as exc:
        record_audit(
            action="compose_apply",
            result="error",
            actor_id=actor.id,
            actor_username=actor.username,
            actor_display_name=actor.display_name,
            target="compose",
            ip=request_ip(request),
            detail={"issues": exc.issues, "message": str(exc)},
        )
        raise HTTPException(409, {"message": str(exc), "issues": exc.issues}) from exc
    except RuntimeError as exc:
        if "작업자" in str(exc):
            raise HTTPException(500, str(exc)) from exc
        raise HTTPException(409, str(exc)) from exc
    record_audit(
        action="compose_apply",
        result="ok",
        actor_id=actor.id,
        actor_username=actor.username,
        actor_display_name=actor.display_name,
        target="compose",
        ip=request_ip(request),
        detail={"revision": result.get("compose_revision"), "instances": result.get("instances")},
        backup_dir=result.get("backup_dir"),
    )
    return result
