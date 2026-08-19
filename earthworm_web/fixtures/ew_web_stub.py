#!/usr/bin/env python3
"""Earthworm CLI stand-in for web-control development (no System V shm).

Copied to bin/ as startstop, status, pau, restart, stopmodule, reconfigure,
sniffwave, sniffring, and module names. Real Earthworm binaries replace these
on a production host.
"""
from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

STATE_NAME = ".ew_web_stub_state.json"
LOCK_NAME = "startstop_unix.d.lock"
STOP_FLAG = ".ew_web_stub_stop"


def _log_dir() -> Path:
    raw = os.environ.get("EW_LOG") or "."
    return Path(raw)


def _params_dir() -> Path:
    raw = os.environ.get("EW_PARAMS") or "."
    return Path(raw)


def _bin_dir() -> Path:
    home = os.environ.get("EW_HOME", "")
    ver = os.environ.get("EW_VERSION", "")
    if home and ver:
        return Path(home) / ver / "bin"
    return Path(sys.argv[0]).resolve().parent


def state_path() -> Path:
    return _log_dir() / STATE_NAME


def lock_path() -> Path:
    return _log_dir() / LOCK_NAME


def load_state() -> dict | None:
    p = state_path()
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def save_state(state: dict) -> None:
    p = state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    tmp.replace(p)


def alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def parse_process_blocks(text: str) -> list[dict]:
    lines = text.splitlines()
    blocks: list[dict] = []
    i = 0
    proc_re = re.compile(r"^(\s*#\s*)?Process\s+\"([^\"]+)\"")
    class_re = re.compile(r"^(\s*#\s*)?Class/Priority\s+(\S+)\s+(\S+)")
    while i < len(lines):
        m = proc_re.match(lines[i])
        if not m:
            i += 1
            continue
        enabled = m.group(1) is None
        cmd = m.group(2).strip()
        cls, prio = "OTHER", "0"
        j = i + 1
        while j < len(lines):
            cm = class_re.match(lines[j])
            if cm:
                cls, prio = cm.group(2), cm.group(3)
                j += 1
                continue
            stripped = lines[j].strip()
            if stripped.startswith("Process") or stripped.startswith("# Process"):
                break
            if stripped.startswith("Ring") or stripped.startswith("nRing"):
                break
            if stripped == "":
                j += 1
                break
            j += 1
        parts = cmd.split()
        blocks.append(
            {
                "command": cmd,
                "name": parts[0] if parts else cmd,
                "args": parts[1:],
                "class": cls,
                "priority": prio,
                "enabled": enabled,
            }
        )
        i = j
    return blocks


def parse_rings(text: str) -> list[tuple[str, int]]:
    rings = []
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("#"):
            continue
        m = re.match(r"^Ring\s+(\S+)\s+(\d+)", s)
        if m:
            rings.append((m.group(1), int(m.group(2))))
    return rings


def spawn_module(name: str, args: list[str], cls: str, prio: str) -> dict:
    binary = _bin_dir() / name
    argv = [str(binary), *args]
    env = os.environ.copy()
    proc = subprocess.Popen(
        argv,
        cwd=str(_params_dir()),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    return {
        "name": name,
        "pid": proc.pid,
        "status": "Alive",
        "argument": " ".join(args),
        "class": cls,
        "priority": prio,
        "argv": argv,
    }


def cmd_startstop(_argv: list[str]) -> int:
    _log_dir().mkdir(parents=True, exist_ok=True)
    if lock_path().is_file():
        try:
            old = int(lock_path().read_text(encoding="utf-8").strip().split()[0])
        except (ValueError, IndexError):
            old = None
        if alive(old):
            sys.stderr.write("startstop already running\n")
            return 1
    cfg = _params_dir() / "startstop_unix.d"
    text = cfg.read_text(encoding="utf-8", errors="replace") if cfg.is_file() else ""
    blocks = [b for b in parse_process_blocks(text) if b["enabled"]]
    children = []
    for b in blocks:
        children.append(spawn_module(b["name"], b["args"], b["class"], b["priority"]))
    lock_path().write_text(f"{os.getpid()}\n", encoding="utf-8")
    state = {
        "startstop_pid": os.getpid(),
        "start_time": time.strftime("%a %b %d %H:%M:%S %Y"),
        "modules": children,
        "rings": parse_rings(text),
    }
    save_state(state)
    stop = _log_dir() / STOP_FLAG
    if stop.exists():
        stop.unlink()

    def _term(_signum, _frame):
        stop.touch()

    signal.signal(signal.SIGTERM, _term)
    signal.signal(signal.SIGINT, _term)
    while not stop.exists():
        time.sleep(0.4)
        st = load_state() or state
        for m in st.get("modules", []):
            if m.get("status") == "Stop":
                continue
            if not alive(m.get("pid")):
                m["status"] = "Dead"
        st["startstop_pid"] = os.getpid()
        save_state(st)
    st = load_state() or state
    for m in st.get("modules", []):
        pid = m.get("pid")
        if pid and alive(pid):
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass
    if lock_path().exists():
        lock_path().unlink()
    if stop.exists():
        stop.unlink()
    if state_path().exists():
        state_path().unlink()
    return 0


def cmd_status(_argv: list[str]) -> int:
    st = load_state()
    if not st or not alive(st.get("startstop_pid")):
        sys.stderr.write("startstop is not running\n")
        return 1
    host = os.uname().nodename
    params = os.environ.get("EW_PARAMS", "")
    log = os.environ.get("EW_LOG", "")
    bindir = str(_bin_dir())
    print("                    EARTHWORM SYSTEM STATUS")
    print()
    print(f"        Hostname-OS: {host}-Linux    Version: v8.0-web-stub")
    print(f"           Start time: {st.get('start_time', '')}")
    print(f"         Current time: {time.strftime('%a %b %d %H:%M:%S %Y')}")
    print("           Disk space: 18200000 KB available")
    print()
    for i, (name, size) in enumerate(st.get("rings") or [], start=1):
        print(f"           Ring  {i} name/key/size:  {name} / 0 / {size} kb")
    print()
    print(f"           Startstop's Log Dir:   {log}")
    print(f"           Startstop's Params Dir:{params}")
    print(f"           Startstop's Bin Dir:   {bindir}")
    print()
    print("  Process Name      Process ID   Status     Class/Priority  Argument")
    print("  -----------      ----------   ------     --------------  --------")
    print(
        f"  {'startstop':<16} {st.get('startstop_pid'):<12} {'Alive':<10} {'OTHER 0':<16}"
    )
    for m in st.get("modules", []):
        status = m.get("status", "Alive")
        if status != "Stop" and not alive(m.get("pid")):
            status = "Dead"
        cls = f"{m.get('class', 'OTHER')} {m.get('priority', '0')}"
        print(
            f"  {m.get('name', ''):<16} {m.get('pid', 0):<12} {status:<10} {cls:<16} {m.get('argument', '')}"
        )
    return 0


def _require_state() -> dict:
    st = load_state()
    if not st or not alive(st.get("startstop_pid")):
        sys.stderr.write("startstop is not running\n")
        sys.exit(1)
    return st


def cmd_pau(_argv: list[str]) -> int:
    st = load_state()
    if not st:
        return 0
    (_log_dir() / STOP_FLAG).touch()
    sspid = st.get("startstop_pid")
    if sspid and alive(sspid):
        try:
            os.kill(sspid, signal.SIGTERM)
        except OSError:
            pass
    for m in st.get("modules", []):
        pid = m.get("pid")
        if pid and alive(pid):
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass
    return 0


def cmd_stopmodule(argv: list[str]) -> int:
    if len(argv) < 2 or not argv[1].isdigit():
        sys.stderr.write("usage: stopmodule <pid>\n")
        return 2
    pid = int(argv[1])
    st = _require_state()
    for m in st.get("modules", []):
        if int(m.get("pid") or 0) == pid:
            if alive(pid):
                try:
                    os.kill(pid, signal.SIGTERM)
                except OSError:
                    pass
            m["status"] = "Stop"
            save_state(st)
            return 0
    sys.stderr.write(f"pid {pid} not found\n")
    return 1


def cmd_restart(argv: list[str]) -> int:
    if len(argv) < 2 or not argv[1].isdigit():
        sys.stderr.write("usage: restart <pid>\n")
        return 2
    pid = int(argv[1])
    st = _require_state()
    for m in st.get("modules", []):
        if int(m.get("pid") or 0) == pid:
            if alive(pid):
                try:
                    os.kill(pid, signal.SIGTERM)
                except OSError:
                    pass
            args = str(m.get("argument") or "").split()
            child = spawn_module(m["name"], args, m.get("class", "OTHER"), m.get("priority", "0"))
            m.update(child)
            save_state(st)
            return 0
    sys.stderr.write(f"pid {pid} not found\n")
    return 1


def cmd_reconfigure(_argv: list[str]) -> int:
    st = _require_state()
    cfg = _params_dir() / "startstop_unix.d"
    text = cfg.read_text(encoding="utf-8", errors="replace") if cfg.is_file() else ""
    wanted = [b for b in parse_process_blocks(text) if b["enabled"]]
    have = {m["name"] for m in st.get("modules", []) if m.get("status") != "Stop"}
    for b in wanted:
        if b["name"] not in have:
            st.setdefault("modules", []).append(
                spawn_module(b["name"], b["args"], b["class"], b["priority"])
            )
    st["rings"] = parse_rings(text)
    save_state(st)
    return 0


def cmd_sniff(argv: list[str]) -> int:
    ring = argv[1] if len(argv) > 1 else "WAVE_RING"
    n = 0
    while True:
        n += 1
        now = time.strftime("%H:%M:%S")
        print(f"{now}  {ring}  STA.HHZ.IU.--  100.0 sps  stub packet {n}", flush=True)
        time.sleep(0.7)


def cmd_module(name: str, argv: list[str]) -> int:
    log = _log_dir()
    log.mkdir(parents=True, exist_ok=True)
    day = time.strftime("%Y%m%d")
    path = log / f"{name}_{day}.log"
    stop = False

    def _term(_s, _f):
        nonlocal stop
        stop = True

    signal.signal(signal.SIGTERM, _term)
    signal.signal(signal.SIGINT, _term)
    arg = " ".join(argv[1:])
    while not stop:
        line = time.strftime("%Y-%m-%d %H:%M:%S") + f"  {name}: heartbeat ok  {arg}\n"
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line)
        time.sleep(2)
    return 0


def main() -> int:
    name = Path(sys.argv[0]).name
    argv = [name, *sys.argv[1:]]
    dispatch = {
        "startstop": cmd_startstop,
        "status": cmd_status,
        "pau": cmd_pau,
        "stopmodule": cmd_stopmodule,
        "restart": cmd_restart,
        "reconfigure": cmd_reconfigure,
        "sniffwave": cmd_sniff,
        "sniffring": cmd_sniff,
    }
    if name in dispatch:
        return dispatch[name](argv)
    return cmd_module(name, argv)


if __name__ == "__main__":
    raise SystemExit(main())
