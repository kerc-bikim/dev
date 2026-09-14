from __future__ import annotations

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import relationship

from .db import Base


class Network(Base):
    __tablename__ = "networks"

    id = Column(Integer, primary_key=True)
    code = Column(String(8), unique=True, nullable=False)
    description = Column(String(255), nullable=True)
    operator_agency = Column(String(255), nullable=True)
    restricted_status = Column(String(32), nullable=True)

    stations = relationship(
        "Station", back_populates="network", cascade="all, delete-orphan"
    )


class Station(Base):
    __tablename__ = "stations"
    __table_args__ = (
        UniqueConstraint("network_id", "code", name="uq_station_net_code"),
    )

    id = Column(Integer, primary_key=True)
    network_id = Column(ForeignKey("networks.id"), nullable=False)
    code = Column(String(16), nullable=False)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    elevation = Column(Float, nullable=False, default=0.0)
    site_name = Column(String(255), nullable=True)
    site_description = Column(Text, nullable=True)
    site_town = Column(String(128), nullable=True)
    site_region = Column(String(128), nullable=True)
    site_country = Column(String(128), nullable=True)
    vault = Column(String(128), nullable=True)
    geology = Column(String(128), nullable=True)
    description = Column(Text, nullable=True)
    creation_date = Column(String(64), nullable=True)
    termination_date = Column(String(64), nullable=True)

    network = relationship("Network", back_populates="stations")
    channels = relationship(
        "Channel", back_populates="station", cascade="all, delete-orphan"
    )


class Channel(Base):
    __tablename__ = "channels"
    __table_args__ = (
        UniqueConstraint(
            "station_id",
            "location",
            "channel",
            "start_time",
            name="uq_channel_nslc_start",
        ),
    )

    id = Column(Integer, primary_key=True)
    station_id = Column(ForeignKey("stations.id"), nullable=False)
    location = Column(String(8), nullable=False, default="")
    channel = Column(String(8), nullable=False)
    start_time = Column(String(64), nullable=False)
    end_time = Column(String(64), nullable=True)
    sample_rate = Column(Float, nullable=False)
    depth = Column(Float, nullable=False, default=0.0)
    azimuth = Column(Float, nullable=False, default=0.0)
    dip = Column(Float, nullable=False, default=0.0)
    description = Column(Text, nullable=True)
    comment = Column(Text, nullable=True)
    channel_types = Column(String(128), nullable=True)
    clock_drift = Column(Float, nullable=True)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    elevation = Column(Float, nullable=True)
    sensor_id = Column(String(64), nullable=True)
    sensor_serial = Column(String(64), nullable=True)
    sensor_type = Column(String(64), nullable=True)
    sensor_install_date = Column(String(64), nullable=True)
    sensor_remove_date = Column(String(64), nullable=True)
    datalogger_id = Column(String(64), nullable=True)
    datalogger_serial = Column(String(64), nullable=True)
    datalogger_type = Column(String(64), nullable=True)
    datalogger_install_date = Column(String(64), nullable=True)
    datalogger_remove_date = Column(String(64), nullable=True)
    response_xml = Column(Text, nullable=True)
    response_source = Column(String(16), nullable=False, default="none")

    station = relationship("Station", back_populates="channels")


class EquipmentCatalog(Base):
    __tablename__ = "equipment_catalog"
    __table_args__ = (UniqueConstraint("kind", "code", name="uq_catalog_kind_code"),)

    id = Column(Integer, primary_key=True)
    kind = Column(String(16), nullable=False)
    code = Column(String(64), nullable=False)
    manufacturer = Column(String(128), nullable=False)
    model = Column(String(128), nullable=False)
    sample_rate = Column(Float, nullable=True)
    nrl_keys = Column(String(512), nullable=True)
    origin = Column(String(16), nullable=False, default="seed")
    description = Column(Text, nullable=True)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    action = Column(String(32), nullable=False)
    entity_type = Column(String(32), nullable=False)
    entity_id = Column(Integer, nullable=True)
    source = Column(String(16), nullable=False, default="ui")
    actor = Column(String(64), nullable=True)
    nslc = Column(String(64), nullable=True)
    before_json = Column(Text, nullable=True)
    after_json = Column(Text, nullable=True)
    summary = Column(Text, nullable=True)
