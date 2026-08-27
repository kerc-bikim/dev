from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import settings
from .app_store import load_app, save_app
from .clone import MAX_PROCESS_CMD, CloneError, clone_module, delete_clone
from .commonvars import (
    parse_commands,
    parse_commonvars,
    parse_key_values,
    replace_command_value,
    replace_repeated_command,
    upsert_command_value,
    upsert_commonvars,
)
from .control import last_snapshot, reconfigure as do_reconfigure
from .earthworm_d import parse_earthworm_d
from .env import bash_path, parsed_core
from .module_catalog import catalog
from .schema import PRIORITY_IO, family_spec, load_families, process_fields
from .seed import SAFE_NAME
from .startstop_file import parse_startstop, serialize_startstop, set_process_enabled, upsert_process

MAX_CHILD = 256
EPHEMERAL_FLOOR = 32768

LISTEN_TYPES = {"tcp_listen", "udp_port"}
TANK_KEYS = {"Tank", "TankStructFile"}

SUGGEST_PORTS = {
    "q3302ew": ("SourcePortControl", 16030, 2),
    "export_generic": ("ServerPort", 16005, 1),
    "export_scnl": ("ServerPort", 16015, 1),
    "import_pasv": ("ReceiverPort", 16025, 1),
    "wave_serverV": ("ServerPort", 16022, 1),
}

SUGGEST_NAMES = {
    "q3302ew": "q3302ew_sta",
    "slink2ew": "slink2ew_n",
    "export_generic": "export_generic_n",
    "export_scnl": "export_scnl_n",
    "import_pasv": "import_pasv_n",
    "wave_serverV": "wave_serverV_n",
}


class ComposeError(ValueError):
    def __init__(self, message: str, issues: list[dict] | None = None):
        super().__init__(message)
        self.issues = issues or []


def _env() -> dict[str, str]:
    return parsed_core(bash_path())


def _params() -> Path:
    return Path(_env()["EW_PARAMS"])


def _bindir() -> Path:
    env = _env()
    return Path(env["EW_HOME"]) / env["EW_VERSION"] / "bin"


def _startstop_rings() -> set[str]:
    ss_path = _params() / "startstop_unix.d"
    names: set[str] = set()
    if ss_path.is_file():
        doc = parse_startstop(ss_path.read_text(encoding="utf-8", errors="replace"))
        for n, _s, on in doc.rings:
            if on:
                names.add(n)
    return names


def _issue(code: str, message: str, instance: str | None = None, field: str | None = None, level: str = "error") -> dict:
    return {"code": code, "message": message, "instance": instance, "field": field, "level": level}


def _values_from_text(family: str, text: str) -> dict[str, Any]:
    cmds = parse_commands(text)
    kv = parse_key_values(text)
    values: dict[str, Any] = {}
    for key in ("MyModuleId", "RingName", "HeartbeatInt", "HeartBeatInt", "LogFile", "InRing", "OutRing"):
        if key in kv:
            values[key if key != "HeartBeatInt" else "HeartbeatInt"] = kv[key]
    for field in process_fields(family):
        key = field["key"]
        if field.get("type") == "lines":
            values[key] = "\n".join(cmds.get(key, []))
        elif key in kv:
            values[key] = kv[key]
    return values


def get_compose() -> dict:
    env = _env()
    params = Path(env["EW_PARAMS"])
    meta = load_app()
    families = load_families()
    cv = {}
    cv_path = params / "earthworm_commonvars.d"
    if cv_path.is_file():
        cv = parse_commonvars(cv_path.read_text(encoding="utf-8", errors="replace"))
    rows = catalog(env)
    instances = []
    for row in rows:
        family = row.clone_of or row.id
        spec = families.get(family) or families.get(row.id)
        if not spec or spec.get("role") != "process" or not spec.get("priority"):
            continue
        if family not in PRIORITY_IO and row.id not in PRIORITY_IO:
            continue
        values: dict[str, Any] = {}
        raw = ""
        if row.param_file:
            pf = params / row.param_file
            if pf.is_file():
                raw = pf.read_text(encoding="utf-8", errors="replace")
                values = _values_from_text(family, raw)
        instances.append(
            {
                "family": family,
                "id": row.id,
                "enabled": row.enabled,
                "clone_of": row.clone_of,
                "module_id": row.module_id,
                "binary_exists": row.binary_exists,
                "values": values,
                "raw": raw,
            }
        )
    site = {
        "heartbeat_int": int(cv.get("HEARTBEAT_INT") or 30),
        "default_wave_ring": "WAVE_RING",
        "log_file": cv.get("LogFile") or "1",
        "installation": env.get("EW_INSTALLATION") or cv.get("EW_INST_ID") or "",
        "propagate_heartbeat": False,
        "statmgr_enabled": any(r.id == "statmgr" and r.enabled for r in rows),
    }
    return {
        "site": site,
        "instances": instances,
        "rings": sorted(_startstop_rings()),
        "compose_revision": meta.compose_revision,
        "running": bool(last_snapshot() and last_snapshot().running),
    }


def _used_names(board: dict, extra_disk: bool = True) -> set[str]:
    names = {str(i.get("id") or "") for i in board.get("instances") or []}
    if extra_disk:
        for m in catalog():
            names.add(m.id)
    return {n for n in names if n}


def _used_listen_ports(instances: list[dict]) -> list[tuple[str, str, int]]:
    found: list[tuple[str, str, int]] = []
    for inst in instances:
        family = inst.get("family") or ""
        iid = inst.get("id") or ""
        values = inst.get("values") or {}
        for field in process_fields(family):
            if field.get("type") not in LISTEN_TYPES and field.get("unique") != "host":
                continue
            if field.get("type") not in LISTEN_TYPES:
                continue
            raw = values.get(field["key"])
            try:
                port = int(raw)
            except (TypeError, ValueError):
                continue
            found.append((iid, field["key"], port))
    return found


def _used_tanks(instances: list[dict]) -> list[tuple[str, str, str]]:
    found = []
    for inst in instances:
        values = inst.get("values") or {}
        iid = inst.get("id") or ""
        for key in TANK_KEYS:
            val = str(values.get(key) or "").strip()
            if val:
                found.append((iid, key, val))
    return found


def suggest(family: str, board: dict | None = None) -> dict:
    spec = family_spec(family)
    if not spec or spec.get("role") != "process":
        raise ComposeError(f"알 수 없는 패밀리: {family}")
    board = board or get_compose()
    instances = list(board.get("instances") or [])
    existing_ids = {str(i.get("id")) for i in instances}
    for m in catalog():
        existing_ids.add(m.id)
    prefix = SUGGEST_NAMES.get(family, f"{family}_n")
    name = family
    if spec.get("fleet") or name in existing_ids:
        n = 1
        while True:
            cand = f"{prefix}{n}" if not prefix.endswith(tuple("0123456789")) else f"{prefix}{n}"
            # q3302ew_sta + N
            cand = f"{prefix}{n}"
            if cand not in existing_ids and SAFE_NAME.match(cand):
                name = cand
                break
            n += 1
            if n > 999:
                raise ComposeError("이름 제안을 만들 수 없습니다")
    values: dict[str, Any] = {}
    site = board.get("site") or {}
    default_ring = spec.get("default_ring") or site.get("default_wave_ring") or "WAVE_RING"
    values["RingName"] = default_ring
    values["HeartbeatInt"] = str(site.get("heartbeat_int") or 30)
    values["LogFile"] = str(site.get("log_file") or "1")
    used_ports = {p for _i, _k, p in _used_listen_ports(instances)}
    hint = SUGGEST_PORTS.get(family)
    if hint:
        key, start, step = hint
        port = start
        while port in used_ports:
            port += step
        values[key] = port
        if family == "q3302ew":
            values["SourcePortData"] = port + 1
            values["BasePort"] = 5330
    env = _env()
    data_dir = env.get("EW_DATA_DIR") or ""
    if family == "wave_serverV":
        tank_dir = str(Path(data_dir) / "tanks")
        values.setdefault("ServerIPAdr", "0.0.0.0")
        values["Tank"] = str(Path(tank_dir) / f"{name}.tnk")
        values["TankStructFile"] = str(Path(tank_dir) / f"{name}.str")
    if family in {"export_generic", "export_scnl"}:
        values.setdefault("ServerIPAdr", "0.0.0.0")
        values.setdefault("MaxMsgSize", "4096")
    if family == "import_pasv":
        values.setdefault("ReceiverIpAdr", "0.0.0.0")
    if family == "slink2ew":
        values.setdefault("SLport", "18000")
    if family == "ew2ringserver":
        values.setdefault("RSPort", "18000")
        values.setdefault("RSAddress", "127.0.0.1")
    if family == "ew2mseed":
        values["OutDir"] = str(Path(data_dir) / "mseed" / name)
    if family == "ewmseedarchiver":
        values["ArchiveDir"] = str(Path(data_dir) / "archive" / name)
    if family in {"tbuf2mseed", "mseed2tbuf"}:
        values["InRing"] = default_ring
        values["OutRing"] = "WAVE_RING"
    return {"family": family, "id": name, "values": values, "enabled": False}


def validate_board(board: dict) -> list[dict]:
    issues: list[dict] = []
    instances = list(board.get("instances") or [])
    ids: list[str] = []
    rings = _startstop_rings()
    bindir = _bindir()
    params = _params()
    ew_path = params / "earthworm.d"
    ew_mods: set[str] = set()
    if ew_path.is_file():
        ew = parse_earthworm_d(ew_path.read_text(encoding="utf-8", errors="replace"))
        ew_mods = {n for n, _i, on in ew.modules() if on}

    seen_ids: dict[str, int] = {}
    for inst in instances:
        iid = str(inst.get("id") or "")
        family = str(inst.get("family") or "")
        if not SAFE_NAME.match(iid):
            issues.append(_issue("bad_name", f"잘못된 이름: {iid}", iid))
        cmd = f"{iid} {iid}.d"
        if len(cmd) > MAX_PROCESS_CMD:
            issues.append(_issue("cmd_len", "Process 명령이 199자를 넘습니다", iid))
        seen_ids[iid] = seen_ids.get(iid, 0) + 1
        ids.append(iid)
        spec = family_spec(family)
        if not spec:
            issues.append(_issue("missing_bin", f"스키마에 없는 패밀리: {family}", iid))
        src_bin = bindir / family
        if not src_bin.is_file() and not (bindir / iid).is_file():
            issues.append(_issue("missing_bin", f"바이너리가 없습니다: {family}", iid))
        values = inst.get("values") or {}
        ring = str(values.get("RingName") or values.get("InRing") or "")
        if ring == "FLAG_RING":
            issues.append(_issue("missing_ring", "FLAG_RING 은 사용할 수 없습니다", iid, "RingName"))
        for rk in ("RingName", "InRing", "OutRing"):
            rv = str(values.get(rk) or "").strip()
            if rv and rv not in rings and rv != "FLAG_RING":
                issues.append(_issue("missing_ring", f"{rk} {rv} 가 startstop 링 목록에 없습니다", iid, rk))
        for field in process_fields(family):
            key = field["key"]
            val = values.get(key)
            empty = val is None or str(val).strip() == ""
            if field.get("required") and empty:
                code = "auth_empty" if key == "AuthCode" else "empty_required"
                issues.append(_issue(code, f"필수 값 없음: {key}", iid, key))
            if field.get("type") in LISTEN_TYPES and not empty:
                try:
                    port = int(val)
                except (TypeError, ValueError):
                    issues.append(_issue("empty_required", f"포트가 숫자가 아닙니다: {key}", iid, key))
                    continue
                if port >= EPHEMERAL_FLOOR:
                    issues.append(
                        _issue("ephemeral_port", f"포트 {port} 가 ephemeral 대역입니다", iid, key, "warning")
                    )

    for iid, n in seen_ids.items():
        if n > 1:
            issues.append(_issue("dup_process", f"Process 이름 중복: {iid}", iid))

    # module constants among board
    mod_consts: dict[str, str] = {}
    for inst in instances:
        iid = str(inst.get("id") or "")
        const = str((inst.get("values") or {}).get("MyModuleId") or ("MOD_" + iid.upper()))
        if const in mod_consts and mod_consts[const] != iid:
            issues.append(_issue("dup_module_id", f"Module 상수 중복: {const}", iid, "MyModuleId"))
        mod_consts[const] = iid
        # clash with earthworm.d if this is a new id
        existing_ids = {m.id for m in catalog()}
        if iid not in existing_ids and const in ew_mods:
            issues.append(_issue("dup_module_id", f"earthworm.d 에 이미 있습니다: {const}", iid, "MyModuleId"))

    ports = _used_listen_ports(instances)
    by_port: dict[int, list[tuple[str, str]]] = {}
    for iid, key, port in ports:
        by_port.setdefault(port, []).append((iid, key))
    for port, owners in by_port.items():
        if len(owners) > 1:
            for iid, key in owners:
                issues.append(_issue("dup_listen", f"리슨 포트 중복: {port}", iid, key))

    tanks = _used_tanks(instances)
    by_tank: dict[str, list[tuple[str, str]]] = {}
    for iid, key, path in tanks:
        by_tank.setdefault(path, []).append((iid, key))
    for path, owners in by_tank.items():
        if len(owners) > 1:
            for iid, key in owners:
                issues.append(_issue("dup_tank", f"탱크 경로 중복: {path}", iid, key))

    # child count: current startstop enabled that we keep + newly enabled
    ss_path = params / "startstop_unix.d"
    current_enabled = 0
    current_names: set[str] = set()
    if ss_path.is_file():
        ss = parse_startstop(ss_path.read_text(encoding="utf-8", errors="replace"))
        current_enabled = sum(1 for p in ss.processes if p.enabled)
        current_names = {p.name for p in ss.processes}
    board_map = {str(i.get("id")): i for i in instances}
    delta = 0
    for iid, inst in board_map.items():
        will_on = bool(inst.get("enabled"))
        was = False
        if ss_path.is_file():
            ss = parse_startstop(ss_path.read_text(encoding="utf-8", errors="replace"))
            block = ss.process_named(iid)
            was = bool(block and block.enabled)
        if will_on and not was:
            delta += 1
        if (not will_on) and was:
            delta -= 1
    if current_enabled + delta > MAX_CHILD:
        issues.append(_issue("max_child", f"활성 Process 가 {MAX_CHILD} 을 넘습니다"))

    _ = current_names  # kept for clarity
    return issues


def _snapshot(params: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    dest = Path(settings.APP_JSON).parent / "backups" / f"compose-{stamp}"
    dest.mkdir(parents=True, exist_ok=True)
    if params.is_dir():
        shutil.copytree(params, dest / "params", dirs_exist_ok=True)
    app_json = Path(settings.APP_JSON)
    if app_json.is_file():
        shutil.copy2(app_json, dest / "app.json")
    bindir = _bindir()
    bins = dest / "bin_names.txt"
    names = []
    if bindir.is_dir():
        names = sorted(p.name for p in bindir.iterdir() if p.is_file())
    bins.write_text("\n".join(names), encoding="utf-8")
    return dest


def _rollback(snap: Path, created_bins: list[Path]) -> None:
    params = _params()
    snap_params = snap / "params"
    if snap_params.is_dir():
        if params.is_dir():
            shutil.rmtree(params)
        shutil.copytree(snap_params, params)
    app_snap = snap / "app.json"
    if app_snap.is_file():
        shutil.copy2(app_snap, settings.APP_JSON)
    for p in created_bins:
        try:
            if p.is_file():
                p.unlink()
        except OSError:
            pass


def _patch_d(path: Path, family: str, values: dict[str, Any]) -> None:
    text = path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""
    common_keys = ["RingName", "HeartbeatInt", "LogFile", "InRing", "OutRing"]
    for key in common_keys:
        if key in values and str(values[key]).strip() != "":
            alt = "HeartBeatInt" if key == "HeartbeatInt" else key
            if key == "HeartbeatInt" and "HeartBeatInt" in parse_key_values(text) and "HeartbeatInt" not in parse_key_values(text):
                text = upsert_command_value(text, "HeartBeatInt", str(values[key]))
            else:
                text = upsert_command_value(text, alt if False else key, str(values[key]))
    for field in process_fields(family):
        key = field["key"]
        if key not in values:
            continue
        val = values[key]
        if field.get("type") == "lines":
            lines = val if isinstance(val, list) else str(val).splitlines()
            lines = [ln.strip() for ln in lines if str(ln).strip()]
            text = replace_repeated_command(text, key, lines)
        else:
            if val is None or str(val).strip() == "":
                continue
            text = upsert_command_value(text, key, str(val))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _ensure_descriptor(module_id: str, family: str, mod_const: str) -> None:
    params = _params()
    dest = params / f"{module_id}.desc"
    if not dest.is_file():
        src = params / f"{family}.desc"
        text = ""
        if src.is_file() and src != dest:
            text = src.read_text(encoding="utf-8", errors="replace")
        else:
            text = f"modName {module_id}\nmodId   {mod_const}\ninstId  ${{EW_INST_ID}}\ntsec    90\nrestartMe\n"
        text, _ = replace_command_value(text, "modName", module_id)
        text, _ = replace_command_value(text, "modId", mod_const)
        dest.write_text(text, encoding="utf-8")
    sm = params / "statmgr.d"
    if sm.is_file():
        sm_text = sm.read_text(encoding="utf-8", errors="replace")
        if f"{module_id}.desc" not in sm_text:
            if not sm_text.endswith("\n"):
                sm_text += "\n"
            sm.write_text(sm_text + f"Descriptor     {module_id}.desc\n", encoding="utf-8")


def apply_board(board: dict, *, reconfigure: bool = False, actor_username: str | None = None) -> dict:
    if not actor_username:
        raise RuntimeError("작업자가 없습니다")
    issues = validate_board(board)
    errors = [i for i in issues if i.get("level") != "warning"]
    if errors:
        raise ComposeError("검증 실패", issues)
    params = _params()
    bindir = _bindir()
    snap = _snapshot(params)
    created_bins: list[Path] = []
    try:
        current = get_compose()
        current_ids = {i["id"] for i in current["instances"]}
        wanted = list(board.get("instances") or [])
        wanted_ids = {str(i.get("id")) for i in wanted}
        site = board.get("site") or {}

        # deletions (clones only)
        for iid in current_ids - wanted_ids:
            if iid == "statmgr":
                continue
            rec = next((c for c in load_app().clones if c["id"] == iid), None)
            if rec:
                delete_clone(iid)
            else:
                # original family: disable, keep files
                ss_path = params / "startstop_unix.d"
                if ss_path.is_file():
                    ss = parse_startstop(ss_path.read_text(encoding="utf-8", errors="replace"))
                    if ss.process_named(iid):
                        set_process_enabled(ss, iid, False)
                        ss_path.write_text(serialize_startstop(ss), encoding="utf-8")

        for inst in wanted:
            iid = str(inst.get("id"))
            family = str(inst.get("family"))
            if iid == "statmgr":
                continue
            values = dict(inst.get("values") or {})
            if site.get("propagate_heartbeat") and site.get("heartbeat_int") is not None:
                values["HeartbeatInt"] = str(site["heartbeat_int"])
            existing = iid in current_ids or (params / f"{iid}.d").is_file()
            if not existing:
                src = family if (bindir / family).is_file() else iid
                before_bin = bindir / iid
                existed_bin = before_bin.is_file()
                try:
                    clone_module(src, iid)
                except CloneError as exc:
                    raise ComposeError(str(exc), [_issue("bad_name", str(exc), iid)]) from exc
                if not existed_bin and before_bin.is_file():
                    created_bins.append(before_bin)
            dest_d = params / f"{iid}.d"
            _patch_d(dest_d, family, values)
            kv = parse_key_values(dest_d.read_text(encoding="utf-8", errors="replace"))
            mod_const = kv.get("MyModuleId") or ("MOD_" + iid.upper())
            _ensure_descriptor(iid, family, mod_const)
            ss_path = params / "startstop_unix.d"
            ss = parse_startstop(ss_path.read_text(encoding="utf-8", errors="replace"))
            cmd = f"{iid} {iid}.d"
            upsert_process(ss, cmd, enabled=bool(inst.get("enabled")))
            ss_path.write_text(serialize_startstop(ss), encoding="utf-8")

        # site commonvars
        cv_path = params / "earthworm_commonvars.d"
        updates = {}
        if site.get("heartbeat_int") is not None:
            updates["HEARTBEAT_INT"] = str(site["heartbeat_int"])
        if site.get("log_file") is not None:
            updates["LogFile"] = str(site["log_file"])
        if updates and cv_path.is_file():
            cv_path.write_text(
                upsert_commonvars(cv_path.read_text(encoding="utf-8", errors="replace"), updates),
                encoding="utf-8",
            )
        if site.get("propagate_heartbeat") and site.get("heartbeat_int") is not None:
            hb = str(site["heartbeat_int"])
            tsec = max(int(hb) * 3, int(hb)) if str(hb).isdigit() else None
            for inst in wanted:
                iid = str(inst.get("id"))
                pf = params / f"{iid}.d"
                if pf.is_file():
                    _patch_d(pf, str(inst.get("family")), {"HeartbeatInt": hb})
                dp = params / f"{iid}.desc"
                if tsec and dp.is_file():
                    dtext = dp.read_text(encoding="utf-8", errors="replace")
                    kv = parse_key_values(dtext)
                    current_t = int(kv["tsec"]) if kv.get("tsec", "").isdigit() else 0
                    dtext, found = replace_command_value(dtext, "tsec", str(max(current_t, tsec)))
                    if found:
                        dp.write_text(dtext, encoding="utf-8")

        meta = load_app()
        meta.compose_revision = int(meta.compose_revision or 0) + 1
        save_app(meta)

        extra: dict[str, Any] = {"reconfigured": False, "restart_needed": False}
        snap_status = last_snapshot()
        running = bool(snap_status and snap_status.running)
        if running:
            extra["restart_needed"] = True
            if reconfigure:
                extra["reconfigured"] = True
                extra["statmgr_restarted"] = True
                # run reconfigure (async caller handles)
        result = {
            "ok": True,
            "issues": issues,
            "compose_revision": meta.compose_revision,
            "backup_dir": str(snap.relative_to(Path(settings.APP_JSON).parent)) if snap else None,
            "instances": [i["id"] for i in wanted],
            **extra,
        }
        return result
    except ComposeError:
        _rollback(snap, created_bins)
        raise
    except Exception:
        _rollback(snap, created_bins)
        raise


async def apply_board_async(board: dict, *, reconfigure: bool = False, actor_username: str | None = None) -> dict:
    result = apply_board(board, reconfigure=False, actor_username=actor_username)
    if reconfigure and result.get("restart_needed"):
        try:
            await do_reconfigure()
            result["reconfigured"] = True
            result["statmgr_restarted"] = True
        except Exception as exc:
            result["reconfigure_error"] = str(exc)
    return result
