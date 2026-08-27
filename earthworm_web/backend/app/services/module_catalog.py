from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .app_store import load_app
from .commonvars import parse_key_values
from .env import bash_path, parsed_core
from .schema import family_fleet, family_priority, family_role
from .seed import CONTROL_BINS
from .startstop_file import parse_startstop


SKIP_PARAM_PREFIX = ("startstop", "earthworm")


@dataclass
class ModuleRow:
    id: str
    binary: str
    binary_exists: bool
    param_file: str | None
    desc_file: str | None
    module_id: str | None
    enabled: bool
    clone_of: str | None
    display_name: str
    restart_me: bool
    locked: bool
    has_descriptor: bool
    priority: bool = False
    role: str = "process"
    fleet: bool = False


def _is_exec(path: Path) -> bool:
    return path.is_file() and os.access(path, os.X_OK)


def _desc_for(params: Path, stem: str) -> Path | None:
    p = params / f"{stem}.desc"
    return p if p.is_file() else None


def catalog(env: dict[str, str] | None = None) -> list[ModuleRow]:
    env = env or parsed_core(bash_path())
    home = Path(env["EW_HOME"])
    ver = env["EW_VERSION"]
    bindir = home / ver / "bin"
    params = Path(env["EW_PARAMS"])
    ss_path = params / "startstop_unix.d"
    enabled: dict[str, bool] = {}
    if ss_path.is_file():
        doc = parse_startstop(ss_path.read_text(encoding="utf-8", errors="replace"))
        for p in doc.processes:
            enabled[p.name] = p.enabled
    clones = {c["id"]: c for c in load_app().clones}
    binaries = {p.name: p for p in bindir.iterdir() if _is_exec(p)} if bindir.is_dir() else {}
    param_files = []
    if params.is_dir():
        for p in sorted(params.glob("*.d")):
            if any(p.name.startswith(pref) for pref in SKIP_PARAM_PREFIX):
                continue
            param_files.append(p)

    rows: dict[str, ModuleRow] = {}
    statmgr_text = ""
    sm = params / "statmgr.d"
    if sm.is_file():
        statmgr_text = sm.read_text(encoding="utf-8", errors="replace")

    def has_desc_line(desc_name: str | None) -> bool:
        if not desc_name:
            return False
        return desc_name in statmgr_text

    for pf in param_files:
        stem = pf.stem
        kv = parse_key_values(pf.read_text(encoding="utf-8", errors="replace"))
        desc = _desc_for(params, stem)
        restart = False
        if desc:
            dkv = parse_key_values(desc.read_text(encoding="utf-8", errors="replace"))
            restart = "restartMe" in dkv
        clone = clones.get(stem)
        clone_of = (clone or {}).get("clone_of")
        family = clone_of or stem
        rows[stem] = ModuleRow(
            id=stem,
            binary=clone["binary"] if clone else stem,
            binary_exists=(clone["binary"] if clone else stem) in binaries
            or stem in binaries,
            param_file=pf.name,
            desc_file=desc.name if desc else None,
            module_id=kv.get("MyModuleId"),
            enabled=enabled.get(stem, False),
            clone_of=clone_of,
            display_name=stem,
            restart_me=restart,
            locked=stem == "statmgr",
            has_descriptor=has_desc_line(desc.name if desc else None),
            priority=family_priority(stem, clone_of),
            role=family_role(family),
            fleet=family_fleet(family),
        )

    for name, _path in binaries.items():
        if name in CONTROL_BINS or name in rows:
            continue
        if name not in enabled and name not in {p.stem for p in param_files}:
            rows[name] = ModuleRow(
                id=name,
                binary=name,
                binary_exists=True,
                param_file=None,
                desc_file=None,
                module_id=None,
                enabled=False,
                clone_of=None,
                display_name=name,
                restart_me=False,
                locked=False,
                has_descriptor=False,
                priority=family_priority(name),
                role=family_role(name),
                fleet=family_fleet(name),
            )

    for name, on in enabled.items():
        if name not in rows:
            rows[name] = ModuleRow(
                id=name,
                binary=name,
                binary_exists=name in binaries,
                param_file=None,
                desc_file=None,
                module_id=None,
                enabled=on,
                clone_of=None,
                display_name=name,
                restart_me=False,
                locked=name == "statmgr",
                has_descriptor=False,
                priority=family_priority(name),
                role=family_role(name),
                fleet=family_fleet(name),
            )

    order = list(enabled.keys()) + [k for k in rows if k not in enabled]
    seen = set()
    out: list[ModuleRow] = []
    for k in order:
        if k in seen or k not in rows:
            continue
        seen.add(k)
        out.append(rows[k])
    return out


def as_dict(row: ModuleRow) -> dict:
    return {
        "id": row.id,
        "binary": row.binary,
        "binary_exists": row.binary_exists,
        "param_file": row.param_file,
        "desc_file": row.desc_file,
        "module_id": row.module_id,
        "enabled": row.enabled,
        "clone_of": row.clone_of,
        "display_name": row.display_name,
        "restart_me": row.restart_me,
        "locked": row.locked,
        "has_descriptor": row.has_descriptor,
        "priority": row.priority,
        "role": row.role,
        "fleet": row.fleet,
    }
