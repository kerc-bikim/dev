"""설정 동기화.

다운로드 → Schema 검증 → 원자적 교체. 검증·적용이 실패하면 이전 파일로 되돌린다.
중앙이 끊긴 동안에는 마지막 성공 설정을 그대로 쓴다. Adapter 를 자동으로 받지 않는다.
"""
from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from app.metrics.catalog import CONTRACTS_DIR
from app.observability.logging import get_logger

logger = get_logger("app.edgeagent.configsync", role="edge")

SCHEMA = json.loads((CONTRACTS_DIR / "edge" / "config.schema.json").read_text("utf-8"))
_VALIDATOR = Draft202012Validator(SCHEMA)


class ConfigError(ValueError):
    """받은 설정을 적용할 수 없다."""


class ConfigStore:
    def __init__(self, root: Path, *, edge_id: str, known_adapters: set[str] | None = None) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.edge_id = edge_id
        self.known_adapters = known_adapters or set()
        self.current_path = self.root / "current.json"
        self.previous_path = self.root / "previous.json"
        self.staging_path = self.root / "staging.json"

    @property
    def current_version(self) -> int:
        current = self.load()
        return int(current["configVersion"]) if current else 0

    def load(self) -> dict | None:
        if not self.current_path.exists():
            return None
        return json.loads(self.current_path.read_text(encoding="utf-8"))

    def validate(self, document: dict) -> None:
        errors = sorted(_VALIDATOR.iter_errors(document), key=lambda item: list(item.path))
        if errors:
            details = "; ".join(
                f"{'/'.join(str(part) for part in error.path) or '(root)'}: {error.message}"
                for error in errors
            )
            raise ConfigError(f"설정 Schema 위반: {details}")
        if document.get("edgeId") != self.edge_id:
            raise ConfigError(
                f"설정 edgeId {document.get('edgeId')} 가 이 Edge({self.edge_id}) 와 다르다"
            )
        seen: set[str] = set()
        for device in document.get("devices") or []:
            device_id = device["deviceId"]
            if device_id in seen:
                raise ConfigError(f"같은 장비가 두 번 할당됐다: {device_id}")
            seen.add(device_id)
            adapter = device.get("adapterKey")
            if self.known_adapters and adapter not in self.known_adapters:
                raise ConfigError(f"이 Edge 에 없는 Adapter 가 필요하다: {adapter}")

    def apply(self, document: dict) -> dict:
        """검증 통과한 설정을 원자적으로 켠다. 실패하면 이전 버전으로 돌아간다."""
        incoming = int(document["configVersion"])
        if incoming <= self.current_version:
            raise ConfigError(
                f"설정 버전 {incoming} 은 적용된 버전 {self.current_version} 보다 크지 않다"
            )
        self.validate(document)
        payload = json.dumps(document, ensure_ascii=False, indent=2)
        self.staging_path.write_text(payload, encoding="utf-8")
        try:
            if self.current_path.exists():
                self.previous_path.write_text(self.current_path.read_text(encoding="utf-8"), encoding="utf-8")
            self.staging_path.replace(self.current_path)
            # 적용 직후 다시 읽어 깨진 파일이면 되돌린다.
            loaded = json.loads(self.current_path.read_text(encoding="utf-8"))
            self.validate(loaded)
        except Exception as exc:
            self.rollback()
            raise ConfigError(f"설정 적용 실패, 이전 버전으로 되돌렸다: {exc}") from exc
        logger.info("설정을 적용했다", extra={"config_version": incoming, "devices": len(document.get("devices") or [])})
        return document

    def rollback(self) -> dict | None:
        if self.previous_path.exists():
            self.previous_path.replace(self.current_path)
            logger.warning("이전 설정으로 되돌렸다", extra={"config_version": self.current_version})
            return self.load()
        if self.current_path.exists():
            self.current_path.unlink()
        return None
