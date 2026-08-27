from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class StatusRow:
    name: str
    pid: int | None
    status: str
    class_priority: str = ""
    argument: str = ""


@dataclass
class StatusSnapshot:
    running: bool
    hostname_os: str = ""
    version: str = ""
    start_time: str = ""
    current_time: str = ""
    disk_kb: int | None = None
    rings: list[dict] = field(default_factory=list)
    log_dir: str = ""
    params_dir: str = ""
    bin_dir: str = ""
    rows: list[StatusRow] = field(default_factory=list)
    raw: str = ""
    error: str | None = None


_ROW = re.compile(
    r"^\s+(\S+)\s+(\d+)\s+(Alive|Stop|Dead)\s*(.*)$",
    re.IGNORECASE,
)
_RING = re.compile(
    r"Ring\s+\d+\s+name/key/size:\s+(\S+)\s*/\s*(\S+)\s*/\s*(\d+)",
    re.IGNORECASE,
)
_DISK = re.compile(r"Disk space:\s+(\d+)", re.IGNORECASE)


def parse_status(text: str) -> StatusSnapshot:
    snap = StatusSnapshot(running=True, raw=text)
    if "not running" in text.lower() or not text.strip():
        snap.running = False
        snap.error = text.strip() or "startstop is not running"
        return snap
    for ln in text.splitlines():
        if "Hostname-OS" in ln:
            snap.hostname_os = ln.split(":", 1)[-1].strip()
        if "Version:" in ln:
            m = re.search(r"Version:\s+(\S+)", ln)
            if m:
                snap.version = m.group(1)
        if "Start time:" in ln:
            snap.start_time = ln.split(":", 1)[-1].strip()
        if "Current time:" in ln:
            snap.current_time = ln.split(":", 1)[-1].strip()
        dm = _DISK.search(ln)
        if dm:
            snap.disk_kb = int(dm.group(1))
        rm = _RING.search(ln)
        if rm:
            snap.rings.append(
                {"name": rm.group(1), "key": rm.group(2), "size_kib": int(rm.group(3))}
            )
        if "Log Dir:" in ln:
            snap.log_dir = ln.split(":", 1)[-1].strip()
        if "Params Dir:" in ln:
            snap.params_dir = ln.split(":", 1)[-1].strip()
        if "Bin Dir:" in ln:
            snap.bin_dir = ln.split(":", 1)[-1].strip()
        row = _ROW.match(ln)
        if row:
            rest = row.group(4).strip()
            cls, arg = "", rest
            parts = rest.split()
            if len(parts) >= 2 and parts[0] in {"OTHER", "TS", "TAPE", "RT"}:
                cls = f"{parts[0]} {parts[1]}"
                arg = " ".join(parts[2:])
            snap.rows.append(
                StatusRow(
                    name=row.group(1),
                    pid=int(row.group(2)),
                    status=row.group(3).title() if row.group(3).lower() != "dead" else "Dead",
                    class_priority=cls,
                    argument=arg,
                )
            )
    if not any(r.name == "startstop" for r in snap.rows) and snap.running:
        # still consider running if we parsed rings/header
        snap.running = bool(snap.rings or snap.rows)
    return snap
