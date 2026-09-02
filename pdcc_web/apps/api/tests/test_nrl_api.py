from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.nrl.client import NrlClient, NrlError, set_nrl_client

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "nrl"


class FakeNrl(NrlClient):
    def __init__(self):
        super().__init__(base_url="http://nrl.test")
        self.calls: list[tuple] = []
        self.cmg = json.loads((FIXTURES / "cmg-3t.json").read_text())
        self.elements = json.loads((FIXTURES / "elements.json").read_text())
        self.manufacturers = json.loads((FIXTURES / "sensor-manufacturers.json").read_text())
        self.models = json.loads((FIXTURES / "guralp-models.json").read_text())
        self.prefixes = json.loads((FIXTURES / "prefix-lookup.json").read_text())
        self.combine_body = (FIXTURES / "stationxml-resp.xml").read_bytes()

    def catalog(self, *, level, element=None, manufacturer=None, model=None):
        self.calls.append(("catalog", level, element, manufacturer, model))
        if level == "element":
            return self.elements
        if level == "manufacturer":
            return self.manufacturers
        if level == "model":
            if manufacturer in (None, "", "Guralp"):
                return self.models
            return {
                "NRLCatalog": {
                    "element": [
                        {
                            "name": element or "sensor",
                            "manufacturer": [{"name": manufacturer, "model": []}],
                        }
                    ]
                }
            }
        if level == "configuration":
            return {
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
        raise NrlError("bad level", 400)

    def prefix_lookup(self):
        self.calls.append(("prefix",))
        return self.prefixes

    def combine(self, instconfig: str, fmt: str):
        self.calls.append(("combine", instconfig, fmt))
        from app.nrl.client import validate_format, validate_instconfig

        validate_instconfig(instconfig)
        validate_format(fmt)
        return self.combine_body, "application/xml"

    def probe(self, timeout=None):
        self.calls.append(("probe",))
        data = self.catalog(level="element")
        elements = []
        for node in data.get("NRLCatalog", {}).get("element") or []:
            if isinstance(node, dict) and node.get("name"):
                elements.append(str(node["name"]))
        return {
            "ok": True,
            "url": f"{self.base_url}/catalog",
            "status_code": 200,
            "elapsed_ms": 1,
            "elements": elements,
            "error": None,
        }


@pytest.fixture
def fake_nrl():
    fake = FakeNrl()
    set_nrl_client(fake)
    yield fake
    set_nrl_client(None)


@pytest.fixture
def authed(client, fake_nrl):
    client.post("/api/login", json={"username": "stub", "password": "stub"})
    return client


def test_nrl_requires_login(client, fake_nrl):
    assert client.get("/api/nrl/elements").status_code == 401


def test_elements_and_manufacturers(authed, fake_nrl):
    elements = authed.get("/api/nrl/elements")
    assert elements.status_code == 200
    assert "sensor" in elements.json()["elements"]
    mfr = authed.get("/api/nrl/manufacturers", params={"element": "sensor"})
    assert mfr.status_code == 200
    assert "Guralp" in mfr.json()["manufacturers"]
    models = authed.get(
        "/api/nrl/models", params={"element": "sensor", "manufacturer": "Guralp"}
    )
    assert "CMG-3T" in models.json()["models"]


def test_wizard_filters_questions(authed):
    empty = authed.post(
        "/api/nrl/wizard",
        json={"element": "sensor", "manufacturer": "Guralp", "model": "CMG-3T"},
    )
    assert empty.status_code == 200
    body = empty.json()
    assert body["match_count"] == 30
    assert [q["key"] for q in body["questions"]] == [
        "High-Frequency_Corner",
        "Long-Period_Corner",
        "Sensitivity",
    ]
    assert body["locked"]["Sensor_Type"] == "groundVel"

    narrowed = authed.post(
        "/api/nrl/wizard",
        json={
            "element": "sensor",
            "manufacturer": "Guralp",
            "model": "CMG-3T",
            "answers": {
                "Long-Period_Corner": "30 s",
                "High-Frequency_Corner": "50 Hz",
                "Sensitivity": "1500 V/m/s",
            },
        },
    )
    data = narrowed.json()
    assert data["match_count"] == 1
    assert data["matches"][0]["instconfig"].endswith("LP30_HF50_SG1500_STgroundVel")


def test_combine_and_reject_full_zip(authed, fake_nrl):
    ok = authed.get(
        "/api/nrl/combine",
        params={"instconfig": "sensor_Guralp_CMG-3T_LP30_HF50_SG1500_STgroundVel"},
    )
    assert ok.status_code == 200
    assert b"<Response" in ok.content
    assert b"InstrumentSensitivity" in ok.content
    bad = authed.get("/api/nrl/combine", params={"instconfig": "full_NRL_v2_zip"})
    assert bad.status_code == 400


def test_curve_requires_login(client, fake_nrl):
    assert client.get(
        "/api/nrl/curve",
        params={"instconfig": "sensor_Guralp_CMG-3T_LP30_HF50_SG1500_STgroundVel"},
    ).status_code == 401


def test_curve_from_combined_response(authed, fake_nrl):
    cascade = (
        "sensor_Guralp_CMG-3T_LP30_HF50_SG1500_STgroundVel:"
        "datalogger_Quanterra_Q330HR_PG1_FR100_ADHR_LRbelow20_DENone"
    )
    ok = authed.get("/api/nrl/curve", params={"instconfig": cascade, "npts": 50})
    assert ok.status_code == 200
    body = ok.json()
    assert body["output"] == "VEL"
    assert body["npts"] == 50
    assert body["sample_rate"] == 100.0
    assert body["instconfig"] == cascade
    assert len(body["frequencies"]) == 50
    assert all(amp > 0 for amp in body["amplitude"])
    assert ("combine", cascade, "stationxml-resp") in fake_nrl.calls

    bad_out = authed.get("/api/nrl/curve", params={"instconfig": cascade, "output": "RAW"})
    assert bad_out.status_code == 400

    over = authed.get(
        "/api/nrl/curve", params={"instconfig": cascade, "max_freq": 80, "npts": 50}
    )
    assert over.status_code == 400
    assert "Nyquist" in over.json()["detail"]
