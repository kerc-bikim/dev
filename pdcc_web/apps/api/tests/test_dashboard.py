from __future__ import annotations

import uuid
from collections import namedtuple
from datetime import timedelta

from app.config import settings
from app.dashboard import LONG_LOCK_SEC
from app.db import SessionLocal
from app.monitoring import Api5xxMonitoringMiddleware
from app.models import FileAsset, Job, StationLock, User, utcnow
from app.nrl.client import (
    META_LAST_OK_AT,
    META_SOURCE,
    combine_cache_key,
    mark_nrl_live_failed,
    mark_nrl_live_ok,
)
from app.seed import seed_users
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
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
    before = client.get("/api/admin/dashboard").json()
    assert before["badges"]["disk"] is False or "percent" in before["disk"]

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
    token = uuid.uuid4().hex[:10]
    failed_id = str(uuid.uuid4())
    original = b"<FDSNStationXML/>"
    exported = b"SEED" * 8
    station_path = f"YZ/DASH{token}/2009-04-10T00:00:00"
    db = SessionLocal()
    try:
        db.add(
            FileAsset(
                project_id=project["id"],
                kind="original",
                filename="YZ.TEST1.xml",
                media_type="application/xml",
                content=original,
            )
        )
        db.add(
            FileAsset(
                project_id=project["id"],
                kind="job_export",
                filename="YZ.TEST1.dataless",
                media_type="application/vnd.fdsn.seed",
                content=exported,
            )
        )
        db.add(
            Job(
                id=failed_id,
                project_id=project["id"],
                user_id=admin_id,
                username="admin",
                kind="dataless",
                status="failed",
                progress=40,
                message="변환 실패",
                error=f"converter JAR가 없습니다 {token}",
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
                station_path=station_path,
                project_id=project["id"],
                user_id=admin_id,
                username="admin",
                expires_at=now + timedelta(seconds=LONG_LOCK_SEC + 120),
                heartbeat_at=now,
            )
        )
        db.add(
            StationLock(
                station_path=f"YZ/SHORT{token}/2009-04-10T00:00:00",
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
    assert body["project_count"] == before["project_count"] + 1
    assert body["export_count_today"] == before["export_count_today"] + 2
    assert body["nrl"]["source"] == "offline"
    assert body["nrl"]["badge"] == "NRL 장애"
    assert body["nrl"]["last_ok_at"] == "2026-08-01T00:00:00Z"
    assert body["nrl"]["cache_count"] >= 1
    assert body["badges"] == {
        "api_5xx": False,
        "nrl": True,
        "failed_jobs": True,
        "disk": True,
    }
    assert body["monitoring"]["worker_failures"]["count"] >= 1
    assert {alert["kind"] for alert in body["alerts"]} == {"worker_failure"}
    failed = {row["id"]: row for row in body["failed_jobs"]}
    assert failed_id in failed
    assert failed[failed_id]["error"] == f"converter JAR가 없습니다 {token}"
    assert failed[failed_id]["kind"] == "dataless"
    locks = {row["station_path"]: row for row in body["locks"]}
    assert station_path in locks
    assert f"YZ/SHORT{token}/2009-04-10T00:00:00" not in locks
    assert locks[station_path]["remaining_sec"] >= LONG_LOCK_SEC
    assert body["disk"]["originals_bytes"] >= before["disk"]["originals_bytes"] + len(original)
    assert body["disk"]["exports_bytes"] >= before["disk"]["exports_bytes"] + len(exported)
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


def test_dashboard_reports_last_successful_backup(client, tmp_path, monkeypatch):
    _enable_admin(client)
    marker = tmp_path / "backup-last-success"
    marker.write_text("2026-09-02T07:15:30+09:00\n", encoding="utf-8")
    monkeypatch.setattr(settings, "backup_status_file", str(marker))

    response = client.get("/api/admin/dashboard")

    assert response.status_code == 200, response.text
    assert response.json()["backup"] == {
        "last_success_at": "2026-09-01T22:15:30Z",
        "confirmed": True,
    }


def test_dashboard_does_not_confirm_missing_or_invalid_backup(client, tmp_path, monkeypatch):
    _enable_admin(client)
    marker = tmp_path / "backup-last-success"
    monkeypatch.setattr(settings, "backup_status_file", str(marker))

    missing = client.get("/api/admin/dashboard")
    assert missing.status_code == 200, missing.text
    assert missing.json()["backup"] == {"last_success_at": None, "confirmed": False}

    marker.write_text("backup started", encoding="utf-8")
    invalid = client.get("/api/admin/dashboard")
    assert invalid.status_code == 200, invalid.text
    assert invalid.json()["backup"] == {"last_success_at": None, "confirmed": False}


def test_dashboard_alerts_on_api_5xx(client, redis_client):
    _enable_admin(client)
    monitored = FastAPI()
    monitored.add_middleware(Api5xxMonitoringMiddleware)

    @monitored.get("/forced-service-error")
    def forced_service_error():
        return JSONResponse({"detail": "forced"}, status_code=503)

    with TestClient(monitored) as monitored_client:
        response = monitored_client.get("/forced-service-error")
    assert response.status_code == 503

    dashboard = client.get("/api/admin/dashboard")
    assert dashboard.status_code == 200, dashboard.text
    body = dashboard.json()
    assert body["badges"]["api_5xx"] is True
    assert body["monitoring"]["api_5xx"]["count"] == 1
    assert body["monitoring"]["api_5xx"]["last_path"] == "/forced-service-error"
    assert body["monitoring"]["api_5xx"]["last_status"] == 503
    assert body["alerts"][0]["kind"] == "api_5xx"


def test_dashboard_alerts_on_consecutive_nrl_failures_and_resets(client, redis_client):
    _enable_admin(client)

    mark_nrl_live_failed(redis_client, has_cache=True)
    mark_nrl_live_failed(redis_client, has_cache=True)
    before_threshold = client.get("/api/admin/dashboard").json()
    assert before_threshold["monitoring"]["nrl"]["consecutive_failures"] == 2
    assert "nrl_consecutive_failure" not in {
        alert["kind"] for alert in before_threshold["alerts"]
    }

    mark_nrl_live_failed(redis_client, has_cache=True)
    active = client.get("/api/admin/dashboard").json()
    assert active["badges"]["nrl"] is True
    assert active["monitoring"]["nrl"]["consecutive_failures"] == 3
    nrl_alert = next(
        alert
        for alert in active["alerts"]
        if alert["kind"] == "nrl_consecutive_failure"
    )
    assert nrl_alert["count"] == 3
    assert nrl_alert["last_at"]

    mark_nrl_live_ok(redis_client)
    recovered = client.get("/api/admin/dashboard").json()
    assert recovered["monitoring"]["nrl"]["consecutive_failures"] == 0
    assert recovered["badges"]["nrl"] is False
    assert "nrl_consecutive_failure" not in {
        alert["kind"] for alert in recovered["alerts"]
    }
