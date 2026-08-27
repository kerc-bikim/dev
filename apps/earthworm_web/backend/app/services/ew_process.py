from __future__ import annotations

import asyncio
import os
from pathlib import Path

from .env import bash_path, source_env

_control_lock = asyncio.Lock()


def control_lock() -> asyncio.Lock:
    return _control_lock


async def run_argv(
    argv: list[str],
    *,
    timeout: float = 20.0,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
    background: bool = False,
    stdout_path: Path | None = None,
) -> tuple[int, str, str]:
    if not argv or not isinstance(argv, list):
        raise ValueError("argv 리스트가 필요합니다")
    if any(not isinstance(a, str) for a in argv):
        raise TypeError("argv 항목은 문자열이어야 합니다")
    sourced = env or source_env(bash_path())
    workdir = cwd or sourced.get("EW_PARAMS") or os.getcwd()
    if background:
        out_f = None
        if stdout_path:
            stdout_path.parent.mkdir(parents=True, exist_ok=True)
            out_f = open(stdout_path, "ab")
        proc = await asyncio.create_subprocess_exec(
            *argv,
            cwd=workdir,
            env=sourced,
            stdout=out_f or asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.STDOUT if out_f else asyncio.subprocess.DEVNULL,
            start_new_session=True,
        )
        if out_f:
            out_f.close()
        return proc.pid or 0, "", ""
    proc = await asyncio.create_subprocess_exec(
        *argv,
        cwd=workdir,
        env=sourced,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=False,
    )
    try:
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise TimeoutError(f"명령 시간 초과: {argv[0]}")
    stdout = stdout_b.decode("utf-8", errors="replace")
    stderr = stderr_b.decode("utf-8", errors="replace")
    return proc.returncode or 0, stdout, stderr


def bin_path(env: dict[str, str], name: str) -> Path:
    home = env["EW_HOME"]
    ver = env["EW_VERSION"]
    return Path(home) / ver / "bin" / name
