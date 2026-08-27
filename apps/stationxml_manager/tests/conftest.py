from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.catalog import seed_catalog
from app.db import Base, make_engine


@pytest.fixture
def session(tmp_path) -> Session:
    engine = make_engine(f"sqlite:///{tmp_path}/test.db")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False)
    s = SessionLocal()
    seed_catalog(s)
    yield s
    s.close()


@pytest.fixture
def api_client(tmp_path, monkeypatch):
    engine = make_engine(f"sqlite:///{tmp_path}/api.db")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False)
    main_module = importlib.import_module("app.main")
    monkeypatch.setattr(main_module, "get_session", SessionLocal)
    with TestClient(main_module.app) as client:
        yield client, SessionLocal
