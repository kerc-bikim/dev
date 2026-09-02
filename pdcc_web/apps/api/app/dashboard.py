"""M4 관리자 대시보드. NRL·작업·디스크·백업 상태를 한 화면에 모은다."""

from __future__ import annotations

import os
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .cache import get_redis
from .config import settings
from .jobs.service import job_out
from .monitoring import api_5xx_snapshot
from .models import FileAsset, Job, Project, StationLock, User, utcnow
from .nrl.client import nrl_snapshot_from_redis

LONG_LOCK_SEC = 10 * 60
EXPORT_JOB_KINDS = ("dataless", "resp")
ORIGINAL_KIND = "original"
EXPORT_KIND = "job_export"
DISK_WARN_PERCENT = 90.0
BACKUP_MARKER_NAME = "backup-last-success"


def _as_aware(value):
    if value is None:
        return None
    if value.tzinfo is None:
        from datetime import timezone

        return value.replace(tzinfo=timezone.utc)
    return value


def _asset_bytes(db: Session, kind: str) -> int:
    stmt = select(func.coalesce(func.sum(func.length(FileAsset.content)), 0)).where(
        FileAsset.kind == kind
    )
    try:
        return int(db.scalar(stmt) or 0)
    except Exception:
        total = 0
        for row in db.scalars(select(FileAsset).where(FileAsset.kind == kind)).all():
            total += len(row.content or b"")
        return total


def _nrl_zip_bytes(cache_bytes: int) -> int:
    path = (settings.nrl_offline_zip or "").strip()
    if path:
        try:
            if os.path.isfile(path):
                return int(os.path.getsize(path))
        except OSError:
            pass
    return 0 if cache_bytes < 0 else cache_bytes


def _disk_usage() -> dict:
    root = (settings.data_dir or ".").strip() or "."
    try:
        usage = shutil.disk_usage(root)
    except OSError:
        usage = shutil.disk_usage(".")
    total = int(usage.total)
    used = int(usage.used)
    percent = (used / total * 100.0) if total else 0.0
    return {
        "path": str(Path(root).resolve()) if root else ".",
        "used_bytes": used,
        "total_bytes": total,
        "free_bytes": int(usage.free),
        "percent": round(percent, 1),
        "over_90": percent >= DISK_WARN_PERCENT,
    }


def _backup_status() -> dict:
    configured = (settings.backup_status_file or "").strip()
    marker = Path(configured) if configured else Path(settings.data_dir or ".") / BACKUP_MARKER_NAME
    try:
        raw = marker.read_text(encoding="utf-8").strip()
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return {
            "last_success_at": parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "confirmed": True,
        }
    except (OSError, UnicodeError, ValueError):
        return {"last_success_at": None, "confirmed": False}


def _failed_jobs(db: Session) -> list[dict]:
    rows = db.scalars(
        select(Job)
        .where(Job.status == "failed")
        .order_by(Job.finished_at.desc(), Job.created_at.desc())
        .limit(10)
    ).all()
    return [job_out(row) for row in rows]


def _worker_failure_snapshot(db: Session, failed: list[dict]) -> dict:
    count = int(
        db.scalar(
            select(func.count()).select_from(Job).where(Job.status == "failed")
        )
        or 0
    )
    latest = failed[0] if failed else {}
    return {
        "count": count,
        "last_at": latest.get("finished_at") or latest.get("created_at"),
        "last_job_id": latest.get("id"),
    }


def _alerts(api_5xx: dict, worker: dict, nrl: dict) -> list[dict]:
    alerts: list[dict] = []
    if api_5xx["count"] > 0:
        alerts.append(
            {
                "kind": "api_5xx",
                "title": "API 5xx",
                "message": (
                    f"최근 {api_5xx['window_sec'] // 60}분 동안 "
                    f"{api_5xx['count']}건"
                ),
                "count": api_5xx["count"],
                "last_at": api_5xx["last_at"],
            }
        )
    if worker["count"] > 0:
        alerts.append(
            {
                "kind": "worker_failure",
                "title": "Worker 작업 실패",
                "message": f"실패 상태 작업 {worker['count']}건",
                "count": worker["count"],
                "last_at": worker["last_at"],
            }
        )
    if nrl["consecutive_failures"] >= nrl["threshold"]:
        alerts.append(
            {
                "kind": "nrl_consecutive_failure",
                "title": "NRL 연속 실패",
                "message": (
                    f"NRL 실시간 요청이 {nrl['consecutive_failures']}회 "
                    "연속 실패했습니다"
                ),
                "count": nrl["consecutive_failures"],
                "last_at": nrl["last_failed_at"],
            }
        )
    return alerts


def _long_locks(db: Session) -> list[dict]:
    now = utcnow()
    threshold = now + timedelta(seconds=LONG_LOCK_SEC)
    rows = db.scalars(
        select(StationLock)
        .where(StationLock.expires_at >= threshold)
        .order_by(StationLock.expires_at.desc())
    ).all()
    out: list[dict] = []
    for row in rows:
        expires = _as_aware(row.expires_at)
        remaining = int((expires - now).total_seconds()) if expires else 0
        if remaining < LONG_LOCK_SEC:
            continue
        out.append(
            {
                "station_path": row.station_path,
                "project_id": row.project_id,
                "username": row.username,
                "expires_at": expires.isoformat() if expires else None,
                "remaining_sec": remaining,
            }
        )
    return out


def _export_count_today(db: Session) -> int:
    start = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    return int(
        db.scalar(
            select(func.count())
            .select_from(Job)
            .where(Job.kind.in_(EXPORT_JOB_KINDS), Job.created_at >= start)
        )
        or 0
    )


def build_dashboard(db: Session) -> dict:
    redis = get_redis()
    nrl = nrl_snapshot_from_redis(redis)
    originals = _asset_bytes(db, ORIGINAL_KIND)
    exports = _asset_bytes(db, EXPORT_KIND)
    nrl_zip = _nrl_zip_bytes(int(nrl.get("cache_bytes") or 0))
    disk = _disk_usage()
    failed = _failed_jobs(db)
    worker = _worker_failure_snapshot(db, failed)
    api_5xx = api_5xx_snapshot(
        redis,
        window_sec=max(1, settings.monitor_api_5xx_window_sec),
    )
    nrl_down = nrl.get("source") == "offline"
    badges = {
        "api_5xx": api_5xx["count"] > 0,
        "nrl": nrl_down
        or nrl["consecutive_failures"] >= nrl["threshold"],
        "failed_jobs": worker["count"] > 0,
        "disk": bool(disk["over_90"]),
    }
    return {
        "user_count": int(db.scalar(select(func.count()).select_from(User)) or 0),
        "project_count": int(db.scalar(select(func.count()).select_from(Project)) or 0),
        "export_count_today": _export_count_today(db),
        "nrl": nrl,
        "failed_jobs": failed,
        "locks": _long_locks(db),
        "disk": {
            **disk,
            "originals_bytes": originals,
            "exports_bytes": exports,
            "nrl_zip_bytes": nrl_zip,
        },
        "backup": _backup_status(),
        "monitoring": {
            "api_5xx": api_5xx,
            "worker_failures": worker,
            "nrl": {
                "consecutive_failures": nrl["consecutive_failures"],
                "threshold": nrl["threshold"],
                "last_failed_at": nrl["last_failed_at"],
            },
        },
        "alerts": _alerts(api_5xx, worker, nrl),
        "badges": badges,
    }
