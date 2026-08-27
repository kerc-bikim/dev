import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.files import PathDenied, resolve_file
from app.services.sniff_broker import sniff_argv


def test_sniffwave_argv(ew_home):
    argv = sniff_argv(
        {
            "tool": "sniffwave",
            "ring": "WAVE_RING",
            "sta": "wild",
            "comp": "HHZ",
            "net": "IU",
            "loc": "wild",
            "flag": "n",
        }
    )
    assert argv[-1] == "n"
    assert "WAVE_RING" in argv
    with pytest.raises(ValueError):
        sniff_argv({"tool": "sniffwave", "ring": "WAVE_RING;rm", "flag": "n"})
    with pytest.raises(ValueError):
        sniff_argv({"tool": "sniffwave", "ring": "FLAG_RING", "flag": "n"})


def test_path_sandbox(ew_home):
    from app.services.env import apply_directories, bash_path

    apply_directories(
        bash_path(),
        str(ew_home),
        "earthworm_8.0",
        str(ew_home / "run_working"),
    )
    with pytest.raises(PathDenied):
        resolve_file("params", "../environment/ew_linux.bash")
    with pytest.raises(PathDenied):
        resolve_file("params", "/etc/passwd")


def test_setup_and_control_flow(ew_home):
    headers = {"X-API-Key": "test-key"}
    with TestClient(app) as client:
        st = client.get("/api/setup/status", headers=headers)
        assert st.status_code == 200
        assert st.json()["setup_complete"] is False
        home = str(ew_home)
        run = str(ew_home / "run_working")
        r = client.put(
            "/api/setup/directories",
            headers=headers,
            json={
                "EW_HOME": home,
                "EW_VERSION": "earthworm_8.0",
                "EW_RUN_DIR": run,
                "retention_days": 14,
            },
        )
        assert r.status_code == 200, r.text
        r = client.put(
            "/api/setup/installation",
            headers=headers,
            json={"EW_INSTALLATION": "INST_UNKNOWN"},
        )
        assert r.status_code == 200, r.text
        rings = client.get("/api/setup/defaults", headers=headers).json()["rings"]
        r = client.put("/api/setup/rings", headers=headers, json={"rings": rings})
        assert r.status_code == 200, r.text
        val = client.post("/api/setup/validate", headers=headers)
        assert val.status_code == 200
        assert val.json()["ok"] is True, val.json()
        done = client.post("/api/setup/complete", headers=headers)
        assert done.status_code == 200, done.text
        assert done.json()["setup_complete"] is True

        start = client.post("/api/control/start", headers=headers)
        assert start.status_code == 200, start.text
        body = start.json()
        if not body.get("running"):
            st2 = client.get("/api/status", headers=headers)
            body = st2.json()
        assert body.get("running") is True, body
        mods = [m for m in body["modules"] if m["id"] == "statmgr"]
        assert mods and mods[0]["process"] == "Alive"

        try:
            cloned = client.post(
                "/api/modules/pick_ew/clone",
                headers=headers,
                json={"new_name": "pick_ew_b"},
            )
            assert cloned.status_code == 200, cloned.text
            tog = client.patch("/api/modules/pick_ew", headers=headers, json={"enabled": True})
            assert tog.status_code == 200, tog.text

            logs = client.get("/api/logs/content?file=../etc/passwd", headers=headers)
            assert logs.status_code == 400
        finally:
            stop = client.post("/api/control/stop", headers=headers)
            assert stop.status_code == 200, stop.text
