"""설정·이력 스키마.

원칙
  * 제조사별 전용 테이블을 만들지 않는다. 제조사 차이는 adapter_key 와
    adapter_metric_mappings 로 흡수한다. 이것이 Gen5·타 제조사 확장의 전제다.
  * 기록계 비밀번호 컬럼은 없다. `device_endpoints.credential_reference` 로 참조만 둔다.
  * 관측소·장비는 물리 삭제하지 않는다. 상태를 RETIRED 로 바꾼다. 지난 시계열의
    맥락을 잃지 않기 위한 것이다.
  * 상태 열거형은 native_enum=False 로 둔다. PostgreSQL enum 타입은 값 추가마다
    마이그레이션이 무거워진다.
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, Timestamped, UuidPrimaryKey
from app.domain.enums import (
    CollectionMode,
    PollErrorCode,
    Severity,
    SupportState,
)


def _enum(py_enum: type[enum.Enum], name: str) -> Enum:
    return Enum(py_enum, name=name, native_enum=False, validate_strings=True, length=32)


class LifecycleStatus(str, enum.Enum):
    PLANNED = "PLANNED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    RETIRED = "RETIRED"


class UserRole(str, enum.Enum):
    ADMIN = "ADMIN"
    OPERATOR = "OPERATOR"
    VIEWER = "VIEWER"


class IncidentStatus(str, enum.Enum):
    PENDING = "PENDING"
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESOLVED = "RESOLVED"


class EdgeStatus(str, enum.Enum):
    ENROLLING = "ENROLLING"
    ONLINE = "ONLINE"
    DEGRADED = "DEGRADED"
    OFFLINE = "OFFLINE"
    DISABLED = "DISABLED"


class BatchStatus(str, enum.Enum):
    RECEIVED = "RECEIVED"
    PROCESSED = "PROCESSED"
    DUPLICATE = "DUPLICATE"
    REJECTED = "REJECTED"


# --------------------------------------------------------------------- 제조사·Adapter


class Manufacturer(UuidPrimaryKey, Timestamped, Base):
    __tablename__ = "manufacturers"

    manufacturer_code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    website: Mapped[str | None] = mapped_column(String(256))

    models: Mapped[list["DeviceModel"]] = relationship(back_populates="manufacturer")


class DeviceModel(UuidPrimaryKey, Timestamped, Base):
    __tablename__ = "device_models"
    __table_args__ = (UniqueConstraint("manufacturer_id", "model_code"),)

    manufacturer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("manufacturers.id", ondelete="RESTRICT"), nullable=False
    )
    model_code: Mapped[str] = mapped_column(String(64), nullable=False)
    product_family: Mapped[str] = mapped_column(String(64), nullable=False)
    generation: Mapped[str | None] = mapped_column(String(32))
    default_adapter_key: Mapped[str] = mapped_column(String(128), nullable=False)
    channel_count: Mapped[int | None] = mapped_column(Integer)
    sensor_port_count: Mapped[int | None] = mapped_column(Integer)
    external_soh_channels: Mapped[int | None] = mapped_column(Integer)

    manufacturer: Mapped[Manufacturer] = relationship(back_populates="models")


class AdapterDefinition(Timestamped, Base):
    __tablename__ = "adapter_definitions"

    adapter_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    manufacturer_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("manufacturers.id", ondelete="SET NULL")
    )
    current_version: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="supported")
    configuration_schema: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    ui_schema: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class AdapterVersion(UuidPrimaryKey, Timestamped, Base):
    __tablename__ = "adapter_versions"
    __table_args__ = (UniqueConstraint("adapter_key", "version"),)

    adapter_key: Mapped[str] = mapped_column(
        ForeignKey("adapter_definitions.adapter_key", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    minimum_collector_version: Mapped[str | None] = mapped_column(String(32))
    minimum_edge_version: Mapped[str | None] = mapped_column(String(32))
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="supported")


class AdapterMetricMapping(UuidPrimaryKey, Timestamped, Base):
    """제조사 원본 경로 → 표준 Metric 변환 규칙.

    펌웨어별 차이를 코드 분기 대신 이 표로 흡수한다. 새 펌웨어가 필드명을 바꾸면
    행 하나를 추가한다.
    """

    __tablename__ = "adapter_metric_mappings"
    __table_args__ = (
        UniqueConstraint(
            "adapter_key", "adapter_version", "firmware_range", "canonical_metric_key", "dimension_value"
        ),
        Index("ix_adapter_metric_mappings_lookup", "adapter_key", "adapter_version"),
    )

    adapter_key: Mapped[str] = mapped_column(String(128), nullable=False)
    adapter_version: Mapped[str] = mapped_column(String(32), nullable=False)
    firmware_range: Mapped[str] = mapped_column(String(64), nullable=False, default="*")
    source_path: Mapped[str] = mapped_column(String(256), nullable=False)
    canonical_metric_key: Mapped[str] = mapped_column(String(128), nullable=False)
    dimension_value: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    source_unit: Mapped[str | None] = mapped_column(String(32))
    target_unit: Mapped[str | None] = mapped_column(String(32))
    scale: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    offset: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    transform_expression: Mapped[str | None] = mapped_column(String(256))
    notes: Mapped[str | None] = mapped_column(Text)


# --------------------------------------------------------------------- 관측소·장비


class Region(UuidPrimaryKey, Timestamped, Base):
    __tablename__ = "regions"

    region_code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)


class Station(UuidPrimaryKey, Timestamped, Base):
    __tablename__ = "stations"
    __table_args__ = (
        UniqueConstraint("network_code", "station_code"),
        Index("ix_stations_status", "status"),
    )

    station_code: Mapped[str] = mapped_column(String(16), nullable=False)
    network_code: Mapped[str] = mapped_column(String(8), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    region_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("regions.id", ondelete="SET NULL")
    )
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    elevation_m: Mapped[float | None] = mapped_column(Float)
    address: Mapped[str | None] = mapped_column(String(256))
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Asia/Seoul")
    operator_name: Mapped[str | None] = mapped_column(String(64))
    operator_contact: Mapped[str | None] = mapped_column(String(128))
    power_profile: Mapped[str | None] = mapped_column(
        String(32), doc="12V 배터리 / 24V / 태양광 등. 전압 임계값 프로파일 선택 근거."
    )
    status: Mapped[LifecycleStatus] = mapped_column(
        _enum(LifecycleStatus, "lifecycle_status"), nullable=False, default=LifecycleStatus.PLANNED
    )
    installed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)

    devices: Mapped[list["Device"]] = relationship(back_populates="station")


class Device(UuidPrimaryKey, Timestamped, Base):
    __tablename__ = "devices"
    __table_args__ = (
        CheckConstraint(
            "collection_mode <> 'EDGE' OR edge_id IS NOT NULL",
            name="edge_mode_requires_edge",
        ),
        Index("ix_devices_next_poll_at", "next_poll_at"),
        Index("ix_devices_collection_mode", "collection_mode"),
    )

    station_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("stations.id", ondelete="CASCADE"), nullable=False
    )
    manufacturer_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("manufacturers.id", ondelete="SET NULL")
    )
    device_model_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("device_models.id", ondelete="SET NULL")
    )
    label: Mapped[str] = mapped_column(String(64), nullable=False, default="기록계")
    serial_number: Mapped[str | None] = mapped_column(String(64))
    instrument_id: Mapped[str | None] = mapped_column(String(64))
    firmware_version: Mapped[str | None] = mapped_column(String(64))
    adapter_key: Mapped[str] = mapped_column(String(128), nullable=False)
    adapter_version: Mapped[str | None] = mapped_column(String(32))
    collection_mode: Mapped[CollectionMode] = mapped_column(
        _enum(CollectionMode, "collection_mode"), nullable=False, default=CollectionMode.DIRECT
    )
    edge_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("edge_collectors.id", ondelete="RESTRICT")
    )
    collection_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("collection_profiles.id", ondelete="SET NULL")
    )
    metric_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("metric_profiles.id", ondelete="SET NULL")
    )
    data_source_uri: Mapped[str | None] = mapped_column(
        String(256), doc="데이터 연속성 검사용 SeedLink/FDSN 주소. 없으면 해당 검사는 UNSUPPORTED."
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    status: Mapped[LifecycleStatus] = mapped_column(
        _enum(LifecycleStatus, "lifecycle_status"), nullable=False, default=LifecycleStatus.PLANNED
    )
    next_poll_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)

    station: Mapped[Station] = relationship(back_populates="devices")
    endpoint: Mapped["DeviceEndpoint | None"] = relationship(
        back_populates="device", uselist=False, cascade="all, delete-orphan"
    )
    sensors: Mapped[list["Sensor"]] = relationship(
        back_populates="device", cascade="all, delete-orphan"
    )
    external_channels: Mapped[list["ExternalSohChannel"]] = relationship(
        back_populates="device", cascade="all, delete-orphan"
    )
    manufacturer: Mapped["Manufacturer | None"] = relationship(lazy="joined")
    device_model: Mapped["DeviceModel | None"] = relationship(lazy="joined")
    collection_profile: Mapped["CollectionProfile | None"] = relationship(lazy="joined")
    metric_profile: Mapped["MetricProfile | None"] = relationship(lazy="joined")


class DeviceEndpoint(UuidPrimaryKey, Timestamped, Base):
    """접속 정보. 비밀번호 자체는 저장하지 않는다."""

    __tablename__ = "device_endpoints"
    __table_args__ = (UniqueConstraint("device_id"),)

    device_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE"), nullable=False
    )
    scheme: Mapped[str] = mapped_column(String(8), nullable=False, default="http")
    hostname: Mapped[str] = mapped_column(String(256), nullable=False)
    port: Mapped[int | None] = mapped_column(Integer)
    base_path: Mapped[str] = mapped_column(String(128), nullable=False, default="/")
    tls_verify: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    credential_reference: Mapped[str | None] = mapped_column(
        String(256), doc="Secret 저장소의 참조 키. 평문 비밀번호를 넣지 않는다."
    )
    connect_timeout_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=5000)
    request_timeout_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=15000)
    connection_options: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    device: Mapped[Device] = relationship(back_populates="endpoint")


class Sensor(UuidPrimaryKey, Timestamped, Base):
    __tablename__ = "sensors"
    __table_args__ = (UniqueConstraint("device_id", "port"),)

    device_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE"), nullable=False
    )
    port: Mapped[str] = mapped_column(String(8), nullable=False)
    manufacturer: Mapped[str | None] = mapped_column(String(64))
    model: Mapped[str | None] = mapped_column(String(64))
    serial_number: Mapped[str | None] = mapped_column(String(64))
    axis_count: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    device: Mapped[Device] = relationship(back_populates="sensors")
    axes: Mapped[list["SensorAxis"]] = relationship(
        back_populates="sensor", cascade="all, delete-orphan"
    )


class SensorAxis(UuidPrimaryKey, Timestamped, Base):
    __tablename__ = "sensor_axes"
    __table_args__ = (UniqueConstraint("sensor_id", "axis_code"),)

    sensor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sensors.id", ondelete="CASCADE"), nullable=False
    )
    axis_code: Mapped[str] = mapped_column(String(8), nullable=False)
    soh_channel: Mapped[str | None] = mapped_column(String(32))
    warning_threshold: Mapped[float | None] = mapped_column(Float)
    critical_threshold: Mapped[float | None] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(16), nullable=False, default="V")

    sensor: Mapped[Sensor] = relationship(back_populates="axes")


class ExternalSohChannel(UuidPrimaryKey, Timestamped, Base):
    __tablename__ = "external_soh_channels"
    __table_args__ = (UniqueConstraint("device_id", "channel_number"),)

    device_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE"), nullable=False
    )
    channel_number: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    measurement_type: Mapped[str] = mapped_column(String(32), nullable=False, default="voltage")
    raw_unit: Mapped[str] = mapped_column(String(16), nullable=False, default="uV")
    output_unit: Mapped[str] = mapped_column(String(16), nullable=False, default="V")
    scale: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    offset: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    warning_low: Mapped[float | None] = mapped_column(Float)
    warning_high: Mapped[float | None] = mapped_column(Float)
    critical_low: Mapped[float | None] = mapped_column(Float)
    critical_high: Mapped[float | None] = mapped_column(Float)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    device: Mapped["Device"] = relationship(back_populates="external_channels")


class DeviceCapability(UuidPrimaryKey, Timestamped, Base):
    __tablename__ = "device_capabilities"
    __table_args__ = (UniqueConstraint("device_id", "capability_key", "dimension_value"),)

    device_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE"), nullable=False
    )
    capability_key: Mapped[str] = mapped_column(String(128), nullable=False)
    dimension_value: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    support_state: Mapped[SupportState] = mapped_column(
        _enum(SupportState, "support_state"), nullable=False, default=SupportState.UNKNOWN
    )
    detected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="probe")


# --------------------------------------------------------------------- 프로파일


class CollectionProfile(UuidPrimaryKey, Timestamped, Base):
    __tablename__ = "collection_profiles"

    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    poll_interval_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    retry_delay_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    data_check_interval_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    connect_timeout_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=5000)
    request_timeout_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=15000)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class MetricProfile(UuidPrimaryKey, Timestamped, Base):
    __tablename__ = "metric_profiles"

    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    entries: Mapped[list["ProfileMetric"]] = relationship(
        back_populates="profile", cascade="all, delete-orphan"
    )


class MetricDefinitionRow(Timestamped, Base):
    """카탈로그 Seed. 원본은 contracts/metrics/catalog.yaml 이고 여기로 복제된다.

    DB 에 두는 이유는 프로파일·Override 가 외래키로 참조해야 하기 때문이다.
    """

    __tablename__ = "metric_definitions"

    metric_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    unit: Mapped[str | None] = mapped_column(String(16))
    value_type: Mapped[str] = mapped_column(String(16), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    measurement: Mapped[str] = mapped_column(String(64), nullable=False)
    field: Mapped[str] = mapped_column(String(64), nullable=False)
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    aggregation: Mapped[str] = mapped_column(String(16), nullable=False, default="last")
    dimensions: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    capability_key: Mapped[str | None] = mapped_column(String(128))
    catalog_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    description: Mapped[str | None] = mapped_column(Text)


class ProfileMetric(UuidPrimaryKey, Timestamped, Base):
    __tablename__ = "profile_metrics"
    __table_args__ = (UniqueConstraint("profile_id", "metric_key"),)

    profile_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("metric_profiles.id", ondelete="CASCADE"), nullable=False
    )
    metric_key: Mapped[str] = mapped_column(
        ForeignKey("metric_definitions.metric_key", ondelete="CASCADE"), nullable=False
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    alerting_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    warning_condition: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    critical_condition: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    hold_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    recovery_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    consecutive_violations: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    profile: Mapped[MetricProfile] = relationship(back_populates="entries")


class DeviceMetricOverride(UuidPrimaryKey, Timestamped, Base):
    __tablename__ = "device_metric_overrides"
    __table_args__ = (UniqueConstraint("device_id", "metric_key", "dimension_value"),)

    device_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE"), nullable=False
    )
    metric_key: Mapped[str] = mapped_column(
        ForeignKey("metric_definitions.metric_key", ondelete="CASCADE"), nullable=False
    )
    dimension_value: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    enabled: Mapped[bool | None] = mapped_column(Boolean)
    alerting_enabled: Mapped[bool | None] = mapped_column(Boolean)
    warning_condition: Mapped[dict | None] = mapped_column(JSON)
    critical_condition: Mapped[dict | None] = mapped_column(JSON)
    hold_seconds: Mapped[int | None] = mapped_column(Integer)
    recovery_seconds: Mapped[int | None] = mapped_column(Integer)
    reason: Mapped[str | None] = mapped_column(Text)


# --------------------------------------------------------------------- Edge


class EdgeCollector(UuidPrimaryKey, Timestamped, Base):
    __tablename__ = "edge_collectors"

    edge_code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    region_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("regions.id", ondelete="SET NULL")
    )
    status: Mapped[EdgeStatus] = mapped_column(
        _enum(EdgeStatus, "edge_status"), nullable=False, default=EdgeStatus.ENROLLING
    )
    software_version: Mapped[str | None] = mapped_column(String(32))
    installed_adapters: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    certificate_serial: Mapped[str | None] = mapped_column(String(128))
    certificate_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    enrollment_token_hash: Mapped[str | None] = mapped_column(String(128))
    enrollment_token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_upload_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_config_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_config_applied_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_config_applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    spool_used_bytes: Mapped[int | None] = mapped_column(BigInteger)
    spool_limit_bytes: Mapped[int | None] = mapped_column(BigInteger)
    ip_address: Mapped[str | None] = mapped_column(String(64))
    registered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)


class EdgeAssignment(UuidPrimaryKey, Timestamped, Base):
    """장비를 어느 Edge 가 수집하는지.

    활성 할당은 장비당 하나만 존재해야 한다. 두 Edge 가 같은 장비를 동시에 수집하면
    데이터가 중복되고 어느 쪽이 최신인지 알 수 없게 된다.
    """

    __tablename__ = "edge_assignments"
    __table_args__ = (
        # 부분 유일 인덱스. 활성 할당만 유일하게 묶어, 과거 할당 이력은 남기면서
        # 동시에 두 Edge 가 같은 장비를 수집하는 것을 DB 수준에서 막는다.
        Index(
            "uq_edge_assignments_active_device",
            "device_id",
            unique=True,
            postgresql_where=text("enabled"),
            sqlite_where=text("enabled = 1"),
        ),
        UniqueConstraint("edge_id", "device_id", "assignment_epoch"),
    )

    edge_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("edge_collectors.id", ondelete="CASCADE"), nullable=False
    )
    device_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE"), nullable=False
    )
    assignment_epoch: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="primary")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EdgeIngestBatch(UuidPrimaryKey, Timestamped, Base):
    __tablename__ = "edge_ingest_batches"
    __table_args__ = (
        UniqueConstraint("edge_id", "batch_id"),
        Index("ix_edge_ingest_batches_received_at", "received_at"),
    )

    edge_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("edge_collectors.id", ondelete="CASCADE"), nullable=False
    )
    batch_id: Mapped[str] = mapped_column(String(64), nullable=False)
    first_sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    last_sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    poll_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[BatchStatus] = mapped_column(
        _enum(BatchStatus, "batch_status"), nullable=False, default=BatchStatus.RECEIVED
    )
    error_message: Mapped[str | None] = mapped_column(Text)


class EdgeRuntimeState(Timestamped, Base):
    __tablename__ = "edge_runtime_states"

    edge_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("edge_collectors.id", ondelete="CASCADE"), primary_key=True
    )
    connectivity_status: Mapped[Severity] = mapped_column(
        _enum(Severity, "severity"), nullable=False, default=Severity.UNKNOWN
    )
    config_status: Mapped[Severity] = mapped_column(
        _enum(Severity, "severity"), nullable=False, default=Severity.UNKNOWN
    )
    collector_status: Mapped[Severity] = mapped_column(
        _enum(Severity, "severity"), nullable=False, default=Severity.UNKNOWN
    )
    spool_status: Mapped[Severity] = mapped_column(
        _enum(Severity, "severity"), nullable=False, default=Severity.UNKNOWN
    )
    certificate_status: Mapped[Severity] = mapped_column(
        _enum(Severity, "severity"), nullable=False, default=Severity.UNKNOWN
    )
    clock_status: Mapped[Severity] = mapped_column(
        _enum(Severity, "severity"), nullable=False, default=Severity.UNKNOWN
    )
    pending_batches: Mapped[int | None] = mapped_column(Integer)
    oldest_pending_age_seconds: Mapped[float | None] = mapped_column(Float)
    clock_offset_ms: Mapped[float | None] = mapped_column(Float)
    detail: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


# --------------------------------------------------------------------- 수집·상태·장애


class PollRun(UuidPrimaryKey, Base):
    """수집 시도 이력. 실패도 반드시 남긴다."""

    __tablename__ = "poll_runs"
    __table_args__ = (
        Index("ix_poll_runs_device_observed", "device_id", "observed_at"),
        Index("ix_poll_runs_observed_at", "observed_at"),
    )

    device_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE"), nullable=False
    )
    edge_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("edge_collectors.id", ondelete="SET NULL")
    )
    poll_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    collection_mode: Mapped[CollectionMode] = mapped_column(
        _enum(CollectionMode, "collection_mode"), nullable=False
    )
    adapter_key: Mapped[str] = mapped_column(String(128), nullable=False)
    adapter_version: Mapped[str | None] = mapped_column(String(32))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    latency_ms: Mapped[float | None] = mapped_column(Float)
    http_status: Mapped[int | None] = mapped_column(Integer)
    payload_bytes: Mapped[int | None] = mapped_column(Integer)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_code: Mapped[PollErrorCode | None] = mapped_column(_enum(PollErrorCode, "poll_error_code"))
    error_message: Mapped[str | None] = mapped_column(Text)
    unmapped_values: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


class DeviceRuntimeState(Timestamped, Base):
    __tablename__ = "device_runtime_states"

    device_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE"), primary_key=True
    )
    last_poll_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_observed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        doc="현재 상태의 근거가 된 관측 시각. 늦게 도착한 과거 데이터로 상태를 되돌리지 않기 위한 기준.",
    )
    last_error_code: Mapped[PollErrorCode | None] = mapped_column(
        _enum(PollErrorCode, "poll_error_code")
    )
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    overall_severity: Mapped[Severity] = mapped_column(
        _enum(Severity, "severity"), nullable=False, default=Severity.UNKNOWN
    )
    poll_lease_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), doc="수집 중복 실행 방지용 Lease 만료 시각."
    )
    poll_lease_owner: Mapped[str | None] = mapped_column(String(64))


class HealthState(UuidPrimaryKey, Timestamped, Base):
    """현재 상태. 화면이 곧바로 읽는 표.

    Metric 단위 행과 분류 단위 집계 행이 함께 들어간다. 집계 행은 `metric_key` 가 빈
    문자열이다. 화면은 분류 행으로 개요를 그리고, 상세에서 Metric 행을 펼친다.
    """

    __tablename__ = "health_states"
    __table_args__ = (
        UniqueConstraint("device_id", "category", "metric_key", "dimension_value"),
        Index("ix_health_states_device_category", "device_id", "category"),
    )

    device_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE"), nullable=False
    )
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    metric_key: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    dimension_value: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    severity: Mapped[Severity] = mapped_column(
        _enum(Severity, "severity"), nullable=False, default=Severity.UNKNOWN
    )
    support_state: Mapped[SupportState] = mapped_column(
        _enum(SupportState, "support_state"), nullable=False, default=SupportState.UNKNOWN
    )
    is_stale: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    evaluated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    value_text: Mapped[str | None] = mapped_column(String(128))
    detail: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


class Incident(UuidPrimaryKey, Timestamped, Base):
    __tablename__ = "incidents"
    __table_args__ = (
        Index("ix_incidents_status", "status"),
        Index("ix_incidents_device_status", "device_id", "status"),
        # 같은 대상에 열려 있는 장애는 하나만 존재해야 한다. 같은 원인으로 장애가 계속
        # 새로 생기면 알림이 폭주하고 이력이 쓸모없어진다. 코드가 아니라 DB 로 막는다.
        Index(
            "uq_incidents_open_target",
            "device_id",
            "category",
            "metric_key",
            "dimension_value",
            unique=True,
            postgresql_where=text("status <> 'RESOLVED'"),
            sqlite_where=text("status <> 'RESOLVED'"),
        ),
    )

    device_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE")
    )
    station_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("stations.id", ondelete="CASCADE")
    )
    edge_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("edge_collectors.id", ondelete="CASCADE")
    )
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    metric_key: Mapped[str | None] = mapped_column(String(128))
    dimension_value: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    severity: Mapped[Severity] = mapped_column(_enum(Severity, "severity"), nullable=False)
    status: Mapped[IncidentStatus] = mapped_column(
        _enum(IncidentStatus, "incident_status"), nullable=False, default=IncidentStatus.PENDING
    )
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    first_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acknowledged_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    worst_value: Mapped[float | None] = mapped_column(Float)
    threshold_value: Mapped[float | None] = mapped_column(Float)
    suppressed_by_edge: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        doc="Edge 장애로 인해 하위 장애로 승격하지 않은 경우. 알림 폭주 방지 기록.",
    )
    maintenance_related: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    detail: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    events: Mapped[list["IncidentEvent"]] = relationship(
        back_populates="incident", cascade="all, delete-orphan"
    )


class IncidentEvent(UuidPrimaryKey, Base):
    __tablename__ = "incident_events"

    incident_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    from_status: Mapped[IncidentStatus | None] = mapped_column(
        _enum(IncidentStatus, "incident_status")
    )
    to_status: Mapped[IncidentStatus | None] = mapped_column(
        _enum(IncidentStatus, "incident_status")
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    message: Mapped[str | None] = mapped_column(Text)

    incident: Mapped[Incident] = relationship(back_populates="events")


class MaintenanceWindow(UuidPrimaryKey, Timestamped, Base):
    __tablename__ = "maintenance_windows"
    __table_args__ = (Index("ix_maintenance_windows_period", "starts_at", "ends_at"),)

    scope: Mapped[str] = mapped_column(
        String(16), nullable=False, default="device", doc="device | station | edge | region | global"
    )
    scope_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    suppress_alerts: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


# --------------------------------------------------------------------- 사용자·감사


class User(UuidPrimaryKey, Timestamped, Base):
    __tablename__ = "users"

    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(64), nullable=False)
    email: Mapped[str | None] = mapped_column(String(128))
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        _enum(UserRole, "user_role"), nullable=False, default=UserRole.VIEWER
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    must_change_password: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class AuditLog(UuidPrimaryKey, Base):
    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_logs_occurred_at", "occurred_at"),)

    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    actor_name: Mapped[str | None] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String(64))
    before_value: Mapped[dict | None] = mapped_column(JSON)
    after_value: Mapped[dict | None] = mapped_column(JSON)
    request_id: Mapped[str | None] = mapped_column(String(64))
    source_ip: Mapped[str | None] = mapped_column(String(64))
