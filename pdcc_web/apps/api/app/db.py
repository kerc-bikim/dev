from __future__ import annotations

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool

from .config import settings


class Base(DeclarativeBase):
    pass


_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def _kwargs(url: str) -> dict:
    if url.startswith("sqlite"):
        return {
            "connect_args": {"check_same_thread": False},
            "poolclass": StaticPool,
        }
    return {"pool_pre_ping": True}


def configure_engine(url: str | None = None) -> Engine:
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    db_url = url or settings.database_url
    _engine = create_engine(db_url, **_kwargs(db_url))
    _SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False)
    return _engine


def get_engine() -> Engine:
    if _engine is None:
        return configure_engine()
    return _engine


def SessionLocal() -> Session:
    if _SessionLocal is None:
        configure_engine()
    assert _SessionLocal is not None
    return _SessionLocal()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def ensure_schema(engine: Engine | None = None) -> None:
    from . import models as _models  # noqa: F401

    eng = engine or get_engine()
    Base.metadata.create_all(bind=eng)
    inspector = inspect(eng)
    dialect = eng.dialect.name
    if "audit_logs" in inspector.get_table_names():
        audit_cols = {column["name"] for column in inspector.get_columns("audit_logs")}
        if "details" not in audit_cols:
            with eng.begin() as conn:
                conn.execute(text("ALTER TABLE audit_logs ADD COLUMN details TEXT DEFAULT ''"))
    if "projects" in inspector.get_table_names():
        project_cols = {column["name"] for column in inspector.get_columns("projects")}
        project_stmts: list[str] = []
        if "archived_at" not in project_cols:
            project_stmts.append("ALTER TABLE projects ADD COLUMN archived_at TIMESTAMP")
        if "archived_by" not in project_cols:
            project_stmts.append("ALTER TABLE projects ADD COLUMN archived_by VARCHAR(64)")
        if project_stmts:
            with eng.begin() as conn:
                for stmt in project_stmts:
                    conn.execute(text(stmt))
    if "users" not in inspector.get_table_names():
        return
    cols = {column["name"] for column in inspector.get_columns("users")}
    stmts: list[str] = []
    if "active" not in cols:
        default = "1" if dialect == "sqlite" else "TRUE"
        stmts.append(f"ALTER TABLE users ADD COLUMN active BOOLEAN DEFAULT {default}")
    if "display_name" not in cols:
        stmts.append("ALTER TABLE users ADD COLUMN display_name VARCHAR(128)")
    if "org_id" not in cols:
        stmts.append("ALTER TABLE users ADD COLUMN org_id INTEGER")
    if not stmts:
        return
    with eng.begin() as conn:
        for stmt in stmts:
            conn.execute(text(stmt))
        if "active" not in cols:
            conn.execute(text("UPDATE users SET active = TRUE WHERE active IS NULL"))
