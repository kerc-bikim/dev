from __future__ import annotations

import logging
import uuid

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from .runtime import request_id_var

log = logging.getLogger("pdcc.http")

_SKIP_ACCESS_LOG = {
    "/health",
    "/api/health",
    "/health/live",
    "/api/health/live",
    "/health/ready",
    "/api/health/ready",
}


class RequestContextMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex
        token = request_id_var.set(rid)
        request.state.request_id = rid
        try:
            try:
                response = await call_next(request)
            except StarletteHTTPException:
                raise
            except Exception:
                log.exception("unhandled path=%s", request.url.path)
                return JSONResponse(
                    status_code=500,
                    content={"detail": "서버 오류", "request_id": rid},
                    headers={"X-Request-ID": rid},
                )
            response.headers["X-Request-ID"] = rid
            if request.url.path not in _SKIP_ACCESS_LOG:
                log.info(
                    "method=%s path=%s status=%s",
                    request.method,
                    request.url.path,
                    response.status_code,
                )
            return response
        finally:
            request_id_var.reset(token)
