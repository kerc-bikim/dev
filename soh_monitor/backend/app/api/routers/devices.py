"""기록계 등록·연결 시험·수동 수집.

수동 수집(poll-now)은 API 가 장비를 직접 부르지 않는다. `next_poll_at` 을 현재로
당겨 두고 collector 가 다음 Tick 에 집어 간다. 연결 시험·Probe·미리보기만
등록 화면을 위해 API 가 나가며, 그 전에 SSRF 화이트리스트를 통과한다.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlalchemy import delete, desc, select
from sqlalchemy.orm import Session

from app.api import audit, connection as connection_ops
from app.api.deps import RequireConfigure, RequireOperate, RequireRead
from app.api.presenters import (
    device_payload,
    external_soh_payload,
    iso,
    lifecycle_or_400,
    override_payload,
    parse_uuid,
    reject_secret_fields,
    sensor_payload,
)
from app.api.schemas import (
    AxisWrite,
    ConnectionProbeRequest,
    DeviceWriteRequest,
    ExternalSohWrite,
    OverrideWrite,
    SensorWrite,
)
from app.auth.credentials import CredentialResolver
from app.db.models import (
    CollectionMode,
    CollectionProfile,
    Device,
    DeviceCapability,
    DeviceEndpoint,
    DeviceMetricOverride,
    DeviceRuntimeState,
    ExternalSohChannel,
    LifecycleStatus,
    MetricDefinitionRow,
    MetricProfile,
    PollRun,
    Sensor,
    SensorAxis,
    Station,
)
from app.db.session import session_scope
from app.health.conditions import ConditionError, validate_condition
from app.repository.postgres import collector_repo as repo

router = APIRouter(prefix="/api/v1", tags=["devices"])

DEFAULT_AXES = ("U", "V", "W")


def _load_device(session: Session, device_id: str) -> Device:
    identifier = parse_uuid(device_id, "장비 식별자")
    device = session.get(Device, identifier)
    if device is None:
        raise HTTPException(status_code=404, detail="등록되지 않은 장비다")
    return device


def _default_profiles(session: Session) -> tuple[CollectionProfile | None, MetricProfile | None]:
    collection = session.scalar(select(CollectionProfile).where(CollectionProfile.is_default.is_(True)))
    metric = session.scalar(select(MetricProfile).where(MetricProfile.is_default.is_(True)))
    return collection, metric


def _apply_endpoint(session: Session, device: Device, endpoint_body) -> None:
    if endpoint_body is None:
        return
    existing = device.endpoint
    values = dict(
        scheme=endpoint_body.scheme,
        hostname=endpoint_body.hostname.strip(),
        port=endpoint_body.port,
        base_path=endpoint_body.base_path or "/",
        tls_verify=endpoint_body.tls_verify,
        credential_reference=endpoint_body.credential_reference,
        connect_timeout_ms=endpoint_body.connect_timeout_ms,
        request_timeout_ms=endpoint_body.request_timeout_ms,
        connection_options=endpoint_body.connection_options or {},
    )
    if existing is None:
        session.add(DeviceEndpoint(device_id=device.id, **values))
    else:
        for name, value in values.items():
            setattr(existing, name, value)


def _apply_device_fields(session: Session, device: Device, body: DeviceWriteRequest) -> None:
    if body.label is not None:
        device.label = body.label
    if body.serial_number is not None:
        device.serial_number = body.serial_number
    if body.instrument_id is not None:
        device.instrument_id = body.instrument_id
    if body.firmware_version is not None:
        device.firmware_version = body.firmware_version
    if body.adapter_key is not None:
        device.adapter_key = body.adapter_key
    if body.adapter_version is not None:
        device.adapter_version = body.adapter_version
    if body.collection_mode is not None:
        try:
            device.collection_mode = CollectionMode(body.collection_mode)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"알 수 없는 수집 방식: {body.collection_mode}") from exc
    if body.edge_id is not None:
        device.edge_id = parse_uuid(body.edge_id, "Edge 식별자") if body.edge_id else None
    if body.collection_profile_id is not None:
        device.collection_profile_id = (
            parse_uuid(body.collection_profile_id, "수집 프로파일") if body.collection_profile_id else None
        )
    if body.metric_profile_id is not None:
        device.metric_profile_id = (
            parse_uuid(body.metric_profile_id, "Metric 프로파일") if body.metric_profile_id else None
        )
    if "data_source_uri" in body.model_fields_set:
        device.data_source_uri = body.data_source_uri
    if body.enabled is not None:
        device.enabled = body.enabled
    if body.status is not None:
        new_status = lifecycle_or_400(body.status)
        if new_status is LifecycleStatus.RETIRED:
            raise HTTPException(status_code=400, detail="폐기는 /retire 로 처리한다")
        device.status = new_status
    if body.notes is not None:
        device.notes = body.notes
    _apply_endpoint(session, device, body.endpoint)
    if device.collection_mode is CollectionMode.EDGE and device.edge_id is None:
        raise HTTPException(status_code=400, detail="EDGE 수집은 Edge 지정이 필요하다")
    from app.api import edge_ops

    edge_ops.sync_device_assignment(session, device)


@router.post(
    "/stations/{station_id}/devices",
    status_code=status.HTTP_201_CREATED,
    summary="기록계 등록",
)
def create_device(
    station_id: str, body: DeviceWriteRequest, request: Request, actor: RequireConfigure
) -> dict:
    reject_secret_fields(body.model_dump(by_alias=True, exclude_none=True))
    identifier = parse_uuid(station_id, "관측소 식별자")
    with session_scope() as session:
        station = session.get(Station, identifier)
        if station is None:
            raise HTTPException(status_code=404, detail="없는 관측소다")
        if station.status is LifecycleStatus.RETIRED:
            raise HTTPException(status_code=409, detail="폐기된 관측소에는 장비를 달 수 없다")
        if not body.adapter_key:
            raise HTTPException(status_code=400, detail="adapterKey 가 필요하다")
        if body.endpoint is None or not body.endpoint.hostname:
            raise HTTPException(status_code=400, detail="접속 정보(hostname)가 필요하다")

        collection, metric = _default_profiles(session)
        device = Device(
            station_id=station.id,
            adapter_key=body.adapter_key,
            label=body.label or "기록계",
            collection_mode=CollectionMode.DIRECT,
            collection_profile_id=collection.id if collection else None,
            metric_profile_id=metric.id if metric else None,
            enabled=True,
            status=LifecycleStatus.PLANNED,
        )
        session.add(device)
        session.flush()
        _apply_device_fields(session, device, body)
        session.flush()
        session.refresh(device)
        audit.record(
            session,
            actor=actor,
            action="create",
            entity_type="device",
            entity_id=str(device.id),
            after=device_payload(device),
            request=request,
        )
        return {"device": device_payload(device, include_children=True)}


@router.get("/devices/{device_id}", summary="기록계 상세")
def get_device(device_id: str, actor: RequireRead) -> dict:
    with session_scope() as session:
        device = _load_device(session, device_id)
        return {"device": device_payload(device, include_children=True)}


@router.put("/devices/{device_id}", summary="기록계 수정")
def update_device(
    device_id: str, body: DeviceWriteRequest, request: Request, actor: RequireConfigure
) -> dict:
    reject_secret_fields(body.model_dump(by_alias=True, exclude_none=True))
    with session_scope() as session:
        device = _load_device(session, device_id)
        if device.status is LifecycleStatus.RETIRED:
            raise HTTPException(status_code=409, detail="폐기된 장비는 수정할 수 없다")
        before = device_payload(device)
        _apply_device_fields(session, device, body)
        session.flush()
        session.refresh(device)
        audit.record(
            session,
            actor=actor,
            action="update",
            entity_type="device",
            entity_id=str(device.id),
            before=before,
            after=device_payload(device),
            request=request,
        )
        return {"device": device_payload(device, include_children=True)}


@router.post("/devices/{device_id}/retire", summary="기록계 폐기")
def retire_device(device_id: str, request: Request, actor: RequireConfigure) -> dict:
    with session_scope() as session:
        device = _load_device(session, device_id)
        before = {"status": device.status.value, "enabled": device.enabled}
        device.status = LifecycleStatus.RETIRED
        device.enabled = False
        audit.record(
            session,
            actor=actor,
            action="retire",
            entity_type="device",
            entity_id=str(device.id),
            before=before,
            after={"status": device.status.value, "enabled": device.enabled},
            request=request,
        )
        return {"device": device_payload(device)}


@router.put("/devices/{device_id}/sensors", summary="센서·축 설정")
def replace_sensors(
    device_id: str, body: list[SensorWrite], request: Request, actor: RequireConfigure
) -> dict:
    with session_scope() as session:
        device = _load_device(session, device_id)
        session.execute(delete(Sensor).where(Sensor.device_id == device.id))
        session.flush()
        for item in body:
            sensor = Sensor(
                device_id=device.id,
                port=item.port,
                manufacturer=item.manufacturer,
                model=item.model,
                serial_number=item.serial_number,
                axis_count=item.axis_count,
                enabled=item.enabled,
            )
            session.add(sensor)
            session.flush()
            axes = item.axes
            if not axes:
                axes = [
                    AxisWrite(axis_code=code)
                    for code in DEFAULT_AXES[: item.axis_count]
                ]
            for axis in axes:
                session.add(
                    SensorAxis(
                        sensor_id=sensor.id,
                        axis_code=axis.axis_code,
                        soh_channel=axis.soh_channel,
                        warning_threshold=axis.warning_threshold,
                        critical_threshold=axis.critical_threshold,
                        unit=axis.unit,
                    )
                )
        session.flush()
        audit.record(
            session,
            actor=actor,
            action="update",
            entity_type="sensor",
            entity_id=str(device.id),
            after={"count": len(body)},
            request=request,
        )
        device = _load_device(session, device_id)
        return {"sensors": [sensor_payload(sensor) for sensor in device.sensors]}


@router.put("/devices/{device_id}/external-soh-channels", summary="외부 SOH 채널 설정")
def replace_external_soh(
    device_id: str, body: list[ExternalSohWrite], request: Request, actor: RequireConfigure
) -> dict:
    with session_scope() as session:
        device = _load_device(session, device_id)
        session.execute(delete(ExternalSohChannel).where(ExternalSohChannel.device_id == device.id))
        session.flush()
        for item in body:
            session.add(
                ExternalSohChannel(
                    device_id=device.id,
                    channel_number=item.channel_number,
                    name=item.name,
                    measurement_type=item.measurement_type,
                    raw_unit=item.raw_unit,
                    output_unit=item.output_unit,
                    scale=item.scale,
                    offset=item.offset,
                    warning_low=item.warning_low,
                    warning_high=item.warning_high,
                    critical_low=item.critical_low,
                    critical_high=item.critical_high,
                    enabled=item.enabled,
                )
            )
        session.flush()
        audit.record(
            session,
            actor=actor,
            action="update",
            entity_type="external_soh",
            entity_id=str(device.id),
            after={"count": len(body)},
            request=request,
        )
        channels = session.scalars(
            select(ExternalSohChannel).where(ExternalSohChannel.device_id == device.id)
        ).all()
        return {"channels": [external_soh_payload(channel) for channel in channels]}


@router.get("/devices/{device_id}/metric-overrides", summary="장비 Metric Override")
def list_overrides(device_id: str, actor: RequireRead) -> dict:
    with session_scope() as session:
        device = _load_device(session, device_id)
        rows = session.scalars(
            select(DeviceMetricOverride).where(DeviceMetricOverride.device_id == device.id)
        ).all()
        return {"overrides": [override_payload(row) for row in rows]}


@router.put("/devices/{device_id}/metric-overrides", summary="장비 Metric Override 저장")
def replace_overrides(
    device_id: str, body: list[OverrideWrite], request: Request, actor: RequireConfigure
) -> dict:
    with session_scope() as session:
        device = _load_device(session, device_id)
        for item in body:
            if session.get(MetricDefinitionRow, item.metric_key) is None:
                raise HTTPException(status_code=400, detail=f"카탈로그에 없는 Metric 이다: {item.metric_key}")
            try:
                validate_condition(item.warning_condition)
                validate_condition(item.critical_condition)
            except ConditionError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

        session.execute(delete(DeviceMetricOverride).where(DeviceMetricOverride.device_id == device.id))
        session.flush()
        for item in body:
            session.add(
                DeviceMetricOverride(
                    device_id=device.id,
                    metric_key=item.metric_key,
                    dimension_value=item.dimension_value or "",
                    enabled=item.enabled,
                    alerting_enabled=item.alerting_enabled,
                    warning_condition=item.warning_condition,
                    critical_condition=item.critical_condition,
                    hold_seconds=item.hold_seconds,
                    recovery_seconds=item.recovery_seconds,
                    reason=item.reason,
                )
            )
        session.flush()
        audit.record(
            session,
            actor=actor,
            action="update",
            entity_type="device_metric_override",
            entity_id=str(device.id),
            after={"count": len(body)},
            request=request,
        )
        rows = session.scalars(
            select(DeviceMetricOverride).where(DeviceMetricOverride.device_id == device.id)
        ).all()
        return {"overrides": [override_payload(row) for row in rows]}


@router.get("/devices/{device_id}/capabilities", summary="장비 Capability")
def device_capabilities(device_id: str, actor: RequireRead) -> dict:
    with session_scope() as session:
        device = _load_device(session, device_id)
        rows = session.scalars(
            select(DeviceCapability).where(DeviceCapability.device_id == device.id)
        ).all()
        return {
            "deviceId": device_id,
            "capabilities": [
                {
                    "key": row.capability_key,
                    "dimension": row.dimension_value or None,
                    "supportState": row.support_state.value,
                    "detectedAt": iso(row.detected_at),
                    "source": row.source,
                }
                for row in rows
            ],
        }


def _endpoint_probe_request(device: Device) -> ConnectionProbeRequest:
    endpoint = device.endpoint
    if endpoint is None:
        raise HTTPException(status_code=409, detail="접속 정보가 없는 장비다")
    return ConnectionProbeRequest(
        adapter_key=device.adapter_key,
        hostname=endpoint.hostname,
        scheme=endpoint.scheme,
        port=endpoint.port,
        base_path=endpoint.base_path,
        tls_verify=endpoint.tls_verify,
        credential_reference=endpoint.credential_reference,
        instrument_id=device.instrument_id,
        connect_timeout_ms=endpoint.connect_timeout_ms,
        request_timeout_ms=min(endpoint.request_timeout_ms, 15000),
    )


async def _run_test_connection(body: ConnectionProbeRequest, station_code: str = "PROBE") -> dict:
    adapter, context = connection_ops.build_context(
        hostname=body.hostname,
        adapter_key=body.adapter_key,
        station_code=station_code,
        scheme=body.scheme,
        port=body.port,
        base_path=body.base_path,
        tls_verify=body.tls_verify,
        instrument_id=body.instrument_id,
        credential_reference=body.credential_reference,
        connect_timeout_ms=body.connect_timeout_ms,
        request_timeout_ms=body.request_timeout_ms,
    )
    result = await adapter.test_connection(context)
    return {
        "reachable": result.reachable,
        "latencyMs": result.latency_ms,
        "httpStatus": result.http_status,
        "message": result.message,
        "identity": connection_ops.identity_payload(result.identity),
    }


@router.post("/devices/test-connection", summary="등록 전 연결 시험")
async def test_connection_preview(body: ConnectionProbeRequest, actor: RequireOperate) -> dict:
    return await _run_test_connection(body)


@router.post("/devices/{device_id}/test-connection", summary="연결 시험")
async def test_connection(device_id: str, actor: RequireOperate) -> dict:
    with session_scope() as session:
        device = _load_device(session, device_id)
        body = _endpoint_probe_request(device)
        station = session.get(Station, device.station_id)
        station_code = station.station_code if station else "PROBE"
        if device.collection_mode is CollectionMode.EDGE:
            if device.edge_id is None:
                raise HTTPException(status_code=409, detail="EDGE 수집 장비에 Edge 가 없다")
            from app.api import edge_ops
            from app.db.models import EdgeCollector

            edge = session.get(EdgeCollector, device.edge_id)
            if edge is None:
                raise HTTPException(status_code=404, detail="없는 Edge 다")
            payload = body.model_dump(by_alias=True)
            payload["deviceId"] = str(device.id)
            payload["stationCode"] = station_code
            task = edge_ops.enqueue_task(
                session,
                edge,
                task_type="test_connection",
                payload=payload,
                device_id=device.id,
            )
            return {
                "queued": True,
                "taskId": str(task.id),
                "edgeId": str(edge.id),
                "message": "지역 Edge 가 연결 시험을 수행한다",
            }
    return await _run_test_connection(body, station_code=station_code)


@router.post("/devices/probe", summary="등록 전 장비 탐지")
async def probe_preview(body: ConnectionProbeRequest, actor: RequireOperate) -> dict:
    adapter, context = connection_ops.build_context(
        hostname=body.hostname,
        adapter_key=body.adapter_key,
        scheme=body.scheme,
        port=body.port,
        base_path=body.base_path,
        tls_verify=body.tls_verify,
        instrument_id=body.instrument_id,
        credential_reference=body.credential_reference,
        connect_timeout_ms=body.connect_timeout_ms,
        request_timeout_ms=body.request_timeout_ms,
    )
    identity = await adapter.probe(context)
    return {"identity": connection_ops.identity_payload(identity)}


@router.post("/devices/{device_id}/probe", summary="장비 탐지")
async def probe_device(device_id: str, actor: RequireOperate) -> dict:
    with session_scope() as session:
        device = _load_device(session, device_id)
        body = _endpoint_probe_request(device)
    adapter, context = connection_ops.build_context(
        hostname=body.hostname,
        adapter_key=body.adapter_key,
        scheme=body.scheme,
        port=body.port,
        base_path=body.base_path,
        tls_verify=body.tls_verify,
        instrument_id=body.instrument_id,
        credential_reference=body.credential_reference,
        connect_timeout_ms=body.connect_timeout_ms,
        request_timeout_ms=body.request_timeout_ms,
    )
    identity = await adapter.probe(context)
    return {"deviceId": device_id, "identity": connection_ops.identity_payload(identity)}


@router.get("/devices/{device_id}/soh-preview", summary="SOH 원본 미리보기")
async def soh_preview(device_id: str, actor: RequireOperate) -> dict:
    with session_scope() as session:
        device = _load_device(session, device_id)
        body = _endpoint_probe_request(device)
        resolver = CredentialResolver()
        credential = resolver.resolve(body.credential_reference)

    adapter, context = connection_ops.build_context(
        hostname=body.hostname,
        adapter_key=body.adapter_key,
        scheme=body.scheme,
        port=body.port,
        base_path=body.base_path,
        tls_verify=body.tls_verify,
        instrument_id=body.instrument_id,
        credential_reference=body.credential_reference,
        connect_timeout_ms=body.connect_timeout_ms,
        request_timeout_ms=body.request_timeout_ms,
        resolver=resolver,
    )
    fetch = await adapter._fetch(context)  # noqa: SLF001 - 미리보기는 수집 파이프라인을 타지 않는다
    payload = adapter.redact(fetch.payload) if fetch.success else None
    serialized = str(payload).lower() if payload else ""
    for leaked in ("password=", credential.get("password", "___never___") if credential else "___never___"):
        if leaked and leaked != "___never___" and leaked.lower() in serialized:
            payload = None
            break
    return {
        "deviceId": device_id,
        "success": fetch.success,
        "httpStatus": fetch.http_status,
        "errorCode": fetch.error_code.value if fetch.error_code else None,
        "errorMessage": fetch.error_message,
        "payload": payload,
    }


@router.post(
    "/devices/{device_id}/poll-now",
    status_code=status.HTTP_202_ACCEPTED,
    summary="수동 수집 요청",
)
def poll_now(device_id: str, response: Response, actor: RequireOperate) -> dict[str, object]:
    identifier = parse_uuid(device_id, "장비 식별자")
    with session_scope() as session:
        device = session.get(Device, identifier)
        if device is None:
            raise HTTPException(status_code=404, detail="등록되지 않은 장비다")
        if not device.enabled:
            raise HTTPException(status_code=409, detail="수집이 비활성된 장비다")
        if device.collection_mode is CollectionMode.EDGE:
            if device.edge_id is None:
                raise HTTPException(status_code=409, detail="EDGE 수집 장비에 Edge 가 없다")
            from app.api import edge_ops
            from app.db.models import EdgeCollector

            edge = session.get(EdgeCollector, device.edge_id)
            if edge is None:
                raise HTTPException(status_code=404, detail="없는 Edge 다")
            task = edge_ops.enqueue_task(
                session,
                edge,
                task_type="poll_now",
                payload={"deviceId": str(device.id)},
                device_id=identifier,
            )
            response.headers["Retry-After"] = "10"
            return {
                "deviceId": device_id,
                "accepted": True,
                "queued": True,
                "taskId": str(task.id),
                "detail": "지역 Edge 가 다음 Tick 에서 이 장비를 수집한다",
            }
        repo.request_immediate_poll(session, identifier)

    response.headers["Retry-After"] = "10"
    return {
        "deviceId": device_id,
        "accepted": True,
        "detail": "다음 수집 Tick 에서 곧바로 수집한다",
    }


@router.get("/devices/{device_id}/poll-runs", summary="최근 수집 이력")
def poll_runs(device_id: str, actor: RequireRead, limit: int = 20) -> dict[str, object]:
    identifier = parse_uuid(device_id, "장비 식별자")
    limit = max(1, min(limit, 200))

    with session_scope() as session:
        if session.get(Device, identifier) is None:
            raise HTTPException(status_code=404, detail="등록되지 않은 장비다")

        runs = session.scalars(
            select(PollRun)
            .where(PollRun.device_id == identifier)
            .order_by(desc(PollRun.observed_at))
            .limit(limit)
        ).all()
        state = session.get(DeviceRuntimeState, identifier)
        return {
            "deviceId": device_id,
            "runtime": {
                "lastPollAt": repo.as_utc(state.last_poll_at) if state else None,
                "lastSuccessAt": repo.as_utc(state.last_success_at) if state else None,
                "lastObservedAt": repo.as_utc(state.last_observed_at) if state else None,
                "consecutiveFailures": state.consecutive_failures if state else 0,
                "severity": state.overall_severity.value if state else "UNKNOWN",
                "lastErrorCode": (
                    state.last_error_code.value if state and state.last_error_code else None
                ),
                "leaseOwner": state.poll_lease_owner if state else None,
            },
            "runs": [
                {
                    "pollId": run.poll_id,
                    "observedAt": repo.as_utc(run.observed_at),
                    "receivedAt": repo.as_utc(run.received_at),
                    "success": run.success,
                    "latencyMs": run.latency_ms,
                    "httpStatus": run.http_status,
                    "sampleCount": run.sample_count,
                    "errorCode": run.error_code.value if run.error_code else None,
                    "errorMessage": run.error_message,
                    "unmappedValues": run.unmapped_values or {},
                }
                for run in runs
            ],
        }
