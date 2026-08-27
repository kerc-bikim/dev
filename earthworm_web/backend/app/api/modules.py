from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..models.schemas import CloneIn, ModulePatchIn, VariablesIn
from ..security import api_key_header
from ..services.app_store import load_app
from ..services.clone import CloneError, clone_module, delete_clone
from ..services.control import toggle_module
from ..services.module_catalog import as_dict, catalog
from ..services.schema import schema_payload
from ..services.variables import apply_variables, current_variables

router = APIRouter(prefix="/api", tags=["modules"], dependencies=[Depends(api_key_header)])


def require_setup() -> None:
    if not load_app().setup_complete:
        raise HTTPException(409, "초기 설정을 먼저 완료하세요")


@router.get("/modules")
def get_modules() -> dict:
    return {"modules": [as_dict(m) for m in catalog()]}


@router.get("/modules/schema")
def get_modules_schema() -> dict:
    return schema_payload()


@router.patch("/modules/{module_id}")
async def patch_module(module_id: str, body: ModulePatchIn, _: None = Depends(require_setup)) -> dict:
    try:
        return await toggle_module(module_id, body.enabled)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/modules/{module_id}/clone")
def post_clone(module_id: str, body: CloneIn, _: None = Depends(require_setup)) -> dict:
    try:
        rec = clone_module(module_id, body.new_name)
        return {"clone": rec, "modules": [as_dict(m) for m in catalog()]}
    except CloneError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.delete("/modules/{module_id}")
def delete_module(module_id: str, _: None = Depends(require_setup)) -> dict:
    try:
        delete_clone(module_id)
        return {"deleted": module_id, "modules": [as_dict(m) for m in catalog()]}
    except CloneError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/variables")
def get_variables() -> dict:
    return current_variables()


@router.put("/variables")
def put_variables(body: VariablesIn, _: None = Depends(require_setup)) -> dict:
    try:
        return apply_variables(body.values)
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
