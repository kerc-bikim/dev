"""운영 계약: 백업 리허설 · 보존정책 · 비밀 검사 · 장애 리허설 목록."""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.db.models import MetricProfile, Station
from app.db.seed import seed_all

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.check_secrets import main as check_secrets  # noqa: E402
from scripts.ops_backup import SECRET_NAMES, make_bundle  # noqa: E402
from scripts.ops_restore import restore  # noqa: E402

REHEARSAL = (
    "central_disconnect",
    "edge_restart",
    "spool_full",
    "duplicate_batch",
    "certificate_revoke",
    "influx_outage",
    "slow_device",
    "recorder_offline",
    "timing_unlock",
    "recording_stopped",
    "edge_heartbeat_miss",
    "delayed_backfill",
)


def test_비밀_파일이_저장소에_없다():
    assert check_secrets() == 0


def test_다운샘플_Task는_원본_만료_뒤에도_집계를_남긴다():
    five = (ROOT / "deploy/influxdb/init/downsample_5m.flux").read_text(encoding="utf-8")
    hour = (ROOT / "deploy/influxdb/init/downsample_1h.flux").read_text(encoding="utf-8")
    init = (ROOT / "deploy/influxdb/init/10-buckets.sh").read_text(encoding="utf-8")
    assert 'bucket: "soh"' in five
    assert 'bucket: "soh_5m"' in five
    assert 'bucket: "soh_1h"' in hour
    assert "180d" in init
    assert "730d" in init
    assert "1825d" in init
    assert "recorder_" in five
    assert "vendor.nanometrics" not in five
    assert "edge_health" not in five  # 운영 상태는 recorder_health scope=edge


def test_빈_서버_복구_리허설(tmp_path):
    source_db = tmp_path / "live.db"
    engine = create_engine(f"sqlite:///{source_db}", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    with factory() as session:
        seed_all(session)
        session.add(Station(station_code="R01", network_code="KS", name="리허설"))
        session.commit()
        before = session.scalar(select(func.count()).select_from(Station))
        profiles = list(session.scalars(select(MetricProfile)))
    engine.dispose()

    archive = make_bundle(
        out_dir=tmp_path / "bak",
        database_url=f"sqlite:///{source_db}",
        secret_dir=tmp_path / "empty-secrets",
    )
    assert archive.exists()
    source_db.unlink()

    restored = tmp_path / "restored.db"
    report = restore(archive=archive, database_url=f"sqlite:///{restored}")
    assert report["assets"]["dashboards"] >= 7
    assert report["assets"]["influxTasks"] >= 2
    assert report["assets"]["secretNames"] == list(SECRET_NAMES)

    inventory = json.loads(
        # 묶음 안의 목록은 값을 담지 않는다
        json.dumps(report["manifest"]["secretInventory"])
    )
    assert "values" not in inventory
    assert set(inventory["names"]) == set(SECRET_NAMES)

    conn = sqlite3.connect(restored)
    try:
        stations = conn.execute("select count(*) from stations").fetchone()[0]
        assert stations == before
        names = {row[0] for row in conn.execute("select name from metric_profiles")}
        assert "기본 감시 항목" in names
        assert "12V 배터리 감시" in names
        assert "24V 직류 감시" in names
    finally:
        conn.close()
    assert {p.name for p in profiles} >= {"기본 감시 항목", "12V 배터리 감시"}


def test_장애_리허설_12종이_문서와_시험에_있다():
    doc = (ROOT / "docs/operations/failure-rehearsal.md").read_text(encoding="utf-8")
    for name in REHEARSAL:
        assert name in doc, name
    # 구현된 시험이 각 항목을 실제로 건드린다. 이름만 있는 점검표가 되지 않게.
    mapping = {
        "central_disconnect": "backend/tests/unit/test_edge_agent.py",
        "edge_restart": "backend/tests/unit/test_edge_agent.py",
        "spool_full": "backend/tests/unit/test_edge_agent.py",
        "duplicate_batch": "backend/tests/unit/test_edge_ingest.py",
        "certificate_revoke": "backend/tests/unit/test_edge_ingest.py",
        "influx_outage": "backend/tests/integration/test_collector.py",
        "slow_device": "backend/tests/integration/test_collector.py",
        "recorder_offline": "backend/tests/integration/test_health_service.py",
        "timing_unlock": "backend/tests/integration/test_health_service.py",
        "recording_stopped": "backend/tests/integration/test_health_service.py",
        "edge_heartbeat_miss": "backend/tests/unit/test_edge_watch.py",
        "delayed_backfill": "backend/tests/unit/test_edge_ingest.py",
    }
    assert set(mapping) == set(REHEARSAL)
    for name, rel in mapping.items():
        assert (ROOT / rel).exists(), rel
        assert name in doc
