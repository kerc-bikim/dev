from __future__ import annotations


def test_health_ok(client):
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body == {"ok": True, "db": True, "redis": True}


def test_api_health_matches(client):
    a = client.get("/health").json()
    b = client.get("/api/health").json()
    assert a == b
