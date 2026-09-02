from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..cache import get_redis, session_key
from ..config import settings
from ..db import get_db
from ..models import User, new_session_token, verify_password
from ..runtime import STUB_USERNAMES, cookie_samesite, cookie_secure, stub_login_allowed

router = APIRouter(prefix="/api", tags=["auth"])


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class UserOut(BaseModel):
    username: str
    role: str


def _set_session_cookie(response: Response, token: str) -> None:
    samesite: Literal["lax", "strict", "none"] = cookie_samesite()  # type: ignore[assignment]
    if samesite not in ("lax", "strict", "none"):
        samesite = "lax"
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        max_age=settings.session_ttl_sec,
        httponly=True,
        secure=cookie_secure(),
        samesite=samesite,
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
    return user


@router.post("/login", response_model=UserOut)
def login(body: LoginIn, response: Response, db: Session = Depends(get_db)) -> UserOut:
    if body.username in STUB_USERNAMES and not stub_login_allowed():
        raise HTTPException(
            status_code=403,
            detail="스텁 로그인은 이 환경에서 꺼져 있습니다 (ALLOW_STUB_LOGIN)",
        )
    if body.username == "admin" and not settings.dev_bootstrap_admin:
        raise HTTPException(
            status_code=403,
            detail="관리자 부트스트랩이 꺼져 있습니다 (DEV_BOOTSTRAP_ADMIN)",
        )
    user = db.scalar(select(User).where(User.username == body.username))
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="아이디 또는 비밀번호가 올바르지 않습니다")
    token = new_session_token()
    get_redis().set(session_key(token), str(user.id), ex=settings.session_ttl_sec)
    _set_session_cookie(response, token)
    return UserOut(username=user.username, role=user.role)


@router.post("/logout")
def logout(request: Request, response: Response) -> dict:
    token = request.cookies.get(settings.session_cookie_name)
    if token:
        get_redis().delete(session_key(token))
    _clear_session_cookie(response)
    return {"ok": True}


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user)) -> UserOut:
    return UserOut(username=user.username, role=user.role)
