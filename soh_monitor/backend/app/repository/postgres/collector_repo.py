"""수집기가 쓰는 데이터 접근.

Lease 를 DB 행으로 구현한다. PostgreSQL Advisory Lock 이 더 가볍지만, 행 Lease 는
  * 어느 인스턴스가 언제까지 잡았는지 화면에서 볼 수 있고,
  * 프로세스가 급사해도 만료 시각이 지나면 자동으로 풀리고,
  * SQLite 로도 같은 논리를 시험할 수 있다.
운영 규모(수백 대, 분 주기)에서는 행 Lease 의 비용이 문제되지 않는다.
"""
from __future__ import annotations

import random
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db.models import (
    CollectionMode,
    Device,
    DeviceCapability,
    DeviceEndpoint,
    DeviceRuntimeState,
    LifecycleStatus,
    PollRun,
    Region,
    Station,
)
from app.domain.enums import PollErrorCode, Severity, SupportState
from app.domain.models import PollResult
from app.repository.influx.points import DeviceTags


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _expire(session: Session, model, identifier) -> None:
    """Bulk UPDATE 이후 세션이 들고 있는 낡은 객체를 버린다.

    ORM 평가를 끄면 세션 안의 객체는 갱신 전 값을 그대로 들고 있다. 같은 세션에서
    다시 읽는 코드가 옛 값을 보게 되는 것을 막는다.
    """
    instance = session.get(model, identifier)
    if instance is not None:
        session.expire(instance)


def as_utc(moment: datetime | None) -> datetime | None:
    """SQLite 는 시간대를 잃는다. 비교 전에 UTC 로 되돌린다."""
    if moment is None:
        return None
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


@dataclass(frozen=True)
class DueDevice:
    """수집 대상 한 대. 수집에 필요한 정보만 담는다."""

    device_id: uuid.UUID
    station_id: uuid.UUID
    station_code: str
    adapter_key: str
    collection_mode: CollectionMode
    connection: dict
    credential_reference: str | None
    connect_timeout_ms: int
    request_timeout_ms: int
    poll_interval_minutes: int
    retry_count: int
    retry_delay_seconds: int
    consecutive_failures: int
    last_observed_at: datetime | None
    tags: DeviceTags


def _connection_from(endpoint: DeviceEndpoint | None, device: Device) -> dict:
    if endpoint is None:
        return {}
    connection = {
        "scheme": endpoint.scheme,
        "hostname": endpoint.hostname,
        "basePath": endpoint.base_path,
        "tlsVerify": endpoint.tls_verify,
        **(endpoint.connection_options or {}),
    }
    if endpoint.port:
        connection["port"] = endpoint.port
    if device.instrument_id:
        connection.setdefault("instrumentId", device.instrument_id)
    return connection


def due_devices(
    session: Session,
    *,
    now: datetime | None = None,
    mode: CollectionMode = CollectionMode.DIRECT,
    limit: int = 200,
    default_interval_minutes: int = 5,
) -> list[DueDevice]:
    """수집 시각이 된 장비를 고른다.

    `next_poll_at` 이 비어 있으면 아직 한 번도 수집하지 않은 장비이므로 대상에 포함한다.
    """
    now = now or utcnow()

    rows = session.execute(
        select(Device, DeviceEndpoint, Station, Region)
        .join(Station, Station.id == Device.station_id)
        .outerjoin(DeviceEndpoint, DeviceEndpoint.device_id == Device.id)
        .outerjoin(Region, Region.id == Station.region_id)
        .where(
            Device.enabled.is_(True),
            Device.collection_mode == mode,
            Device.status != LifecycleStatus.RETIRED,
        )
        .limit(limit)
    ).all()

    runtime_states = {
        state.device_id: state
        for state in session.scalars(select(DeviceRuntimeState))
    }

    result: list[DueDevice] = []
    for device, endpoint, station, region in rows:
        next_poll_at = as_utc(device.next_poll_at)
        if next_poll_at is not None and next_poll_at > now:
            continue

        profile = device.collection_profile
        interval = default_interval_minutes
        retry_count = 1
        retry_delay = 10
        connect_timeout = endpoint.connect_timeout_ms if endpoint else 5000
        request_timeout = endpoint.request_timeout_ms if endpoint else 15000
        if profile is not None:
            interval = profile.poll_interval_minutes
            retry_count = profile.retry_count
            retry_delay = profile.retry_delay_seconds

        state = runtime_states.get(device.id)
        result.append(
            DueDevice(
                device_id=device.id,
                station_id=station.id,
                station_code=station.station_code,
                adapter_key=device.adapter_key,
                collection_mode=device.collection_mode,
                connection=_connection_from(endpoint, device),
                credential_reference=endpoint.credential_reference if endpoint else None,
                connect_timeout_ms=connect_timeout,
                request_timeout_ms=request_timeout,
                poll_interval_minutes=interval,
                retry_count=retry_count,
                retry_delay_seconds=retry_delay,
                consecutive_failures=state.consecutive_failures if state else 0,
                last_observed_at=as_utc(state.last_observed_at) if state else None,
                tags=DeviceTags(
                    device_id=str(device.id),
                    station_id=str(station.id),
                    station_code=station.station_code,
                    collection_mode=device.collection_mode.value,
                    generation=device.device_model.generation if device.device_model else None,
                    model=device.device_model.model_code if device.device_model else None,
                    product_family=device.device_model.product_family if device.device_model else None,
                    manufacturer=(
                        device.manufacturer.manufacturer_code if device.manufacturer else None
                    ),
                    region=region.region_code if region else None,
                    edge_id=str(device.edge_id) if device.edge_id else None,
                ),
            )
        )

    return result


def load_due_device(
    session: Session,
    device_id: uuid.UUID,
    *,
    default_interval_minutes: int = 5,
) -> DueDevice | None:
    """Ingest Writer 가 장비 한 대의 태그·프로파일을 읽을 때 쓴다."""
    row = session.execute(
        select(Device, DeviceEndpoint, Station, Region)
        .join(Station, Station.id == Device.station_id)
        .outerjoin(DeviceEndpoint, DeviceEndpoint.device_id == Device.id)
        .outerjoin(Region, Region.id == Station.region_id)
        .where(Device.id == device_id)
    ).first()
    if row is None:
        return None
    device, endpoint, station, region = row
    profile = device.collection_profile
    interval = profile.poll_interval_minutes if profile else default_interval_minutes
    retry_count = profile.retry_count if profile else 1
    retry_delay = profile.retry_delay_seconds if profile else 10
    connect_timeout = endpoint.connect_timeout_ms if endpoint else 5000
    request_timeout = endpoint.request_timeout_ms if endpoint else 15000
    state = session.get(DeviceRuntimeState, device.id)
    return DueDevice(
        device_id=device.id,
        station_id=station.id,
        station_code=station.station_code,
        adapter_key=device.adapter_key,
        collection_mode=device.collection_mode,
        connection=_connection_from(endpoint, device),
        credential_reference=endpoint.credential_reference if endpoint else None,
        connect_timeout_ms=connect_timeout,
        request_timeout_ms=request_timeout,
        poll_interval_minutes=interval,
        retry_count=retry_count,
        retry_delay_seconds=retry_delay,
        consecutive_failures=state.consecutive_failures if state else 0,
        last_observed_at=as_utc(state.last_observed_at) if state else None,
        tags=DeviceTags(
            device_id=str(device.id),
            station_id=str(station.id),
            station_code=station.station_code,
            collection_mode=device.collection_mode.value,
            generation=device.device_model.generation if device.device_model else None,
            model=device.device_model.model_code if device.device_model else None,
            product_family=device.device_model.product_family if device.device_model else None,
            manufacturer=(device.manufacturer.manufacturer_code if device.manufacturer else None),
            region=region.region_code if region else None,
            edge_id=str(device.edge_id) if device.edge_id else None,
        ),
    )


def acquire_lease(
    session: Session,
    device_id: uuid.UUID,
    owner: str,
    *,
    ttl_seconds: int = 300,
    now: datetime | None = None,
) -> bool:
    """장비별 수집 권한을 잡는다.

    같은 장비를 두 인스턴스가 동시에 수집하면 같은 시각에 다른 값이 쌓이고, 어느 쪽이
    맞는지 알 수 없게 된다. 조건부 UPDATE 한 번으로 막는다.
    """
    now = now or utcnow()
    state = session.get(DeviceRuntimeState, device_id)
    if state is None:
        session.add(
            DeviceRuntimeState(
                device_id=device_id,
                poll_lease_owner=owner,
                poll_lease_until=now + timedelta(seconds=ttl_seconds),
            )
        )
        session.flush()
        return True

    lease_until = as_utc(state.poll_lease_until)
    if lease_until is not None and lease_until > now and state.poll_lease_owner != owner:
        return False

    # synchronize_session=False 로 둔다. ORM 이 조건을 Python 에서 다시 평가하면,
    # SQLite 처럼 시간대를 잃는 DB 에서 naive/aware 비교로 터진다. 판정은 DB 가 한다.
    updated = session.execute(
        update(DeviceRuntimeState)
        .where(
            DeviceRuntimeState.device_id == device_id,
            (
                DeviceRuntimeState.poll_lease_until.is_(None)
                | (DeviceRuntimeState.poll_lease_until <= now)
                | (DeviceRuntimeState.poll_lease_owner == owner)
            ),
        )
        .values(poll_lease_owner=owner, poll_lease_until=now + timedelta(seconds=ttl_seconds))
        .execution_options(synchronize_session=False)
    )
    session.flush()
    session.expire(state)
    return updated.rowcount > 0


def release_lease(session: Session, device_id: uuid.UUID, owner: str) -> None:
    session.execute(
        update(DeviceRuntimeState)
        .where(
            DeviceRuntimeState.device_id == device_id,
            DeviceRuntimeState.poll_lease_owner == owner,
        )
        .values(poll_lease_owner=None, poll_lease_until=None)
        .execution_options(synchronize_session=False)
    )
    session.flush()
    state = session.get(DeviceRuntimeState, device_id)
    if state is not None:
        session.expire(state)


def schedule_next_poll(
    session: Session,
    device_id: uuid.UUID,
    *,
    interval_minutes: int,
    jitter_percent: int = 15,
    now: datetime | None = None,
) -> datetime:
    """다음 수집 시각을 잡는다.

    Jitter 를 준다. 수십 대가 같은 초에 몰리면 회선과 수집기가 함께 튄다.
    """
    now = now or utcnow()
    base = interval_minutes * 60
    spread = base * (jitter_percent / 100)
    offset = random.uniform(-spread, spread) if spread else 0.0
    next_at = now + timedelta(seconds=max(5.0, base + offset))
    session.execute(
        update(Device)
        .where(Device.id == device_id)
        .values(next_poll_at=next_at)
        .execution_options(synchronize_session=False)
    )
    session.flush()
    _expire(session, Device, device_id)
    return next_at


def request_immediate_poll(session: Session, device_id: uuid.UUID, *, now: datetime | None = None) -> None:
    """수동 수집 요청. 다음 Tick 에서 곧바로 대상이 된다."""
    session.execute(
        update(Device)
        .where(Device.id == device_id)
        .values(next_poll_at=now or utcnow())
        .execution_options(synchronize_session=False)
    )
    session.flush()
    _expire(session, Device, device_id)


def record_poll_run(
    session: Session,
    device: DueDevice,
    result: PollResult,
    *,
    received_at: datetime | None = None,
    edge_id: uuid.UUID | None = None,
) -> PollRun:
    run = PollRun(
        device_id=device.device_id,
        edge_id=edge_id,
        poll_id=result.poll_id,
        collection_mode=device.collection_mode,
        adapter_key=result.adapter_key,
        adapter_version=result.adapter_version,
        observed_at=result.observed_at,
        received_at=received_at or utcnow(),
        success=result.success,
        latency_ms=result.latency_ms,
        http_status=result.http_status,
        payload_bytes=result.payload_bytes,
        sample_count=len(result.samples),
        error_code=result.error_code,
        error_message=result.error_message,
        unmapped_values={
            **result.unmapped_values,
            **(
                {"__unknown_channels": list(result.unknown_channels)}
                if result.unknown_channels
                else {}
            ),
        },
    )
    session.add(run)
    session.flush()
    return run


def update_runtime_state(
    session: Session,
    device: DueDevice,
    result: PollResult,
    *,
    warning_threshold: int,
    critical_threshold: int,
    now: datetime | None = None,
) -> DeviceRuntimeState:
    """현재 상태를 갱신한다.

    늦게 도착한 과거 데이터가 현재 상태를 되돌리지 못하게, `observed_at` 이 기존보다
    최신일 때만 값 기반 상태를 갱신한다. Edge 가 하루 뒤 올린 데이터로 '지금 정상'
    이라고 표시하면 안 된다.
    """
    now = now or utcnow()
    state = session.get(DeviceRuntimeState, device.device_id)
    if state is None:
        state = DeviceRuntimeState(device_id=device.device_id)
        session.add(state)
        session.flush()

    state.last_poll_at = now
    observed_at = as_utc(result.observed_at)
    previous_observed = as_utc(state.last_observed_at)
    is_newer = previous_observed is None or (observed_at is not None and observed_at >= previous_observed)

    if result.success:
        if is_newer:
            state.last_success_at = now
            state.last_observed_at = observed_at
            state.last_error_code = None
            state.overall_severity = Severity.OK
        state.consecutive_failures = 0
    else:
        state.consecutive_failures = (state.consecutive_failures or 0) + 1
        state.last_error_code = result.error_code
        if state.consecutive_failures >= critical_threshold:
            state.overall_severity = Severity.CRITICAL
        elif state.consecutive_failures >= warning_threshold:
            state.overall_severity = Severity.WARNING
        else:
            # 1회 실패로는 상태를 내리지 않는다. 순간적인 회선 흔들림이 알림이 되면
            # 운영자가 알림을 무시하게 된다.
            state.overall_severity = state.overall_severity or Severity.UNKNOWN

    session.flush()
    return state


def upsert_capabilities(
    session: Session,
    device_id: uuid.UUID,
    states: dict[str, SupportState],
    *,
    now: datetime | None = None,
) -> None:
    """기능 지원 상태를 저장한다.

    값이 없는 이유를 여기서 설명한다. InfluxDB 에 데이터가 비어 있을 때
    '장비에 기능이 없어서' 인지 '수집이 안 돼서' 인지 구분하는 근거다.
    """
    now = now or utcnow()
    existing = {
        (row.capability_key, row.dimension_value): row
        for row in session.scalars(
            select(DeviceCapability).where(DeviceCapability.device_id == device_id)
        )
    }

    for raw_key, support_state in states.items():
        capability_key, _, dimension = raw_key.partition("[")
        dimension_value = dimension.rstrip("]") if dimension else ""
        row = existing.get((capability_key, dimension_value))
        if row is None:
            session.add(
                DeviceCapability(
                    device_id=device_id,
                    capability_key=capability_key,
                    dimension_value=dimension_value,
                    support_state=support_state,
                    detected_at=now,
                    source="probe",
                )
            )
        elif row.support_state is not support_state:
            row.support_state = support_state
            row.detected_at = now

    session.flush()


def stale_devices(
    session: Session, *, threshold_seconds: float, now: datetime | None = None
) -> list[uuid.UUID]:
    """수집이 멈춘 장비. 마지막 성공으로부터 임계 시간을 넘긴 것들.

    수집기가 죽어 있는 동안에는 실패 기록조차 남지 않는다. 그래서 '조용한 정상' 과
    '조용한 장애' 를 구분하려면 마지막 성공 시각을 별도로 봐야 한다.
    """
    now = now or utcnow()
    stale: list[uuid.UUID] = []
    for state in session.scalars(select(DeviceRuntimeState)):
        last_success = as_utc(state.last_success_at)
        if last_success is None:
            continue
        if (now - last_success).total_seconds() > threshold_seconds:
            stale.append(state.device_id)
    return stale


def failure_summary(session: Session) -> dict[PollErrorCode, int]:
    counts: dict[PollErrorCode, int] = {}
    for state in session.scalars(select(DeviceRuntimeState)):
        if state.last_error_code is None:
            continue
        counts[state.last_error_code] = counts.get(state.last_error_code, 0) + 1
    return counts
