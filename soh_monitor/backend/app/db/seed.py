"""초기 데이터 적재.

  * metric_definitions : contracts/metrics/catalog.yaml 을 DB 로 복제한다.
    프로파일·Override 가 외래키로 참조해야 하므로 DB 에도 있어야 한다.
    카탈로그가 원본이므로 여기서는 항상 카탈로그 방향으로 덮어쓴다.
  * 기본 수집·Metric 프로파일 : 관측소를 등록할 때 고를 것이 없으면 안 된다.
  * 초기 관리자 : 비밀번호는 환경변수로 주고, 없으면 1회용을 생성해 로그에 남긴다.
"""
from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.metric_mappings import load_mapping_table
from app.auth.passwords import generate_password, hash_password
from app.db.models import (
    AdapterMetricMapping,
    CollectionProfile,
    MetricDefinitionRow,
    MetricProfile,
    ProfileMetric,
    User,
    UserRole,
)
from app.metrics.catalog import load_catalog
from app.observability.logging import get_logger

logger = get_logger("app.db.seed", role="migrate")

DEFAULT_COLLECTION_PROFILE = "기본 5분 수집"
DEFAULT_METRIC_PROFILE = "기본 감시 항목"


def seed_metric_definitions(session: Session) -> tuple[int, int]:
    """카탈로그를 DB 로 동기화한다. (추가, 갱신) 개수를 돌려준다."""
    catalog = load_catalog()
    existing = {row.metric_key: row for row in session.scalars(select(MetricDefinitionRow))}

    inserted = 0
    updated = 0
    for metric in catalog.metrics.values():
        row = existing.get(metric.key)
        values = dict(
            category=metric.category,
            display_name=metric.display_name,
            unit=metric.unit,
            value_type=metric.value_type.value,
            source=metric.source.value,
            measurement=metric.measurement,
            field=metric.field,
            required=metric.required,
            aggregation=metric.aggregation.value,
            dimensions=list(metric.dimensions),
            capability_key=metric.capability,
            catalog_version=catalog.version,
            description=metric.description or None,
        )
        if row is None:
            session.add(MetricDefinitionRow(metric_key=metric.key, **values))
            inserted += 1
            continue

        changed = any(getattr(row, name) != value for name, value in values.items())
        if changed:
            for name, value in values.items():
                setattr(row, name, value)
            updated += 1

    removed = set(existing) - set(catalog.metrics)
    if removed:
        # 카탈로그에서 사라진 Metric 은 지우지 않는다. 과거 프로파일·장애 이력이 참조한다.
        logger.warning(
            "카탈로그에 없는 Metric 정의가 DB 에 남아 있다",
            extra={"metric_keys": sorted(removed)},
        )

    return inserted, updated


def seed_default_profiles(session: Session) -> None:
    collection = session.scalar(
        select(CollectionProfile).where(CollectionProfile.name == DEFAULT_COLLECTION_PROFILE)
    )
    if collection is None:
        session.add(
            CollectionProfile(
                name=DEFAULT_COLLECTION_PROFILE,
                description="계획서 기본값. 5분 주기, 1회 재시도.",
                poll_interval_minutes=5,
                retry_count=1,
                retry_delay_seconds=10,
                data_check_interval_minutes=10,
                is_default=True,
            )
        )

    metric_profile = session.scalar(
        select(MetricProfile).where(MetricProfile.name == DEFAULT_METRIC_PROFILE)
    )
    if metric_profile is None:
        metric_profile = MetricProfile(
            name=DEFAULT_METRIC_PROFILE,
            description="통신·저장소·시각·센서 등 운영 필수 항목만 켠 기본 프로파일.",
            is_default=True,
        )
        session.add(metric_profile)
        session.flush()

    catalog = load_catalog()
    existing_entries = {
        entry.metric_key
        for entry in session.scalars(
            select(ProfileMetric).where(ProfileMetric.profile_id == metric_profile.id)
        )
    }

    # 계획서 8절의 MVP 기본 규칙. 값 없이 활성화만 하는 항목은 조건이 비어 있다.
    thresholds: dict[str, tuple[dict, dict, int]] = {
        "connectivity.consecutive_failures": (
            {"op": ">=", "value": 2},
            {"op": ">=", "value": 3},
            0,
        ),
        "storage.used_percent": ({"op": ">=", "value": 80}, {"op": ">=", "value": 90}, 0),
        "device.overall_status": ({"status": "WARNING"}, {"status": "CRITICAL"}, 0),
        "storage.recording_status": ({"status": "WARNING"}, {"status": "CRITICAL"}, 120),
        "storage.sd_status": ({"status": "WARNING"}, {"status": "CRITICAL"}, 0),
        "timing.status": ({"status": "WARNING"}, {"status": "CRITICAL"}, 120),
        "timing.phase_lock": ({"status": "WARNING"}, {"status": "CRITICAL"}, 300),
        "sensor.status": ({"status": "WARNING"}, {"status": "CRITICAL"}, 0),
        "device.configuration_status": ({"status": "WARNING"}, {}, 600),
        "archive.continuous_status": ({"status": "WARNING"}, {"status": "CRITICAL"}, 0),
        "acquisition.latest_sample_age_seconds": ({"op": ">=", "value": 180}, {"op": ">=", "value": 600}, 60),
        "acquisition.gap_duration_seconds": ({"op": ">=", "value": 60}, {"op": ">=", "value": 300}, 60),
        "acquisition.channel_active": ({}, {"expect": True}, 0),
    }

    # 전압·온도·Mass Position 은 공통 기준을 두지 않는다. 관측소 전원 구성과 센서 모델이
    # 달라 하나의 임계값을 강요하면 오탐이 된다. 프로파일에서 값을 넣어 쓰도록 비워 둔다.
    monitored_without_threshold = (
        "power.input_voltage_v",
        "power.current_a",
        "device.temperature_c",
        "sensor.mass_position_v",
        "gnss.satellite_count",
        "timing.uncertainty_ns",
        "external_soh.value",
    )

    for metric_key, (warning, critical, hold) in thresholds.items():
        if metric_key in existing_entries or metric_key not in catalog.metrics:
            continue
        session.add(
            ProfileMetric(
                profile_id=metric_profile.id,
                metric_key=metric_key,
                enabled=True,
                alerting_enabled=True,
                warning_condition=warning,
                critical_condition=critical,
                hold_seconds=hold,
                recovery_seconds=max(hold, 60),
                consecutive_violations=1,
            )
        )

    # 예전 Seed 는 경과 시간을 임계 없이 켜 두었다. 파형 정지를 잡으려면 값을 채운다.
    stale = session.scalar(
        select(ProfileMetric).where(
            ProfileMetric.profile_id == metric_profile.id,
            ProfileMetric.metric_key == "acquisition.latest_sample_age_seconds",
        )
    )
    if stale is not None and not stale.warning_condition and not stale.critical_condition:
        stale.alerting_enabled = True
        stale.warning_condition = {"op": ">=", "value": 180}
        stale.critical_condition = {"op": ">=", "value": 600}
        stale.hold_seconds = 60
        stale.recovery_seconds = 60

    for metric_key in monitored_without_threshold:
        if metric_key in existing_entries or metric_key not in catalog.metrics:
            continue
        session.add(
            ProfileMetric(
                profile_id=metric_profile.id,
                metric_key=metric_key,
                enabled=True,
                alerting_enabled=False,
                warning_condition={},
                critical_condition={},
                hold_seconds=0,
                recovery_seconds=60,
            )
        )

    seed_power_profiles(session, catalog)


def seed_power_profiles(session: Session, catalog) -> None:
    """전원 구성별 전압 프로파일. 기본 프로파일에는 전압 임계를 넣지 않는다.

    12V 배터리와 24V 직류를 한 숫자에 묶으면 한쪽은 항상 장애가 된다.
    관측소 `powerProfile` 에 맞춰 이 프로파일을 고른다.
    """
    presets: tuple[tuple[str, str, float, float], ...] = (
        ("12V 배터리 감시", "12V 납축전지. 주의 11.8V, 장애 11.0V.", 11.8, 11.0),
        ("24V 직류 감시", "24V 직류. 주의 22.0V, 장애 20.0V.", 22.0, 20.0),
    )
    for name, description, warn, critical in presets:
        existing = session.scalar(select(MetricProfile).where(MetricProfile.name == name))
        if existing is not None:
            continue
        profile = MetricProfile(name=name, description=description, is_default=False)
        session.add(profile)
        session.flush()
        if "power.input_voltage_v" not in catalog.metrics:
            continue
        session.add(
            ProfileMetric(
                profile_id=profile.id,
                metric_key="power.input_voltage_v",
                enabled=True,
                alerting_enabled=True,
                warning_condition={"op": "<=", "value": warn},
                critical_condition={"op": "<=", "value": critical},
                hold_seconds=300,
                recovery_seconds=600,
                consecutive_violations=2,
            )
        )


def seed_admin_user(session: Session) -> str | None:
    """관리자가 없으면 하나 만든다. 생성한 1회용 비밀번호를 돌려준다."""
    if session.scalar(select(User).limit(1)) is not None:
        return None

    username = os.environ.get("SOH_BOOTSTRAP_ADMIN_USER", "admin")
    password = os.environ.get("SOH_BOOTSTRAP_ADMIN_PASSWORD") or ""
    generated = None
    if not password:
        password = generate_password()
        generated = password

    session.add(
        User(
            username=username,
            display_name="초기 관리자",
            password_hash=hash_password(password),
            role=UserRole.ADMIN,
            enabled=True,
            must_change_password=True,
        )
    )
    return generated


MAPPING_FILES = (
    Path(__file__).resolve().parents[1] / "adapters" / "centaur_ctr" / "mappings.yaml",
)


def seed_adapter_mappings(session: Session) -> tuple[int, int]:
    """Adapter YAML 매핑을 DB 로 복사한다. 수집은 YAML 을 직접 읽는다."""
    inserted = 0
    updated = 0
    for path in MAPPING_FILES:
        if not path.exists():
            continue
        table = load_mapping_table(path)
        existing = {
            (
                row.adapter_key,
                row.adapter_version,
                row.firmware_range,
                row.source_path,
                row.canonical_metric_key,
                row.dimension_value,
            ): row
            for row in session.scalars(
                select(AdapterMetricMapping).where(AdapterMetricMapping.adapter_key == table.adapter_key)
            )
        }
        seen: set[tuple] = set()
        for rule in table.rules:
            key = (
                rule.adapter_key,
                rule.adapter_version,
                rule.firmware_range,
                rule.source_path,
                rule.canonical_metric_key,
                rule.dimension_value,
            )
            seen.add(key)
            values = dict(
                source_unit=rule.source_unit,
                target_unit=rule.target_unit,
                scale=rule.scale,
                offset=rule.offset,
                notes=rule.notes,
            )
            row = existing.get(key)
            if row is None:
                session.add(
                    AdapterMetricMapping(
                        adapter_key=rule.adapter_key,
                        adapter_version=rule.adapter_version,
                        firmware_range=rule.firmware_range,
                        source_path=rule.source_path,
                        canonical_metric_key=rule.canonical_metric_key,
                        dimension_value=rule.dimension_value,
                        **values,
                    )
                )
                inserted += 1
                continue
            if any(getattr(row, name) != value for name, value in values.items()):
                for name, value in values.items():
                    setattr(row, name, value)
                updated += 1
        for key, row in existing.items():
            if key not in seen:
                session.delete(row)
    return inserted, updated


def seed_all(session: Session) -> dict[str, object]:
    inserted, updated = seed_metric_definitions(session)
    mapping_inserted, mapping_updated = seed_adapter_mappings(session)
    seed_default_profiles(session)
    generated_password = seed_admin_user(session)
    session.commit()
    return {
        "metric_definitions_inserted": inserted,
        "metric_definitions_updated": updated,
        "adapter_mappings_inserted": mapping_inserted,
        "adapter_mappings_updated": mapping_updated,
        "generated_admin_password": generated_password,
    }
