from __future__ import annotations

import json
import os
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import settings


@dataclass
class CloneRecord:
    id: str
    clone_of: str
    binary: str
    param_file: str
    module_id: str
    desc_file: str | None = None


@dataclass
class AppMeta:
    version: int = 1
    setup_complete: bool = False
    setup_at: str | None = None
    log_retention_days: int = 14
    status_interval_sec: float = 2.0
    sniff_session_limit: int = 2
    clones: list[dict[str, Any]] = field(default_factory=list)
    disabled_process_names: list[str] = field(default_factory=list)
    startstop_pid: int | None = None


_lock = threading.Lock()


def _path() -> Path:
    return Path(settings.APP_JSON)


def load_app() -> AppMeta:
    p = _path()
    if not p.is_file():
        return AppMeta(
            status_interval_sec=settings.STATUS_INTERVAL_SEC,
            sniff_session_limit=settings.SNIFF_MAX_SESSIONS,
        )
    data = json.loads(p.read_text(encoding="utf-8"))
    known = {f.name for f in AppMeta.__dataclass_fields__.values()}  # type: ignore[attr-defined]
    return AppMeta(**{k: v for k, v in data.items() if k in known})


def save_app(meta: AppMeta) -> None:
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    with _lock:
        tmp.write_text(json.dumps(asdict(meta), indent=2), encoding="utf-8")
        tmp.replace(p)


def status_interval_sec() -> float:
    try:
        return max(0.5, min(float(load_app().status_interval_sec), 60.0))
    except Exception:
        return float(settings.STATUS_INTERVAL_SEC)


def sniff_session_limit() -> int:
    try:
        return max(1, min(int(load_app().sniff_session_limit), 8))
    except Exception:
        return int(settings.SNIFF_MAX_SESSIONS)


def mark_setup_complete() -> AppMeta:
    meta = load_app()
    meta.setup_complete = True
    meta.setup_at = datetime.now(timezone.utc).isoformat()
    save_app(meta)
    return meta
