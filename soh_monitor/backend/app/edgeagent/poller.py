"""설정에 적힌 장비를 수집한다.

중앙 Postgres 를 읽지 않는다. 내려받은 설정과 로컬 일정만 본다. 실제 수집은
중앙 Collector 와 같은 `poll_device` · Adapter 를 탄다.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.adapters.registry import AdapterRegistry
from app.auth.credentials import CredentialResolver
from app.collector.retry import RetryPolicy
from app.collector.runner import poll_device
from app.db.models import CollectionMode
from app.domain.models import PollResult
from app.observability.logging import get_logger
from app.repository.influx.points import DeviceTags
from app.repository.postgres.collector_repo import DueDevice

logger = get_logger("app.edgeagent.poller", role="edge")


def parse_device_uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError:
        return uuid.uuid5(uuid.NAMESPACE_URL, value)


class LocalSchedule:
    """장비별 마지막 수집 시각. 중앙 DB 의 next_poll_at 을 지역에서 대신한다."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._times: dict[str, str] = {}
        if self.path.exists():
            try:
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    self._times = {str(key): str(value) for key, value in loaded.items()}
            except (OSError, json.JSONDecodeError):
                self._times = {}

    def last_poll(self, device_id: str) -> datetime | None:
        raw = self._times.get(device_id)
        if not raw:
            return None
        moment = datetime.fromisoformat(raw)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        return moment

    def due(self, device: dict, *, now: datetime) -> bool:
        if not device.get("enabled", True):
            return False
        last = self.last_poll(device["deviceId"])
        if last is None:
            return True
        interval = int(device.get("pollIntervalMinutes") or 5)
        return last + timedelta(minutes=interval) <= now

    def mark(self, device_id: str, when: datetime) -> None:
        self._times[device_id] = when.astimezone(timezone.utc).isoformat()
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self._times, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def force(self, device_id: str) -> None:
        self._times.pop(device_id, None)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self._times, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)


def to_due_device(device: dict, *, edge_id: str) -> DueDevice:
    device_id = str(device["deviceId"])
    station_id_raw = device.get("stationId") or device_id
    connection = dict(device.get("connection") or {})
    credential = device.get("credential") or {}
    reference = credential.get("reference") or connection.pop("credentialReference", None)
    return DueDevice(
        device_id=parse_device_uuid(device_id),
        station_id=parse_device_uuid(str(station_id_raw)),
        station_code=str(device.get("stationCode") or "UNKN"),
        adapter_key=str(device["adapterKey"]),
        collection_mode=CollectionMode.EDGE,
        connection=connection,
        credential_reference=reference,
        connect_timeout_ms=int(device.get("connectTimeoutMs") or 5000),
        request_timeout_ms=int(device.get("requestTimeoutMs") or 15000),
        poll_interval_minutes=int(device.get("pollIntervalMinutes") or 5),
        retry_count=int(device.get("retryCount") or 1),
        retry_delay_seconds=10,
        consecutive_failures=0,
        last_observed_at=None,
        data_source_uri=device.get("dataSourceUri") or connection.get("dataSourceUri"),
        tags=DeviceTags(
            device_id=device_id,
            station_id=str(station_id_raw),
            station_code=str(device.get("stationCode") or "UNKN"),
            collection_mode=CollectionMode.EDGE.value,
            edge_id=edge_id,
        ),
    )


async def collect_due(
    document: dict,
    schedule: LocalSchedule,
    registry: AdapterRegistry,
    resolver: CredentialResolver,
    *,
    edge_id: str,
    max_concurrent: int = 10,
    now: datetime | None = None,
    sleep=asyncio.sleep,
    sleepless: bool = False,
) -> list[PollResult]:
    now = now or datetime.now(timezone.utc)
    due = [device for device in (document.get("devices") or []) if schedule.due(device, now=now)]
    if not due:
        return []

    semaphore = asyncio.Semaphore(max_concurrent)

    async def one(device: dict) -> PollResult:
        async with semaphore:
            target = to_due_device(device, edge_id=edge_id)
            attempts = 1 + max(0, target.retry_count)
            policy = RetryPolicy(
                max_attempts=attempts,
                delay_seconds=0.0 if sleepless else float(target.retry_delay_seconds),
            )
            outcome = await poll_device(target, registry, resolver, policy, sleep=sleep)
            schedule.mark(device["deviceId"], outcome.result.observed_at)
            return outcome.result

    gathered = await asyncio.gather(*[one(device) for device in due], return_exceptions=True)
    results: list[PollResult] = []
    for item, device in zip(gathered, due, strict=True):
        if isinstance(item, Exception):
            logger.exception(
                "장비 수집이 예외로 끝났다",
                extra={"device_id": device.get("deviceId"), "error": str(item)},
            )
            continue
        results.append(item)
    return results
