"""Edge 자체 진단.

중앙이 Heartbeat 를 놓쳤을 때 기록계 장애와 Edge 장애를 가르려면, Edge 가 자신의
CPU·메모리·디스크·시각을 같이 보내야 한다.
"""
from __future__ import annotations

import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.edgeagent import AGENT_VERSION
from app.edgeagent.codec import iso_z
from app.edgeagent.spool import Spool


def _cpu_percent() -> float | None:
    try:
        load1, _, _ = os.getloadavg()
    except OSError:
        return None
    ncpu = os.cpu_count() or 1
    return round(min(100.0, 100.0 * load1 / ncpu), 1)


def _memory_percent() -> float | None:
    path = Path("/proc/meminfo")
    if not path.exists():
        return None
    values: dict[str, int] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if ":" not in line:
            continue
        key, raw = line.split(":", 1)
        number = raw.strip().split()[0]
        try:
            values[key] = int(number)
        except ValueError:
            continue
    total = values.get("MemTotal")
    available = values.get("MemAvailable")
    if not total or available is None:
        return None
    used = max(0, total - available)
    return round(100.0 * used / total, 1)


def _disk_percent(path: Path) -> float | None:
    try:
        usage = shutil.disk_usage(path)
    except OSError:
        return None
    if usage.total <= 0:
        return None
    return round(100.0 * usage.used / usage.total, 1)


def collect_health(*, spool_path: Path, clock_offset_ms: float | None = None) -> dict[str, Any]:
    return {
        "cpuPercent": _cpu_percent(),
        "memoryPercent": _memory_percent(),
        "diskPercent": _disk_percent(spool_path),
        "clockOffsetMs": clock_offset_ms,
        "pid": os.getpid(),
    }


def build_heartbeat(
    *,
    edge_id: str,
    config_version: int,
    spool: Spool,
    health: dict[str, Any],
    adapters: list[str],
    agent_version: str = AGENT_VERSION,
) -> dict[str, Any]:
    snapshot = spool.snapshot()
    return {
        "edgeId": edge_id,
        "agentVersion": agent_version,
        "observedAt": iso_z(datetime.now(timezone.utc)),
        "configVersion": config_version,
        "installedAdapters": adapters,
        "spool": snapshot,
        "health": health,
    }


def clock_offset_ms(server_time: str | None, *, now: datetime | None = None) -> float | None:
    if not server_time:
        return None
    try:
        remote = datetime.fromisoformat(server_time.replace("Z", "+00:00"))
    except ValueError:
        return None
    current = now or datetime.now(timezone.utc)
    if remote.tzinfo is None:
        remote = remote.replace(tzinfo=timezone.utc)
    return (current - remote).total_seconds() * 1000.0
