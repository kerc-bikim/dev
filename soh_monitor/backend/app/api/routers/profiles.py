"""수집·Metric 프로파일."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api import audit
from app.api.deps import RequireConfigure, RequireRead
from app.api.presenters import collection_profile_payload, metric_profile_payload, parse_uuid
from app.api.schemas import CollectionProfileWrite, MetricProfileWrite
from app.db.models import CollectionProfile, Device, MetricDefinitionRow, MetricProfile, ProfileMetric
from app.db.session import session_scope
from app.health.conditions import ConditionError, validate_condition

router = APIRouter(prefix="/api/v1", tags=["profiles"])


def _collection_affected(session: Session, profile_id) -> int:
    return session.scalar(
        select(func.count()).select_from(Device).where(Device.collection_profile_id == profile_id)
    ) or 0


def _metric_affected(session: Session, profile_id) -> int:
    return session.scalar(
        select(func.count()).select_from(Device).where(Device.metric_profile_id == profile_id)
    ) or 0


def _clear_default_collection(session: Session, keep_id) -> None:
    for profile in session.scalars(select(CollectionProfile).where(CollectionProfile.is_default.is_(True))):
        if profile.id != keep_id:
            profile.is_default = False


def _clear_default_metric(session: Session, keep_id) -> None:
    for profile in session.scalars(select(MetricProfile).where(MetricProfile.is_default.is_(True))):
        if profile.id != keep_id:
            profile.is_default = False


def _replace_entries(session: Session, profile: MetricProfile, entries) -> None:
    session.execute(delete(ProfileMetric).where(ProfileMetric.profile_id == profile.id))
    session.flush()
    for item in entries:
        if session.get(MetricDefinitionRow, item.metric_key) is None:
            raise HTTPException(status_code=400, detail=f"카탈로그에 없는 Metric 이다: {item.metric_key}")
        try:
            validate_condition(item.warning_condition)
            validate_condition(item.critical_condition)
        except ConditionError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        session.add(
            ProfileMetric(
                profile_id=profile.id,
                metric_key=item.metric_key,
                enabled=item.enabled,
                alerting_enabled=item.alerting_enabled,
                warning_condition=item.warning_condition or {},
                critical_condition=item.critical_condition or {},
                hold_seconds=item.hold_seconds,
                recovery_seconds=item.recovery_seconds,
                consecutive_violations=item.consecutive_violations,
            )
        )


@router.get("/collection-profiles", summary="수집 프로파일 목록")
def list_collection_profiles(actor: RequireRead) -> dict:
    with session_scope() as session:
        profiles = session.scalars(select(CollectionProfile).order_by(CollectionProfile.name)).all()
        return {
            "profiles": [
                collection_profile_payload(profile, affected=_collection_affected(session, profile.id))
                for profile in profiles
            ]
        }


@router.post("/collection-profiles", status_code=status.HTTP_201_CREATED, summary="수집 프로파일 생성")
def create_collection_profile(
    body: CollectionProfileWrite, request: Request, actor: RequireConfigure
) -> dict:
    if not body.name:
        raise HTTPException(status_code=400, detail="이름이 필요하다")
    with session_scope() as session:
        profile = CollectionProfile(
            name=body.name,
            description=body.description,
            poll_interval_minutes=body.poll_interval_minutes or 5,
            retry_count=body.retry_count if body.retry_count is not None else 1,
            retry_delay_seconds=body.retry_delay_seconds if body.retry_delay_seconds is not None else 10,
            data_check_interval_minutes=body.data_check_interval_minutes or 10,
            connect_timeout_ms=body.connect_timeout_ms or 5000,
            request_timeout_ms=body.request_timeout_ms or 15000,
            is_default=bool(body.is_default),
        )
        session.add(profile)
        try:
            session.flush()
        except IntegrityError as exc:
            raise HTTPException(status_code=409, detail="같은 이름의 프로파일이 있다") from exc
        if profile.is_default:
            _clear_default_collection(session, profile.id)
        audit.record(
            session,
            actor=actor,
            action="create",
            entity_type="collection_profile",
            entity_id=str(profile.id),
            after=collection_profile_payload(profile),
            request=request,
        )
        return {"profile": collection_profile_payload(profile)}


@router.get("/collection-profiles/{profile_id}", summary="수집 프로파일 상세")
def get_collection_profile(profile_id: str, actor: RequireRead) -> dict:
    identifier = parse_uuid(profile_id, "프로파일 식별자")
    with session_scope() as session:
        profile = session.get(CollectionProfile, identifier)
        if profile is None:
            raise HTTPException(status_code=404, detail="없는 프로파일이다")
        return {
            "profile": collection_profile_payload(profile, affected=_collection_affected(session, profile.id))
        }


@router.put("/collection-profiles/{profile_id}", summary="수집 프로파일 수정")
def update_collection_profile(
    profile_id: str, body: CollectionProfileWrite, request: Request, actor: RequireConfigure
) -> dict:
    identifier = parse_uuid(profile_id, "프로파일 식별자")
    with session_scope() as session:
        profile = session.get(CollectionProfile, identifier)
        if profile is None:
            raise HTTPException(status_code=404, detail="없는 프로파일이다")
        before = collection_profile_payload(profile, affected=_collection_affected(session, profile.id))
        for field in (
            "name",
            "description",
            "poll_interval_minutes",
            "retry_count",
            "retry_delay_seconds",
            "data_check_interval_minutes",
            "connect_timeout_ms",
            "request_timeout_ms",
        ):
            value = getattr(body, field)
            if value is not None:
                setattr(profile, field, value)
        if body.is_default is not None:
            profile.is_default = body.is_default
            if profile.is_default:
                _clear_default_collection(session, profile.id)
        try:
            session.flush()
        except IntegrityError as exc:
            raise HTTPException(status_code=409, detail="같은 이름의 프로파일이 있다") from exc
        after = collection_profile_payload(profile, affected=_collection_affected(session, profile.id))
        audit.record(
            session,
            actor=actor,
            action="update",
            entity_type="collection_profile",
            entity_id=str(profile.id),
            before=before,
            after=after,
            request=request,
        )
        return {"profile": after}


@router.get("/metric-profiles", summary="Metric 프로파일 목록")
def list_metric_profiles(actor: RequireRead) -> dict:
    with session_scope() as session:
        profiles = session.scalars(select(MetricProfile).order_by(MetricProfile.name)).all()
        return {
            "profiles": [
                metric_profile_payload(
                    profile,
                    affected=_metric_affected(session, profile.id),
                    entries=profile.entries,
                )
                for profile in profiles
            ]
        }


@router.post("/metric-profiles", status_code=status.HTTP_201_CREATED, summary="Metric 프로파일 생성")
def create_metric_profile(body: MetricProfileWrite, request: Request, actor: RequireConfigure) -> dict:
    if not body.name:
        raise HTTPException(status_code=400, detail="이름이 필요하다")
    with session_scope() as session:
        profile = MetricProfile(
            name=body.name,
            description=body.description,
            is_default=bool(body.is_default),
        )
        session.add(profile)
        try:
            session.flush()
        except IntegrityError as exc:
            raise HTTPException(status_code=409, detail="같은 이름의 프로파일이 있다") from exc
        if profile.is_default:
            _clear_default_metric(session, profile.id)
        if body.entries:
            _replace_entries(session, profile, body.entries)
        session.flush()
        audit.record(
            session,
            actor=actor,
            action="create",
            entity_type="metric_profile",
            entity_id=str(profile.id),
            after={"name": profile.name, "entryCount": len(body.entries or [])},
            request=request,
        )
        session.refresh(profile)
        return {
            "profile": metric_profile_payload(
                profile, affected=_metric_affected(session, profile.id), entries=profile.entries
            )
        }


@router.get("/metric-profiles/{profile_id}", summary="Metric 프로파일 상세")
def get_metric_profile(profile_id: str, actor: RequireRead) -> dict:
    identifier = parse_uuid(profile_id, "프로파일 식별자")
    with session_scope() as session:
        profile = session.get(MetricProfile, identifier)
        if profile is None:
            raise HTTPException(status_code=404, detail="없는 프로파일이다")
        return {
            "profile": metric_profile_payload(
                profile, affected=_metric_affected(session, profile.id), entries=profile.entries
            )
        }


@router.put("/metric-profiles/{profile_id}", summary="Metric 프로파일 수정")
def update_metric_profile(
    profile_id: str, body: MetricProfileWrite, request: Request, actor: RequireConfigure
) -> dict:
    identifier = parse_uuid(profile_id, "프로파일 식별자")
    with session_scope() as session:
        profile = session.get(MetricProfile, identifier)
        if profile is None:
            raise HTTPException(status_code=404, detail="없는 프로파일이다")
        before = metric_profile_payload(
            profile, affected=_metric_affected(session, profile.id), entries=profile.entries
        )
        if body.name is not None:
            profile.name = body.name
        if body.description is not None:
            profile.description = body.description
        if body.is_default is not None:
            profile.is_default = body.is_default
            if profile.is_default:
                _clear_default_metric(session, profile.id)
        if body.entries is not None:
            _replace_entries(session, profile, body.entries)
        try:
            session.flush()
        except IntegrityError as exc:
            raise HTTPException(status_code=409, detail="같은 이름의 프로파일이 있다") from exc
        session.refresh(profile)
        after = metric_profile_payload(
            profile, affected=_metric_affected(session, profile.id), entries=profile.entries
        )
        audit.record(
            session,
            actor=actor,
            action="update",
            entity_type="metric_profile",
            entity_id=str(profile.id),
            before={"name": before["name"], "affectedDeviceCount": before["affectedDeviceCount"]},
            after={"name": after["name"], "affectedDeviceCount": after["affectedDeviceCount"]},
            request=request,
        )
        return {"profile": after}
