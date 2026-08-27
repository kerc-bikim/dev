from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.requests import Request
from starlette.responses import JSONResponse

from .api.audit import router as audit_router
from .api.auth import router as auth_router
from .api.compose import router as compose_router
from .api.control import router as control_router
from .api.health import router as health_router
from .api.logs import router as logs_router
from .api.modules import router as modules_router
from .api.operators import router as operators_router
from .api.params import router as params_router
from .api.setup import router as setup_router
from .config import settings
from .security import OPEN_PATHS, actor_from_request, request_ip, ws_actor
from .services.app_store import load_app, status_interval_sec
from .services.audit import record_audit, sweep_audit
from .services.auth import seed_bootstrap_from_env
from .services.control import dashboard_payload, read_status
from .services.control_db import connect
from .services.log_store import read_log, sweep_logs
from .services.seed import ensure_default_home
from .services.sniff_broker import get_session as get_sniff_session

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("earthworm_web")

SKIP_AUDIT = {
    ("GET",),
    ("HEAD",),
    ("OPTIONS",),
}
SKIP_AUDIT_PATHS = {
    "/api/health",
    "/api/auth/status",
    "/api/auth/me",
    "/api/auth/ws-ticket",
    "/api/auth/login",
    "/api/auth/bootstrap",
    "/api/auth/logout",
    "/api/auth/password",
    "/api/compose/validate",
    "/api/compose/suggest",
}

ACTION_MAP = (
    ("POST", "/api/control/start", "control_start", "startstop"),
    ("POST", "/api/control/stop", "control_pau", "startstop"),
    ("POST", "/api/control/pause", "control_stopmodule", "pause"),
    ("POST", "/api/control/resume", "control_restart", "resume"),
    ("POST", "/api/control/reconfigure", "control_restart", "reconfigure"),
    ("POST", "/api/setup/complete", "setup_complete", "setup"),
    ("POST", "/api/compose/apply", "compose_apply", "compose"),
    ("PUT", "/api/variables", "variables_apply", "variables"),
    ("PUT", "/api/files/content", "file_write", "file"),
    ("PUT", "/api/logs/settings", "file_write", "logs"),
    ("POST", "/api/diagnostics/lock/unlock", "lock_unlock", "lock"),
    ("POST", "/api/sniff/sessions", "sniff_start", "sniff"),
)


def _map_action(method: str, path: str) -> tuple[str, str] | None:
    for m, prefix, action, target in ACTION_MAP:
        if method == m and path == prefix:
            return action, target
    if method == "PATCH" and path.startswith("/api/modules/") and "/clone" not in path:
        return "module_toggle", path.rsplit("/", 1)[-1]
    if method == "POST" and path.endswith("/clone") and path.startswith("/api/modules/"):
        return "module_clone", path.split("/")[3]
    if method == "DELETE" and path.startswith("/api/modules/"):
        return "module_delete", path.rsplit("/", 1)[-1]
    if method == "POST" and path.startswith("/api/control/modules/") and path.endswith("/restart"):
        return "control_restart", path.split("/")[4]
    if method == "POST" and path.startswith("/api/control/modules/") and path.endswith("/stop"):
        return "control_stopmodule", path.split("/")[4]
    if method == "DELETE" and path.startswith("/api/sniff/sessions/"):
        return "sniff_stop", path.rsplit("/", 1)[-1]
    if method == "POST" and path == "/api/operators":
        return "operator_create", "operators"
    if method == "PATCH" and path.startswith("/api/operators/"):
        return "operator_update", path.rsplit("/", 1)[-1]
    if method in {"POST", "PUT", "PATCH", "DELETE"} and path.startswith("/api/"):
        return path.strip("/").replace("/", "_"), path
    return None


VIEWER_WRITE_ALLOW = {
    "/api/auth/logout",
    "/api/auth/password",
    "/api/auth/ws-ticket",
}

ADMIN_ONLY_PREFIXES = ("/api/operators",)
ADMIN_ONLY_EXACT = {("POST", "/api/diagnostics/lock/unlock")}


@asynccontextmanager
async def lifespan(_app: FastAPI):
    connect()
    seed_bootstrap_from_env()
    if not (settings.API_KEY or "").strip():
        log.warning("EW_WEB_API_KEY 가 비어 있습니다. 사람 세션만 사용합니다.")
    elif settings.API_KEY.strip() == "dev":
        log.warning("EW_WEB_API_KEY 가 기본값 'dev' 입니다. 배포 시 변경하세요. pytest/서비스 합성 작업자 전용입니다.")
    if settings.AUTO_SEED:
        try:
            ensure_default_home()
        except Exception:
            log.exception("stub Earthworm home seed failed")
    task = asyncio.create_task(_retention_loop())
    yield
    task.cancel()


_docs = "/docs" if settings.OPEN_DOCS else None
_redoc = "/redoc" if settings.OPEN_DOCS else None
_openapi = "/openapi.json" if settings.OPEN_DOCS else None

app = FastAPI(
    title="Earthworm Web Control",
    version="0.1.0",
    description="Earthworm v8 웹 콘솔 (FastAPI). 프론트엔드는 /api 와 /ws 만 사용합니다.",
    lifespan=lifespan,
    docs_url=_docs,
    redoc_url=_redoc,
    openapi_url=_openapi,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(auth_router)
app.include_router(operators_router)
app.include_router(audit_router)
app.include_router(setup_router)
app.include_router(params_router)
app.include_router(modules_router)
app.include_router(compose_router)
app.include_router(control_router)
app.include_router(logs_router)


def _docs_open(path: str) -> bool:
    if not settings.OPEN_DOCS:
        return False
    return path.startswith("/docs") or path.startswith("/redoc") or path.startswith("/openapi")


def _deny(request: Request, actor, detail: str) -> JSONResponse:
    mapped = _map_action(request.method, request.url.path)
    action, target = mapped if mapped else ("denied", request.url.path)
    if actor:
        record_audit(
            action=action,
            result="denied",
            actor_id=actor.id,
            actor_username=actor.username,
            actor_display_name=actor.display_name,
            target=target,
            ip=request_ip(request),
            detail={"detail": detail},
        )
    return JSONResponse({"detail": detail}, status_code=403)


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path
    if path in OPEN_PATHS or _docs_open(path) or not path.startswith("/api/"):
        return await call_next(request)
    if path.startswith("/ws/"):
        return await call_next(request)

    actor = actor_from_request(request)
    request.state.actor = actor
    if actor is None:
        expected = (settings.API_KEY or "").strip()
        # 쿼리 ?key= 로는 인증하지 않는다.
        if request.query_params.get("key") and not request.headers.get("X-API-Key"):
            return JSONResponse({"detail": "쿼리 키는 사용할 수 없습니다"}, status_code=403)
        if not expected:
            return JSONResponse({"detail": "로그인이 필요합니다"}, status_code=401)
        return JSONResponse({"detail": "로그인이 필요합니다"}, status_code=401)

    method = request.method.upper()
    if actor.role == "viewer" and method in {"POST", "PUT", "PATCH", "DELETE"}:
        if path not in VIEWER_WRITE_ALLOW:
            return _deny(request, actor, "조회자는 변경할 수 없습니다")
    if any(path.startswith(p) for p in ADMIN_ONLY_PREFIXES) and actor.role != "admin":
        return _deny(request, actor, "관리자만 작업자를 관리할 수 있습니다")
    if (method, path) in ADMIN_ONLY_EXACT and actor.role != "admin":
        return _deny(request, actor, "관리자만 락을 해제할 수 있습니다")

    response = await call_next(request)

    if method in {"POST", "PUT", "PATCH", "DELETE"} and path not in SKIP_AUDIT_PATHS:
        mapped = _map_action(method, path)
        if mapped:
            action, target = mapped
            if action == "compose_apply":
                pass  # handler records
            elif path.startswith("/api/operators"):
                pass  # handler records
            else:
                code = response.status_code
                if code >= 400:
                    result = "denied" if code == 403 else "error"
                else:
                    result = "ok"
                # login/bootstrap recorded in handlers; skip 401 noise
                if code != 401:
                    record_audit(
                        action=action,
                        result=result,
                        actor_id=actor.id,
                        actor_username=actor.username,
                        actor_display_name=actor.display_name,
                        target=target,
                        ip=request_ip(request),
                        detail={"status": code},
                    )
    return response


async def _retention_loop() -> None:
    while True:
        try:
            sweep_logs()
        except Exception:
            log.debug("log sweep skipped", exc_info=True)
        try:
            days = load_app().audit_retention_days or settings.AUDIT_RETENTION_DAYS
            sweep_audit(days)
        except Exception:
            log.debug("audit sweep skipped", exc_info=True)
        await asyncio.sleep(3600)


async def _accept_ws(ws: WebSocket, ticket: str | None, key: str | None) -> bool:
    actor = ws_actor(ticket, key)
    if actor is None:
        await ws.close(code=4403)
        return False
    await ws.accept()
    return True


@app.websocket("/ws/status")
async def ws_status(ws: WebSocket, ticket: str | None = None, key: str | None = None):
    if not await _accept_ws(ws, ticket, key):
        return
    try:
        while True:
            snap = await read_status()
            await ws.send_json(dashboard_payload(snap))
            await asyncio.sleep(status_interval_sec())
    except WebSocketDisconnect:
        return


@app.websocket("/ws/logs")
async def ws_logs(ws: WebSocket, file: str, ticket: str | None = None, key: str | None = None):
    if not await _accept_ws(ws, ticket, key):
        return
    seen = 0
    try:
        while True:
            try:
                data = read_log(file, tail=400)
                lines = data["lines"]
                if len(lines) >= seen:
                    new = lines[seen:]
                else:
                    new = lines
                seen = len(lines)
                if new:
                    await ws.send_json({"file": data["file"], "lines": new})
            except Exception as exc:
                await ws.send_json({"error": str(exc)})
            await asyncio.sleep(1.0)
    except WebSocketDisconnect:
        return


@app.websocket("/ws/sniff")
async def ws_sniff(ws: WebSocket, session: str, ticket: str | None = None, key: str | None = None):
    if not await _accept_ws(ws, ticket, key):
        return
    sess = get_sniff_session(session)
    if not sess:
        await ws.close(code=4404)
        return
    q: asyncio.Queue = asyncio.Queue(maxsize=200)
    sess.subscribers.add(q)
    try:
        for line in sess.lines[-50:]:
            await ws.send_json({"type": "line", "text": line})
        while True:
            msg = await q.get()
            await ws.send_json(msg)
            if msg.get("type") == "closed":
                break
    except WebSocketDisconnect:
        pass
    finally:
        sess.subscribers.discard(q)


dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if dist.is_dir():
    app.mount("/", StaticFiles(directory=str(dist), html=True), name="frontend")
