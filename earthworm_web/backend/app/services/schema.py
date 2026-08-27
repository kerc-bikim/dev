from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

YAML_PATH = Path(__file__).resolve().parent.parent / "module_fields.yaml"

PRIORITY_IO = (
    "export_generic",
    "export_scnl",
    "import_generic",
    "import_pasv",
    "tbuf2mseed",
    "mseed2tbuf",
    "ew2ringserver",
    "slink2ew",
    "wave_serverV",
    "ew2mseed",
    "ewmseedarchiver",
    "q3302ew",
)

FLEET_FAMILIES = ("q3302ew", "slink2ew", "export_scnl", "export_generic", "wave_serverV")

COMMON_FIELDS = [
    {"key": "MyModuleId", "label": "MyModuleId", "required": False, "type": "readonly"},
    {"key": "RingName", "label": "RingName", "required": False, "type": "ring"},
    {"key": "HeartbeatInt", "label": "HeartbeatInt", "required": False, "type": "int"},
    {"key": "LogFile", "label": "LogFile", "required": False, "type": "int"},
]


@lru_cache(maxsize=1)
def load_families() -> dict[str, dict[str, Any]]:
    if not YAML_PATH.is_file():
        return {}
    data = yaml.safe_load(YAML_PATH.read_text(encoding="utf-8")) or {}
    families = data.get("families") or {}
    for name, spec in families.items():
        spec.setdefault("role", "process")
        spec.setdefault("fleet", name in FLEET_FAMILIES)
        spec.setdefault("priority", name in PRIORITY_IO or name == "statmgr")
        spec.setdefault("fields", [])
        spec.setdefault("label", name)
        spec.setdefault("default_ring", "WAVE_RING")
    return families


def schema_payload() -> dict:
    families = load_families()
    return {
        "families": families,
        "priority_io": list(PRIORITY_IO),
        "fleet": list(FLEET_FAMILIES),
        "common_fields": COMMON_FIELDS,
    }


def family_spec(name: str) -> dict[str, Any]:
    return load_families().get(name, {})


def family_role(name: str) -> str:
    spec = family_spec(name)
    if spec:
        return str(spec.get("role") or "process")
    return "process"


def family_fleet(name: str) -> bool:
    spec = family_spec(name)
    if spec:
        return bool(spec.get("fleet"))
    return name in FLEET_FAMILIES


def family_priority(name: str, clone_of: str | None = None) -> bool:
    root = clone_of or name
    spec = family_spec(root) or family_spec(name)
    if spec:
        return bool(spec.get("priority"))
    return root in PRIORITY_IO or name in PRIORITY_IO


def process_fields(family: str) -> list[dict[str, Any]]:
    spec = family_spec(family)
    return list(spec.get("fields") or [])
