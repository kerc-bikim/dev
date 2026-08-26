from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base

PBKDF2_ITERS = 120_000
STUB_ROLE = "editor"
ADMIN_ROLE = "admin"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def hash_password(plain: str, *, salt: bytes | None = None) -> str:
    salt = salt or os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", plain.encode("utf-8"), salt, PBKDF2_ITERS)
    return f"pbkdf2${PBKDF2_ITERS}${salt.hex()}${digest.hex()}"


def verify_password(plain: str, stored: str) -> bool:
    try:
        scheme, iters_s, salt_hex, digest_hex = stored.split("$", 3)
    except ValueError:
        return False
    if scheme != "pbkdf2":
        return False
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        plain.encode("utf-8"),
        bytes.fromhex(salt_hex),
        int(iters_s),
    )
    return hmac.compare_digest(digest.hex(), digest_hex)


class User(Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("username", name="uq_users_username"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default=STUB_ROLE)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


def new_session_token() -> str:
    return secrets.token_urlsafe(32)
