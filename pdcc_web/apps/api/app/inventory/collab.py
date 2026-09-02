from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import EditUndo, Project, ProjectDraft, ProjectVersion, User, utcnow
from .xmlbuild import InventoryError, diff_fields, field_snapshot


def _iso(project: Project) -> str:
    return project.updated_at.isoformat() if project.updated_at else ""


def version_out(row: ProjectVersion) -> dict:
    return {
        "id": row.id,
        "number": row.number,
        "actor": row.actor,
        "action": row.action,
        "summary": row.summary,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def next_version_number(db: Session, project_id: int) -> int:
    last = db.scalars(
        select(ProjectVersion.number)
        .where(ProjectVersion.project_id == project_id)
        .order_by(ProjectVersion.number.desc())
    ).first()
    return int(last or 0) + 1


def record_edit(
    db: Session,
    project: Project,
    user: User,
    *,
    before: str,
    after: str,
    action: str,
    summary: str,
    undo: bool = True,
) -> ProjectVersion:
    version = ProjectVersion(
        project_id=project.id,
        number=next_version_number(db, project.id),
        actor=user.username,
        action=action,
        summary=summary,
        xml_text=after,
    )
    db.add(version)
    if undo and before != after:
        db.add(
            EditUndo(
                project_id=project.id,
                user_id=user.id,
                action=action,
                summary=summary,
                before_xml=before,
                after_xml=after,
            )
        )
        db.flush()
        extras = db.scalars(
            select(EditUndo)
            .where(EditUndo.project_id == project.id, EditUndo.user_id == user.id)
            .order_by(EditUndo.id.desc())
        ).all()
        for stale in extras[20:]:
            db.delete(stale)
    db.flush()
    return version


def latest_undo(db: Session, project_id: int, user_id: int) -> EditUndo | None:
    return db.scalars(
        select(EditUndo)
        .where(EditUndo.project_id == project_id, EditUndo.user_id == user_id)
        .order_by(EditUndo.id.desc())
    ).first()


def get_draft(db: Session, project_id: int, user_id: int) -> ProjectDraft | None:
    return db.scalar(
        select(ProjectDraft).where(
            ProjectDraft.project_id == project_id, ProjectDraft.user_id == user_id
        )
    )


def upsert_draft(db: Session, project: Project, user: User, xml_text: str) -> ProjectDraft:
    row = get_draft(db, project.id, user.id)
    if row is None:
        row = ProjectDraft(
            project_id=project.id,
            user_id=user.id,
            xml_text=xml_text,
            base_updated_at=_iso(project),
        )
        db.add(row)
    else:
        row.xml_text = xml_text
        row.updated_at = utcnow()
    db.flush()
    return row


def draft_conflict(project: Project, draft: ProjectDraft) -> bool:
    return bool(draft.base_updated_at) and draft.base_updated_at != _iso(project)


def conflict_fields(project: Project, draft: ProjectDraft) -> list[dict]:
    server = field_snapshot(project.xml_text, project.network_code, project.id)
    mine = field_snapshot(draft.xml_text, project.network_code, project.id)
    rows = diff_fields(server, mine)
    for row in rows:
        row["server"] = row.pop("a")
        row["mine"] = row.pop("b")
    return rows


def require_no_foreign_lock(project: Project, user: User) -> None:
    from .locks import lock_snapshot
    from .xmlbuild import list_inventory

    for sta in list_inventory(project.xml_text, project.network_code, project.id):
        snap = lock_snapshot(sta["station_path"])
        if snap and int(snap.get("user_id") or 0) != user.id:
            raise InventoryError(f"{snap.get('username')} 님이 수정 중입니다", 409)
