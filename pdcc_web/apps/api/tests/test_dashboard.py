from __future__ import annotations

import uuid
from collections import namedtuple
from datetime import timedelta

from app.config import settings
from app.dashboard import LONG_LOCK_SEC
from app.db import SessionLocal
from app.models import FileAsset, Job, StationLock, User, utcnow
from app.nrl.client import META_LAST_OK_AT, META_SOURCE, combine_cache_key
from app.seed import seed_users
from sqlalchemy import select
from tests.test_wizard import _project


def _enable_admin(client):
    settings.dev_bootstrap_admin = True
    db = SessionLocal()
    try:
        seed_users(db)
    finally:
        db.close()
    ok = client.post("/api/login", json={"username": "admin", "password": "admin"})
    assert ok.status_code == 200, ok.text
    return client


def _user_id(username: str) -> int:
    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.username == username))
        assert user is not None
        return user.id
    finally:
        db.close()


def test_editor_cannot_read_dashboard(client):
    client.post("/api/login", json={"username": "stub", "password": "stub"})
    response = client.get("/api/admin/dashboard")
    assert response.status_code == 403
    assert "관리자" in response.json()["detail"]


def test_admin_dashboard_counts_and_red_badges(client, redis_client, tmp_path, monkeypatch):
    _enable_admin(client)
    project = _project(client)
    zip_path = tmp_path / "nrl.zip"
    zip_path.write_bytes(b"NRLZIP" * 20)
    monkeypatch.setattr(settings, "nrl_offline_zip", str(zip_path))
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))

    redis_client.set(META_SOURCE, "offline")
    redis_client.set(META_LAST_OK_AT, "2026-08-01T00:00:00Z")
    redis_client.set(combine_cache_key("sensor.guralp.cmg3t", "stationxml-resp"), "<xml/>")

    Usage = namedtuple("Usage", "total used free")
    monkeypatch.setattr(
        "app.dashboard.shutil.disk_usage",
        lambda _path: Usage(total=1000, used=950, free=50),
    )

    admin_id = _user_id("admin")
    now = utcnow()
    db = SessionLocal()
    try:
        db.add(
            FileAsset(
                project_id=project["id"],
                kind="original",
                filename="YZ.TEST1.xml",
                media_type="application/xml",
                content=b"<FDSNStationXML/>",
            )
        )
        db.add(
            FileAsset(
                project_id=project["id"],
                kind="job_export",
                filename="YZ.TEST1.dataless",
                media_type="application/vnd.fdsn.seed",
                content=b"SEED" * 8,
            )
        )
        db.add(
            Job(
                id=str(uuid.uuid4()),
                project_id=project["id"],
                user_id=admin_id,
                username="admin",
                kind="dataless",
                status="failed",
                progress=40,
                message="변환 실패",
                error="converter JAR가 없습니다",
                xml_snapshot="<xml/>",
                created_at=now,
                finished_at=now,
            )
        )
        db.add(
            Job(
                id=str(uuid.uuid4()),
                project_id=project["id"],
                user_id=admin_id,
                username="admin",
                kind="resp",
                status="succeeded",
                progress=100,
                message="완료",
                xml_snapshot="<xml/>",
                created_at=now,
                finished_at=now,
            )
        )
        db.add(
            StationLock(
                station_path="YZ/TEST1/2009-04-10T00:00:00",
                project_id=project["id"],
                user_id=admin_id,
                username="admin",
                expires_at=now + timedelta(seconds=LONG_LOCK_SEC + 120),
                heartbeat_at=now,
            )
        )
        db.add(
            StationLock(
                station_path="YZ/TEST2/2009-04-10T00:00:00",
                project_id=project["id"],
                user_id=admin_id,
                username="admin",
                expires_at=now + timedelta(minutes=2),
                heartbeat_at=now,
            )
        )
        db.commit()
    finally:
        db.close()

    response = client.get("/api/admin/dashboard")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["user_count"] >= 3
    assert body["project_count"] >= 1
    assert body["export_count_today"] == 2
    assert body["nrl"]["source"] == "offline"
    assert body["nrl"]["badge"] == "NRL 장애"
    assert body["nrl"]["last_ok_at"] == "2026-08-01T00:00:00Z"
    assert body["nrl"]["cache_count"] >= 1
    assert body["badges"] == {"nrl": True, "failed_jobs": True, "disk": True}
    assert len(body["failed_jobs"]) == 1
    assert body["failed_jobs"][0]["error"] == "converter JAR가 없습니다"
    assert body["failed_jobs"][0]["kind"] == "dataless"
    assert len(body["locks"]) == 1
    assert body["locks"][0]["station_path"].startswith("YZ/TEST1")
    assert body["locks"][0]["remaining_sec"] >= LONG_LOCK_SEC
    assert body["disk"]["originals_bytes"] == len(b"<FDSNStationXML/>")
    assert body["disk"]["exports_bytes"] == len(b"SEED" * 8)
    assert body["disk"]["nrl_zip_bytes"] == zip_path.stat().st_size
    assert body["disk"]["percent"] == 95.0
    assert body["disk"]["over_90"] is True


def test_dashboard_nrl_zip_falls_back_to_cache_bytes(client, redis_client, monkeypatch):
    _enable_admin(client)
    monkeypatch.setattr(settings, "nrl_offline_zip", "")
    blob = "cached-combine-body"
    redis_client.set(combine_cache_key("sensor.guralp.cmg3t", "stationxml-resp"), blob)
    redis_client.set(META_SOURCE, "cache")
    response = client.get("/api/admin/dashboard")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["nrl"]["source"] == "cache"
    assert body["nrl"]["badge"] == "캐시 사용"
    assert body["badges"]["nrl"] is False
    assert body["disk"]["nrl_zip_bytes"] == len(blob)
    assert body["failed_jobs"] == []
    assert body["locks"] == []
