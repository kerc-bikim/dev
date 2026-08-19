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

from .api.control import router as control_router
from .api.health import router as health_router
from .api.logs import router as logs_router
from .api.modules import router as modules_router
from .api.params import router as params_router
from .api.setup import router as setup_router
from .config import settings
from .security import OPEN_PATHS, check_key
from .services.control import dashboard_payload, read_status
from .services.log_store import read_log, sweep_logs
from .services.seed import ensure_default_home
from .services.sniff_broker import get_session

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("earthworm_web")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if settings.AUTO_SEED:
        try:
            ensure_default_home()
        except Exception:
            log.exception("stub Earthworm home seed failed")
    task = asyncio.create_task(_retention_loop())
    yield
    task.cancel()


app = FastAPI(
    title="Earthworm Web Control",
    version="0.1.0",
    description="Earthworm v8 웹 콘솔 (FastAPI). 프론트엔드는 /api 와 /ws 만 사용합니다.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(setup_router)
app.include_router(params_router)
app.include_router(modules_router)
app.include_router(control_router)
app.include_router(logs_router)


@app.middleware("http")
async def api_key_middleware(request: Request, call_next):
    path = request.url.path
    if path in OPEN_PATHS or path.startswith("/docs") or path.startswith("/redoc"):
        return await call_next(request)
    if path.startswith("/api/") or path.startswith("/ws/"):
        # routers also check; this covers anything missed. GET /api/health is open.
        if path != "/api/health":
            key = request.headers.get("X-API-Key") or request.query_params.get("key")
            try:
                check_key(key)
            except Exception as exc:
                return JSONResponse({"detail": getattr(exc, "detail", str(exc))}, status_code=403)
    return await call_next(request)


async def _retention_loop() -> None:
    while True:
        try:
            sweep_logs()
        except Exception:
            log.debug("log sweep skipped", exc_info=True)
        await asyncio.sleep(3600)


@app.websocket("/ws/status")
async def ws_status(ws: WebSocket, key: str | None = None):
    try:
        check_key(key)
    except Exception:
        await ws.close(code=4403)
        return
    await ws.accept()
    try:
        while True:
            snap = await read_status()
            await ws.send_json(dashboard_payload(snap))
            await asyncio.sleep(max(0.5, settings.STATUS_INTERVAL_SEC))
    except WebSocketDisconnect:
        return


@app.websocket("/ws/logs")
async def ws_logs(ws: WebSocket, file: str, key: str | None = None):
    try:
        check_key(key)
    except Exception:
        await ws.close(code=4403)
        return
    await ws.accept()
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
async def ws_sniff(ws: WebSocket, session: str, key: str | None = None):
    try:
        check_key(key)
    except Exception:
        await ws.close(code=4403)
        return
    sess = get_session(session)
    if not sess:
        await ws.close(code=4404)
        return
    await ws.accept()
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
