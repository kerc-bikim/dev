from __future__ import annotations

import logging

from redis import Redis

from .config import settings

log = logging.getLogger("pdcc.redis")

_client: Redis | None = None


def get_redis() -> Redis:
    global _client
    if _client is None:
        _client = Redis.from_url(settings.redis_url, decode_responses=True)
    return _client


def set_redis(client: Redis | None) -> None:
    global _client
    _client = client


def session_key(token: str) -> str:
    return f"pdcc:session:{token}"
