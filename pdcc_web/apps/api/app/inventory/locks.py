from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..cache import get_redis
from ..config import settings
from ..models import StationLock, User, utcnow

LOCK_PREFIX = "pdcc:lock:"


class LockError(Exception):
    def __init__(self, message: str, status_code: int = 409, payload: dict | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload or {}


def _key(station_path: str) -> str:
    return f"{LOCK_PREFIX}{station_path}"


def _ttl() -> int:
    return max(int(settings.lock_ttl_sec), 30)


def _now() -> datetime:
    return utcnow()


def lock_snapshot(station_path: str) -> dict | None:
    raw = get_redis().get(_key(station_path))
    if not raw:
        return None
    data = json.loads(raw)
    data["station_path"] = station_path
    return data


def acquire_lock(
    db: Session,
    *,
    project_id: int,
    station_path: str,
    user: User,
) -> dict:
    redis = get_redis()
    current = lock_snapshot(station_path)
    if current and int(current["user_id"]) != user.id:
        raise LockError(
            f"{current.get('username')} 님이 수정 중입니다",
            409,
            {
                "holder": current.get("username"),
                "station_path": station_path,
                "expires_at": current.get("expires_at"),
                "mine": False,
            },
        )
    expires = _now() + timedelta(seconds=_ttl())
    payload = {
        "user_id": user.id,
        "username": user.username,
        "project_id": project_id,
        "heartbeat_at": _now().isoformat(),
        "expires_at": expires.isoformat(),
    }
    redis.set(_key(station_path), json.dumps(payload), ex=_ttl())
    row = db.get(StationLock, station_path)
    if row is None:
        row = StationLock(
            station_path=station_path,
            project_id=project_id,
            user_id=user.id,
            username=user.username,
            expires_at=expires,
            heartbeat_at=_now(),
        )
        db.add(row)
    else:
        row.project_id = project_id
        row.user_id = user.id
        row.username = user.username
        row.expires_at = expires
        row.heartbeat_at = _now()
    db.flush()
    payload["station_path"] = station_path
    payload["mine"] = True
    return payload


def heartbeat_lock(db: Session, station_path: str, user: User) -> dict:
    current = lock_snapshot(station_path)
    if current is None:
        raise LockError("잠금이 없습니다", 404)
    if int(current["user_id"]) != user.id:
        raise LockError(
            f"{current.get('username')} 님이 수정 중입니다",
            409,
            {"holder": current.get("username"), "mine": False},
        )
    return acquire_lock(
        db,
        project_id=int(current["project_id"]),
        station_path=station_path,
        user=user,
    )


def require_lock(station_path: str, user: User) -> dict:
    current = lock_snapshot(station_path)
    if current is None:
        raise LockError("관측소 잠금이 필요합니다", 409)
    if int(current["user_id"]) != user.id:
        raise LockError(
            f"{current.get('username')} 님이 수정 중입니다",
            409,
            {
                "holder": current.get("username"),
                "station_path": station_path,
                "expires_at": current.get("expires_at"),
                "mine": False,
            },
        )
    return current


def release_lock(
    db: Session,
    station_path: str,
    user: User,
    *,
    force: bool = False,
) -> None:
    current = lock_snapshot(station_path)
    if current is None:
        row = db.get(StationLock, station_path)
        if row is not None:
            db.delete(row)
        return
    if int(current["user_id"]) != user.id and not (force and user.role == "admin"):
        raise LockError("이 잠금을 해제할 수 없습니다", 403)
    get_redis().delete(_key(station_path))
    row = db.get(StationLock, station_path)
    if row is not None:
        db.delete(row)


def project_locks(db: Session, project_id: int) -> list[dict]:
    rows = db.scalars(select(StationLock).where(StationLock.project_id == project_id)).all()
    out: list[dict] = []
    now = _now()
    for row in rows:
        live = lock_snapshot(row.station_path)
        if live is None:
            if row.expires_at.replace(tzinfo=timezone.utc) < now:
                db.delete(row)
            continue
        live["mine"] = None
        out.append(live)
    return out
