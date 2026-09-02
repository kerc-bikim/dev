from __future__ import annotations


def test_health_ok(client):
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body == {"ok": True, "db": True, "redis": True}
    assert response.headers.get("x-request-id")


def test_live_ready_split(client):
    live = client.get("/health/live")
    assert live.status_code == 200
    assert live.json() == {"ok": True}
    ready = client.get("/api/health/ready")
    assert ready.status_code == 200
    assert ready.json()["ok"] is True


def test_api_health_matches(client):
    a = client.get("/health").json()
    b = client.get("/api/health").json()
    assert a == b
