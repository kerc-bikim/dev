from __future__ import annotations

import os
import re
from pathlib import Path

from .app_store import load_app, save_app
from .env import bash_path, parsed_core, rewrite_bash

LOG_DATE_RE = re.compile(r"^(.+)_(\d{8})\.(log|err)$")


def log_dir() -> Path:
    return Path(parsed_core()["EW_LOG"])


def list_logs() -> list[dict]:
    root = log_dir()
    if not root.is_dir():
        return []
    grouped: dict[str, list[dict]] = {}
    for p in sorted(root.iterdir()):
        if not p.is_file():
            continue
        if p.suffix == ".lock" or p.name.endswith(".lock"):
            continue
        m = LOG_DATE_RE.match(p.name)
        if not m:
            if p.name == "web_startstop.out":
                grouped.setdefault("startstop", []).append(
                    {"file": p.name, "date": None, "size": p.stat().st_size, "module": "startstop"}
                )
            continue
        module, date, _ext = m.group(1), m.group(2), m.group(3)
        grouped.setdefault(module, []).append(
            {"file": p.name, "date": date, "size": p.stat().st_size, "module": module}
        )
    out = []
    for module, files in grouped.items():
        out.append({"module": module, "files": files})
    return out


def read_log(file: str, date: str | None = None, tail: int = 200) -> dict:
    if "/" in file or "\\" in file or ".." in file:
        raise ValueError("file 은 basename 만 허용합니다")
    root = log_dir().resolve()
    path = (root / file).resolve()
    if path.parent != root:
        raise ValueError("로그 경로가 허용 범위를 벗어났습니다")
    if not path.is_file():
        if date and not LOG_DATE_RE.match(file):
            cand = root / f"{file}_{date}.log"
            if cand.is_file():
                path = cand
            else:
                raise FileNotFoundError(file)
        else:
            raise FileNotFoundError(file)
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    if tail and tail > 0:
        lines = lines[-int(tail) :]
    return {"file": path.name, "lines": lines, "size": path.stat().st_size}


def update_log_settings(directory: str | None, retention_days: int | None) -> dict:
    env = parsed_core()
    meta = load_app()
    if retention_days is not None:
        if retention_days < 1 or retention_days > 3650:
            raise ValueError("보관 일수는 1–3650 입니다")
        meta.log_retention_days = retention_days
        save_app(meta)
    if directory:
        directory = directory if directory.endswith("/") else directory + "/"
        Path(directory).mkdir(parents=True, exist_ok=True)
        rewrite_bash(bash_path(), {"EW_LOG": directory})
        env = parsed_core()
    return {"directory": env["EW_LOG"], "retention_days": meta.log_retention_days}


def sweep_logs() -> list[str]:
    meta = load_app()
    days = meta.log_retention_days
    root = log_dir()
    if not root.is_dir():
        return []
    from datetime import datetime, timedelta, timezone

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    deleted: list[str] = []
    for p in root.iterdir():
        if not p.is_file():
            continue
        if p.suffix == ".lock" or p.name.endswith(".lock"):
            continue
        m = LOG_DATE_RE.match(p.name)
        if not m:
            continue
        try:
            stamp = datetime.strptime(m.group(2), "%Y%m%d").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if stamp < cutoff:
            p.unlink()
            deleted.append(p.name)
    out = root / "web_startstop.out"
    if out.is_file() and out.stat().st_size > 5_000_000:
        rotated = out.with_suffix(".out.1")
        if rotated.exists():
            rotated.unlink()
        out.replace(rotated)
    return deleted


def preview_sweep() -> list[str]:
    meta = load_app()
    days = meta.log_retention_days
    root = log_dir()
    from datetime import datetime, timedelta, timezone

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    would = []
    if not root.is_dir():
        return would
    for p in root.iterdir():
        if p.suffix == ".lock" or p.name.endswith(".lock"):
            continue
        m = LOG_DATE_RE.match(p.name)
        if not m:
            continue
        try:
            stamp = datetime.strptime(m.group(2), "%Y%m%d").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if stamp < cutoff:
            would.append(p.name)
    return would
