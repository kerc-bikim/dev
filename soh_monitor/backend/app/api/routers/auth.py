"""인증 엔드포인트."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlalchemy import select

from app.api.deps import CurrentActor
from app.api.presenters import user_payload
from app.api.schemas import LoginRequest, PasswordChangeRequest
from app.auth.passwords import hash_password, verify_password
from app.auth.sessions import COOKIE_NAME, SESSION_TTL_SECONDS, issue_session
from app.config.settings import get_settings
from app.db.models import User
from app.db.session import session_scope

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


def _cookie_kwargs() -> dict:
    settings = get_settings()
    return {
        "key": COOKIE_NAME,
        "httponly": True,
        "samesite": "lax",
        "secure": settings.is_production,
        "path": "/",
        "max_age": SESSION_TTL_SECONDS,
    }


@router.post("/login", summary="로그인")
def login(body: LoginRequest, response: Response) -> dict:
    settings = get_settings()
    secret = settings.session_signing_key()
    if settings.is_production and not settings.resolved_secret("session_secret"):
        raise HTTPException(status_code=500, detail="세션 서명 키가 설정되지 않았다")

    with session_scope() as session:
        user = session.scalar(select(User).where(User.username == body.username))
        if user is None or not user.enabled or not verify_password(body.password, user.password_hash):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="로그인 정보가 맞지 않는다")
        user.last_login_at = datetime.now(timezone.utc)
        token = issue_session(user.id, secret)
        payload = user_payload(user)

    response.set_cookie(value=token, **_cookie_kwargs())
    return {"user": payload}


@router.post("/logout", summary="로그아웃")
def logout(response: Response) -> dict:
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}


@router.get("/me", summary="현재 사용자")
def me(actor: CurrentActor) -> dict:
    with session_scope() as session:
        user = session.get(User, actor.id)
        if user is None:
            raise HTTPException(status_code=401, detail="로그인이 필요하다")
        return {"user": user_payload(user)}


@router.post("/change-password", summary="비밀번호 변경")
def change_password(body: PasswordChangeRequest, actor: CurrentActor) -> dict:
    if body.current_password == body.new_password:
        raise HTTPException(status_code=400, detail="새 비밀번호가 이전과 같다")

    with session_scope() as session:
        user = session.get(User, actor.id)
        if user is None:
            raise HTTPException(status_code=401, detail="로그인이 필요하다")
        if not verify_password(body.current_password, user.password_hash):
            raise HTTPException(status_code=400, detail="현재 비밀번호가 맞지 않는다")
        user.password_hash = hash_password(body.new_password)
        user.must_change_password = False
        return {"user": user_payload(user)}
