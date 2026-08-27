from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.nrl.client import (
    CACHE_MISS_DETAIL,
    NrlClient,
    NrlError,
    combine_cache_key,
    set_nrl_client,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "nrl"
GURALP = "sensor_Guralp_CMG-3T_LP30_HF50_SG1500_STgroundVel"
UNKNOWN = "sensor_NoSuchMaker_NewModel_XX"


class FakeHttp:
    def __init__(self, json_data=None, content=b"", content_type="application/xml"):
        self._json = json_data
        self.content = content if isinstance(content, bytes) else content.encode("utf-8")
        self.headers = {"content-type": content_type}

    def json(self):
        return self._json


class ScriptedNrl(NrlClient):
    def __init__(self):
        super().__init__(base_url="http://nrl.test", timeout=0.2)
        self.down = False
        self.live_gets = 0
        self.elements = json.loads((FIXTURES / "elements.json").read_text())
        self.manufacturers = json.loads((FIXTURES / "sensor-manufacturers.json").read_text())
        self.models = json.loads((FIXTURES / "guralp-models.json").read_text())
        self.prefixes = json.loads((FIXTURES / "prefix-lookup.json").read_text())
        self.combine_body = (FIXTURES / "stationxml-resp.xml").read_bytes()
        self.cmg = json.loads((FIXTURES / "cmg-3t.json").read_text())

    def probe(self, timeout=None):
        if self.down:
            return {
                "ok": False,
                "url": f"{self.base_url}/catalog",
                "status_code": 0,
                "elapsed_ms": 1,
                "elements": [],
                "error": "NRL 서비스에 연결할 수 없습니다",
            }
        return {
            "ok": True,
            "url": f"{self.base_url}/catalog",
            "status_code": 200,
            "elapsed_ms": 1,
            "elements": ["sensor"],
            "error": None,
        }

    def _get(self, path, params):
        if self.down:
            raise NrlError("NRL 서비스에 연결할 수 없습니다")
        self.live_gets += 1
        if path == "/catalog":
            level = params.get("level")
            manufacturer = params.get("manufacturer")
            if level == "element":
                return FakeHttp(json_data=self.elements)
            if level == "manufacturer":
                return FakeHttp(json_data=self.manufacturers)
            if level == "model":
                if manufacturer in (None, "", "Guralp"):
                    return FakeHttp(json_data=self.models)
                return FakeHttp(json_data={"NRLCatalog": {"element": []}})
            if level == "configuration":
                return FakeHttp(
                    json_data={
                        "NRLCatalog": {
                            "element": [
                                {
                                    "name": self.cmg["element"],
                                    "manufacturer": [
                                        {
                                            "name": self.cmg["manufacturer"],
                                            "model": [
                                                {
                                                    "name": self.cmg["model"],
                                                    "configuration": self.cmg["configurations"],
                                                }
                                            ],
                                        }
                                    ],
                                }
                            ]
                        }
                    }
                )
        if path == "/prefix-lookup":
            return FakeHttp(json_data=self.prefixes)
        if path == "/combine":
            inst = str(params.get("instconfig") or "")
            if "Guralp" in inst or "CMG-3T" in inst:
                return FakeHttp(content=self.combine_body, content_type="application/xml")
            raise NrlError("NRL에 해당 항목이 없습니다", 404)
        raise NrlError("bad path", 400)


@pytest.fixture
def scripted_nrl():
    nrl = ScriptedNrl()
    set_nrl_client(nrl)
    yield nrl
    set_nrl_client(None)


@pytest.fixture
def authed(client, scripted_nrl):
    client.post("/api/login", json={"username": "stub", "password": "stub"})
    return client


def test_s10_cached_guralp_preview_when_nrl_down(authed, scripted_nrl):
    models = authed.get(
        "/api/nrl/models", params={"element": "sensor", "manufacturer": "Guralp"}
    )
    assert models.status_code == 200
    assert "CMG-3T" in models.json()["models"]

    preview = authed.get("/api/nrl/combine", params={"instconfig": GURALP})
    assert preview.status_code == 200
    assert b"<Response" in preview.content
    assert b"InstrumentSensitivity" in preview.content

    warmed = authed.post(
        "/api/nrl/wizard",
        json={"element": "sensor", "manufacturer": "Guralp", "model": "CMG-3T"},
    )
    assert warmed.status_code == 200
    live_before = scripted_nrl.live_gets
    assert live_before >= 1

    scripted_nrl.down = True
    scripted_nrl.base_url = "http://127.0.0.1:1"

    cached_models = authed.get(
        "/api/nrl/models", params={"element": "sensor", "manufacturer": "Guralp"}
    )
    assert cached_models.status_code == 200
    assert "CMG-3T" in cached_models.json()["models"]

    cached = authed.get("/api/nrl/combine", params={"instconfig": GURALP})
    assert cached.status_code == 200, cached.text
    assert b"<Response" in cached.content
    assert scripted_nrl.live_gets == live_before

    missing = authed.get("/api/nrl/combine", params={"instconfig": UNKNOWN})
    assert missing.status_code == 503
    assert "캐시에 없는" in missing.json()["detail"]

    wizard = authed.post(
        "/api/nrl/wizard",
        json={"element": "sensor", "manufacturer": "Guralp", "model": "CMG-3T"},
    )
    assert wizard.status_code == 200, wizard.text
    assert wizard.json()["match_count"] == 30

    unknown_model = authed.get(
        "/api/nrl/models",
        params={"element": "sensor", "manufacturer": "NoSuchMaker"},
    )
    assert unknown_model.status_code == 503
    assert "캐시에 없는" in unknown_model.json()["detail"]

    status = authed.get("/api/nrl/status")
    assert status.status_code == 200
    body = status.json()
    assert body["source"] == "cache"
    assert body["badge"] == "캐시 사용"
    assert body["cache_count"] >= 1
    assert body["last_ok_at"]


def test_wrong_url_falls_back_to_stale_guralp(redis_client):
    body = (FIXTURES / "stationxml-resp.xml").read_text()
    blob = json.dumps({"body": body, "content_type": "application/xml"})
    key = combine_cache_key(GURALP, "stationxml-resp")
    redis_client.set(f"{key}:stale", blob, ex=86400)

    client = NrlClient(base_url="http://127.0.0.1:1", timeout=0.2)
    payload, content_type = client.combine(GURALP, "stationxml-resp")
    assert b"<Response" in payload
    assert "xml" in content_type

    with pytest.raises(NrlError) as exc:
        client.combine(UNKNOWN, "stationxml-resp")
    assert exc.value.status_code == 503
    assert CACHE_MISS_DETAIL in str(exc.value)
