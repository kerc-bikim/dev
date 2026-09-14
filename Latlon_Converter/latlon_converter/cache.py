"""API 응답 캐시.

브이월드는 일일 호출 한도가 있고 같은 필지를 다시 조회하는 일이 잦아,
응답 원문을 sqlite에 담아 두고 재사용한다.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS response_cache (
    key TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    endpoint TEXT NOT NULL,
    payload TEXT NOT NULL,
    fetched_at REAL NOT NULL
)
"""

# 인증 정보는 응답을 좌우하지 않으므로 캐시 키에서 뺀다.
_IGNORED_PARAMS = frozenset({"key", "domain"})


def make_key(provider: str, endpoint: str, params: dict[str, Any]) -> str:
    items = sorted(
        (name, str(value))
        for name, value in params.items()
        if name not in _IGNORED_PARAMS and value is not None
    )
    raw = json.dumps([provider, endpoint, items], ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class NullCache:
    """캐시를 쓰지 않을 때의 빈 구현."""

    def get(self, provider: str, endpoint: str, params: dict[str, Any]) -> dict | None:
        return None

    def set(self, provider: str, endpoint: str, params: dict[str, Any], payload: dict) -> None:
        return None

    def close(self) -> None:
        return None


class ResponseCache:
    """sqlite 파일 기반 캐시."""

    def __init__(self, path: str | Path, ttl_days: int = 30) -> None:
        self.path = Path(path)
        self.ttl_seconds = max(ttl_days, 0) * 86400
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path))
        self._conn.execute(_SCHEMA)
        self._conn.commit()

    def get(self, provider: str, endpoint: str, params: dict[str, Any]) -> dict | None:
        key = make_key(provider, endpoint, params)
        row = self._conn.execute(
            "SELECT payload, fetched_at FROM response_cache WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            return None
        payload, fetched_at = row
        if self.ttl_seconds and time.time() - fetched_at > self.ttl_seconds:
            self._conn.execute("DELETE FROM response_cache WHERE key = ?", (key,))
            self._conn.commit()
            return None
        try:
            return json.loads(payload)
        except json.JSONDecodeError:
            return None

    def set(self, provider: str, endpoint: str, params: dict[str, Any], payload: dict) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO response_cache VALUES (?, ?, ?, ?, ?)",
            (
                make_key(provider, endpoint, params),
                provider,
                endpoint,
                json.dumps(payload, ensure_ascii=False),
                time.time(),
            ),
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()


def build_cache(cache_db: str, ttl_days: int, enabled: bool = True) -> NullCache | ResponseCache:
    if not enabled or not cache_db:
        return NullCache()
    return ResponseCache(cache_db, ttl_days)
