from __future__ import annotations

import re

SET_RE = re.compile(r"^(\s*#\s*)?SetEnvVariable\s+(\S+)\s+(.*)$")


def parse_commonvars(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for ln in text.splitlines():
        m = SET_RE.match(ln.strip())
        if m and m.group(1) is None:
            out[m.group(2)] = m.group(3).strip()
    return out


def upsert_commonvars(text: str, updates: dict[str, str]) -> str:
    lines = text.splitlines()
    seen: set[str] = set()
    out: list[str] = []
    for ln in lines:
        m = SET_RE.match(ln.strip())
        if m and m.group(2) in updates:
            out.append(f"SetEnvVariable {m.group(2)} {updates[m.group(2)]}")
            seen.add(m.group(2))
        else:
            out.append(ln)
    for key, val in updates.items():
        if key not in seen:
            out.append(f"SetEnvVariable {key} {val}")
    return "\n".join(out).rstrip() + "\n"


def parse_key_values(text: str) -> dict[str, str]:
    """Best-effort token/value pairs for .d / .desc command files."""
    out: dict[str, str] = {}
    for ln in text.splitlines():
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        parts = s.split(None, 1)
        if len(parts) == 2:
            out[parts[0]] = parts[1]
        elif len(parts) == 1:
            out[parts[0]] = ""
    return out


def parse_commands(text: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for ln in text.splitlines():
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        parts = s.split(None, 1)
        key = parts[0]
        val = parts[1] if len(parts) > 1 else ""
        out.setdefault(key, []).append(val)
    return out


def replace_command_value(text: str, key: str, value: str) -> tuple[str, bool]:
    lines = text.splitlines()
    found = False
    out: list[str] = []
    pat = re.compile(rf"^(\s*#\s*)?{re.escape(key)}\b(.*)$")
    for ln in lines:
        m = pat.match(ln)
        if m and m.group(1) is None:
            out.append(f"{key}     {value}")
            found = True
        else:
            out.append(ln)
    return "\n".join(out).rstrip() + "\n", found


def replace_repeated_command(text: str, key: str, values: list[str]) -> str:
    lines = text.splitlines()
    pat = re.compile(rf"^(\s*#\s*)?{re.escape(key)}\b")
    first_idx: int | None = None
    out: list[str] = []
    for ln in lines:
        m = pat.match(ln)
        if m and m.group(1) is None:
            if first_idx is None:
                first_idx = len(out)
            continue
        out.append(ln)
    block = [f"{key}     {v}" for v in values if str(v).strip() != ""]
    if first_idx is None:
        out.extend(block)
    else:
        out[first_idx:first_idx] = block
    return "\n".join(out).rstrip() + "\n"


def upsert_command_value(text: str, key: str, value: str) -> str:
    new, found = replace_command_value(text, key, value)
    if found:
        return new
    if not new.endswith("\n"):
        new += "\n"
    return new + f"{key}     {value}\n"
