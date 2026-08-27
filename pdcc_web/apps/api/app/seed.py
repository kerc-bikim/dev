from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .models import ADMIN_ROLE, STUB_ROLE, User, hash_password

log = logging.getLogger("pdcc.seed")


def _ensure_user(db: Session, username: str, password: str, role: str) -> User:
    user = db.scalar(select(User).where(User.username == username))
    if user is None:
        user = User(username=username, password_hash=hash_password(password), role=role)
        db.add(user)
        db.flush()
        log.info("seeded user %s role=%s", username, role)
    return user


def seed_users(db: Session) -> None:
    from .runtime import stub_login_allowed

    if stub_login_allowed():
        _ensure_user(db, settings.stub_username, settings.stub_password, STUB_ROLE)
        _ensure_user(db, "stub2", "stub2", STUB_ROLE)
    if settings.dev_bootstrap_admin:
        _ensure_user(db, "admin", "admin", ADMIN_ROLE)
    db.commit()
