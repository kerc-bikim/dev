from __future__ import annotations

from fastapi import HTTPException, Request

from .config import settings
from .services.auth import Actor, actor_from_api_key, actor_from_session, consume_ws_ticket

OPEN_PATHS = {
    "/api/health",
    "/api/auth/login",
    "/api/auth/bootstrap",
    "/api/auth/status",
}

VIEWER_WRITE_ALLOW = {
    ("POST", "/api/auth/logout"),
    ("POST", "/api/auth/password"),
    ("POST", "/api/auth/ws-ticket"),
}

SESSION_COOKIE = None  # resolved from settings at request time


def cookie_name() -> str:
    return settings.SESSION_COOKIE or "ew_session"


def request_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def actor_from_request(request: Request) -> Actor | None:
    token = request.cookies.get(cookie_name())
    actor = actor_from_session(token)
    if actor:
        return actor
    # HTTP: header only. Query ?key= 는 사람·서비스 모두 거부(비밀번호 유출 경로).
    key = request.headers.get("X-API-Key")
    return actor_from_api_key(key)


def ws_actor(ticket: str | None, key: str | None) -> Actor | None:
    actor = consume_ws_ticket(ticket)
    if actor:
        return actor
    return actor_from_api_key(key)


def require_actor(request: Request) -> Actor:
    actor = getattr(request.state, "actor", None)
    if actor is None:
        actor = actor_from_request(request)
        request.state.actor = actor
    if actor is None:
        expected = (settings.API_KEY or "").strip()
        if not expected and not request.cookies.get(cookie_name()):
            # 키도 세션도 없음. 빈 키는 서비스 계정을 쓰지 않는다는 뜻이지 503이 아님.
            raise HTTPException(401, "로그인이 필요합니다")
        raise HTTPException(401, "로그인이 필요합니다")
    return actor


def require_roles(*roles: str):
    def _dep(request: Request) -> Actor:
        actor = require_actor(request)
        if actor.role not in roles:
            raise HTTPException(403, "권한이 없습니다")
        return actor

    return _dep


def require_admin(request: Request) -> Actor:
    return require_roles("admin")(request)


def require_operator(request: Request) -> Actor:
    return require_roles("admin", "operator")(request)


# 기존 라우터 호환: 미들웨어가 이미 인증했다면 통과.
def api_key_header(request: Request) -> Actor:
    return require_actor(request)
