from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .models import ADMIN_ROLE, STUB_ROLE, NrlAlias, NrlExcluded, User, hash_password

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
    _ensure_user(db, settings.stub_username, settings.stub_password, STUB_ROLE)
    _ensure_user(db, "stub2", "stub2", STUB_ROLE)
    if settings.dev_bootstrap_admin:
        _ensure_user(db, "admin", "admin", ADMIN_ROLE)
    seed_nrl_lookups(db)
    db.commit()


DEFAULT_ALIASES = (
    ("metrozet", "EQMet", ""),
    ("cme", "RSensors", ""),
    ("mark products", "Sercel", ""),
    ("daq systems", "NetDAS", ""),
)

DEFAULT_EXCLUDED = (
    (
        "certimus",
        "Certimus",
        "Certimus, Minimus, Fortimus는 장비별 교정값을 쓰므로 NRL에 없습니다. RESP 또는 교정 시트를 가져오세요.",
    ),
    (
        "minimus",
        "Minimus",
        "Certimus, Minimus, Fortimus는 장비별 교정값을 쓰므로 NRL에 없습니다. RESP 또는 교정 시트를 가져오세요.",
    ),
    (
        "fortimus",
        "Fortimus",
        "Certimus, Minimus, Fortimus는 장비별 교정값을 쓰므로 NRL에 없습니다. RESP 또는 교정 시트를 가져오세요.",
    ),
)


def seed_nrl_lookups(db: Session) -> None:
    for query, manufacturer, model in DEFAULT_ALIASES:
        if db.scalar(select(NrlAlias).where(NrlAlias.query == query)) is None:
            db.add(NrlAlias(query=query, manufacturer=manufacturer, model=model))
    for query, name, message in DEFAULT_EXCLUDED:
        if db.scalar(select(NrlExcluded).where(NrlExcluded.query == query)) is None:
            db.add(NrlExcluded(query=query, name=name, message=message))
    db.flush()
