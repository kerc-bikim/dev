from __future__ import annotations

import os
import subprocess
from pathlib import Path

from .env import parsed_core


def lock_info() -> dict:
    env = parsed_core()
    lock = Path(env["EW_LOG"]) / "startstop_unix.d.lock"
    info: dict = {"path": str(lock), "exists": lock.is_file(), "pid": None, "alive": False}
    if lock.is_file():
        raw = lock.read_text(encoding="utf-8", errors="replace").strip().split()
        if raw and raw[0].isdigit():
            info["pid"] = int(raw[0])
            try:
                os.kill(info["pid"], 0)
                info["alive"] = True
            except OSError:
                info["alive"] = False
    return info


def unlock(force: bool = False) -> dict:
    info = lock_info()
    if not info["exists"]:
        return info
    if info["alive"] and not force:
        raise PermissionError("startstop 가 살아 있습니다. 강제 해제는 force=true 가 필요합니다")
    Path(info["path"]).unlink(missing_ok=True)
    info["exists"] = False
    return info


def ipc_summary() -> dict:
    try:
        proc = subprocess.run(
            ["ipcs", "-m"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except FileNotFoundError:
        return {"available": False, "raw": "", "segments": []}
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    return {"available": True, "raw": proc.stdout, "segments": lines[2:20], "auto_delete": False}
