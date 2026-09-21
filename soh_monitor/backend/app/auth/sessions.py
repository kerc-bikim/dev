"""관리 UI 세션.

서버가 HMAC 으로 서명한 쿠키만 믿는다. 세션 저장소를 따로 두지 않는 이유는
API 프로세스를 여러 대 띄워도 공유 상태가 필요 없기 때문이다.

토큰 형식
    <payload-b64url>.<hmac-sha256-hex>

payload 는 `user_id:expires_unix` 이다. 비밀값은 넣지 않는다.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import time
import uuid
from dataclasses import dataclass

COOKIE_NAME = "soh_session"
SESSION_TTL_SECONDS = 12 * 60 * 60


class SessionError(ValueError):
    """쿠키가 없거나 서명이 맞지 않거나 만료됐다."""


@dataclass(frozen=True)
class SessionClaims:
    user_id: uuid.UUID
    expires_at: int


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64url_decode(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


def issue_session(user_id: uuid.UUID, secret: str, *, now: int | None = None) -> str:
    if not secret:
        raise SessionError("세션 서명 키가 비어 있다")
    issued_at = int(now if now is not None else time.time())
    expires_at = issued_at + SESSION_TTL_SECONDS
    payload = f"{user_id}:{expires_at}".encode("utf-8")
    body = _b64url(payload)
    signature = hmac.new(secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{body}.{signature}"


def verify_session(token: str | None, secret: str, *, now: int | None = None) -> SessionClaims:
    if not token or "." not in token:
        raise SessionError("세션이 없다")
    if not secret:
        raise SessionError("세션 서명 키가 비어 있다")

    body, _, signature = token.partition(".")
    expected = hmac.new(secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise SessionError("세션 서명이 맞지 않는다")

    try:
        payload = _b64url_decode(body).decode("utf-8")
        user_raw, _, expires_raw = payload.partition(":")
        user_id = uuid.UUID(user_raw)
        expires_at = int(expires_raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise SessionError("세션 내용이 깨졌다") from exc

    current = int(now if now is not None else time.time())
    if expires_at <= current:
        raise SessionError("세션이 만료됐다")
    return SessionClaims(user_id=user_id, expires_at=expires_at)
