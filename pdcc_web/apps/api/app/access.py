from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .models import (
    ADMIN_ROLE,
    EDITOR_ROLE,
    ROLES,
    VIEWER_ROLE,
    Organization,
    Project,
    ProjectMember,
    User,
)


def is_admin(user: User) -> bool:
    return user.role == ADMIN_ROLE


def require_admin(user: User) -> User:
    if not is_admin(user):
        raise HTTPException(status_code=403, detail="관리자만 할 수 있습니다")
    return user


def require_creator(user: User) -> User:
    if user.role == VIEWER_ROLE:
        raise HTTPException(status_code=403, detail="조회자는 프로젝트를 만들 수 없습니다")
    return user


def normalize_role(role: str) -> str:
    value = (role or "").strip().lower()
    aliases = {"조회자": VIEWER_ROLE, "편집자": EDITOR_ROLE, "관리자": ADMIN_ROLE}
    value = aliases.get(value, value)
    if value not in ROLES:
        raise HTTPException(status_code=400, detail="역할은 조회자·편집자·관리자만 가능합니다")
    return value


def membership(db: Session, project_id: int, user_id: int) -> ProjectMember | None:
    return db.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user_id,
        )
    )


def project_role(db: Session, project: Project, user: User) -> str | None:
    mem = membership(db, project.id, user.id)
    if mem is not None:
        return mem.role
    if is_admin(user):
        return ADMIN_ROLE
    if project.owner_id == user.id:
        return user.role if user.role in ROLES else EDITOR_ROLE
    return None


def can_edit_role(role: str | None) -> bool:
    return role in (EDITOR_ROLE, ADMIN_ROLE)


def add_member(db: Session, project: Project, user: User, role: str) -> ProjectMember:
    role = normalize_role(role)
    row = membership(db, project.id, user.id)
    if row is None:
        row = ProjectMember(project_id=project.id, user_id=user.id, role=role)
        db.add(row)
        db.flush()
    else:
        row.role = role
    return row


def require_view(db: Session, project_id: int, user: User) -> Project:
    project = db.get(Project, project_id)
    if project is None or project_role(db, project, user) is None:
        raise HTTPException(status_code=404, detail="프로젝트가 없습니다")
    return project


def require_edit(db: Session, project_id: int, user: User) -> Project:
    project = require_view(db, project_id, user)
    if not can_edit_role(project_role(db, project, user)):
        raise HTTPException(status_code=403, detail="조회자는 편집할 수 없습니다")
    return project


def require_manage_members(db: Session, project_id: int, user: User) -> Project:
    project = require_view(db, project_id, user)
    role = project_role(db, project, user)
    if role != ADMIN_ROLE:
        raise HTTPException(status_code=403, detail="멤버는 관리자만 바꿀 수 있습니다")
    return project


def visible_projects(db: Session, user: User) -> list[Project]:
    query = select(Project).order_by(Project.updated_at.desc())
    if is_admin(user):
        return list(db.scalars(query).all())
    member_ids = select(ProjectMember.project_id).where(ProjectMember.user_id == user.id)
    query = query.where(or_(Project.owner_id == user.id, Project.id.in_(member_ids)))
    return list(db.scalars(query).all())


def org_of(db: Session, user: User) -> Organization | None:
    if user.org_id is None:
        return None
    return db.get(Organization, user.org_id)


def user_out(user: User, org: Organization | None = None) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name or user.username,
        "role": user.role,
        "active": bool(user.active),
        "org_id": user.org_id,
        "org_name": org.name if org is not None else None,
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }


def member_out(row: ProjectMember, user: User) -> dict:
    return {
        "user_id": user.id,
        "username": user.username,
        "display_name": user.display_name or user.username,
        "role": row.role,
        "active": bool(user.active),
    }
