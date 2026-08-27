from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from ..config import settings

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None
_path: Path | None = None

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS operators (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    username_lc TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('admin', 'operator', 'viewer')),
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    created_by INTEGER
);

CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    operator_id INTEGER NOT NULL REFERENCES operators(id),
    created_at TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ws_tickets (
    ticket TEXT PRIMARY KEY,
    operator_id INTEGER,
    username TEXT NOT NULL,
    display_name TEXT NOT NULL,
    role TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS login_fail (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username_lc TEXT NOT NULL,
    at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_event (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at TEXT NOT NULL,
    actor_id INTEGER,
    actor_username TEXT NOT NULL,
    actor_display_name TEXT NOT NULL,
    action TEXT NOT NULL,
    target TEXT,
    result TEXT NOT NULL CHECK(result IN ('ok', 'error', 'denied')),
    ip TEXT,
    detail TEXT,
    backup_dir TEXT
);

CREATE INDEX IF NOT EXISTS idx_audit_at ON audit_event(at);
CREATE INDEX IF NOT EXISTS idx_audit_actor ON audit_event(actor_username);
CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_event(action);
CREATE INDEX IF NOT EXISTS idx_login_fail ON login_fail(username_lc, at);
"""


def db_path() -> Path:
    p = Path(settings.CONTROL_DB)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def connect() -> sqlite3.Connection:
    global _conn, _path
    path = db_path()
    with _lock:
        if _conn is not None and _path == path:
            return _conn
        if _conn is not None:
            try:
                _conn.close()
            except Exception:
                pass
        conn = sqlite3.connect(str(path), check_same_thread=False, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.executescript(SCHEMA)
        _conn = conn
        _path = path
        return conn


def reset_connection() -> None:
    global _conn, _path
    with _lock:
        if _conn is not None:
            try:
                _conn.close()
            except Exception:
                pass
        _conn = None
        _path = None
