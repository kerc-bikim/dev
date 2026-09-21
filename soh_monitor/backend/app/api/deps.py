"""요청 주체와 권한 의존성."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Annotated, Callable

from fastapi import Depends, HTTPException, Request, status

from app.auth.rbac import Permission, has_permission
from app.auth.sessions import COOKIE_NAME, SessionError, verify_session
from app.config.settings import get_settings
from app.db.models import User, UserRole
from app.db.session import session_scope

PASSWORD_CHANGE_ALLOWED = {
    "/api/v1/auth/me",
    "/api/v1/auth/logout",
    "/api/v1/auth/change-password",
}


@dataclass(frozen=True)
class Actor:
    id: uuid.UUID
    username: str
    display_name: str
    role: UserRole
    must_change_password: bool

    def can(self, permission: Permission) -> bool:
        return has_permission(self.role, permission)


def _actor_from_user(user: User) -> Actor:
    return Actor(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        role=user.role,
        must_change_password=user.must_change_password,
    )


def optional_actor(request: Request) -> Actor | None:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    settings = get_settings()
    try:
        claims = verify_session(token, settings.session_signing_key())
    except SessionError:
        return None

    with session_scope() as session:
        user = session.get(User, claims.user_id)
        if user is None or not user.enabled:
            return None
        return _actor_from_user(user)


def current_actor(request: Request) -> Actor:
    actor = optional_actor(request)
    if actor is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="로그인이 필요하다")
    if actor.must_change_password and request.url.path not in PASSWORD_CHANGE_ALLOWED:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="비밀번호를 먼저 변경해야 한다",
        )
    return actor


def require_permission(permission: Permission) -> Callable[..., Actor]:
    def dependency(actor: Annotated[Actor, Depends(current_actor)]) -> Actor:
        if not actor.can(permission):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="권한이 없다")
        return actor

    return dependency


RequireRead = Annotated[Actor, Depends(require_permission(Permission.READ))]
RequireOperate = Annotated[Actor, Depends(require_permission(Permission.OPERATE))]
RequireConfigure = Annotated[Actor, Depends(require_permission(Permission.CONFIGURE))]
RequireAdmin = Annotated[Actor, Depends(require_permission(Permission.ADMINISTER))]
CurrentActor = Annotated[Actor, Depends(current_actor)]
