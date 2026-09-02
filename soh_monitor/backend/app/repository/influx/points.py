"""PollResult → InfluxDB Point 변환.

순수 함수로 둔다. InfluxDB 를 띄우지 않고도 적재 형식을 시험할 수 있어야 한다.
적재 형식이 조용히 어긋나면 Grafana 대시보드가 통째로 빈다.

규칙
  * measurement 와 field 이름은 카탈로그에서 온다. 코드에 문자열로 적지 않는다.
  * 값이 없는 샘플은 Point 를 만들지 않는다. 없는 데이터를 0 으로 채우면 그래프가
    거짓말을 한다. '왜 없는지' 는 device_capabilities 와 health_states 가 답한다.
  * 상태는 숫자와 문자열을 함께 적재한다. 숫자는 Grafana 알림·집계용, 문자열은 사람용.
  * timestamp 는 관측 시각(observed_at)이다. 중앙 수신 시각이 아니다. Edge 가 하루 뒤
    올려도 원래 시각에 채워져야 한다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.domain.enums import Severity, ValueType
from app.domain.models import PollResult
from app.metrics.catalog import MetricCatalog, load_catalog

POLL_MEASUREMENT = "recorder_poll"
VENDOR_MEASUREMENT = "recorder_vendor_metric"


@dataclass(frozen=True)
class DeviceTags:
    """모든 Point 에 붙는 공통 Tag.

    IP·펌웨어 버전은 변동값이라 Tag 로 쓰지 않는다. Cardinality 가 커지고, 값이 바뀌면
    같은 장비의 시계열이 둘로 갈라진다.
    """

    device_id: str
    station_id: str
    station_code: str
    collection_mode: str
    manufacturer: str | None = None
    product_family: str | None = None
    generation: str | None = None
    model: str | None = None
    region: str | None = None
    edge_id: str | None = None

    def as_dict(self) -> dict[str, str]:
        tags = {
            "device_id": self.device_id,
            "station_id": self.station_id,
            "station_code": self.station_code,
            "collection_mode": self.collection_mode,
        }
        for key, value in (
            ("manufacturer", self.manufacturer),
            ("product_family", self.product_family),
            ("generation", self.generation),
            ("model", self.model),
            ("region", self.region),
            ("edge_id", self.edge_id),
        ):
            if value:
                tags[key] = value
        return tags


@dataclass(frozen=True)
class PointSpec:
    """InfluxDB 에 적재할 한 점. 특정 클라이언트에 묶이지 않은 표현이다."""

    measurement: str
    tags: dict[str, str]
    fields: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime | None = None

    def merged_with(self, other: "PointSpec") -> "PointSpec":
        return PointSpec(
            measurement=self.measurement,
            tags=self.tags,
            fields={**self.fields, **other.fields},
            timestamp=self.timestamp,
        )


def _to_epoch_seconds(moment: datetime) -> float:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.timestamp()


def _field_values(value_type: ValueType, field_name: str, sample) -> dict[str, Any]:
    if value_type is ValueType.STATUS:
        severity: Severity = sample.value_status
        # 숫자는 Grafana 알림·집계용, 문자열은 사람이 읽는 용도다.
        return {field_name: severity.code, f"{field_name}_text": severity.value}
    if value_type is ValueType.BOOLEAN:
        return {field_name: bool(sample.value_bool)}
    if value_type is ValueType.INTEGER:
        return {field_name: int(sample.value_int)}
    if value_type is ValueType.FLOAT:
        return {field_name: float(sample.value_float)}
    if value_type is ValueType.TEXT:
        return {field_name: str(sample.value_text)}
    if value_type is ValueType.TIMESTAMP:
        # epoch 초로 적재한다. Grafana 에서 경과 시간 계산이 쉽다.
        return {field_name: _to_epoch_seconds(sample.value_timestamp)}
    raise ValueError(f"처리하지 않은 value_type: {value_type}")


def poll_point(result: PollResult, tags: DeviceTags, *, consecutive_failures: int) -> PointSpec:
    """수집 시도 자체의 기록. 성공이든 실패든 항상 만든다.

    실패를 남기지 않으면 '데이터가 없는 것' 과 '장비가 죽은 것' 을 구분할 수 없다.
    """
    fields: dict[str, Any] = {
        "reachable": bool(result.success),
        "consecutive_failures": int(consecutive_failures),
    }
    if result.latency_ms is not None:
        fields["latency_ms"] = float(result.latency_ms)
    if result.http_status is not None:
        fields["http_status"] = int(result.http_status)
    if result.payload_bytes is not None:
        fields["payload_bytes"] = int(result.payload_bytes)
    if result.error_code is not None:
        fields["error_code"] = result.error_code.value
    if result.samples:
        fields["sample_count"] = len(result.samples)

    return PointSpec(
        measurement=POLL_MEASUREMENT,
        tags=tags.as_dict(),
        fields=fields,
        timestamp=result.observed_at,
    )


def build_points(
    result: PollResult,
    tags: DeviceTags,
    *,
    consecutive_failures: int = 0,
    catalog: MetricCatalog | None = None,
) -> list[PointSpec]:
    """PollResult 를 적재할 Point 목록으로 옮긴다.

    같은 measurement·같은 Tag 조합은 한 Point 로 묶는다. Point 수가 줄면 쓰기 비용과
    저장 공간이 함께 줄어든다.
    """
    catalog = catalog or load_catalog()
    base_tags = tags.as_dict()

    grouped: dict[tuple[str, tuple[tuple[str, str], ...]], PointSpec] = {}

    def merge(measurement: str, extra_tags: dict[str, str], fields: dict[str, Any]) -> None:
        point_tags = {**base_tags, **extra_tags}
        key = (measurement, tuple(sorted(point_tags.items())))
        existing = grouped.get(key)
        if existing is None:
            grouped[key] = PointSpec(
                measurement=measurement,
                tags=point_tags,
                fields=dict(fields),
                timestamp=result.observed_at,
            )
        else:
            existing.fields.update(fields)

    poll = poll_point(result, tags, consecutive_failures=consecutive_failures)
    grouped[(poll.measurement, tuple(sorted(poll.tags.items())))] = poll

    for sample in result.samples:
        if not sample.has_value:
            # 값이 없으면 적재하지 않는다. 이유는 device_capabilities·health_states 가 답한다.
            continue

        definition = catalog.metrics.get(sample.metric_key)
        if definition is None:
            # 카탈로그에 없는 Metric 은 버린다. Adapter 시험에서 이미 걸러지지만,
            # 적재 단계에서도 막아 Cardinality 폭발을 방지한다.
            continue

        extra_tags = dict(sample.dimensions)
        field_name = definition.field
        if definition.measurement == VENDOR_MEASUREMENT:
            # 제조사 전용 Metric 은 metric_key 를 Tag 로 둔다. 공통 대시보드는 쓰지 않는다.
            extra_tags["metric_key"] = sample.metric_key

        merge(
            definition.measurement,
            extra_tags,
            _field_values(definition.value_type, field_name, sample),
        )

    return list(grouped.values())


def to_line_protocol(point: PointSpec) -> str:
    """디버깅·시험용 Line Protocol 표현."""

    def escape_tag(value: str) -> str:
        return value.replace(" ", "\\ ").replace(",", "\\,").replace("=", "\\=")

    tag_part = "".join(
        f",{escape_tag(key)}={escape_tag(value)}" for key, value in sorted(point.tags.items())
    )

    field_parts: list[str] = []
    for key, value in sorted(point.fields.items()):
        if isinstance(value, bool):
            field_parts.append(f"{key}={'true' if value else 'false'}")
        elif isinstance(value, int):
            field_parts.append(f"{key}={value}i")
        elif isinstance(value, float):
            field_parts.append(f"{key}={value}")
        else:
            escaped = str(value).replace('"', '\\"')
            field_parts.append(f'{key}="{escaped}"')

    timestamp = ""
    if point.timestamp is not None:
        moment = point.timestamp
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        timestamp = f" {int(moment.timestamp() * 1_000_000_000)}"

    return f"{point.measurement}{tag_part} {','.join(field_parts)}{timestamp}"
