from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.app_store import load_app, save_app, sniff_session_limit, status_interval_sec
from app.services.clone import CloneError, clone_module, delete_clone
from app.services.env import bash_path, rewrite_bash, validate_ew_assignment
from app.services.files import PathDenied, write_file
from app.services.startstop_file import parse_startstop


HEADERS = {"X-API-Key": "test-key"}


def _complete(client: TestClient, ew_home: Path) -> None:
    r = client.put(
        "/api/setup/directories",
        headers=HEADERS,
        json={
            "EW_HOME": str(ew_home),
            "EW_VERSION": "earthworm_8.0",
            "EW_RUN_DIR": str(ew_home / "run_working"),
            "retention_days": 14,
        },
    )
    assert r.status_code == 200, r.text
    r = client.put(
        "/api/setup/installation",
        headers=HEADERS,
        json={"EW_INSTALLATION": "INST_UNKNOWN"},
    )
    assert r.status_code == 200, r.text
    rings = client.get("/api/setup/defaults", headers=HEADERS).json()["rings"]
    r = client.put("/api/setup/rings", headers=HEADERS, json={"rings": rings})
    assert r.status_code == 200, r.text
    done = client.post("/api/setup/complete", headers=HEADERS)
    assert done.status_code == 200, done.text


def test_rewrite_bash_rejects_metacharacters_and_quotes(ew_home):
    with pytest.raises(ValueError):
        validate_ew_assignment("EW_HOME", "/tmp/$(whoami)")
    with pytest.raises(ValueError):
        validate_ew_assignment("EW_HOME", "/tmp; rm -rf /")
    with pytest.raises(ValueError):
        validate_ew_assignment("EW_VERSION", "v8`id`")
    with pytest.raises(ValueError):
        validate_ew_assignment("EW_INSTALLATION", "INST;x")
    script = bash_path()
    rewrite_bash(script, {"EW_HOME": str(ew_home)})
    text = script.read_text(encoding="utf-8")
    assert f"export EW_HOME={str(ew_home)!s}" in text or "export EW_HOME=" in text
    line = next(ln for ln in text.splitlines() if ln.startswith("export EW_HOME="))
    assert "$(" not in line
    assert ";" not in line
    assert line.split("=", 1)[1].startswith("'") or line.split("=", 1)[1].startswith('"') or "/" in line


def test_public_health_has_no_paths(ew_home):
    with TestClient(app) as client:
        r = client.get("/api/health")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}
        assert "ew_home" not in r.json()
        assert "lock" not in r.json()
        denied = client.get("/api/health/detail")
        assert denied.status_code == 401
        ok = client.get("/api/health/detail", headers=HEADERS)
        assert ok.status_code == 200
        assert "setup_complete" in ok.json()


def test_http_query_key_rejected(ew_home):
    with TestClient(app) as client:
        r = client.get("/api/setup/status?key=test-key")
        assert r.status_code == 403
        r = client.get("/api/setup/status", headers=HEADERS)
        assert r.status_code == 200


def test_empty_api_key_is_unavailable(ew_home, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "API_KEY", "")
    with TestClient(app) as client:
        r = client.get("/api/setup/status", headers={"X-API-Key": "anything"})
        assert r.status_code == 401


def test_docs_closed_by_default(ew_home):
    with TestClient(app) as client:
        assert client.get("/docs").status_code == 404
        assert client.get("/openapi.json").status_code == 404


def test_cannot_write_ew_linux_bash(ew_home):
    from app.services.env import apply_directories

    apply_directories(bash_path(), str(ew_home), "earthworm_8.0", str(ew_home / "run_working"))
    with pytest.raises(PathDenied):
        write_file("environment", "ew_linux.bash", "export EW_HOME=/tmp/$(id)\n", allow_global=True)


def test_complete_again_does_not_wipe_enabled_modules(ew_home):
    with TestClient(app) as client:
        _complete(client, ew_home)
        tog = client.patch("/api/modules/pick_ew", headers=HEADERS, json={"enabled": True})
        assert tog.status_code == 200, tog.text
        again = client.post("/api/setup/complete", headers=HEADERS)
        assert again.status_code == 200, again.text
        mods = client.get("/api/modules", headers=HEADERS).json()["modules"]
        pick = next(m for m in mods if m["id"] == "pick_ew")
        assert pick["enabled"] is True


def test_clone_delete_descriptor_exact_match(ew_home):
    from app.services.env import apply_directories, parsed_core
    from app.services.setup_wizard import set_installation

    apply_directories(bash_path(), str(ew_home), "earthworm_8.0", str(ew_home / "run_working"))
    set_installation("INST_UNKNOWN")
    rec = clone_module("pick_ew", "pick_ew_b")
    params = Path(parsed_core()["EW_PARAMS"])
    sm = params / "statmgr.d"
    extra = "Descriptor     pick_ew_b.desc.keep\n"
    sm.write_text(sm.read_text(encoding="utf-8") + extra, encoding="utf-8")
    delete_clone(rec["id"])
    text = sm.read_text(encoding="utf-8")
    assert "pick_ew_b.desc.keep" in text
    for ln in text.splitlines():
        parts = ln.strip().lstrip("#").split()
        if len(parts) >= 2 and parts[0] == "Descriptor":
            assert parts[1] != "pick_ew_b.desc"


def test_clone_rejects_unsafe_source_id(ew_home):
    from app.services.env import apply_directories
    from app.services.setup_wizard import set_installation

    apply_directories(bash_path(), str(ew_home), "earthworm_8.0", str(ew_home / "run_working"))
    set_installation("INST_UNKNOWN")
    with pytest.raises(CloneError):
        clone_module("../etc/passwd", "xclone")
    with pytest.raises(CloneError):
        clone_module("pick_ew;rm", "xclone")


def test_settings_drive_runtime_limits(ew_home):
    meta = load_app()
    meta.status_interval_sec = 7.5
    meta.sniff_session_limit = 5
    save_app(meta)
    assert status_interval_sec() == 7.5
    assert sniff_session_limit() == 5
    meta.status_interval_sec = 0.1
    meta.sniff_session_limit = 99
    save_app(meta)
    assert status_interval_sec() == 0.5
    assert sniff_session_limit() == 8


def test_module_stop_rejects_startstop(ew_home):
    with TestClient(app) as client:
        _complete(client, ew_home)
        r = client.post("/api/control/modules/startstop/stop", headers=HEADERS)
        assert r.status_code == 409
        r = client.post("/api/control/modules/statmgr/stop", headers=HEADERS)
        assert r.status_code == 409


def test_path_change_blocked_while_alive(ew_home, monkeypatch):
    monkeypatch.setattr("app.services.ipc_diag.startstop_is_alive", lambda: True)
    with TestClient(app) as client:
        r = client.put(
            "/api/setup/directories",
            headers=HEADERS,
            json={
                "EW_HOME": str(ew_home),
                "EW_VERSION": "earthworm_8.0",
                "EW_RUN_DIR": str(ew_home / "run_working"),
            },
        )
        assert r.status_code == 409


def test_complete_keeps_pick_ew_process_enabled_in_file(ew_home):
    with TestClient(app) as client:
        _complete(client, ew_home)
        client.patch("/api/modules/pick_ew", headers=HEADERS, json={"enabled": True})
        client.post("/api/setup/complete", headers=HEADERS)
        from app.services.env import parsed_core

        ss = parse_startstop(
            (Path(parsed_core()["EW_PARAMS"]) / "startstop_unix.d").read_text(encoding="utf-8")
        )
        assert ss.process_named("pick_ew").enabled is True
