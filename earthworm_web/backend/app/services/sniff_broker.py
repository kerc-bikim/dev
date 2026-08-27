from __future__ import annotations

import asyncio
import os
import signal
import uuid
from dataclasses import dataclass, field

from ..config import settings
from .app_store import sniff_session_limit
from .env import bash_path, parsed_core, source_env
from .seed import SAFE_TOKEN


@dataclass
class SniffSession:
    id: str
    tool: str
    argv: list[str]
    proc: asyncio.subprocess.Process | None = None
    lines: list[str] = field(default_factory=list)
    overflow: int = 0
    subscribers: set[asyncio.Queue] = field(default_factory=set)


_sessions: dict[str, SniffSession] = {}


def sniff_argv(payload: dict) -> list[str]:
    tool = payload.get("tool")
    if tool not in {"sniffwave", "sniffring"}:
        raise ValueError("tool 은 sniffwave 또는 sniffring 이어야 합니다")
    ring = str(payload.get("ring") or "")
    if not SAFE_TOKEN.match(ring) or ring == "FLAG_RING":
        raise ValueError("잘못된 링 이름")
    env = parsed_core()
    binary = str((os.path.join(env["EW_HOME"], env["EW_VERSION"], "bin", tool)))
    if tool == "sniffwave":
        sta = str(payload.get("sta") or "wild")
        comp = str(payload.get("comp") or "wild")
        net = str(payload.get("net") or "wild")
        loc = str(payload.get("loc") or "wild")
        flag = str(payload.get("flag") or "n")
        for tok in (sta, comp, net, loc, flag):
            if not SAFE_TOKEN.match(tok):
                raise ValueError("허용되지 않은 인자")
        if flag not in {"n", "y", "s"} and not flag.isdigit():
            raise ValueError("flag 는 n/y/s 또는 초 단위 숫자")
        argv = [binary, ring, sta, comp, net, loc, flag]
        if payload.get("verbose"):
            argv.append("verbose")
        return argv
    argv = [binary]
    if payload.get("no_flush"):
        argv.append("-n")
    argv.append(ring)
    inst = payload.get("instid")
    mod = payload.get("mod")
    typ = payload.get("type")
    if inst or mod or typ:
        for tok in (inst, mod, typ):
            if tok is None or not SAFE_TOKEN.match(str(tok)):
                raise ValueError("허용되지 않은 sniffring 필터")
        argv.extend([str(inst), str(mod), str(typ)])
    if payload.get("verbose"):
        argv.append("verbose")
    return argv


async def start_session(payload: dict) -> SniffSession:
    live = [s for s in _sessions.values() if s.proc and s.proc.returncode is None]
    limit = sniff_session_limit()
    if len(live) >= limit:
        raise RuntimeError(f"sniff 세션 상한 {limit}")
    argv = sniff_argv(payload)
    env = source_env(bash_path())
    proc = await asyncio.create_subprocess_exec(
        *argv,
        cwd=env.get("EW_PARAMS"),
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        start_new_session=True,
    )
    sess = SniffSession(id=uuid.uuid4().hex[:12], tool=payload["tool"], argv=argv, proc=proc)
    _sessions[sess.id] = sess
    asyncio.create_task(_pump(sess))
    return sess


async def _pump(sess: SniffSession) -> None:
    assert sess.proc and sess.proc.stdout
    try:
        while True:
            line = await sess.proc.stdout.readline()
            if not line:
                break
            text = line.decode("utf-8", errors="replace").rstrip("\n")
            sess.lines.append(text)
            if len(sess.lines) > settings.SNIFF_LINE_LIMIT:
                sess.lines = sess.lines[-settings.SNIFF_LINE_LIMIT :]
                sess.overflow += 1
                msg = {"type": "overflow", "dropped": sess.overflow}
            else:
                msg = {"type": "line", "text": text}
            dead = []
            for q in sess.subscribers:
                try:
                    q.put_nowait(msg)
                except asyncio.QueueFull:
                    dead.append(q)
            for q in dead:
                sess.subscribers.discard(q)
    finally:
        for q in list(sess.subscribers):
            q.put_nowait({"type": "closed"})


async def stop_session(session_id: str) -> None:
    sess = _sessions.get(session_id)
    if not sess:
        return
    proc = sess.proc
    if proc and proc.returncode is None:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except OSError:
            proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=3)
        except asyncio.TimeoutError:
            proc.kill()
    _sessions.pop(session_id, None)


def get_session(session_id: str) -> SniffSession | None:
    return _sessions.get(session_id)
