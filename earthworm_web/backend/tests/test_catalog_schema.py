from fastapi.testclient import TestClient

from app.main import app
from app.services.schema import FLEET_FAMILIES, PRIORITY_IO, load_families, schema_payload
from app.services.seed import PRIORITY_IO_BINS

HEADERS = {"X-API-Key": "test-key"}


def test_yaml_has_priority_io_and_fleet():
    families = load_families()
    for name in PRIORITY_IO:
        assert name in families, name
        assert families[name]["role"] == "process"
        assert families[name]["priority"] is True
    for name in FLEET_FAMILIES:
        assert families[name]["fleet"] is True
    payload = schema_payload()
    assert "IPAddress" in [f["key"] for f in payload["families"]["q3302ew"]["fields"]]
    assert len(payload["fleet"]) == 5


def test_seed_bins_executable(ew_home):
    bindir = ew_home / "earthworm_8.0" / "bin"
    for name in PRIORITY_IO_BINS:
        p = bindir / name
        assert p.is_file(), name
        assert p.stat().st_mode & 0o111
    assert (ew_home / "earthworm_8.0" / "params" / "q3302ew.d").is_file() or (
        ew_home / "earthworm_8.0" / "environment"
    ).is_dir()


def test_catalog_flags_and_schema_api(ew_home):
    from pathlib import Path

    with TestClient(app) as client:
        home = str(ew_home)
        run = str(ew_home / "run_working")
        client.put(
            "/api/setup/directories",
            headers=HEADERS,
            json={"EW_HOME": home, "EW_VERSION": "earthworm_8.0", "EW_RUN_DIR": run, "retention_days": 14},
        )
        client.put("/api/setup/installation", headers=HEADERS, json={"EW_INSTALLATION": "INST_UNKNOWN"})
        rings = client.get("/api/setup/defaults", headers=HEADERS).json()["rings"]
        client.put("/api/setup/rings", headers=HEADERS, json={"rings": rings})
        client.post("/api/setup/complete", headers=HEADERS)
        schema = client.get("/api/modules/schema", headers=HEADERS)
        assert schema.status_code == 200, schema.text
        q330 = schema.json()["families"]["q3302ew"]
        assert any(f["key"] == "IPAddress" for f in q330["fields"])
        mods = client.get("/api/modules", headers=HEADERS).json()["modules"]
        pick = next(m for m in mods if m["id"] == "pick_ew")
        assert pick["priority"] is False
        q = next(m for m in mods if m["id"] == "q3302ew")
        assert q["priority"] is True
        assert q["fleet"] is True
        assert q["role"] == "process"
        assert Path(ew_home / "earthworm_8.0" / "bin" / "q3302ew").is_file()
