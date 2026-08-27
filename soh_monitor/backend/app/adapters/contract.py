"""기록계 Adapter 공통 계약.

새 제조사를 붙이는 작업의 전부는 이 계약의 구현체 하나와 Manifest 하나를 만드는 일이다.
Collector·Edge·DB·Grafana 는 손대지 않는다.

계약이 지켜야 하는 것
  * 제조사 원본 필드명은 구현체 내부에만 존재한다.
  * 예외를 밖으로 던지지 않는다. 실패는 PollResult(success=False) 로 표현한다.
    한 장비의 예외가 수집 루프 전체를 멈추면 안 된다.
  * 지원하지 않는 기능은 값 없이 UNSUPPORTED 로 표시한다. 0 이나 OK 로 채우지 않는다.
"""
from __future__ import annotations

import abc
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.domain.models import CapabilityReport, DeviceIdentity, PollResult


class AdapterManifest(BaseModel):
    """Adapter 자기 선언. contracts/adapter/manifest.schema.json 을 따른다."""

    model_config = ConfigDict(frozen=True, populate_by_name=True)

    adapter_key: str = Field(alias="adapterKey")
    adapter_version: str = Field(alias="adapterVersion")
    manufacturer: str
    product_families: tuple[str, ...] = Field(alias="productFamilies")
    generation: str | None = None
    supported_models: tuple[str, ...] = Field(default=(), alias="supportedModels")
    protocols: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ()
    provided_metrics: tuple[str, ...] = Field(default=(), alias="providedMetrics")
    minimum_collector_version: str | None = Field(default=None, alias="minimumCollectorVersion")
    minimum_edge_version: str | None = Field(default=None, alias="minimumEdgeVersion")
    status: str = "supported"
    configuration_schema: dict[str, Any] = Field(alias="configurationSchema")
    ui_hints: dict[str, Any] = Field(default_factory=dict, alias="uiHints")

    @property
    def secret_fields(self) -> tuple[str, ...]:
        return tuple(self.configuration_schema.get("secretFields") or ())

    @property
    def selectable(self) -> bool:
        """등록 화면에서 실제로 선택 가능한지. planned 는 '준비 중' 으로만 보인다."""
        return self.status in {"experimental", "supported"}

    @classmethod
    def from_file(cls, path: Path) -> "AdapterManifest":
        return cls.model_validate(json.loads(path.read_text(encoding="utf-8")))


@dataclass(frozen=True)
class ConnectionTest:
    """연결 시험 결과. 등록 화면이 그대로 보여 준다."""

    reachable: bool
    latency_ms: float | None = None
    http_status: int | None = None
    message: str = ""
    identity: DeviceIdentity | None = None


@dataclass(frozen=True)
class DeviceContext:
    """Adapter 에 넘기는 장비 문맥.

    비밀값은 `credential` 로만 들어오고 로그·응답에 남지 않는다.
    """

    device_id: str
    station_code: str
    connection: dict[str, Any]
    credential: dict[str, str] | None = None
    expected_identity: DeviceIdentity | None = None
    connect_timeout_ms: int = 5000
    request_timeout_ms: int = 15000
    sensor_ports: tuple[str, ...] = ()
    external_soh_channels: int = 0
    options: dict[str, Any] | None = None


class RecorderAdapter(abc.ABC):
    """모든 기록계 Adapter 의 상위 계약."""

    manifest: AdapterManifest

    @property
    def adapter_key(self) -> str:
        return self.manifest.adapter_key

    @property
    def adapter_version(self) -> str:
        return self.manifest.adapter_version

    @abc.abstractmethod
    def validate_configuration(self, connection: dict[str, Any]) -> list[str]:
        """접속 설정을 검사해 오류 메시지 목록을 돌려준다. 빈 목록이면 통과."""

    @abc.abstractmethod
    async def test_connection(self, context: DeviceContext) -> ConnectionTest:
        """등록 화면의 '연결 시험'. 상태를 바꾸지 않는 읽기 동작만 수행한다."""

    @abc.abstractmethod
    async def probe(self, context: DeviceContext) -> DeviceIdentity:
        """장비 신원(모델·시리얼·펌웨어·채널 수)을 확인한다."""

    @abc.abstractmethod
    async def detect_capabilities(self, context: DeviceContext) -> CapabilityReport:
        """장비 기능 지원 상태를 판정한다. 모르면 UNKNOWN 으로 둔다."""

    @abc.abstractmethod
    async def collect(self, context: DeviceContext) -> PollResult:
        """SOH 를 수집해 표준 Metric 으로 변환한다. 예외를 던지지 않는다."""

    @abc.abstractmethod
    def redact(self, payload: Any) -> Any:
        """원본 응답에서 비밀값·내부 경로를 제거한다. soh-preview 응답에 쓴다."""
