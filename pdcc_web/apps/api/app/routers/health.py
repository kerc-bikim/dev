from __future__ import annotations

import json

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from ..cache import get_redis
from ..db import get_engine

router = APIRouter(tags=["health"])


def health_payload() -> dict:
    db_ok = False
    redis_ok = False
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False
    try:
        redis_ok = bool(get_redis().ping())
    except Exception:
        redis_ok = False
    return {"ok": db_ok and redis_ok, "db": db_ok, "redis": redis_ok}


@router.get("/health")
@router.get("/api/health")
def health():
    body = health_payload()
    status = 200 if body["ok"] else 503
    return JSONResponse(content=body, status_code=status)
