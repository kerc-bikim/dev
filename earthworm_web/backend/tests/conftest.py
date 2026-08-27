from __future__ import annotations

import pytest

from app.config import settings
from app.services.control_db import reset_connection
from app.services.seed import seed_earthworm_home


@pytest.fixture
def ew_home(tmp_path, monkeypatch):
    home = tmp_path / "ew_home"
    seed_earthworm_home(home)
    app_json = tmp_path / "app.json"
    monkeypatch.setattr(settings, "DEFAULT_EW_HOME", home)
    monkeypatch.setattr(settings, "APP_JSON", app_json)
    monkeypatch.setattr(settings, "BASH_PATH", home / "earthworm_8.0" / "environment" / "ew_linux.bash")
    monkeypatch.setattr(settings, "API_KEY", "test-key")
    monkeypatch.setattr(settings, "AUTO_SEED", False)
    monkeypatch.setattr(settings, "CONTROL_DB", tmp_path / "control.sqlite")
    monkeypatch.setattr(settings, "BOOTSTRAP_USERNAME", "")
    monkeypatch.setattr(settings, "BOOTSTRAP_PASSWORD", "")
    reset_connection()
    return home
