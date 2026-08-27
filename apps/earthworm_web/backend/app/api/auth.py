from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from ..config import settings
from ..models.schemas import BootstrapIn, LoginIn, PasswordIn
from ..security import cookie_name, request_ip, require_actor
from ..services.auth import (
    Actor,
    bootstrap_admin,
    change_own_password,
    delete_session,
    issue_ws_ticket,
    login,
    operator_count,
)
from ..services.audit import record_audit

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _set_session(response: Response, token: str) -> None:
    response.set_cookie(
        key=cookie_name(),
        value=token,
        httponly=True,
        samesite="lax",
        secure=bool(settings.COOKIE_SECURE),
        max_age=7 * 24 * 3600,
        path="/",
    )


@router.get("/status")
def auth_status() -> dict:
    return {"has_operators": operator_count() > 0, "bootstrap_required": operator_count() == 0}


@router.post("/bootstrap")
def post_bootstrap(body: BootstrapIn, request: Request, response: Response) -> dict:
    rec = bootstrap_admin(body.username, body.display_name or body.username, body.password)
    from ..services.auth import create_session

    token = create_session(rec["id"])
    _set_session(response, token)
    record_audit(
        action="bootstrap_admin",
        result="ok",
        actor_id=rec["id"],
        actor_username=rec["username"],
        actor_display_name=rec["display_name"],
        target=rec["username"],
        ip=request_ip(request),
    )
    return {"operator": rec}


@router.post("/login")
def post_login(body: LoginIn, request: Request, response: Response) -> dict:
    rec, token = login(body.username, body.password, ip=request_ip(request))
    _set_session(response, token)
    return {"operator": rec}


@router.post("/logout")
def post_logout(request: Request, response: Response, actor: Actor = Depends(require_actor)) -> dict:
    delete_session(request.cookies.get(cookie_name()))
    response.delete_cookie(cookie_name(), path="/")
    record_audit(
        action="logout",
        result="ok",
        actor_id=actor.id,
        actor_username=actor.username,
        actor_display_name=actor.display_name,
        target=actor.username,
        ip=request_ip(request),
    )
    return {"ok": True}


@router.get("/me")
def get_me(actor: Actor = Depends(require_actor)) -> dict:
    return actor.as_dict()


@router.post("/password")
def post_password(body: PasswordIn, request: Request, actor: Actor = Depends(require_actor)) -> dict:
    change_own_password(actor, body.current, body.new)
    record_audit(
        action="operator_update",
        result="ok",
        actor_id=actor.id,
        actor_username=actor.username,
        actor_display_name=actor.display_name,
        target=actor.username,
        ip=request_ip(request),
        detail={"password_changed": True},
    )
    return {"ok": True}


@router.post("/ws-ticket")
def post_ws_ticket(actor: Actor = Depends(require_actor)) -> dict:
    return issue_ws_ticket(actor)
