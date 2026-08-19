from __future__ import annotations

from pathlib import Path

from .commonvars import parse_commonvars, parse_key_values, replace_command_value, upsert_commonvars
from .env import bash_path, parsed_core, rewrite_bash
from .module_catalog import catalog
from .setup_wizard import backup_params

UNIFIED_KEYS = ("EW_INST_ID", "HEARTBEAT_INT", "STATIONFILE", "LogFile")


def current_variables() -> dict:
    env = parsed_core()
    params = Path(env["EW_PARAMS"])
    cv_path = params / "earthworm_commonvars.d"
    common = parse_commonvars(cv_path.read_text(encoding="utf-8", errors="replace")) if cv_path.is_file() else {}
    usages: dict[str, list[str]] = {k: ["earthworm_commonvars.d"] for k in common}
    modules = catalog()
    for m in modules:
        if not m.param_file:
            continue
        pf = params / m.param_file
        kv = parse_key_values(pf.read_text(encoding="utf-8", errors="replace"))
        if "HeartbeatInt" in kv:
            usages.setdefault("HEARTBEAT_INT", []).append(m.param_file)
        if "LogFile" in kv:
            usages.setdefault("LogFile", []).append(m.param_file)
        if "GetWavesFrom" in kv or "GetStatusFrom" in kv:
            usages.setdefault("EW_INST_ID", []).append(m.param_file)
        if any(k in kv for k in ("site_file", "StationFile", "stationFile")):
            usages.setdefault("STATIONFILE", []).append(m.param_file)
    fields = []
    values = {
        "EW_INST_ID": common.get("EW_INST_ID", env.get("EW_INSTALLATION", "")),
        "HEARTBEAT_INT": common.get("HEARTBEAT_INT", "30"),
        "STATIONFILE": common.get("STATIONFILE", "${EW_PARAMS}/stations.hinv"),
        "LogFile": common.get("LogFile", "1"),
        "EW_LOG": env.get("EW_LOG", ""),
        "EW_INSTALLATION": env.get("EW_INSTALLATION", ""),
    }
    labels = {
        "EW_INST_ID": "설치 ID (commonvars)",
        "HEARTBEAT_INT": "HeartbeatInt",
        "STATIONFILE": "관측소 파일",
        "LogFile": "LogFile",
        "EW_LOG": "로그 디렉터리 (ew_linux.bash)",
        "EW_INSTALLATION": "EW_INSTALLATION",
    }
    for key, label in labels.items():
        fields.append(
            {
                "key": key,
                "label": label,
                "value": values.get(key, ""),
                "used_in": sorted(set(usages.get(key, []))),
            }
        )
    return {"fields": fields, "values": values}


def apply_variables(updates: dict[str, str]) -> dict:
    env = parsed_core()
    params = Path(env["EW_PARAMS"])
    changed: list[str] = []
    backup_params(params)
    common_keys = {k: v for k, v in updates.items() if k in {"EW_INST_ID", "HEARTBEAT_INT", "STATIONFILE"}}
    if "LogFile" in updates:
        common_keys["LogFile"] = updates["LogFile"]
    cv_path = params / "earthworm_commonvars.d"
    if common_keys and cv_path.is_file():
        cv_path.write_text(
            upsert_commonvars(cv_path.read_text(encoding="utf-8", errors="replace"), common_keys),
            encoding="utf-8",
        )
        changed.append("earthworm_commonvars.d")
    if "EW_INSTALLATION" in updates:
        rewrite_bash(bash_path(), {"EW_INSTALLATION": updates["EW_INSTALLATION"]})
        changed.append("ew_linux.bash")
    if "EW_INST_ID" in updates and "EW_INSTALLATION" not in updates:
        rewrite_bash(bash_path(), {"EW_INSTALLATION": updates["EW_INST_ID"]})
        changed.append("ew_linux.bash")
    if "EW_LOG" in updates:
        log = updates["EW_LOG"]
        if not log.endswith("/"):
            log += "/"
        Path(log).mkdir(parents=True, exist_ok=True)
        rewrite_bash(bash_path(), {"EW_LOG": log})
        changed.append("ew_linux.bash")
    hb = updates.get("HEARTBEAT_INT")
    tsec = None
    if hb and hb.isdigit():
        tsec = max(int(hb) * 3, int(hb))
    for m in catalog():
        if m.param_file:
            pf = params / m.param_file
            text = pf.read_text(encoding="utf-8", errors="replace")
            orig = text
            if "HeartbeatInt" in updates or hb:
                text, _ = replace_command_value(text, "HeartbeatInt", hb or parse_key_values(text).get("HeartbeatInt", "30"))
            if "LogFile" in updates:
                text, _ = replace_command_value(text, "LogFile", updates["LogFile"])
            if text != orig:
                pf.write_text(text, encoding="utf-8")
                changed.append(m.param_file)
        if tsec and m.desc_file:
            dp = params / m.desc_file
            if dp.is_file():
                dtext = dp.read_text(encoding="utf-8", errors="replace")
                kv = parse_key_values(dtext)
                current = int(kv["tsec"]) if kv.get("tsec", "").isdigit() else 0
                new_tsec = max(current, tsec)
                dtext, found = replace_command_value(dtext, "tsec", str(new_tsec))
                if found:
                    dp.write_text(dtext, encoding="utf-8")
                    changed.append(m.desc_file)
    return {"changed": sorted(set(changed)), "values": current_variables()["values"]}
