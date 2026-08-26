from __future__ import annotations

import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("APP_SECRET", "test-secret")
os.environ.setdefault("DEV_BOOTSTRAP_ADMIN", "false")

import pytest
from fakeredis import FakeRedis
from fastapi.testclient import TestClient

from app.cache import set_redis
from app.config import settings
from app.main import app


@pytest.fixture
def redis_client():
    fake = FakeRedis(decode_responses=True)
    set_redis(fake)
    yield fake
    set_redis(None)


@pytest.fixture
def client(redis_client):
    settings.dev_bootstrap_admin = False
    with TestClient(app) as test_client:
        yield test_client
