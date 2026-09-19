"""사용자 관리. ADMIN 만 호출한다."""
from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select

from app.api import audit
from app.api.deps import RequireAdmin
from app.api.presenters import parse_uuid, user_payload
from app.api.schemas import UserCreateRequest, UserUpdateRequest
from app.auth.passwords import hash_password
from app.db.models import User, UserRole
from app.db.session import session_scope

router = APIRouter(prefix="/api/v1/users", tags=["users"])

USERNAME_RE = re.compile(r"^[A-Za-z0-9._-]{2,64}$")


@router.get("", summary="사용자 목록")
def list_users(actor: RequireAdmin) -> dict:
    with session_scope() as session:
        users = session.scalars(select(User).order_by(User.username)).all()
        return {"users": [user_payload(user) for user in users]}


@router.post("", status_code=status.HTTP_201_CREATED, summary="사용자 생성")
def create_user(body: UserCreateRequest, request: Request, actor: RequireAdmin) -> dict:
    if not USERNAME_RE.match(body.username):
        raise HTTPException(status_code=400, detail="사용자 이름 형식이 잘못됐다")
    try:
        role = UserRole(body.role)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"알 수 없는 역할: {body.role}") from exc

    with session_scope() as session:
        if session.scalar(select(User).where(User.username == body.username)):
            raise HTTPException(status_code=409, detail="이미 있는 사용자 이름이다")
        user = User(
            username=body.username,
            display_name=body.display_name,
            email=body.email,
            password_hash=hash_password(body.password),
            role=role,
            enabled=True,
            must_change_password=True,
        )
        session.add(user)
        session.flush()
        audit.record(
            session,
            actor=actor,
            action="create",
            entity_type="user",
            entity_id=str(user.id),
            after={"username": user.username, "role": user.role.value},
            request=request,
        )
        return {"user": user_payload(user)}


@router.put("/{user_id}", summary="사용자 수정")
def update_user(user_id: str, body: UserUpdateRequest, request: Request, actor: RequireAdmin) -> dict:
    identifier = parse_uuid(user_id, "사용자 식별자")
    with session_scope() as session:
        user = session.get(User, identifier)
        if user is None:
            raise HTTPException(status_code=404, detail="없는 사용자다")

        before = {"role": user.role.value, "enabled": user.enabled, "displayName": user.display_name}
        if body.display_name is not None:
            user.display_name = body.display_name
        if body.email is not None:
            user.email = body.email
        if body.enabled is not None:
            if user.id == actor.id and body.enabled is False:
                raise HTTPException(status_code=400, detail="자기 자신을 비활성할 수 없다")
            user.enabled = body.enabled
        if body.role is not None:
            try:
                new_role = UserRole(body.role)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=f"알 수 없는 역할: {body.role}") from exc
            if user.id == actor.id and new_role is not UserRole.ADMIN:
                raise HTTPException(status_code=400, detail="자기 자신의 관리 권한은 내릴 수 없다")
            user.role = new_role
        if body.password:
            user.password_hash = hash_password(body.password)
            user.must_change_password = True

        audit.record(
            session,
            actor=actor,
            action="update",
            entity_type="user",
            entity_id=str(user.id),
            before=before,
            after={"role": user.role.value, "enabled": user.enabled, "displayName": user.display_name},
            request=request,
        )
        return {"user": user_payload(user)}
