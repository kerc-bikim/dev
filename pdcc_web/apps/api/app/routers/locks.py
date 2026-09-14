from __future__ import annotations

from typing import NoReturn

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import get_db
from ..inventory.locks import LockError, heartbeat_lock, release_lock
from ..inventory.service import write_audit
from ..models import User
from ..routers.auth import current_user

router = APIRouter(prefix="/api/locks", tags=["locks"])


def _http(exc: LockError) -> NoReturn:
    raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


class HeartbeatIn(BaseModel):
    station_path: str = Field(min_length=1, max_length=160)


@router.post("/heartbeat")
def post_heartbeat(
    body: HeartbeatIn, db: Session = Depends(get_db), user: User = Depends(current_user)
) -> dict:
    try:
        lock = heartbeat_lock(db, body.station_path, user)
        db.commit()
    except LockError as exc:
        db.rollback()
        _http(exc)
    return lock


@router.delete("")
def delete_lock(
    station_path: str = Query(min_length=1),
    force: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    try:
        release_lock(db, station_path, user, force=force)
        if force:
            write_audit(
                db,
                project_id=None,
                actor=user.username,
                action="unlock",
                target=station_path,
                summary="잠금 강제 해제" if user.role == "admin" else "잠금 해제",
            )
        db.commit()
    except LockError as exc:
        db.rollback()
        _http(exc)
    return {"ok": True, "station_path": station_path}
