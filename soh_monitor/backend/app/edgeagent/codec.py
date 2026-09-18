"""PollResult ↔ Edge Ingest Poll 변환.

중앙 Writer 가 받는 형태와 수집 Adapter 가 내는 형태를 여기서만 맞춘다.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.domain.enums import Severity
from app.domain.models import PollResult


def iso_z(moment: datetime) -> str:
    converted = moment.astimezone(timezone.utc)
    return converted.isoformat().replace("+00:00", "Z")


def poll_to_ingest(result: PollResult, sequence: int) -> dict:
    samples = []
    for sample in result.samples:
        item: dict = {"metricKey": sample.metric_key}
        if sample.dimensions:
            item["dimensions"] = dict(sample.dimensions)
        if sample.value_float is not None:
            item["valueFloat"] = sample.value_float
        if sample.value_int is not None:
            item["valueInt"] = sample.value_int
        if sample.value_bool is not None:
            item["valueBool"] = sample.value_bool
        if sample.value_text is not None:
            item["valueText"] = sample.value_text
        if sample.value_status is not None:
            item["valueStatus"] = sample.value_status.value
        if sample.value_timestamp is not None:
            item["valueTimestamp"] = iso_z(sample.value_timestamp)
        if sample.raw_value is not None:
            item["rawValue"] = sample.raw_value
        if sample.support_state is not None:
            item["supportState"] = sample.support_state.value
        samples.append(item)

    capabilities = {
        key: state.value if hasattr(state, "value") else str(state)
        for key, state in (result.capabilities.states or {}).items()
    }
    return {
        "pollId": result.poll_id,
        "sequence": sequence,
        "deviceId": result.device_id,
        "adapterKey": result.adapter_key,
        "adapterVersion": result.adapter_version,
        "observedAt": iso_z(result.observed_at),
        "success": result.success,
        "errorCode": result.error_code.value if result.error_code else None,
        "errorMessage": result.error_message,
        "latencyMs": result.latency_ms,
        "httpStatus": result.http_status,
        "payloadBytes": result.payload_bytes,
        "capabilities": capabilities,
        "samples": samples,
    }


def is_incident_poll(result: PollResult) -> bool:
    """디스크가 가득 차면 이런 Poll 을 마지막까지 남긴다."""
    if not result.success:
        return True
    for sample in result.samples:
        if sample.value_status in {Severity.WARNING, Severity.CRITICAL, Severity.UNKNOWN}:
            return True
    return False
