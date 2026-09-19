"""Adapter 계약과 Registry 검증.

여기서 막고 싶은 사고는 하나다. 계약과 어긋난 Adapter 가 조용히 등록되어
UNKNOWN 만 쌓는 상황. 그보다 등록 실패가 낫다.
"""
from __future__ import annotations

import copy
import json

import pytest

from app.adapters.contract import (
    AdapterManifest,
    ConnectionTest,
    DeviceContext,
    RecorderAdapter,
)
from app.adapters.registry import (
    AdapterRegistrationError,
    AdapterRegistry,
    validate_manifest_document,
)
from app.domain.models import CapabilityReport, DeviceIdentity, PollResult

VALID_MANIFEST = {
    "adapterKey": "vendor_x.recorder_a.gen1",
    "adapterVersion": "1.0",
    "manufacturer": "Vendor X",
    "productFamilies": ["Recorder A"],
    "supportedModels": ["RA-100"],
    "protocols": ["http"],
    "capabilities": ["power.input_voltage", "timing.status"],
    "providedMetrics": ["power.input_voltage_v", "timing.status"],
    "status": "supported",
    "configurationSchema": {
        "type": "object",
        "properties": {
            "hostname": {"type": "string"},
            "apiToken": {"type": "string"},
        },
        "required": ["hostname"],
        "secretFields": ["apiToken"],
    },
}


class 최소Adapter(RecorderAdapter):
    def __init__(self, document: dict) -> None:
        self.manifest = AdapterManifest.model_validate(document)

    def validate_configuration(self, connection):  # noqa: ANN001
        return [] if connection.get("hostname") else ["hostname 이 필요하다"]

    async def test_connection(self, context: DeviceContext) -> ConnectionTest:
        return ConnectionTest(reachable=True, latency_ms=1.0)

    async def probe(self, context: DeviceContext) -> DeviceIdentity:
        return DeviceIdentity(model="RA-100")

    async def detect_capabilities(self, context: DeviceContext) -> CapabilityReport:
        return CapabilityReport()

    async def collect(self, context: DeviceContext) -> PollResult:
        return PollResult(
            poll_id="p1",
            device_id=context.device_id,
            adapter_key=self.adapter_key,
            adapter_version=self.adapter_version,
            success=True,
        )

    def redact(self, payload):  # noqa: ANN001
        return payload


def test_올바른_Manifest는_통과한다():
    validate_manifest_document(copy.deepcopy(VALID_MANIFEST))


def test_카탈로그에_없는_Metric을_선언하면_거부한다():
    document = copy.deepcopy(VALID_MANIFEST)
    document["providedMetrics"].append("power.imaginary_metric")
    with pytest.raises(AdapterRegistrationError, match="catalog.yaml"):
        validate_manifest_document(document)


def test_정의되지_않은_capability를_선언하면_거부한다():
    document = copy.deepcopy(VALID_MANIFEST)
    document["capabilities"].append("power.imaginary_capability")
    with pytest.raises(AdapterRegistrationError, match="capabilities.yaml"):
        validate_manifest_document(document)


def test_비밀필드가_설정_Schema에_없으면_거부한다():
    """secretFields 가 실제 필드와 어긋나면 그 값이 암호화되지 않고 새어 나간다."""
    document = copy.deepcopy(VALID_MANIFEST)
    document["configurationSchema"]["secretFields"] = ["missingField"]
    with pytest.raises(AdapterRegistrationError, match="secretFields"):
        validate_manifest_document(document)


def test_adapter_key_형식이_틀리면_거부한다():
    document = copy.deepcopy(VALID_MANIFEST)
    document["adapterKey"] = "Vendor X Recorder"
    with pytest.raises(AdapterRegistrationError, match="Schema 위반"):
        validate_manifest_document(document)


def test_필수_항목이_빠지면_거부한다():
    document = copy.deepcopy(VALID_MANIFEST)
    del document["configurationSchema"]
    with pytest.raises(AdapterRegistrationError, match="Schema 위반"):
        validate_manifest_document(document)


class TestRegistry:
    def test_등록과_조회(self):
        registry = AdapterRegistry()
        registry.register(최소Adapter(copy.deepcopy(VALID_MANIFEST)))
        assert len(registry) == 1
        assert "vendor_x.recorder_a.gen1" in registry
        assert registry.get("vendor_x.recorder_a.gen1").adapter_version == "1.0"

    def test_같은_키를_두_번_등록하면_거부한다(self):
        registry = AdapterRegistry()
        registry.register(최소Adapter(copy.deepcopy(VALID_MANIFEST)))
        with pytest.raises(AdapterRegistrationError, match="이미 등록된"):
            registry.register(최소Adapter(copy.deepcopy(VALID_MANIFEST)))

    def test_등록되지_않은_키_조회는_실패한다(self):
        registry = AdapterRegistry()
        with pytest.raises(AdapterRegistrationError, match="등록되지 않은"):
            registry.get("nanometrics.centaur.gen5")

    def test_준비중_Adapter는_선택할_수_없다(self):
        document = copy.deepcopy(VALID_MANIFEST)
        document["status"] = "planned"
        manifest = AdapterManifest.model_validate(document)
        assert manifest.selectable is False

    def test_Manifest_파일도_같은_규칙으로_검증한다(tmp_path=None):
        # 파일 경로로 등록하는 경로도 Schema 검증을 지나는지 확인한다.
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "manifest.json"
            broken = copy.deepcopy(VALID_MANIFEST)
            broken["providedMetrics"] = ["nonexistent.metric"]
            path.write_text(json.dumps(broken), encoding="utf-8")

            registry = AdapterRegistry()
            with pytest.raises(AdapterRegistrationError):
                registry.register(최소Adapter(copy.deepcopy(VALID_MANIFEST)), manifest_path=path)


def test_기본_Registry는_Manifest_파일_원본으로_검증한다():
    """배포되는 실체가 파일이므로 파일을 검증한다.

    계약과 어긋난 Adapter 가 등록되면 여기서 기동이 실패한다. 조용히 UNKNOWN 을 쌓는
    것보다 뜨지 않는 편이 낫다.
    """
    from app.adapters.registry import get_registry, reset_registry

    reset_registry()
    registry = get_registry()
    assert registry.keys() == ("acme.mock.recorder", "nanometrics.centaur.ctr")
    reset_registry()
