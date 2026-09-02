from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..access import (
    add_member,
    member_out,
    normalize_role,
    org_of,
    require_admin,
    user_out,
)
from ..dashboard import build_dashboard
from ..db import get_db
from ..inventory.service import write_audit
from ..models import Organization, Project, ProjectMember, User, hash_password
from ..routers.auth import current_user

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _admin(user: User = Depends(current_user)) -> User:
    return require_admin(user)


class OrgIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)


class UserIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)
    role: str = Field(min_length=1, max_length=32)
    display_name: str | None = Field(default=None, max_length=128)
    org_id: int | None = None


class PasswordIn(BaseModel):
    password: str = Field(min_length=1, max_length=128)


class RoleIn(BaseModel):
    role: str = Field(min_length=1, max_length=32)


class MemberIn(BaseModel):
    user_id: int
    role: str = Field(min_length=1, max_length=32)
    project_id: int


def _org_or_404(db: Session, org_id: int | None) -> Organization:
    if org_id is None:
        org = db.scalar(select(Organization).order_by(Organization.id.asc()))
        if org is None:
            raise HTTPException(status_code=400, detail="기관이 없습니다")
        return org
    org = db.get(Organization, org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="기관이 없습니다")
    return org


@router.get("/dashboard")
def admin_dashboard(db: Session = Depends(get_db), _admin: User = Depends(_admin)) -> dict:
    return build_dashboard(db)


@router.get("/orgs")
def list_orgs(db: Session = Depends(get_db), _admin: User = Depends(_admin)) -> dict:
    rows = db.scalars(select(Organization).order_by(Organization.name)).all()
    out = []
    for org in rows:
        users = db.scalars(select(User).where(User.org_id == org.id)).all()
        out.append(
            {
                "id": org.id,
                "name": org.name,
                "user_count": len(users),
                "created_at": org.created_at.isoformat() if org.created_at else None,
            }
        )
    return {"orgs": out}


@router.post("/orgs")
def create_org(
    body: OrgIn, db: Session = Depends(get_db), admin: User = Depends(_admin)
) -> dict:
    name = body.name.strip()
    if db.scalar(select(Organization).where(Organization.name == name)) is not None:
        raise HTTPException(status_code=409, detail="같은 이름의 기관이 있습니다")
    org = Organization(name=name)
    db.add(org)
    db.flush()
    write_audit(
        db,
        project_id=None,
        actor=admin.username,
        action="org_create",
        target=name,
        summary=f"기관 생성 {name}",
    )
    db.commit()
    db.refresh(org)
    return {
        "id": org.id,
        "name": org.name,
        "user_count": 0,
        "created_at": org.created_at.isoformat() if org.created_at else None,
    }


@router.get("/users")
def list_users(db: Session = Depends(get_db), _admin: User = Depends(_admin)) -> dict:
    rows = db.scalars(select(User).order_by(User.username)).all()
    orgs = {org.id: org for org in db.scalars(select(Organization)).all()}
    return {"users": [user_out(row, orgs.get(row.org_id) if row.org_id else None) for row in rows]}


@router.post("/users")
def create_user(
    body: UserIn, db: Session = Depends(get_db), admin: User = Depends(_admin)
) -> dict:
    username = body.username.strip()
    if db.scalar(select(User).where(User.username == username)) is not None:
        raise HTTPException(status_code=409, detail="같은 아이디가 있습니다")
    role = normalize_role(body.role)
    org = _org_or_404(db, body.org_id)
    user = User(
        username=username,
        display_name=(body.display_name or "").strip() or username,
        password_hash=hash_password(body.password),
        role=role,
        active=True,
        org_id=org.id,
    )
    db.add(user)
    db.flush()
    write_audit(
        db,
        project_id=None,
        actor=admin.username,
        action="user_create",
        target=username,
        summary=f"{username} {role} 생성",
    )
    db.commit()
    db.refresh(user)
    return user_out(user, org)


@router.post("/users/{user_id}/deactivate")
def deactivate_user(
    user_id: int, db: Session = Depends(get_db), admin: User = Depends(_admin)
) -> dict:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="사용자가 없습니다")
    if user.id == admin.id:
        raise HTTPException(status_code=400, detail="자기 자신은 비활성할 수 없습니다")
    user.active = False
    write_audit(
        db,
        project_id=None,
        actor=admin.username,
        action="user_deactivate",
        target=user.username,
        summary=f"{user.username} 비활성",
    )
    db.commit()
    db.refresh(user)
    return user_out(user, org_of(db, user))


@router.post("/users/{user_id}/activate")
def activate_user(
    user_id: int, db: Session = Depends(get_db), admin: User = Depends(_admin)
) -> dict:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="사용자가 없습니다")
    user.active = True
    write_audit(
        db,
        project_id=None,
        actor=admin.username,
        action="user_activate",
        target=user.username,
        summary=f"{user.username} 활성",
    )
    db.commit()
    db.refresh(user)
    return user_out(user, org_of(db, user))


@router.post("/users/{user_id}/password")
def reset_password(
    user_id: int,
    body: PasswordIn,
    db: Session = Depends(get_db),
    admin: User = Depends(_admin),
) -> dict:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="사용자가 없습니다")
    user.password_hash = hash_password(body.password)
    write_audit(
        db,
        project_id=None,
        actor=admin.username,
        action="user_password",
        target=user.username,
        summary=f"{user.username} 비밀번호 재설정",
    )
    db.commit()
    return {"ok": True, "username": user.username}


@router.post("/users/{user_id}/role")
def set_role(
    user_id: int,
    body: RoleIn,
    db: Session = Depends(get_db),
    admin: User = Depends(_admin),
) -> dict:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="사용자가 없습니다")
    user.role = normalize_role(body.role)
    write_audit(
        db,
        project_id=None,
        actor=admin.username,
        action="user_role",
        target=user.username,
        summary=f"{user.username} 역할 {user.role}",
    )
    db.commit()
    db.refresh(user)
    return user_out(user, org_of(db, user))


@router.get("/projects/{project_id}/members")
def admin_list_members(
    project_id: int, db: Session = Depends(get_db), _admin: User = Depends(_admin)
) -> dict:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="프로젝트가 없습니다")
    rows = db.scalars(
        select(ProjectMember).where(ProjectMember.project_id == project.id)
    ).all()
    users = {row.id: row for row in db.scalars(select(User)).all()}
    return {
        "project_id": project.id,
        "members": [member_out(row, users[row.user_id]) for row in rows if row.user_id in users],
    }


@router.put("/members")
def admin_put_member(
    body: MemberIn, db: Session = Depends(get_db), admin: User = Depends(_admin)
) -> dict:
    project = db.get(Project, body.project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="프로젝트가 없습니다")
    user = db.get(User, body.user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="사용자가 없습니다")
    row = add_member(db, project, user, body.role)
    write_audit(
        db,
        project_id=project.id,
        actor=admin.username,
        action="member",
        target=user.username,
        summary=f"{user.username} 멤버 {row.role}",
    )
    db.commit()
    return member_out(row, user)
