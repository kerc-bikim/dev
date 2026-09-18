"""PollResult ↔ Edge Ingest Poll 변환.

중앙 Writer 가 받는 형태와 수집 Adapter 가 내는 형태를 여기서만 맞춘다.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.domain.enums import PollErrorCode, Severity, SupportState
from app.domain.models import CapabilityReport, MetricSample, PollResult


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


def parse_iso(value: str) -> datetime:
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    moment = datetime.fromisoformat(raw)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def ingest_to_poll(poll: dict) -> PollResult:
    """중앙 Ingest 가 받은 Poll JSON 을 Adapter 결과와 같은 형태로 되돌린다."""
    samples: list[MetricSample] = []
    for item in poll.get("samples") or []:
        status = item.get("valueStatus")
        timestamp = item.get("valueTimestamp")
        support = item.get("supportState")
        samples.append(
            MetricSample(
                metric_key=item["metricKey"],
                dimensions=item.get("dimensions") or {},
                value_float=item.get("valueFloat"),
                value_int=item.get("valueInt"),
                value_bool=item.get("valueBool"),
                value_text=item.get("valueText"),
                value_status=Severity(status) if status else None,
                value_timestamp=parse_iso(timestamp) if timestamp else None,
                raw_value=item.get("rawValue"),
                support_state=SupportState(support) if support else SupportState.SUPPORTED_ENABLED,
            )
        )
    capabilities = {
        key: SupportState(state) for key, state in (poll.get("capabilities") or {}).items()
    }
    error = poll.get("errorCode")
    return PollResult(
        poll_id=str(poll["pollId"]),
        device_id=str(poll["deviceId"]),
        adapter_key=str(poll.get("adapterKey") or "unknown"),
        adapter_version=str(poll.get("adapterVersion") or "1.0"),
        observed_at=parse_iso(str(poll["observedAt"])),
        success=bool(poll.get("success")),
        samples=tuple(samples),
        capabilities=CapabilityReport(states=capabilities),
        latency_ms=poll.get("latencyMs"),
        http_status=poll.get("httpStatus"),
        payload_bytes=poll.get("payloadBytes"),
        error_code=PollErrorCode(error) if error else None,
        error_message=poll.get("errorMessage"),
    )


def is_incident_poll(result: PollResult) -> bool:
    """디스크가 가득 차면 이런 Poll 을 마지막까지 남긴다."""
    if not result.success:
        return True
    for sample in result.samples:
        if sample.value_status in {Severity.WARNING, Severity.CRITICAL, Severity.UNKNOWN}:
            return True
    return False
