from __future__ import annotations

import shutil
from pathlib import Path

from .app_store import load_app, save_app
from .commonvars import parse_key_values, replace_command_value
from .earthworm_d import add_module, comment_module, next_module_id, parse_earthworm_d
from .env import bash_path, parsed_core
from .seed import SAFE_NAME
from .startstop_file import parse_startstop, serialize_startstop, upsert_process

MAX_PROCESS_CMD = 199


class CloneError(ValueError):
    pass


def _contained(base: Path, name: str) -> Path:
    ident = name
    if name.endswith(".d") or name.endswith(".desc"):
        ident = name.rsplit(".", 1)[0]
    if not SAFE_NAME.match(ident) or "/" in name or "\\" in name or ".." in name:
        raise CloneError("이름은 영문·숫자·밑줄만, 32자 이하입니다")
    base_r = base.resolve()
    path = (base_r / name).resolve()
    if path.parent != base_r:
        raise CloneError("경로가 허용 범위를 벗어났습니다")
    return path


def clone_module(source_id: str, new_name: str) -> dict:
    if not SAFE_NAME.match(new_name):
        raise CloneError("이름은 영문·숫자·밑줄만, 32자 이하입니다")
    env = parsed_core(bash_path())
    home = Path(env["EW_HOME"])
    ver = env["EW_VERSION"]
    bindir = home / ver / "bin"
    params = Path(env["EW_PARAMS"])
    src_bin = _contained(bindir, source_id)
    if not src_bin.is_file():
        raise CloneError(f"바이너리가 없습니다: {source_id}")
    dest_bin = _contained(bindir, new_name)
    dest_d = _contained(params, f"{new_name}.d")
    if dest_bin.exists() or dest_d.exists():
        raise CloneError("이미 같은 이름의 모듈이 있습니다")
    src_d = _contained(params, f"{source_id}.d")
    if not src_d.is_file():
        raise CloneError(f"{source_id}.d 가 없습니다")
    cmd = f"{new_name} {new_name}.d"
    if len(cmd) > MAX_PROCESS_CMD:
        raise CloneError("Process 명령이 너무 깁니다")

    ew_path = params / "earthworm.d"
    ew = parse_earthworm_d(ew_path.read_text(encoding="utf-8", errors="replace"))
    mod_const = "MOD_" + new_name.upper()
    if any(n == mod_const for n, _i, _on in ew.modules()):
        raise CloneError("Module 상수가 이미 있습니다")
    mid = next_module_id(ew)
    add_module(ew, mod_const, mid)

    shutil.copy2(src_bin, dest_bin)
    dest_bin.chmod(src_bin.stat().st_mode)

    d_text = src_d.read_text(encoding="utf-8", errors="replace")
    d_text, _ = replace_command_value(d_text, "MyModuleId", mod_const)
    dest_d.write_text(d_text, encoding="utf-8")

    desc_name = None
    src_desc = _contained(params, f"{source_id}.desc")
    if src_desc.is_file():
        desc_text = src_desc.read_text(encoding="utf-8", errors="replace")
        desc_text, _ = replace_command_value(desc_text, "modName", new_name)
        desc_text, _ = replace_command_value(desc_text, "modId", mod_const)
        dest_desc = _contained(params, f"{new_name}.desc")
        dest_desc.write_text(desc_text, encoding="utf-8")
        desc_name = dest_desc.name
        sm = params / "statmgr.d"
        if sm.is_file():
            sm_text = sm.read_text(encoding="utf-8", errors="replace")
            if f"Descriptor     {desc_name}" not in sm_text and f"Descriptor {desc_name}" not in sm_text:
                if not sm_text.endswith("\n"):
                    sm_text += "\n"
                sm.write_text(sm_text + f"Descriptor     {desc_name}\n", encoding="utf-8")

    ew_path.write_text(ew.text(), encoding="utf-8")
    ss_path = params / "startstop_unix.d"
    ss = parse_startstop(ss_path.read_text(encoding="utf-8", errors="replace"))
    upsert_process(ss, cmd, enabled=False)
    ss_path.write_text(serialize_startstop(ss), encoding="utf-8")

    meta = load_app()
    meta.clones.append(
        {
            "id": new_name,
            "clone_of": source_id,
            "binary": new_name,
            "param_file": dest_d.name,
            "module_id": mod_const,
            "desc_file": desc_name,
        }
    )
    save_app(meta)
    return meta.clones[-1]


def delete_clone(module_id: str) -> None:
    if not SAFE_NAME.match(module_id):
        raise CloneError("이름은 영문·숫자·밑줄만, 32자 이하입니다")
    meta = load_app()
    rec = next((c for c in meta.clones if c["id"] == module_id), None)
    if rec is None:
        raise CloneError("복제본만 삭제할 수 있습니다")
    env = parsed_core(bash_path())
    bindir = Path(env["EW_HOME"]) / env["EW_VERSION"] / "bin"
    params = Path(env["EW_PARAMS"])
    ss_path = params / "startstop_unix.d"
    ss = parse_startstop(ss_path.read_text(encoding="utf-8", errors="replace"))
    ss.processes = [p for p in ss.processes if p.name != module_id]
    ss_path.write_text(serialize_startstop(ss), encoding="utf-8")
    for name in (f"{module_id}.d", f"{module_id}.desc"):
        p = _contained(params, name)
        if p.is_file():
            p.unlink()
    b = _contained(bindir, module_id)
    if b.is_file():
        b.unlink()
    ew_path = params / "earthworm.d"
    if ew_path.is_file():
        ew = parse_earthworm_d(ew_path.read_text(encoding="utf-8", errors="replace"))
        comment_module(ew, rec.get("module_id") or ("MOD_" + module_id.upper()))
        ew_path.write_text(ew.text(), encoding="utf-8")
    sm = params / "statmgr.d"
    if sm.is_file() and rec.get("desc_file"):
        want = rec["desc_file"]
        kept = []
        for ln in sm.read_text(encoding="utf-8", errors="replace").splitlines():
            parts = ln.strip().lstrip("#").split()
            if len(parts) >= 2 and parts[0] == "Descriptor" and parts[1] == want:
                continue
            kept.append(ln)
        sm.write_text("\n".join(kept).rstrip() + "\n", encoding="utf-8")
    meta.clones = [c for c in meta.clones if c["id"] != module_id]
    save_app(meta)
