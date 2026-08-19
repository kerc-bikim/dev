from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from .seed import default_bash_path, ensure_default_home

_CORE_KEYS = (
    "EW_HOME",
    "EW_VERSION",
    "EW_RUN_DIR",
    "EW_PARAMS",
    "EW_LOG",
    "EW_DATA_DIR",
    "EW_INSTALLATION",
    "SYS_NAME",
    "PATH",
)

_ASSIGN_RE = re.compile(
    r"^(export\s+)?(EW_HOME|EW_VERSION|EW_RUN_DIR|EW_INSTALLATION|EW_PARAMS|EW_LOG|EW_DATA_DIR)=(.*)$"
)


def bash_path() -> Path:
    p = default_bash_path()
    if not p.is_file() and os.environ.get("EW_WEB_AUTO_SEED", "1") not in {"0", "false"}:
        ensure_default_home()
        p = default_bash_path()
    return p


def source_env(script: Path | None = None) -> dict[str, str]:
    script = Path(script) if script else bash_path()
    if not script.is_file():
        raise FileNotFoundError(f"ew_linux.bash 를 찾을 수 없습니다: {script}")
    proc = subprocess.run(
        ["bash", "-lc", f"source {sh_single(str(script))} >/dev/null; env -0"],
        check=False,
        capture_output=True,
    )
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", errors="replace")
        raise RuntimeError(f"ew_linux.bash 소스 실패: {err}")
    env: dict[str, str] = {}
    for chunk in proc.stdout.split(b"\0"):
        if not chunk or b"=" not in chunk:
            continue
        key, _, val = chunk.partition(b"=")
        try:
            env[key.decode("utf-8")] = val.decode("utf-8", errors="replace")
        except UnicodeDecodeError:
            continue
    return env


def sh_single(path: str) -> str:
    return "'" + path.replace("'", "'\"'\"'") + "'"


def required_ew(env: dict[str, str]) -> dict[str, str]:
    missing = [k for k in ("EW_HOME", "EW_VERSION", "EW_PARAMS", "EW_LOG") if not env.get(k)]
    if missing:
        raise RuntimeError("필수 환경 변수 없음: " + ", ".join(missing))
    return {k: env.get(k, "") for k in _CORE_KEYS}


def parsed_core(script: Path | None = None) -> dict[str, str]:
    env = source_env(script)
    core = required_ew(env)
    for key in ("EW_PARAMS", "EW_LOG", "EW_DATA_DIR"):
        if core.get(key) and not core[key].endswith("/"):
            core[key] = core[key] + "/"
    return core


def rewrite_bash(script: Path, updates: dict[str, str]) -> None:
    text = script.read_text(encoding="utf-8")
    lines = text.splitlines()
    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        m = _ASSIGN_RE.match(line.strip()) if line.strip() else None
        if m and m.group(2) in updates:
            key = m.group(2)
            out.append(f"export {key}={updates[key]}")
            seen.add(key)
        else:
            out.append(line)
    for key, val in updates.items():
        if key not in seen:
            out.append(f"export {key}={val}")
    script.write_text("\n".join(out) + "\n", encoding="utf-8")


def apply_directories(
    script: Path,
    ew_home: str,
    ew_version: str,
    ew_run_dir: str,
    installation: str | None = None,
    ew_log: str | None = None,
) -> dict[str, str]:
    params = os.path.join(ew_run_dir, "params") + "/"
    log = (ew_log or os.path.join(ew_run_dir, "log")) 
    if not log.endswith("/"):
        log += "/"
    data = os.path.join(ew_run_dir, "data") + "/"
    updates = {
        "EW_HOME": ew_home.rstrip("/"),
        "EW_VERSION": ew_version,
        "EW_RUN_DIR": ew_run_dir.rstrip("/"),
        "EW_PARAMS": params,
        "EW_LOG": log,
        "EW_DATA_DIR": data,
    }
    if installation:
        updates["EW_INSTALLATION"] = installation
    rewrite_bash(script, updates)
    Path(params).mkdir(parents=True, exist_ok=True)
    Path(log).mkdir(parents=True, exist_ok=True)
    Path(data).mkdir(parents=True, exist_ok=True)
    return parsed_core(script)
