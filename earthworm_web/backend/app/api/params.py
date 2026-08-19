from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from ..models.schemas import EnvironmentIn, FileWriteIn
from ..security import api_key_header
from ..services.app_store import load_app
from ..services.env import parsed_core, rewrite_bash, bash_path
from ..services.files import PathDenied, list_tree, read_file, write_file

router = APIRouter(prefix="/api", tags=["files"], dependencies=[Depends(api_key_header)])


def require_setup() -> None:
    if not load_app().setup_complete:
        raise HTTPException(409, "초기 설정을 먼저 완료하세요")


@router.put("/environment")
def put_environment(body: EnvironmentIn, _: None = Depends(require_setup)) -> dict:
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        return parsed_core()
    rewrite_bash(bash_path(), updates)
    return parsed_core()


@router.get("/files")
def get_files(root: str = Query(..., pattern="^(params|environment)$")) -> dict:
    try:
        return {"root": root, "items": list_tree(root)}
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/files/content")
def get_file_content(
    root: str = Query(..., pattern="^(params|environment)$"),
    path: str = Query(...),
) -> dict:
    try:
        return read_file(root, path)
    except PathDenied as exc:
        raise HTTPException(400, str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.put("/files/content")
def put_file_content(body: FileWriteIn, _: None = Depends(require_setup)) -> dict:
    try:
        return write_file(body.root, body.path, body.content, allow_global=body.allow_global)
    except PathDenied as exc:
        raise HTTPException(400, str(exc)) from exc
