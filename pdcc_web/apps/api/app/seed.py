from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from .access import EDITOR_ROLE, add_member, membership
from .config import settings
from .models import (
    ADMIN_ROLE,
    ROLES,
    STUB_ROLE,
    NrlAlias,
    NrlExcluded,
    Organization,
    Project,
    User,
    hash_password,
)

log = logging.getLogger("pdcc.seed")

DEFAULT_ORG = "기본 기관"


def _ensure_org(db: Session, name: str = DEFAULT_ORG) -> Organization:
    org = db.scalar(select(Organization).where(Organization.name == name))
    if org is None:
        org = Organization(name=name)
        db.add(org)
        db.flush()
        log.info("seeded organization %s", name)
    return org


def _ensure_user(db: Session, username: str, password: str, role: str, org: Organization) -> User:
    user = db.scalar(select(User).where(User.username == username))
    if user is None:
        user = User(
            username=username,
            display_name=username,
            password_hash=hash_password(password),
            role=role,
            active=True,
            org_id=org.id,
        )
        db.add(user)
        db.flush()
        log.info("seeded user %s role=%s", username, role)
        return user
    if user.org_id is None:
        user.org_id = org.id
    if not user.display_name:
        user.display_name = username
    return user


def seed_project_owners(db: Session) -> None:
    for project in db.scalars(select(Project)).all():
        owner = db.get(User, project.owner_id)
        if owner is None:
            continue
        if membership(db, project.id, owner.id) is not None:
            continue
        role = owner.role if owner.role in ROLES else EDITOR_ROLE
        add_member(db, project, owner, role)


def seed_users(db: Session) -> None:
    org = _ensure_org(db)
    _ensure_user(db, settings.stub_username, settings.stub_password, STUB_ROLE, org)
    _ensure_user(db, "stub2", "stub2", STUB_ROLE, org)
    if settings.dev_bootstrap_admin:
        _ensure_user(db, "admin", "admin", ADMIN_ROLE, org)
    seed_nrl_lookups(db)
    seed_project_owners(db)
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
