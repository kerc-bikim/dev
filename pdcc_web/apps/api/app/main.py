from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .cache import get_redis, set_redis
from .config import settings
from .db import SessionLocal, configure_engine, ensure_schema
from .nrl.client import set_nrl_client
from .routers.admin import router as admin_router
from .routers.auth import router as auth_router
from .routers.collab import router as collab_router
from .routers.health import router as health_router
from .routers.locks import router as locks_router
from .routers.jobs import router as jobs_router
from .routers.nrl import router as nrl_router
from .routers.projects import router as projects_router
from .seed import seed_users

log = logging.getLogger("pdcc.api")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if settings.app_secret == "dev-insecure-change-me":
        log.warning("APP_SECRET 가 기본값입니다. 배포 시 변경하세요.")
    if settings.dev_bootstrap_admin:
        log.warning("DEV_BOOTSTRAP_ADMIN=true — admin/admin 로그인이 허용됩니다.")
    configure_engine()
    ensure_schema()
    db = SessionLocal()
    try:
        seed_users(db)
    finally:
        db.close()
    try:
        get_redis().ping()
    except Exception:
        log.exception("redis ping failed at startup; /health will report redis=false")
    yield
    set_redis(None)
    set_nrl_client(None)


app = FastAPI(
    title="PDCC Web API",
    version="0.1.0",
    description="PDCC 웹 편집기 API. NRL은 서버 프록시로만 호출합니다.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(nrl_router)
app.include_router(projects_router)
app.include_router(jobs_router)
app.include_router(locks_router)
app.include_router(collab_router)
