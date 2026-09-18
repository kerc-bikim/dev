"""Edge Batch → PollResult → Influx·이력·현재 상태.

규칙
  * 같은 (edge_id, batch_id) 는 한 번만 처리한다.
  * 같은 (edge_id, sequence) 는 한 번만 적재한다. batch_id 가 달라도 건너뛴다.
  * 같은 poll_id 는 한 번만 적재한다.
  * 시계열 timestamp 는 observed_at 이다. 수신 시각이 아니다.
  * 현재 상태·판정은 observed_at 이 기존 last_observed_at 이상일 때만 갱신한다.
    하루 늦은 데이터가 그래프의 과거를 채우는 것은 맞지만, '지금 정상' 으로
    되돌리면 안 된다.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config.settings import Settings, get_settings
from app.db.models import (
    BatchStatus,
    Device as DeviceRow,
    DeviceRuntimeState,
    EdgeCollector,
    EdgeIngestBatch,
    EdgeIngestSequence,
    PollRun,
    Station as StationRow,
)
from app.edgeagent.codec import ingest_to_poll
from app.health.service import HealthService
from app.observability.logging import get_logger
from app.repository.influx.points import build_points
from app.repository.influx.sink import InMemoryMetricSink, MetricSink
from app.repository.postgres import collector_repo as repo
from app.repository.postgres.collector_repo import as_utc

logger = get_logger("app.ingest", role="api")


@dataclass
class IngestReport:
    accepted: bool = True
    duplicate: bool = False
    batch_id: str = ""
    first_sequence: int = 0
    last_sequence: int = 0
    poll_count: int = 0
    written: int = 0
    skipped_duplicate: int = 0
    delayed: int = 0
    points_written: int = 0
    opened: int = 0
    resolved: int = 0


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def sink_for(app: FastAPI) -> MetricSink:
    """API 프로세스의 적재 대상.

    시험은 app.state.ingest_sink 에 InMemory 를 넣는다. 운영은 Influx 토큰이
    있을 때만 실제 쓰기를 연다. 토큰이 없으면 메모리에만 담아 수집 ACK 를 막지 않는다.
    적재를 조용히 버리면 Edge 는 성공으로 알고 Spool 을 지운다.
    """
    existing = getattr(app.state, "ingest_sink", None)
    if existing is not None:
        return existing
    settings = get_settings()
    token = settings.resolved_secret("influx_token")
    if token:
        from app.repository.influx.sink import BufferedMetricSink, InfluxMetricSink

        sink: MetricSink = BufferedMetricSink(
            InfluxMetricSink(
                url=settings.influx_url,
                token=token,
                org=settings.influx_org,
                bucket=settings.influx_bucket,
            )
        )
    else:
        sink = InMemoryMetricSink()
    app.state.ingest_sink = sink
    return sink


def _poll_id_seen(session: Session, poll_id: str) -> bool:
    return session.scalar(select(PollRun.id).where(PollRun.poll_id == poll_id)) is not None


def _sequence_seen(session: Session, edge_id: uuid.UUID, sequence: int) -> bool:
    return (
        session.scalar(
            select(EdgeIngestSequence.id).where(
                EdgeIngestSequence.edge_id == edge_id,
                EdgeIngestSequence.sequence == sequence,
            )
        )
        is not None
    )


def _record_sequence(
    session: Session,
    *,
    edge_id: uuid.UUID,
    sequence: int,
    poll_id: str,
    batch_id: str,
    observed_at: datetime,
) -> bool:
    nested = session.begin_nested()
    try:
        session.add(
            EdgeIngestSequence(
                edge_id=edge_id,
                sequence=sequence,
                poll_id=poll_id,
                batch_id=batch_id,
                observed_at=observed_at,
            )
        )
        session.flush()
        nested.commit()
        return True
    except IntegrityError:
        nested.rollback()
        return False


def process_batch(
    session: Session,
    edge: EdgeCollector,
    document: dict[str, Any],
    *,
    sink: MetricSink,
    health: HealthService | None = None,
    settings: Settings | None = None,
    received_at: datetime | None = None,
) -> IngestReport:
    settings = settings or get_settings()
    now = received_at or utcnow()
    batch_id = str(document["batchId"])
    report = IngestReport(
        batch_id=batch_id,
        first_sequence=int(document["firstSequence"]),
        last_sequence=int(document["lastSequence"]),
    )

    existing = session.scalar(
        select(EdgeIngestBatch).where(
            EdgeIngestBatch.edge_id == edge.id,
            EdgeIngestBatch.batch_id == batch_id,
        )
    )
    if existing is not None:
        existing.status = BatchStatus.DUPLICATE
        report.duplicate = True
        report.poll_count = existing.poll_count
        report.first_sequence = existing.first_sequence
        report.last_sequence = existing.last_sequence
        return report

    polls = list(document.get("polls") or [])
    report.poll_count = len(polls)
    sample_count = sum(len(poll.get("samples") or []) for poll in polls)
    row = EdgeIngestBatch(
        edge_id=edge.id,
        batch_id=batch_id,
        first_sequence=report.first_sequence,
        last_sequence=report.last_sequence,
        poll_count=len(polls),
        sample_count=sample_count,
        received_at=now,
        processed_at=now,
        status=BatchStatus.RECEIVED,
    )
    session.add(row)
    session.flush()

    health_service = health if health is not None else HealthService(
        warning_threshold=settings.failure_warning_threshold,
        critical_threshold=settings.failure_critical_threshold,
    )

    for poll in polls:
        sequence = int(poll["sequence"])
        poll_id = str(poll["pollId"])
        if _sequence_seen(session, edge.id, sequence) or _poll_id_seen(session, poll_id):
            report.skipped_duplicate += 1
            continue

        try:
            result = ingest_to_poll(poll)
            device_id = uuid.UUID(str(poll["deviceId"]))
        except (KeyError, ValueError, TypeError) as exc:
            logger.warning("Poll JSON 을 해석하지 못했다", extra={"poll_id": poll_id, "error": str(exc)})
            report.skipped_duplicate += 1
            continue

        device = repo.load_due_device(session, device_id)
        if device is None:
            logger.warning("없는 장비 Poll 을 건너뛴다", extra={"device_id": str(device_id), "poll_id": poll_id})
            report.skipped_duplicate += 1
            continue

        if not _record_sequence(
            session,
            edge_id=edge.id,
            sequence=sequence,
            poll_id=poll_id,
            batch_id=batch_id,
            observed_at=result.observed_at,
        ):
            report.skipped_duplicate += 1
            continue

        repo.record_poll_run(session, device, result, received_at=now, edge_id=edge.id)

        runtime = session.get(DeviceRuntimeState, device.device_id)
        observed = as_utc(result.observed_at)
        previous = as_utc(runtime.last_observed_at) if runtime else None
        previous_success = as_utc(runtime.last_success_at) if runtime else None
        is_newer = previous is None or (observed is not None and observed >= previous)

        consecutive = device.consecutive_failures
        health_points: list = []
        if is_newer:
            state = repo.update_runtime_state(
                session,
                device,
                result,
                warning_threshold=settings.failure_warning_threshold,
                critical_threshold=settings.failure_critical_threshold,
                now=now,
            )
            consecutive = state.consecutive_failures or 0
            if result.success and result.capabilities.states:
                repo.upsert_capabilities(session, device.device_id, result.capabilities.states, now=now)
            device_row = session.get(DeviceRow, device.device_id)
            station_row = session.get(StationRow, device.station_id)
            if device_row is not None and station_row is not None:
                health_report = health_service.evaluate(
                    session,
                    device_row,
                    station_row,
                    result,
                    consecutive_failures=consecutive,
                    tags=device.tags,
                    poll_interval_minutes=device.poll_interval_minutes,
                    last_success_at=previous_success,
                    now=now,
                )
                health_points = health_report.points
                report.opened += len(health_report.opened)
                report.resolved += len(health_report.resolved)
        else:
            report.delayed += 1

        points = build_points(result, device.tags, consecutive_failures=consecutive)
        points.extend(health_points)
        if sink.write(points):
            report.points_written += len(points)
        report.written += 1

    row.status = BatchStatus.PROCESSED
    row.processed_at = now
    edge.last_upload_at = now
    spool = (document.get("edgeHealth") or {}).get("spool") or {}
    if spool.get("usedBytes") is not None:
        edge.spool_used_bytes = int(spool["usedBytes"])
    if spool.get("limitBytes") is not None:
        edge.spool_limit_bytes = int(spool["limitBytes"])
    return report
