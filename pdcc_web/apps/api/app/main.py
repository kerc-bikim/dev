from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .cache import get_redis, set_redis
from .db import Base, SessionLocal, configure_engine, get_engine
from .middleware import RequestContextMiddleware
from .nrl.client import set_nrl_client
from .routers.auth import router as auth_router
from .routers.collab import router as collab_router
from .routers.health import router as health_router
from .routers.jobs import router as export_router
from .routers.locks import router as locks_router
from .routers.nrl import router as nrl_router
from .routers.ops import purge_expired_audit, router as ops_router
from .routers.projects import router as projects_router
from .runtime import RequestIdFilter, apply_runtime_policy, cors_origin_list
from .seed import seed_users

log = logging.getLogger("pdcc.api")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s request_id=%(request_id)s: %(message)s",
)
for _handler in logging.getLogger().handlers:
    _handler.addFilter(RequestIdFilter())


@asynccontextmanager
async def lifespan(_app: FastAPI):
    apply_runtime_policy()
    configure_engine()
    Base.metadata.create_all(bind=get_engine())
    db = SessionLocal()
    try:
        seed_users(db)
        deleted = purge_expired_audit(db)
        db.commit()
        if deleted:
            log.info("purged %s expired audit rows", deleted)
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
    allow_origins=cors_origin_list(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RequestContextMiddleware)

app.include_router(health_router)
app.include_router(auth_router)
app.include_router(nrl_router)
app.include_router(projects_router)
app.include_router(locks_router)
app.include_router(ops_router)
