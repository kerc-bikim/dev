from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

Base = declarative_base()


def default_db_path() -> Path:
    data_dir = Path(__file__).resolve().parent.parent / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "stationxml.db"


def make_engine(url: str | None = None):
    if url is None:
        url = f"sqlite:///{default_db_path()}"
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, connect_args=connect_args)


engine = make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_session():
    return SessionLocal()


def migrate_schema(bind=None) -> None:
    from sqlalchemy import inspect, text

    bind = bind or engine
    inspector = inspect(bind)
    if "equipment_catalog" not in inspector.get_table_names():
        return
    columns = {col["name"] for col in inspector.get_columns("equipment_catalog")}
    statements: list[str] = []
    if "origin" not in columns:
        statements.append(
            "ALTER TABLE equipment_catalog ADD COLUMN origin VARCHAR(16) DEFAULT 'seed'"
        )
        statements.append(
            "UPDATE equipment_catalog SET origin = 'seed' WHERE origin IS NULL"
        )
    if "description" not in columns:
        statements.append("ALTER TABLE equipment_catalog ADD COLUMN description TEXT")
    if not statements:
        return
    with bind.begin() as conn:
        for statement in statements:
            conn.execute(text(statement))


def init_db() -> None:
    from . import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    migrate_schema(engine)
