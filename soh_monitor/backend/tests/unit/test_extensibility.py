"""M11 확장성 회귀.

새 제조사를 붙일 때 수집기·스키마·공통 Grafana 를 건드리면 안 된다.
이 시험은 그 경계를 파일과 import 로 못 박는다.
"""
from __future__ import annotations

import ast
import inspect
import json
from pathlib import Path

from app.adapters.registry import get_registry, reset_registry
from app.collector import runner, scheduler
from app.db.base import Base
from app.db.models import DeviceCapability

ROOT = Path(__file__).resolve().parents[3]
COMMON_LAYER = (
    ROOT / "backend" / "app" / "collector",
    ROOT / "backend" / "app" / "health",
    ROOT / "backend" / "app" / "ingest",
    ROOT / "backend" / "app" / "repository",
)
FORBIDDEN_IMPORTS = (
    "app.adapters.centaur_ctr",
    "app.adapters.mock_recorder",
    "app.adapters.transport",
)
VENDOR_TABLE_WORDS = ("centaur", "nanometrics", "acme", "mock_recorder", "gen5", "strataos")
KNOWN_MIGRATIONS = {
    "0001_initial_schema.py",
    "0002_health_state_metric_key.py",
    "0003_edge_tasks.py",
    "0004_edge_ingest_sequences.py",
}


def _python_files(root: Path) -> list[Path]:
    return [path for path in root.rglob("*.py") if "__pycache__" not in path.parts]


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


def test_수집계층은_제조사_모듈을_직접_가져오지_않는다():
    for folder in COMMON_LAYER:
        for path in _python_files(folder):
            imported = _imports(path)
            leaked = [name for name in FORBIDDEN_IMPORTS if any(item == name or item.startswith(name + ".") for item in imported)]
            assert not leaked, f"{path.relative_to(ROOT)} 가 제조사 모듈을 가져온다: {leaked}"


def test_스케줄러_소스는_Adapter_키를_모른다():
    source = (inspect.getsource(scheduler) + inspect.getsource(runner)).lower()
    for token in ("centaur", "nanometrics", "acme.mock", "mock_recorder", "snmp"):
        assert token not in source
    assert "get_registry" in inspect.getsource(scheduler)
    assert "registry.get" in inspect.getsource(runner)


def test_Registry에_두_제조사가_등록된다():
    reset_registry()
    registry = get_registry()
    assert "nanometrics.centaur.ctr" in registry
    assert "acme.mock.recorder" in registry
    assert registry.get("acme.mock.recorder").manifest.manufacturer == "ACME"
    reset_registry()


def test_제조사_추가에_신규_테이블이_없다():
    versions = ROOT / "backend" / "app" / "migrations" / "versions"
    names = {path.name for path in versions.glob("*.py") if path.name != "__init__.py"}
    assert names == KNOWN_MIGRATIONS
    for name, table in Base.metadata.tables.items():
        lowered = name.lower()
        for word in VENDOR_TABLE_WORDS:
            assert word not in lowered, f"테이블 {name} 에 제조사 이름이 있다"
        del table
    # 기능 지원 상태는 기존 device_capabilities 한 테이블이면 충분하다.
    assert DeviceCapability.__tablename__ == "device_capabilities"


def test_프론트_탭은_Capability로_미지원을_표시한다():
    text = (ROOT / "frontend" / "src" / "lib" / "capabilityTabs.ts").read_text(encoding="utf-8")
    assert "UNSUPPORTED" in text
    assert "external_soh.analog" in text
    assert "sensor.status" in text
    assert "stationTabVisibility" in text


def test_가상제조사_선언만으로_센서와_외부SOH가_빠진다():
    reset_registry()
    capabilities = get_registry().get("acme.mock.recorder").manifest.capabilities
    reset_registry()
    assert "power.input_voltage" in capabilities
    assert "sensor.status" not in capabilities
    assert "external_soh.analog" not in capabilities
    assert "archive.continuous" not in capabilities
    tab_keys = {
        "power": ("power.input_voltage", "power.current"),
        "timing": ("timing.status", "timing.quality", "gnss.receiver"),
        "sensor": ("sensor.status", "sensor.control_lines", "sensor.mass_position"),
        "storage": ("storage.internal", "storage.removable", "archive.continuous", "archive.event"),
        "external": ("external_soh.analog",),
    }
    declared = set(capabilities)
    unsupported = {
        tab for tab, keys in tab_keys.items() if not declared.intersection(keys)
    }
    assert unsupported == {"sensor", "external"}


def test_공통_Grafana는_카탈로그_Measurement만_본다():
    grafana = ROOT / "deploy" / "grafana" / "dashboards"
    common = (
        "01-fleet-overview.json",
        "02-station-detail.json",
        "04-edge-fleet.json",
        "05-collector-operations.json",
        "06-data-quality.json",
        "07-kiosk-overview.json",
    )
    for filename in common:
        blob = (grafana / filename).read_text(encoding="utf-8")
        assert "vendor." not in blob
        assert "recorder_vendor_metric" not in blob
        payload = json.loads(blob)
        assert payload["uid"] == filename.removesuffix(".json")
