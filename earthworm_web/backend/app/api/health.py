from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..models.schemas import SettingsIn
from ..security import api_key_header
from ..services.app_store import load_app, save_app
from ..services.control import last_snapshot
from ..services.env import parsed_core
from ..services.ipc_diag import lock_info

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.get("/health/detail", dependencies=[Depends(api_key_header)])
def health_detail() -> dict:
    meta = load_app()
    try:
        env = parsed_core()
        env_ok = True
        err = None
    except Exception as exc:
        env = {}
        env_ok = False
        err = str(exc)
    snap = last_snapshot()
    lock = None
    try:
        lock = lock_info()
    except Exception:
        lock = None
    return {
        "status": "ok" if env_ok else "degraded",
        "setup_complete": meta.setup_complete,
        "ew_version": env.get("EW_VERSION"),
        "ew_home": env.get("EW_HOME"),
        "env_loaded": env_ok,
        "startstop_alive": bool(snap and snap.running) if snap else False,
        "lock": lock,
        "error": err,
    }


@router.get("/environment", dependencies=[Depends(api_key_header)])
def get_environment() -> dict:
    try:
        return parsed_core()
    except Exception as exc:
        raise HTTPException(503, str(exc)) from exc


@router.get("/settings", dependencies=[Depends(api_key_header)])
def get_settings() -> dict:
    meta = load_app()
    return {
        "status_interval_sec": meta.status_interval_sec,
        "sniff_session_limit": meta.sniff_session_limit,
        "log_retention_days": meta.log_retention_days,
        "setup_complete": meta.setup_complete,
    }


@router.put("/settings", dependencies=[Depends(api_key_header)])
def put_settings(body: SettingsIn) -> dict:
    meta = load_app()
    if body.status_interval_sec is not None:
        meta.status_interval_sec = float(body.status_interval_sec)
    if body.sniff_session_limit is not None:
        meta.sniff_session_limit = int(body.sniff_session_limit)
    if body.log_retention_days is not None:
        meta.log_retention_days = int(body.log_retention_days)
    save_app(meta)
    return get_settings()
