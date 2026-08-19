from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..security import api_key_header
from ..services.app_store import load_app
from ..services.control import (
    dashboard_payload,
    module_restart,
    module_stop,
    pause_earthworm,
    read_status,
    reconfigure,
    resume_earthworm,
    start_earthworm,
    stop_earthworm,
)

router = APIRouter(prefix="/api", tags=["control"], dependencies=[Depends(api_key_header)])


def require_setup() -> None:
    if not load_app().setup_complete:
        raise HTTPException(409, "초기 설정을 먼저 완료하세요")


def _wrap(exc: Exception) -> None:
    if isinstance(exc, RuntimeError):
        raise HTTPException(409, str(exc)) from exc
    raise HTTPException(400, str(exc)) from exc


@router.post("/control/start")
async def control_start(_: None = Depends(require_setup)) -> dict:
    try:
        return await start_earthworm()
    except Exception as exc:
        _wrap(exc)
        raise


@router.post("/control/stop")
async def control_stop(_: None = Depends(require_setup)) -> dict:
    try:
        return await stop_earthworm()
    except Exception as exc:
        _wrap(exc)
        raise


@router.post("/control/pause")
async def control_pause(_: None = Depends(require_setup)) -> dict:
    try:
        return await pause_earthworm()
    except Exception as exc:
        _wrap(exc)
        raise


@router.post("/control/resume")
async def control_resume(_: None = Depends(require_setup)) -> dict:
    try:
        return await resume_earthworm()
    except Exception as exc:
        _wrap(exc)
        raise


@router.post("/control/reconfigure")
async def control_reconfigure(_: None = Depends(require_setup)) -> dict:
    try:
        return await reconfigure()
    except Exception as exc:
        _wrap(exc)
        raise


@router.post("/control/modules/{module_id}/restart")
async def control_mod_restart(module_id: str, _: None = Depends(require_setup)) -> dict:
    try:
        return await module_restart(module_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except Exception as exc:
        _wrap(exc)
        raise


@router.post("/control/modules/{module_id}/stop")
async def control_mod_stop(module_id: str, _: None = Depends(require_setup)) -> dict:
    try:
        return await module_stop(module_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except Exception as exc:
        _wrap(exc)
        raise


@router.get("/status")
async def get_status() -> dict:
    snap = await read_status()
    return dashboard_payload(snap)
