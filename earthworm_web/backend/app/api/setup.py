from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..security import api_key_header
from ..models.schemas import DirectoriesIn, InstallationIn, RingsIn
from ..services.app_store import load_app
from ..services import setup_wizard as wiz

router = APIRouter(prefix="/api/setup", tags=["setup"], dependencies=[Depends(api_key_header)])


def _http(exc: Exception, code: int = 400) -> None:
    raise HTTPException(status_code=code, detail=str(exc)) from exc


@router.get("/status")
def setup_status() -> dict:
    return wiz.setup_status()


@router.get("/defaults")
def setup_defaults() -> dict:
    try:
        return wiz.setup_defaults()
    except Exception as exc:
        _http(exc, 503)


@router.put("/directories")
def put_directories(body: DirectoriesIn) -> dict:
    try:
        return wiz.set_directories(body.EW_HOME, body.EW_VERSION, body.EW_RUN_DIR, body.retention_days)
    except RuntimeError as exc:
        _http(exc, 409)
    except Exception as exc:
        _http(exc)


@router.put("/installation")
def put_installation(body: InstallationIn) -> dict:
    try:
        return wiz.set_installation(body.EW_INSTALLATION)
    except Exception as exc:
        _http(exc)


@router.put("/rings")
def put_rings(body: RingsIn) -> dict:
    try:
        wiz.apply_rings([r.model_dump() for r in body.rings])
        return {"ok": True, "rings": [r.model_dump() for r in body.rings]}
    except RuntimeError as exc:
        _http(exc, 409)
    except Exception as exc:
        _http(exc)


@router.post("/validate")
def post_validate() -> dict:
    checks = wiz.validate()
    return {"ok": all(c["ok"] for c in checks), "checks": checks}


@router.post("/complete")
def post_complete() -> dict:
    try:
        return wiz.complete_setup()
    except Exception as exc:
        _http(exc)


@router.post("/import-existing")
def post_import() -> dict:
    try:
        return wiz.import_existing()
    except Exception as exc:
        _http(exc, 503)
