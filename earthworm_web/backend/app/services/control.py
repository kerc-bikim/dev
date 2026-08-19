from __future__ import annotations

import asyncio
import time
from pathlib import Path

from .app_store import load_app
from .env import parsed_core, source_env
from .ew_process import bin_path, control_lock, run_argv
from .ipc_diag import lock_info
from .module_catalog import catalog
from .status_parser import StatusSnapshot, parse_status
from .startstop_file import parse_startstop, serialize_startstop, set_process_enabled

PROTECTED = {"startstop", "statmgr"}

_last_snapshot: StatusSnapshot | None = None


def last_snapshot() -> StatusSnapshot | None:
    return _last_snapshot


async def read_status() -> StatusSnapshot:
    global _last_snapshot
    env = parsed_core()
    status_bin = str(bin_path(env, "status"))
    try:
        code, out, err = await run_argv(
            [status_bin], timeout=8, cwd=env["EW_PARAMS"], env=source_env()
        )
    except Exception as exc:
        snap = StatusSnapshot(running=False, error=str(exc), raw="")
        _last_snapshot = snap
        return snap
    text = (out or "") + (("\n" + err) if err else "")
    if code != 0 and "not running" in text.lower():
        snap = parse_status(text)
        snap.running = False
        _last_snapshot = snap
        return snap
    snap = parse_status(out)
    if code != 0 and not snap.rows:
        snap.running = False
        snap.error = err or out or f"status exit {code}"
    _last_snapshot = snap
    return snap


def dashboard_payload(snap: StatusSnapshot | None = None) -> dict:
    snap = snap or _last_snapshot or StatusSnapshot(running=False)
    modules = catalog()
    by_name = {r.name: r for r in snap.rows}
    rows = []
    for m in modules:
        st = by_name.get(m.id)
        process = st.status if st else ("—" if not m.enabled else "없음")
        pid = st.pid if st else None
        if not m.enabled:
            hb = "off"
        elif not m.has_descriptor or not m.desc_file:
            hb = "no-desc"
        elif process == "Alive":
            hb = "ok"
        else:
            hb = "missing"
        if m.enabled and process == "Alive" and hb != "ok":
            health = "하트비트 장애"
        elif m.enabled and process not in {"Alive"}:
            health = "프로세스 장애"
        elif not m.enabled and process == "Alive":
            health = "설정과 불일치"
        elif not m.enabled:
            health = "꺼짐"
        else:
            health = "정상"
        rows.append(
            {
                "id": m.id,
                "binary": m.binary,
                "binary_exists": m.binary_exists,
                "param_file": m.param_file,
                "desc_file": m.desc_file,
                "module_id": m.module_id,
                "enabled": m.enabled,
                "clone_of": m.clone_of,
                "restart_me": m.restart_me,
                "locked": m.locked,
                "has_descriptor": m.has_descriptor,
                "pid": pid,
                "process": process,
                "heartbeat": hb,
                "health": health,
                "argument": st.argument if st else (m.param_file or ""),
            }
        )
    ss_row = by_name.get("startstop")
    return {
        "running": snap.running,
        "startstop": {
            "alive": bool(ss_row and ss_row.status == "Alive") or snap.running,
            "pid": ss_row.pid if ss_row else None,
            "status": ss_row.status if ss_row else ("Alive" if snap.running else "stopped"),
        },
        "hostname_os": snap.hostname_os,
        "version": snap.version,
        "start_time": snap.start_time,
        "current_time": snap.current_time,
        "disk_kb": snap.disk_kb,
        "rings": snap.rings,
        "log_dir": snap.log_dir,
        "params_dir": snap.params_dir,
        "bin_dir": snap.bin_dir,
        "modules": rows,
        "error": snap.error,
    }


async def start_earthworm() -> dict:
    async with control_lock():
        env = parsed_core()
        if not load_app().setup_complete:
            raise RuntimeError("초기 설정을 먼저 완료하세요")
        lock = lock_info()
        if lock["exists"]:
            raise RuntimeError(
                f"락파일이 있습니다: {lock['path']} pid={lock['pid']} alive={lock['alive']}"
            )
        snap = await read_status()
        if snap.running:
            raise RuntimeError("startstop 이 이미 실행 중입니다")
        start_bin = str(bin_path(env, "startstop"))
        log = Path(env["EW_LOG"])
        pid, _, _ = await run_argv(
            [start_bin],
            cwd=env["EW_PARAMS"],
            env=source_env(),
            background=True,
            stdout_path=log / "web_startstop.out",
        )
        await asyncio.sleep(0.8)
        return dashboard_payload(await read_status()) | {"startstop_spawn_pid": pid}


async def stop_earthworm() -> dict:
    async with control_lock():
        env = parsed_core()
        pau = str(bin_path(env, "pau"))
        await run_argv([pau], cwd=env["EW_PARAMS"], env=source_env(), timeout=15)
        deadline = time.time() + 12
        snap = await read_status()
        while snap.running and time.time() < deadline:
            await asyncio.sleep(0.4)
            snap = await read_status()
        return dashboard_payload(snap)


async def pause_earthworm() -> dict:
    async with control_lock():
        snap = await read_status()
        if not snap.running:
            raise RuntimeError("startstop 이 실행 중이 아닙니다")
        env = parsed_core()
        stopm = str(bin_path(env, "stopmodule"))
        for row in snap.rows:
            if row.name in PROTECTED:
                continue
            if row.pid and row.status == "Alive":
                await run_argv(
                    [stopm, str(row.pid)],
                    cwd=env["EW_PARAMS"],
                    env=source_env(),
                    timeout=10,
                )
        await asyncio.sleep(0.3)
        return dashboard_payload(await read_status())


async def resume_earthworm() -> dict:
    async with control_lock():
        snap = await read_status()
        env = parsed_core()
        restart = str(bin_path(env, "restart"))
        for row in snap.rows:
            if row.status == "Stop" and row.pid:
                await run_argv(
                    [restart, str(row.pid)],
                    cwd=env["EW_PARAMS"],
                    env=source_env(),
                    timeout=10,
                )
        await asyncio.sleep(0.3)
        return dashboard_payload(await read_status())


async def reconfigure() -> dict:
    async with control_lock():
        env = parsed_core()
        exe = str(bin_path(env, "reconfigure"))
        await run_argv([exe], cwd=env["EW_PARAMS"], env=source_env(), timeout=15)
        await asyncio.sleep(0.3)
        return dashboard_payload(await read_status())


def _pid_for(module_id: str, snap: StatusSnapshot) -> int:
    for row in snap.rows:
        if row.name == module_id and row.pid:
            return row.pid
    raise KeyError(f"{module_id} 의 pid 를 찾을 수 없습니다")


async def module_stop(module_id: str) -> dict:
    if module_id == "statmgr":
        raise RuntimeError("statmgr 은 개별 중지하지 않습니다")
    async with control_lock():
        snap = await read_status()
        pid = _pid_for(module_id, snap)
        env = parsed_core()
        await run_argv(
            [str(bin_path(env, "stopmodule")), str(pid)],
            cwd=env["EW_PARAMS"],
            env=source_env(),
            timeout=10,
        )
        await asyncio.sleep(0.2)
        return dashboard_payload(await read_status())


async def module_restart(module_id: str) -> dict:
    async with control_lock():
        snap = await read_status()
        pid = _pid_for(module_id, snap)
        env = parsed_core()
        await run_argv(
            [str(bin_path(env, "restart")), str(pid)],
            cwd=env["EW_PARAMS"],
            env=source_env(),
            timeout=10,
        )
        await asyncio.sleep(0.2)
        return dashboard_payload(await read_status())


async def toggle_module(module_id: str, enabled: bool) -> dict:
    env = parsed_core()
    params = Path(env["EW_PARAMS"])
    ss_path = params / "startstop_unix.d"
    ss = parse_startstop(ss_path.read_text(encoding="utf-8", errors="replace"))
    if module_id == "statmgr" and not enabled:
        raise RuntimeError("statmgr 는 끄지 않는 것이 좋습니다")
    set_process_enabled(ss, module_id, enabled)
    ss_path.write_text(serialize_startstop(ss), encoding="utf-8")
    snap = await read_status()
    extra: dict = {"reconfigured": False, "stopped": False, "statmgr_restarted": False}
    if snap.running:
        if enabled:
            extra["reconfigured"] = True
            extra["statmgr_restarted"] = True
            payload = await reconfigure()
            return {"id": module_id, "enabled": enabled, **extra, **payload}
        try:
            extra["stopped"] = True
            payload = await module_stop(module_id)
            return {"id": module_id, "enabled": enabled, **extra, **payload}
        except KeyError:
            pass
    return {"id": module_id, "enabled": enabled, **extra, **dashboard_payload(await read_status())}
