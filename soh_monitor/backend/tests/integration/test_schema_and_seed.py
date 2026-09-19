"""마이그레이션과 Seed 통합 검증.

운영 DB 는 PostgreSQL 이지만, 이 시험은 SQLite 로 스키마 생성·제약·Seed 동작을
확인한다. PostgreSQL 전용 동작(부분 인덱스 표현식 등)은 Compose 환경에서 다시 확인한다.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.db.models import (
    CollectionMode,
    Device,
    DeviceEndpoint,
    EdgeAssignment,
    EdgeCollector,
    MetricDefinitionRow,
    MetricProfile,
    ProfileMetric,
    Station,
    User,
)
from app.db.seed import seed_all
from app.metrics.catalog import load_catalog


@pytest.fixture()
def session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path/'test.db'}", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    with factory() as db_session:
        yield db_session
    engine.dispose()


def _station(session: Session) -> Station:
    station = Station(station_code="A01", network_code="KS", name="시험 관측소")
    session.add(station)
    session.flush()
    return station


def _edge(session: Session, code: str = "edge-a") -> EdgeCollector:
    edge = EdgeCollector(edge_code=code, name="지역 A Edge")
    session.add(edge)
    session.flush()
    return edge


class Test스키마제약:
    def test_EDGE_수집_장비는_Edge_지정이_필수다(self, session):
        station = _station(session)
        session.add(
            Device(
                station_id=station.id,
                adapter_key="nanometrics.centaur.ctr",
                collection_mode=CollectionMode.EDGE,
                edge_id=None,
            )
        )
        with pytest.raises(IntegrityError):
            session.flush()

    def test_같은_장비를_두_Edge에_활성_할당할_수_없다(self, session):
        station = _station(session)
        device = Device(
            station_id=station.id,
            adapter_key="nanometrics.centaur.ctr",
            collection_mode=CollectionMode.DIRECT,
        )
        session.add(device)
        edge_a = _edge(session, "edge-a")
        edge_b = _edge(session, "edge-b")
        session.flush()

        session.add(
            EdgeAssignment(edge_id=edge_a.id, device_id=device.id, assignment_epoch=1, enabled=True)
        )
        session.flush()

        session.add(
            EdgeAssignment(edge_id=edge_b.id, device_id=device.id, assignment_epoch=1, enabled=True)
        )
        with pytest.raises(IntegrityError):
            session.flush()

    def test_비활성_할당_이력은_남길_수_있다(self, session):
        """과거 어느 Edge 가 수집했는지는 장애 분석에 필요하다."""
        station = _station(session)
        device = Device(
            station_id=station.id,
            adapter_key="nanometrics.centaur.ctr",
            collection_mode=CollectionMode.DIRECT,
        )
        session.add(device)
        edge_a = _edge(session, "edge-a")
        edge_b = _edge(session, "edge-b")
        session.flush()

        session.add(
            EdgeAssignment(edge_id=edge_a.id, device_id=device.id, assignment_epoch=1, enabled=False)
        )
        session.add(
            EdgeAssignment(edge_id=edge_b.id, device_id=device.id, assignment_epoch=2, enabled=True)
        )
        session.flush()
        assert session.scalar(select(func.count()).select_from(EdgeAssignment)) == 2

    def test_접속정보에_비밀번호_컬럼이_없다(self):
        """평문 비밀번호를 담을 자리를 아예 만들지 않는다."""
        columns = set(DeviceEndpoint.__table__.columns.keys())
        assert not {"password", "secret", "credential_value"} & columns
        assert "credential_reference" in columns

    def test_관측소는_네트워크와_코드_조합이_유일하다(self, session):
        session.add(Station(station_code="A01", network_code="KS", name="첫 번째"))
        session.flush()
        session.add(Station(station_code="A01", network_code="KS", name="중복"))
        with pytest.raises(IntegrityError):
            session.flush()

    def test_같은_코드라도_네트워크가_다르면_등록된다(self, session):
        session.add(Station(station_code="A01", network_code="KS", name="첫 번째"))
        session.add(Station(station_code="A01", network_code="KG", name="다른 망"))
        session.flush()
        assert session.scalar(select(func.count()).select_from(Station)) == 2


class TestSeed:
    def test_카탈로그가_DB로_복제된다(self, session):
        result = seed_all(session)
        catalog = load_catalog()
        rows = {row.metric_key for row in session.scalars(select(MetricDefinitionRow))}
        assert rows == set(catalog.metrics)
        assert result["metric_definitions_inserted"] == len(catalog.metrics)

    def test_두_번_실행해도_결과가_같다(self, session):
        seed_all(session)
        before = session.scalar(select(func.count()).select_from(MetricDefinitionRow))
        second = seed_all(session)
        after = session.scalar(select(func.count()).select_from(MetricDefinitionRow))
        assert before == after
        assert second["metric_definitions_inserted"] == 0
        assert second["generated_admin_password"] is None

    def test_카탈로그_변경이_DB에_반영된다(self, session):
        seed_all(session)
        row = session.get(MetricDefinitionRow, "power.input_voltage_v")
        row.display_name = "예전 이름"
        session.commit()

        result = seed_all(session)
        refreshed = session.get(MetricDefinitionRow, "power.input_voltage_v")
        assert refreshed.display_name == "입력 전압"
        assert result["metric_definitions_updated"] >= 1

    def test_기본_프로파일이_만들어진다(self, session):
        seed_all(session)
        profile = session.scalar(select(MetricProfile).where(MetricProfile.is_default.is_(True)))
        assert profile is not None

        entries = {
            entry.metric_key: entry
            for entry in session.scalars(
                select(ProfileMetric).where(ProfileMetric.profile_id == profile.id)
            )
        }
        assert entries["storage.used_percent"].warning_condition == {"op": ">=", "value": 80}
        assert entries["storage.used_percent"].critical_condition == {"op": ">=", "value": 90}
        assert entries["connectivity.consecutive_failures"].critical_condition["value"] == 3
        assert entries["acquisition.latest_sample_age_seconds"].critical_condition == {
            "op": ">=",
            "value": 600,
        }
        assert entries["acquisition.channel_active"].critical_condition == {"expect": True}

    def test_예전_빈_경과규칙에_임계값을_채운다(self, session):
        seed_all(session)
        profile = session.scalar(select(MetricProfile).where(MetricProfile.is_default.is_(True)))
        entry = session.scalar(
            select(ProfileMetric).where(
                ProfileMetric.profile_id == profile.id,
                ProfileMetric.metric_key == "acquisition.latest_sample_age_seconds",
            )
        )
        entry.warning_condition = {}
        entry.critical_condition = {}
        session.flush()
        seed_all(session)
        session.refresh(entry)
        assert entry.warning_condition == {"op": ">=", "value": 180}
        assert entry.critical_condition == {"op": ">=", "value": 600}

    def test_전압과_Mass_Position은_기본_임계값을_강요하지_않는다(self, session):
        """전원 구성과 센서 모델이 다르면 하나의 기준이 곧 오탐이 된다."""
        seed_all(session)
        profile = session.scalar(select(MetricProfile).where(MetricProfile.is_default.is_(True)))
        entries = {
            entry.metric_key: entry
            for entry in session.scalars(
                select(ProfileMetric).where(ProfileMetric.profile_id == profile.id)
            )
        }
        for metric_key in ("power.input_voltage_v", "sensor.mass_position_v", "device.temperature_c"):
            assert entries[metric_key].enabled is True
            assert entries[metric_key].alerting_enabled is False
            assert entries[metric_key].warning_condition == {}

    def test_초기_관리자는_비밀번호_변경이_강제된다(self, session):
        seed_all(session)
        user = session.scalar(select(User))
        assert user.role.value == "ADMIN"
        assert user.must_change_password is True
        assert user.password_hash.startswith("scrypt$")

    def test_모든_프로파일_항목은_카탈로그의_Metric을_참조한다(self, session):
        seed_all(session)
        catalog = load_catalog()
        for entry in session.scalars(select(ProfileMetric)):
            assert entry.metric_key in catalog.metrics


def test_수집이력은_실패도_남긴다(session):
    """실패를 버리면 '데이터 없음'과 '장비 죽음'을 구분할 수 없다."""
    from app.db.models import PollErrorCode, PollRun

    station = _station(session)
    device = Device(
        station_id=station.id,
        adapter_key="nanometrics.centaur.ctr",
        collection_mode=CollectionMode.DIRECT,
    )
    session.add(device)
    session.flush()

    session.add(
        PollRun(
            device_id=device.id,
            poll_id=str(uuid.uuid4()),
            collection_mode=CollectionMode.DIRECT,
            adapter_key="nanometrics.centaur.ctr",
            observed_at=datetime.now(timezone.utc),
            success=False,
            error_code=PollErrorCode.CONNECT_TIMEOUT,
            error_message="연결 시간 초과",
        )
    )
    session.flush()

    stored = session.scalar(select(PollRun))
    assert stored.success is False
    assert stored.error_code is PollErrorCode.CONNECT_TIMEOUT
