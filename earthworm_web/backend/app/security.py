from __future__ import annotations

from fastapi import Header, HTTPException, Query, WebSocket

from .config import settings

OPEN_PATHS = {"/api/health", "/api/openapi.json", "/docs", "/redoc", "/openapi.json"}


def check_key(key: str | None) -> None:
    expected = settings.API_KEY
    if not expected:
        return
    if key != expected:
        raise HTTPException(status_code=403, detail="API 키가 올바르지 않습니다")


def api_key_header(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> None:
    check_key(x_api_key)


async def ws_key(websocket: WebSocket, key: str | None = Query(default=None)) -> None:
    try:
        check_key(key)
    except HTTPException:
        await websocket.close(code=4403)
        raise
