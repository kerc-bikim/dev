from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..access import org_of, user_out
from ..cache import get_redis, session_key
from ..config import settings
from ..db import get_db
from ..models import User, new_session_token, verify_password
from ..notices import ack_notice, list_notices

router = APIRouter(prefix="/api", tags=["auth"])


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class UserOut(BaseModel):
    username: str
    role: str
    display_name: str
    active: bool
    org_id: int | None = None
    org_name: str | None = None


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        max_age=settings.session_ttl_sec,
        httponly=True,
        samesite="lax",
        path="/",
    )


def _clear_session_cookie(response: Response) -> None:
    response.delete_cookie(settings.session_cookie_name, path="/")


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get(settings.session_cookie_name)
    if not token:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다")
    raw = get_redis().get(session_key(token))
    if not raw:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다")
    user = db.get(User, int(raw))
    if user is None:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다")
    if not user.active:
        raise HTTPException(status_code=401, detail="비활성 계정입니다")
    return user


def _as_out(db: Session, user: User) -> UserOut:
    data = user_out(user, org_of(db, user))
    return UserOut(
        username=data["username"],
        role=data["role"],
        display_name=data["display_name"],
        active=data["active"],
        org_id=data["org_id"],
        org_name=data["org_name"],
    )


@router.post("/login", response_model=UserOut)
def login(body: LoginIn, response: Response, db: Session = Depends(get_db)) -> UserOut:
    if body.username == "admin" and not settings.dev_bootstrap_admin:
        raise HTTPException(
            status_code=403,
            detail="관리자 부트스트랩이 꺼져 있습니다 (DEV_BOOTSTRAP_ADMIN)",
        )
    user = db.scalar(select(User).where(User.username == body.username))
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="아이디 또는 비밀번호가 올바르지 않습니다")
    if not user.active:
        raise HTTPException(status_code=401, detail="비활성 계정입니다")
    token = new_session_token()
    get_redis().set(session_key(token), str(user.id), ex=settings.session_ttl_sec)
    _set_session_cookie(response, token)
    return _as_out(db, user)


@router.post("/logout")
def logout(request: Request, response: Response) -> dict:
    token = request.cookies.get(settings.session_cookie_name)
    if token:
        get_redis().delete(session_key(token))
    _clear_session_cookie(response)
    return {"ok": True}


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user), db: Session = Depends(get_db)) -> UserOut:
    return _as_out(db, user)


@router.get("/notices")
def get_notices(user: User = Depends(current_user)) -> dict:
    return {"notices": list_notices(user.id)}


@router.post("/notices/{notice_id}/ack")
def post_ack_notice(notice_id: str, user: User = Depends(current_user)) -> dict:
    ack_notice(user.id, notice_id)
    return {"ok": True, "notices": list_notices(user.id)}
