"""Adapter Registry.

MVP 는 검증된 Adapter 를 프로그램에 포함해 배포한다. 런타임 동적 플러그인은 쓰지 않는다.
운영체제·빌드 버전에 민감해 Edge 수십 대의 배포 관리가 오히려 어려워진다.

등록 시점에 Manifest 를 계약과 대조한다. 카탈로그에 없는 Metric 이나 capability 를
선언한 Adapter 는 등록 자체가 실패한다. 잘못된 Adapter 가 조용히 UNKNOWN 을 쌓는 것보다
기동 실패가 낫다.
"""
from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from app.adapters.contract import AdapterManifest, RecorderAdapter
from app.metrics.catalog import CONTRACTS_DIR, load_catalog

MANIFEST_SCHEMA_PATH = CONTRACTS_DIR / "adapter" / "manifest.schema.json"


class AdapterRegistrationError(Exception):
    """Adapter 선언이 계약과 어긋나는 경우."""


def manifest_validator() -> Draft202012Validator:
    schema = json.loads(MANIFEST_SCHEMA_PATH.read_text(encoding="utf-8"))
    return Draft202012Validator(schema)


def validate_manifest_document(document: dict) -> None:
    """Manifest 원본 JSON 을 Schema 와 계약에 대조한다."""
    errors = sorted(manifest_validator().iter_errors(document), key=lambda e: list(e.path))
    if errors:
        details = "; ".join(f"{'/'.join(str(p) for p in e.path) or '(root)'}: {e.message}" for e in errors)
        raise AdapterRegistrationError(f"Manifest Schema 위반: {details}")

    catalog = load_catalog()

    unknown_capabilities = sorted(set(document.get("capabilities") or ()) - set(catalog.capabilities))
    if unknown_capabilities:
        raise AdapterRegistrationError(
            f"capabilities.yaml 에 없는 capability 선언: {unknown_capabilities}"
        )

    unknown_metrics = sorted(set(document.get("providedMetrics") or ()) - set(catalog.metrics))
    if unknown_metrics:
        raise AdapterRegistrationError(f"catalog.yaml 에 없는 Metric 선언: {unknown_metrics}")

    secret_fields = set((document.get("configurationSchema") or {}).get("secretFields") or ())
    declared_properties = set((document.get("configurationSchema") or {}).get("properties") or {})
    missing = sorted(secret_fields - declared_properties)
    if missing:
        raise AdapterRegistrationError(
            f"secretFields 가 configurationSchema.properties 에 없다: {missing}"
        )


class AdapterRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, RecorderAdapter] = {}

    def register(self, adapter: RecorderAdapter, *, manifest_path: Path | None = None) -> None:
        # 파일이 있으면 파일 원본을 검증한다. 배포되는 실체가 파일이기 때문이다.
        # 없으면 모델을 JSON 형태로 직렬화한다. tuple 을 그대로 넘기면 JSON Schema 의
        # array 검사에 걸린다.
        document = (
            json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest_path is not None
            else adapter.manifest.model_dump(by_alias=True, mode="json", exclude_none=True)
        )
        validate_manifest_document(document)

        key = adapter.adapter_key
        if key in self._adapters:
            raise AdapterRegistrationError(f"이미 등록된 adapter_key: {key}")
        self._adapters[key] = adapter

    def get(self, adapter_key: str) -> RecorderAdapter:
        try:
            return self._adapters[adapter_key]
        except KeyError as exc:
            raise AdapterRegistrationError(f"등록되지 않은 adapter_key: {adapter_key}") from exc

    def manifests(self) -> tuple[AdapterManifest, ...]:
        return tuple(a.manifest for a in self._adapters.values())

    def keys(self) -> tuple[str, ...]:
        return tuple(sorted(self._adapters))

    def __len__(self) -> int:
        return len(self._adapters)

    def __contains__(self, adapter_key: object) -> bool:
        return adapter_key in self._adapters


_registry: AdapterRegistry | None = None


def get_registry() -> AdapterRegistry:
    """기본 Registry. 내장 Adapter 를 이 자리에서 등록한다.

    Manifest 파일 원본으로 검증한다. 배포되는 실체가 파일이기 때문이다.
    등록에 실패하면 프로세스가 뜨지 않는다. 계약과 어긋난 Adapter 가 조용히
    UNKNOWN 을 쌓는 것보다 기동 실패가 낫다.
    """
    global _registry
    if _registry is None:
        registry = AdapterRegistry()

        from app.adapters.centaur_ctr.adapter import MANIFEST_PATH, CentaurCtrAdapter
        from app.adapters.mock_recorder.adapter import (
            MANIFEST_PATH as MOCK_MANIFEST_PATH,
        )
        from app.adapters.mock_recorder.adapter import MockRecorderAdapter

        registry.register(CentaurCtrAdapter(), manifest_path=MANIFEST_PATH)
        registry.register(MockRecorderAdapter(), manifest_path=MOCK_MANIFEST_PATH)
        _registry = registry
    return _registry


def reset_registry() -> None:
    """테스트 전용."""
    global _registry
    _registry = None
