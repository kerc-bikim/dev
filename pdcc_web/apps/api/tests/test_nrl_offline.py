from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from app.config import settings
from app.nrl.client import NrlClient, set_nrl_client
from app.nrl.offline import reset_offline_library
from tests.test_users import _enable_admin

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "nrl"
SENSOR = "sensor_Guralp_CMG-3T_LP30_SG1500_STgroundVel"
DATALOGGER = "datalogger_Quanterra_Q330HR_PG1_FR100"


def _tree(question: str, sections: list[tuple[str, str, str]]) -> str:
    rows = ["[Main]", f'question = "{question}"', ""]
    for name, key, value in sections:
        rows.extend([f"[{name}]", f'{key} = "{value}"', ""])
    return "\n".join(rows)


def _make_library(path: Path) -> None:
    xml = (FIXTURES / "stationxml-resp.xml").read_bytes()
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "NRL/index.txt",
            _tree(
                "Select element",
                [
                    ("Sensor", "path", "sensor/index.txt"),
                    ("Datalogger", "path", "datalogger/index.txt"),
                ],
            ),
        )
        archive.writestr(
            "NRL/sensor/index.txt",
            _tree("Select manufacturer", [("Guralp", "path", "Guralp/index.txt")]),
        )
        archive.writestr(
            "NRL/sensor/Guralp/index.txt",
            _tree("Select model", [("CMG-3T", "path", "CMG-3T.txt")]),
        )
        archive.writestr(
            "NRL/sensor/Guralp/CMG-3T.txt",
            "\n".join(
                [
                    "[Main]",
                    'question = "Select sensitivity"',
                    "",
                    "[1500]",
                    (
                        'description = "Guralp; CMG-3T; Long-Period_Corner 30 s; '
                        'Sensitivity 1500 V/m/s; Sensor_Type groundVel"'
                    ),
                    'xml = "CMG-3T_LP30_SG1500_STgroundVel.xml"',
                ]
            ),
        )
        archive.writestr(
            "NRL/sensor/Guralp/CMG-3T_LP30_SG1500_STgroundVel.xml", xml
        )
        archive.writestr(
            "NRL/datalogger/index.txt",
            _tree(
                "Select manufacturer", [("Quanterra", "path", "Quanterra/index.txt")]
            ),
        )
        archive.writestr(
            "NRL/datalogger/Quanterra/index.txt",
            _tree("Select model", [("Q330HR", "path", "Q330HR.txt")]),
        )
        archive.writestr(
            "NRL/datalogger/Quanterra/Q330HR.txt",
            "\n".join(
                [
                    "[Main]",
                    'question = "Select sample rate"',
                    "",
                    "[100]",
                    'description = "Quanterra; Q330HR; Preamp_Gain 1; Final_Rate 100 Hz"',
                    'xml = "Q330HR_PG1_FR100.xml"',
                ]
            ),
        )
        archive.writestr("NRL/datalogger/Quanterra/Q330HR_PG1_FR100.xml", xml)


@pytest.fixture
def offline_zip(tmp_path, monkeypatch):
    path = tmp_path / "nrl.zip"
    _make_library(path)
    old_mode = settings.nrl_mode
    old_path = settings.nrl_offline_zip
    monkeypatch.setattr(settings, "nrl_mode", "offline")
    monkeypatch.setattr(settings, "nrl_offline_zip", str(path))
    reset_offline_library()
    client = NrlClient(base_url="http://127.0.0.1:1", timeout=0.01)
    set_nrl_client(client)
    yield path, client
    settings.nrl_mode = old_mode
    settings.nrl_offline_zip = old_path
    reset_offline_library()
    set_nrl_client(None)


def test_offline_zip_explores_searches_and_previews_without_upstream(
    client, offline_zip, monkeypatch
):
    _path, nrl = offline_zip

    def upstream_forbidden(*_args, **_kwargs):
        raise AssertionError("offline mode attempted an upstream request")

    monkeypatch.setattr(nrl, "_get", upstream_forbidden)
    assert client.post(
        "/api/login", json={"username": "stub", "password": "stub"}
    ).status_code == 200

    elements = client.get("/api/nrl/elements")
    assert elements.status_code == 200
    assert set(elements.json()["elements"]) == {"sensor", "datalogger"}

    models = client.get(
        "/api/nrl/models",
        params={"element": "sensor", "manufacturer": "Guralp"},
    )
    assert models.status_code == 200
    assert models.json()["models"] == ["CMG-3T"]

    search = client.get("/api/nrl/search", params={"q": "3T", "element": "sensor"})
    assert search.status_code == 200
    assert search.json()["hits"][0]["model"] == "CMG-3T"

    wizard = client.post(
        "/api/nrl/wizard",
        json={"element": "sensor", "manufacturer": "Guralp", "model": "CMG-3T"},
    )
    assert wizard.status_code == 200
    assert wizard.json()["matches"][0]["instconfig"] == SENSOR

    preview = client.get(
        "/api/nrl/combine",
        params={"instconfig": f"{SENSOR}:{DATALOGGER}"},
    )
    assert preview.status_code == 200, preview.text
    assert preview.content.count(b"<Stage") >= 2
    assert b"<Response" in preview.content

    status = client.get("/api/nrl/status")
    assert status.status_code == 200
    assert status.json()["source"] == "zip"
    assert status.json()["badge"] == "오프라인 zip"
    assert status.json()["library"]["responses"] == 2


def test_offline_mode_without_zip_returns_503(client, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "nrl_mode", "offline")
    monkeypatch.setattr(settings, "nrl_offline_zip", str(tmp_path / "missing.zip"))
    reset_offline_library()
    set_nrl_client(NrlClient(base_url="http://127.0.0.1:1", timeout=0.01))
    try:
        client.post("/api/login", json={"username": "stub", "password": "stub"})
        response = client.get("/api/nrl/elements")
        assert response.status_code == 503
        assert "zip이 없습니다" in response.json()["detail"]
    finally:
        settings.nrl_mode = "online"
        reset_offline_library()
        set_nrl_client(None)


def test_editor_cannot_manage_library_or_mode(client, offline_zip):
    client.post("/api/login", json={"username": "stub", "password": "stub"})
    assert client.get("/api/nrl/library").status_code == 403
    assert client.post("/api/nrl/library/download").status_code == 403
    assert client.post("/api/nrl/mode", json={"mode": "online"}).status_code == 403


def test_admin_can_download_and_set_offline_mode(client, offline_zip, monkeypatch):
    path, _nrl = offline_zip
    _enable_admin(client)
    expected = {
        "available": True,
        "path": str(path),
        "bytes": path.stat().st_size,
        "responses": 2,
        "error": None,
    }
    monkeypatch.setattr("app.nrl.offline.download_library", lambda: expected)

    downloaded = client.post("/api/nrl/library/download")
    assert downloaded.status_code == 200
    assert downloaded.json()["responses"] == 2

    changed = client.post("/api/nrl/mode", json={"mode": "offline"})
    assert changed.status_code == 200
    assert changed.json()["mode"] == "offline"
    assert changed.json()["source"] == "zip"
