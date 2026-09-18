"""관측소 CRUD 와 CSV 일괄 등록."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile, status
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api import audit
from app.api.csv_import import parse_stations_csv, row_to_dict
from app.api.deps import RequireConfigure, RequireRead
from app.api.presenters import iso, lifecycle_or_400, parse_uuid, station_payload
from app.api.schemas import StationWriteRequest
from app.db.models import (
    CollectionMode,
    CollectionProfile,
    Device,
    DeviceEndpoint,
    DeviceRuntimeState,
    HealthState,
    LifecycleStatus,
    MetricProfile,
    Region,
    Station,
)
from app.db.session import session_scope
from app.domain.enums import Severity
from app.health.state_machine import rollup
from app.repository.postgres.collector_repo import as_utc

router = APIRouter(prefix="/api/v1", tags=["stations"])


def _region_id(session: Session, region_id: str | None, region_code: str | None) -> uuid.UUID | None:
    if region_id:
        identifier = parse_uuid(region_id, "지역 식별자")
        if session.get(Region, identifier) is None:
            raise HTTPException(status_code=400, detail="없는 지역이다")
        return identifier
    if region_code:
        region = session.scalar(select(Region).where(Region.region_code == region_code.upper()))
        if region is None:
            region = Region(region_code=region_code.upper(), name=region_code.upper())
            session.add(region)
            session.flush()
        return region.id
    return None


def _counts(session: Session) -> dict[uuid.UUID, int]:
    rows = session.execute(select(Device.station_id, func.count()).group_by(Device.station_id))
    return {row[0]: row[1] for row in rows}


def _worst_from_categories(categories: dict[uuid.UUID, dict[str, str]]) -> dict[uuid.UUID, str]:
    """장비 통신 성공 여부가 아니라 분류 상태의 최악값이다."""
    result: dict[uuid.UUID, str] = {}
    for station_id, cats in categories.items():
        values = [Severity(value) for value in cats.values()]
        result[station_id] = rollup(values).value if values else "UNKNOWN"
    return result


def _categories_by_station(session: Session) -> dict[uuid.UUID, dict[str, str]]:
    rows = session.execute(
        select(Device.station_id, HealthState.category, HealthState.severity)
        .join(HealthState, HealthState.device_id == Device.id)
        .where(HealthState.metric_key == "")
    )
    grouped: dict[uuid.UUID, dict[str, list[Severity]]] = {}
    for station_id, category, severity in rows:
        grouped.setdefault(station_id, {}).setdefault(category, []).append(severity)
    return {
        station_id: {category: rollup(values).value for category, values in categories.items()}
        for station_id, categories in grouped.items()
    }


def _last_success_by_station(session: Session) -> dict[uuid.UUID, object]:
    rows = session.execute(
        select(Device.station_id, func.max(DeviceRuntimeState.last_success_at)).join(
            DeviceRuntimeState, DeviceRuntimeState.device_id == Device.id
        ).group_by(Device.station_id)
    )
    return {row[0]: row[1] for row in rows if row[1] is not None}


def _modes_by_station(session: Session) -> dict[uuid.UUID, str]:
    rows = session.execute(select(Device.station_id, Device.collection_mode))
    grouped: dict[uuid.UUID, set[str]] = {}
    for station_id, mode in rows:
        grouped.setdefault(station_id, set()).add(mode.value)
    result: dict[uuid.UUID, str] = {}
    for station_id, modes in grouped.items():
        result[station_id] = next(iter(modes)) if len(modes) == 1 else "MIXED"
    return result


@router.get("/regions", summary="지역 목록")
def list_regions(actor: RequireRead) -> dict:
    with session_scope() as session:
        regions = session.scalars(select(Region).order_by(Region.region_code)).all()
        return {
            "regions": [
                {
                    "id": str(region.id),
                    "regionCode": region.region_code,
                    "name": region.name,
                    "description": region.description,
                }
                for region in regions
            ]
        }


@router.get("/stations", summary="관측소 목록")
def list_stations(
    actor: RequireRead,
    status_filter: str | None = Query(default=None, alias="status"),
    q: str | None = None,
) -> dict:
    with session_scope() as session:
        query = select(Station).order_by(Station.network_code, Station.station_code)
        if status_filter:
            query = query.where(Station.status == lifecycle_or_400(status_filter))
        if q:
            pattern = f"%{q.lower()}%"
            query = query.where(
                or_(
                    func.lower(Station.station_code).like(pattern),
                    func.lower(Station.name).like(pattern),
                    func.lower(Station.network_code).like(pattern),
                )
            )
        stations = session.scalars(query).all()
        counts = _counts(session)
        categories = _categories_by_station(session)
        worst = _worst_from_categories(categories)
        last_success = _last_success_by_station(session)
        modes = _modes_by_station(session)
        return {
            "stations": [
                station_payload(
                    station,
                    device_count=counts.get(station.id, 0),
                    worst_severity=worst.get(station.id),
                    categories=categories.get(station.id),
                    last_success_at=last_success.get(station.id),
                    collection_mode=modes.get(station.id),
                )
                for station in stations
            ]
        }


@router.post("/stations", status_code=status.HTTP_201_CREATED, summary="관측소 등록")
def create_station(body: StationWriteRequest, request: Request, actor: RequireConfigure) -> dict:
    if not body.station_code or not body.network_code or not body.name:
        raise HTTPException(status_code=400, detail="networkCode, stationCode, name 이 필요하다")

    with session_scope() as session:
        station = Station(
            station_code=body.station_code.upper(),
            network_code=body.network_code.upper(),
            name=body.name,
            region_id=_region_id(session, body.region_id, body.region_code),
            latitude=body.latitude,
            longitude=body.longitude,
            elevation_m=body.elevation_m,
            address=body.address,
            timezone=body.timezone or "Asia/Seoul",
            operator_name=body.operator_name,
            operator_contact=body.operator_contact,
            power_profile=body.power_profile,
            status=lifecycle_or_400(body.status) if body.status else LifecycleStatus.PLANNED,
            notes=body.notes,
        )
        session.add(station)
        try:
            session.flush()
        except IntegrityError as exc:
            raise HTTPException(status_code=409, detail="같은 네트워크의 관측소 코드가 이미 있다") from exc
        audit.record(
            session,
            actor=actor,
            action="create",
            entity_type="station",
            entity_id=str(station.id),
            after=station_payload(station),
            request=request,
        )
        return {"station": station_payload(station)}


@router.get("/stations/{station_id}", summary="관측소 상세")
def get_station(station_id: str, actor: RequireRead) -> dict:
    identifier = parse_uuid(station_id, "관측소 식별자")
    with session_scope() as session:
        station = session.get(Station, identifier)
        if station is None:
            raise HTTPException(status_code=404, detail="없는 관측소다")
        devices = session.scalars(select(Device).where(Device.station_id == identifier)).all()
        from app.api.presenters import device_payload

        return {
            "station": station_payload(station, device_count=len(devices)),
            "devices": [device_payload(device, include_children=True) for device in devices],
        }


@router.put("/stations/{station_id}", summary="관측소 수정")
def update_station(
    station_id: str, body: StationWriteRequest, request: Request, actor: RequireConfigure
) -> dict:
    identifier = parse_uuid(station_id, "관측소 식별자")
    with session_scope() as session:
        station = session.get(Station, identifier)
        if station is None:
            raise HTTPException(status_code=404, detail="없는 관측소다")
        if station.status is LifecycleStatus.RETIRED:
            raise HTTPException(status_code=409, detail="폐기된 관측소는 수정할 수 없다")

        before = station_payload(station)
        if body.station_code:
            station.station_code = body.station_code.upper()
        if body.network_code:
            station.network_code = body.network_code.upper()
        if body.name:
            station.name = body.name
        if body.region_id is not None or body.region_code is not None:
            station.region_id = _region_id(session, body.region_id, body.region_code)
        for field in (
            "latitude",
            "longitude",
            "elevation_m",
            "address",
            "timezone",
            "operator_name",
            "operator_contact",
            "power_profile",
            "notes",
        ):
            value = getattr(body, field)
            if value is not None:
                setattr(station, field, value)
        if body.status:
            new_status = lifecycle_or_400(body.status)
            if new_status is LifecycleStatus.RETIRED:
                raise HTTPException(status_code=400, detail="폐기는 /retire 로 처리한다")
            station.status = new_status
        try:
            session.flush()
        except IntegrityError as exc:
            raise HTTPException(status_code=409, detail="같은 네트워크의 관측소 코드가 이미 있다") from exc
        audit.record(
            session,
            actor=actor,
            action="update",
            entity_type="station",
            entity_id=str(station.id),
            before=before,
            after=station_payload(station),
            request=request,
        )
        return {"station": station_payload(station)}


@router.post("/stations/{station_id}/retire", summary="관측소 폐기")
def retire_station(station_id: str, request: Request, actor: RequireConfigure) -> dict:
    identifier = parse_uuid(station_id, "관측소 식별자")
    with session_scope() as session:
        station = session.get(Station, identifier)
        if station is None:
            raise HTTPException(status_code=404, detail="없는 관측소다")
        before = {"status": station.status.value}
        station.status = LifecycleStatus.RETIRED
        devices = session.scalars(select(Device).where(Device.station_id == identifier)).all()
        for device in devices:
            device.status = LifecycleStatus.RETIRED
            device.enabled = False
        audit.record(
            session,
            actor=actor,
            action="retire",
            entity_type="station",
            entity_id=str(station.id),
            before=before,
            after={"status": station.status.value, "retiredDevices": len(devices)},
            request=request,
        )
        return {"station": station_payload(station, device_count=len(devices))}


@router.get("/stations/{station_id}/current-health", summary="관측소 현재 상태")
def station_health(station_id: str, actor: RequireRead) -> dict:
    identifier = parse_uuid(station_id, "관측소 식별자")
    with session_scope() as session:
        station = session.get(Station, identifier)
        if station is None:
            raise HTTPException(status_code=404, detail="없는 관측소다")
        devices = session.scalars(select(Device).where(Device.station_id == identifier)).all()
        device_ids = [device.id for device in devices]
        runtimes = {
            state.device_id: state
            for state in session.scalars(
                select(DeviceRuntimeState).where(
                    DeviceRuntimeState.device_id.in_(device_ids or [uuid.uuid4()])
                )
            )
        }
        category_rows = session.execute(
            select(HealthState.device_id, HealthState.severity).where(
                HealthState.device_id.in_(device_ids or [uuid.uuid4()]),
                HealthState.metric_key == "",
            )
        )
        by_device: dict[uuid.UUID, list[Severity]] = {}
        for device_id, severity in category_rows:
            by_device.setdefault(device_id, []).append(severity)
        device_overall = {
            device_id: rollup(values).value if values else "UNKNOWN"
            for device_id, values in by_device.items()
        }
        station_severities = [Severity(value) for value in device_overall.values()]
        return {
            "stationId": station_id,
            "stationCode": station.station_code,
            "overall": rollup(station_severities).value if station_severities else "UNKNOWN",
            "devices": [
                {
                    "deviceId": str(device.id),
                    "label": device.label,
                    "enabled": device.enabled,
                    "status": device.status.value,
                    "overall": device_overall.get(device.id, "UNKNOWN"),
                    "lastSuccessAt": iso(runtimes[device.id].last_success_at) if device.id in runtimes else None,
                    "consecutiveFailures": (
                        runtimes[device.id].consecutive_failures if device.id in runtimes else 0
                    ),
                }
                for device in devices
            ],
        }


def _default_profiles(session: Session) -> tuple[CollectionProfile | None, MetricProfile | None]:
    collection = session.scalar(select(CollectionProfile).where(CollectionProfile.is_default.is_(True)))
    metric = session.scalar(select(MetricProfile).where(MetricProfile.is_default.is_(True)))
    return collection, metric


@router.post("/stations/import", summary="CSV 일괄 등록")
async def import_stations(
    request: Request,
    actor: RequireConfigure,
    file: UploadFile = File(...),
) -> dict:
    raw = await file.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="CSV 는 UTF-8 이어야 한다") from exc

    parsed = parse_stations_csv(text)
    imported: list[dict] = []
    errors = [
        {"row": error.row, "field": error.field, "message": error.message} for error in parsed.errors
    ]

    with session_scope() as session:
        collection, metric = _default_profiles(session)
        for row in parsed.rows:
            existing = session.scalar(
                select(Station).where(
                    Station.network_code == row.network_code,
                    Station.station_code == row.station_code,
                )
            )
            if existing is not None:
                errors.append(
                    {
                        "row": row.row_number,
                        "field": "stationCode",
                        "message": "이미 등록된 관측소다",
                    }
                )
                continue

            station = Station(
                network_code=row.network_code,
                station_code=row.station_code,
                name=row.name,
                latitude=row.latitude,
                longitude=row.longitude,
                elevation_m=row.elevation_m,
                timezone=row.timezone,
                region_id=_region_id(session, None, row.region_code),
                status=LifecycleStatus.PLANNED,
            )
            session.add(station)
            session.flush()

            if row.hostname:
                device = Device(
                    station_id=station.id,
                    adapter_key=row.adapter_key,
                    instrument_id=row.instrument_id,
                    serial_number=row.serial_number,
                    collection_mode=CollectionMode.DIRECT,
                    collection_profile_id=collection.id if collection else None,
                    metric_profile_id=metric.id if metric else None,
                    enabled=True,
                    status=LifecycleStatus.PLANNED,
                )
                session.add(device)
                session.flush()
                session.add(
                    DeviceEndpoint(
                        device_id=device.id,
                        scheme=row.scheme,
                        hostname=row.hostname,
                        port=row.port,
                        credential_reference=row.credential_reference,
                    )
                )

            imported.append(row_to_dict(row) | {"id": str(station.id)})

        if imported:
            audit.record(
                session,
                actor=actor,
                action="import",
                entity_type="station",
                entity_id=None,
                after={"imported": len(imported), "failed": len(errors)},
                request=request,
            )

    return {"imported": len(imported), "failed": len(errors), "stations": imported, "errors": errors}


@router.get("/poll-runs", summary="최근 수집 이력")
def list_poll_runs(actor: RequireRead, limit: int = Query(default=50, ge=1, le=500)) -> dict:
    from app.db.models import PollRun

    with session_scope() as session:
        runs = session.scalars(select(PollRun).order_by(PollRun.observed_at.desc()).limit(limit)).all()
        return {
            "runs": [
                {
                    "pollId": run.poll_id,
                    "deviceId": str(run.device_id),
                    "observedAt": as_utc(run.observed_at).isoformat() if as_utc(run.observed_at) else None,
                    "success": run.success,
                    "latencyMs": run.latency_ms,
                    "errorCode": run.error_code.value if run.error_code else None,
                    "errorMessage": run.error_message,
                    "sampleCount": run.sample_count,
                }
                for run in runs
            ]
        }
