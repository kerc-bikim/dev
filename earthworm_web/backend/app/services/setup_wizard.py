from __future__ import annotations

import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

from .app_store import load_app, mark_setup_complete, save_app
from .commonvars import replace_command_value, upsert_commonvars
from .earthworm_d import (
    MAX_RING,
    parse_earthworm_d,
    parse_inst_names,
    replace_startstop_rings,
)
from .env import apply_directories, bash_path, parsed_core, rewrite_bash
from .ipc_diag import require_stopped
from .seed import SAFE_NAME, fixtures_dir
from .startstop_file import parse_startstop, serialize_startstop, set_rings as write_ss_rings

DEFAULT_RINGS = [
    {"name": "STATUS_RING", "key": 1040, "size": 128, "in_startstop": True},
    {"name": "WAVE_RING", "key": 1000, "size": 1024, "in_startstop": True},
    {"name": "PICK_RING", "key": 1005, "size": 1024, "in_startstop": True},
    {"name": "HYPO_RING", "key": 1015, "size": 1024, "in_startstop": True},
    {"name": "BINDER_RING", "key": 1020, "size": 256, "in_startstop": False},
]


def version_tree(env: dict[str, str]) -> Path:
    return Path(env["EW_HOME"]) / env["EW_VERSION"]


def copy_if_missing(src: Path, dest: Path) -> bool:
    if dest.exists():
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    return True


def backup_params(params: Path) -> Path | None:
    targets = ["startstop_unix.d", "earthworm.d", "earthworm_commonvars.d"]
    existing = [params / n for n in targets if (params / n).is_file()]
    if not existing:
        return None
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    dest = params / "web_backup" / stamp
    dest.mkdir(parents=True, exist_ok=True)
    for p in existing:
        shutil.copy2(p, dest / p.name)
    return dest


def set_directories(ew_home: str, ew_version: str, ew_run_dir: str, retention_days: int = 14) -> dict:
    require_stopped("디렉터리·경로를 바꿀 수 없습니다")
    startstop = Path(ew_home) / ew_version / "bin" / "startstop"
    if not startstop.is_file():
        raise FileNotFoundError(f"startstop 이 없습니다: {startstop}")
    core = apply_directories(bash_path(), ew_home, ew_version, ew_run_dir)
    meta = load_app()
    meta.log_retention_days = int(retention_days)
    save_app(meta)
    return core


def set_installation(inst: str) -> dict:
    env = parsed_core()
    tree = version_tree(env)
    params = Path(env["EW_PARAMS"])
    global_src = tree / "environment" / "earthworm_global.d"
    if not global_src.is_file():
        raise FileNotFoundError("environment/earthworm_global.d 가 없습니다")
    names = parse_inst_names(global_src.read_text(encoding="utf-8", errors="replace"))
    if inst not in names:
        raise ValueError(f"Inst 목록에 없습니다: {inst}")
    rewrite_bash(bash_path(), {"EW_INSTALLATION": inst})
    for name in ("earthworm.d", "earthworm_global.d", "earthworm_commonvars.d"):
        copy_if_missing(tree / "environment" / name, params / name)
    tmpl = tree / "params"
    if not tmpl.is_dir():
        tmpl = fixtures_dir() / env["EW_VERSION"] / "params"
    if tmpl.is_dir():
        for p in tmpl.glob("*"):
            if p.is_file():
                copy_if_missing(p, params / p.name)
    cv = params / "earthworm_commonvars.d"
    if cv.is_file():
        cv.write_text(
            upsert_commonvars(
                cv.read_text(encoding="utf-8", errors="replace"), {"EW_INST_ID": inst}
            ),
            encoding="utf-8",
        )
    return parsed_core()


def apply_rings(rows: list[dict]) -> None:
    from .ipc_diag import lock_info

    try:
        info = lock_info()
        if info.get("alive"):
            raise RuntimeError(
                "startstop 실행 중에는 링 크기·순서를 바꿀 수 없습니다. 종료 후 수정하세요."
            )
    except FileNotFoundError:
        pass
    env = parsed_core()
    params = Path(env["EW_PARAMS"])
    if len(rows) > MAX_RING:
        raise ValueError(f"링은 {MAX_RING} 개를 넘을 수 없습니다")
    ss_rings: list[tuple[str, int]] = []
    table_rings: list[tuple[str, int]] = []
    seen_keys: set[int] = set()
    seen_names: set[str] = set()
    first_ss = None
    for row in rows:
        name = str(row["name"])
        key = int(row["key"])
        size = int(row["size"])
        if not SAFE_NAME.match(name):
            raise ValueError(f"잘못된 링 이름: {name}")
        in_ss = bool(row.get("in_startstop", True))
        if name == "FLAG_RING" and in_ss:
            raise ValueError("FLAG_RING 은 startstop 목록에 넣을 수 없습니다")
        if size < 1 or size > 1_048_576:
            raise ValueError(f"링 크기 범위 오류: {name}")
        if key in seen_keys:
            raise ValueError(f"링 키 중복: {key}")
        if name in seen_names:
            raise ValueError(f"링 이름 중복: {name}")
        seen_keys.add(key)
        seen_names.add(name)
        table_rings.append((name, key))
        if in_ss:
            if first_ss is None:
                first_ss = name
            ss_rings.append((name, size))
    if not ss_rings:
        raise ValueError("startstop 에 넣을 링이 하나 이상 필요합니다")
    if first_ss == "FLAG_RING":
        raise ValueError("첫 링이 FLAG_RING 이면 안 됩니다")
    ew_path = params / "earthworm.d"
    if not ew_path.is_file():
        raise FileNotFoundError("earthworm.d 가 없습니다. 설치 ID 단계를 먼저 마치세요")
    ss_path = params / "startstop_unix.d"
    if not ss_path.is_file():
        raise FileNotFoundError("startstop_unix.d 가 없습니다")
    backup_params(params)
    ew = parse_earthworm_d(ew_path.read_text(encoding="utf-8", errors="replace"))
    replace_startstop_rings(ew, table_rings)
    ew_path.write_text(ew.text(), encoding="utf-8")
    ss = parse_startstop(ss_path.read_text(encoding="utf-8", errors="replace"))
    write_ss_rings(ss, ss_rings)
    ss_path.write_text(serialize_startstop(ss), encoding="utf-8")
    _tune_statmgr(params)


def _tune_statmgr(params: Path) -> None:
    sm = params / "statmgr.d"
    if not sm.is_file():
        return
    text = sm.read_text(encoding="utf-8", errors="replace")
    text, _ = replace_command_value(text, "RingName", "STATUS_RING")
    text, found = replace_command_value(text, "CheckAllRings", "1")
    if not found:
        text = text.rstrip() + "\nCheckAllRings  1\n"
    lines = []
    for ln in text.splitlines():
        if "copystatus" in ln and "HYPO_RING" in ln and not ln.strip().startswith("#"):
            lines.append("# " + ln.lstrip())
        else:
            lines.append(ln)
    sm.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def enable_min_modules() -> None:
    env = parsed_core()
    params = Path(env["EW_PARAMS"])
    ss_path = params / "startstop_unix.d"
    ss = parse_startstop(ss_path.read_text(encoding="utf-8", errors="replace"))
    for p in ss.processes:
        p.enabled = p.name == "statmgr"
    if ss.process_named("statmgr") is None:
        from .startstop_file import upsert_process

        upsert_process(ss, "statmgr statmgr.d", enabled=True)
    backup_params(params)
    ss_path.write_text(serialize_startstop(ss), encoding="utf-8")


def validate() -> list[dict]:
    checks: list[dict] = []

    def add(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"name": name, "ok": ok, "detail": detail})

    try:
        env = parsed_core()
    except Exception as exc:
        add("ew_linux.bash", False, str(exc))
        return checks
    add("ew_linux.bash", True, env.get("EW_VERSION", ""))
    tree = version_tree(env)
    bindir = tree / "bin"
    for exe in ("startstop", "status", "pau", "statmgr"):
        p = bindir / exe
        add(f"bin/{exe}", p.is_file() and os.access(p, os.X_OK), str(p))
    params = Path(env["EW_PARAMS"])
    for name in ("earthworm.d", "earthworm_global.d", "earthworm_commonvars.d"):
        add(f"EW_PARAMS/{name}", (params / name).is_file())
    inst = env.get("EW_INSTALLATION", "")
    gpath = params / "earthworm_global.d"
    names = parse_inst_names(gpath.read_text(encoding="utf-8", errors="replace")) if gpath.is_file() else []
    add(f"설치 ID {inst}", inst in names)
    ss_path = params / "startstop_unix.d"
    if ss_path.is_file():
        ss = parse_startstop(ss_path.read_text(encoding="utf-8", errors="replace"))
        ss_names = [n for n, _s, on in ss.rings if on]
        first = ss_names[0] if ss_names else ""
        add(f"첫 링 {first or '?'}", first != "" and first != "FLAG_RING")
        add("FLAG_RING 미포함", "FLAG_RING" not in ss_names)
        add("MAX_RING", len(ss_names) <= MAX_RING, str(len(ss_names)))
        ew = parse_earthworm_d((params / "earthworm.d").read_text(encoding="utf-8", errors="replace"))
        missing = [n for n in ss_names if n not in ew.ring_names()]
        add("링 이름 ⊆ earthworm.d", not missing, ", ".join(missing))
    else:
        add("startstop_unix.d", False)
    log = Path(env["EW_LOG"])
    writable = False
    try:
        log.mkdir(parents=True, exist_ok=True)
        probe = log / ".web_write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        writable = True
    except OSError:
        writable = False
    add("log/ 쓰기", writable, str(log))
    return checks


def complete_setup() -> dict:
    already = load_app().setup_complete
    if not already:
        enable_min_modules()
    checks = validate()
    if not all(c["ok"] for c in checks):
        failed = [c["name"] for c in checks if not c["ok"]]
        raise ValueError("검증 실패: " + ", ".join(failed))
    meta = mark_setup_complete()
    return {"setup_complete": meta.setup_complete, "setup_at": meta.setup_at, "checks": checks}


def import_existing() -> dict:
    env = parsed_core()
    params = Path(env["EW_PARAMS"])
    rings = []
    ss_path = params / "startstop_unix.d"
    ew_path = params / "earthworm.d"
    keys: dict[str, int] = {}
    if ew_path.is_file():
        ew = parse_earthworm_d(ew_path.read_text(encoding="utf-8", errors="replace"))
        keys = {n: k for n, k, on in ew.rings() if on}
    ss_names: list[tuple[str, int]] = []
    if ss_path.is_file():
        ss = parse_startstop(ss_path.read_text(encoding="utf-8", errors="replace"))
        ss_names = [(n, s) for n, s, on in ss.rings if on]
        ss_set = {n for n, _s in ss_names}
        for name, size in ss_names:
            rings.append(
                {
                    "name": name,
                    "key": keys.get(name, 0),
                    "size": size,
                    "in_startstop": True,
                }
            )
        for name, key in keys.items():
            if name in ss_set or name == "FLAG_RING":
                continue
            rings.append({"name": name, "key": key, "size": 256, "in_startstop": False})
    return {
        "directories": env,
        "installation": env.get("EW_INSTALLATION"),
        "rings": rings or DEFAULT_RINGS,
        "has_params": (params / "earthworm.d").is_file() and ss_path.is_file(),
    }


def setup_status() -> dict:
    meta = load_app()
    try:
        env = parsed_core()
        home = env.get("EW_HOME", str(Path.home()))
        versions = []
        hp = Path(home)
        if hp.is_dir():
            versions = [p.name for p in hp.iterdir() if (p / "bin" / "startstop").is_file()]
        params_ok = (Path(env["EW_PARAMS"]) / "earthworm.d").is_file()
        return {
            "setup_complete": meta.setup_complete,
            "setup_at": meta.setup_at,
            "ew_home": env.get("EW_HOME"),
            "ew_version": env.get("EW_VERSION"),
            "ew_run_dir": env.get("EW_RUN_DIR"),
            "versions": versions,
            "has_existing_params": params_ok,
            "bash_path": str(bash_path()),
        }
    except Exception as exc:
        return {
            "setup_complete": meta.setup_complete,
            "setup_at": meta.setup_at,
            "ew_home": None,
            "ew_version": None,
            "ew_run_dir": None,
            "versions": [],
            "has_existing_params": False,
            "bash_path": str(bash_path()),
            "error": str(exc),
        }


def setup_defaults() -> dict:
    env = parsed_core()
    tree = version_tree(env)
    gpath = tree / "environment" / "earthworm_global.d"
    insts = parse_inst_names(gpath.read_text(encoding="utf-8", errors="replace")) if gpath.is_file() else ["INST_UNKNOWN"]
    return {
        "directories": {
            "EW_HOME": env.get("EW_HOME"),
            "EW_VERSION": env.get("EW_VERSION"),
            "EW_RUN_DIR": env.get("EW_RUN_DIR") or str(Path(env["EW_HOME"]) / "run_working"),
            "retention_days": load_app().log_retention_days,
        },
        "installations": insts,
        "rings": DEFAULT_RINGS,
        "hostname": os.uname().nodename,
    }
