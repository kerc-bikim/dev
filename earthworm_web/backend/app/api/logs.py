from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from ..models.schemas import LogSettingsIn, SniffIn, UnlockIn
from ..security import api_key_header
from ..services.app_store import load_app
from ..services.earthworm_d import parse_earthworm_d
from ..services.env import parsed_core
from ..services.ipc_diag import ipc_summary, lock_info, unlock
from ..services.log_store import list_logs, preview_sweep, read_log, sweep_logs, update_log_settings
from ..services.sniff_broker import start_session, stop_session
from ..services.startstop_file import parse_startstop

router = APIRouter(prefix="/api", tags=["ops"], dependencies=[Depends(api_key_header)])


def require_setup() -> None:
    if not load_app().setup_complete:
        raise HTTPException(409, "초기 설정을 먼저 완료하세요")


@router.get("/logs/settings")
def get_log_settings() -> dict:
    env = parsed_core()
    meta = load_app()
    return {"directory": env.get("EW_LOG"), "retention_days": meta.log_retention_days}


@router.put("/logs/settings")
def put_log_settings(body: LogSettingsIn, _: None = Depends(require_setup)) -> dict:
    try:
        return update_log_settings(body.directory, body.retention_days)
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/logs")
def get_logs() -> dict:
    return {"modules": list_logs()}


@router.get("/logs/content")
def get_log_content(
    file: str = Query(...),
    date: str | None = Query(default=None),
    tail: int = Query(default=200, ge=1, le=5000),
) -> dict:
    try:
        return read_log(file, date, tail)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/logs/sweep")
def post_sweep(preview: bool = Query(default=False), _: None = Depends(require_setup)) -> dict:
    if preview:
        return {"would_delete": preview_sweep()}
    return {"deleted": sweep_logs()}


@router.get("/rings")
def get_rings() -> dict:
    env = parsed_core()
    params = __import__("pathlib").Path(env["EW_PARAMS"])
    names = []
    ss = params / "startstop_unix.d"
    if ss.is_file():
        doc = parse_startstop(ss.read_text(encoding="utf-8", errors="replace"))
        for n, size, on in doc.rings:
            if on and n != "FLAG_RING":
                names.append({"name": n, "size": size, "in_startstop": True})
    ew = params / "earthworm.d"
    if ew.is_file():
        table = parse_earthworm_d(ew.read_text(encoding="utf-8", errors="replace"))
        have = {r["name"] for r in names}
        for n, key, on in table.rings():
            if on and n != "FLAG_RING" and n not in have:
                names.append({"name": n, "key": key, "in_startstop": False})
    return {"rings": names}


@router.post("/sniff/sessions")
async def post_sniff(body: SniffIn, _: None = Depends(require_setup)) -> dict:
    try:
        sess = await start_session(body.model_dump())
        return {"session_id": sess.id, "tool": sess.tool, "argv": sess.argv[1:]}
    except Exception as exc:
        raise HTTPException(409 if "상한" in str(exc) else 400, str(exc)) from exc


@router.delete("/sniff/sessions/{session_id}")
async def delete_sniff(session_id: str, _: None = Depends(require_setup)) -> dict:
    await stop_session(session_id)
    return {"stopped": session_id}


@router.get("/diagnostics/lock")
def get_lock() -> dict:
    return lock_info()


@router.post("/diagnostics/lock/unlock")
def post_unlock(body: UnlockIn, _: None = Depends(require_setup)) -> dict:
    if not body.confirm:
        raise HTTPException(400, "confirm=true 가 필요합니다")
    try:
        return unlock(force=body.force)
    except PermissionError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/diagnostics/ipc")
def get_ipc() -> dict:
    return ipc_summary()
