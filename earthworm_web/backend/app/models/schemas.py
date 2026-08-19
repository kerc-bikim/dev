from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class DirectoriesIn(BaseModel):
    EW_HOME: str
    EW_VERSION: str
    EW_RUN_DIR: str
    retention_days: int = 14


class InstallationIn(BaseModel):
    EW_INSTALLATION: str


class RingRow(BaseModel):
    name: str
    key: int
    size: int
    in_startstop: bool = True


class RingsIn(BaseModel):
    rings: list[RingRow]


class FileWriteIn(BaseModel):
    root: str
    path: str
    content: str
    allow_global: bool = False


class ModulePatchIn(BaseModel):
    enabled: bool


class CloneIn(BaseModel):
    new_name: str


class VariablesIn(BaseModel):
    values: dict[str, str]


class LogSettingsIn(BaseModel):
    directory: str | None = None
    retention_days: int | None = None


class SniffIn(BaseModel):
    tool: str
    ring: str
    sta: str = "wild"
    comp: str = "wild"
    net: str = "wild"
    loc: str = "wild"
    flag: str = "n"
    verbose: bool = False
    no_flush: bool = False
    instid: str | None = None
    mod: str | None = None
    type: str | None = None


class UnlockIn(BaseModel):
    force: bool = False
    confirm: bool = Field(default=False)


class SettingsIn(BaseModel):
    status_interval_sec: float | None = None
    sniff_session_limit: int | None = None
    log_retention_days: int | None = None


class EnvironmentIn(BaseModel):
    EW_HOME: str | None = None
    EW_VERSION: str | None = None
    EW_RUN_DIR: str | None = None
    EW_INSTALLATION: str | None = None
    EW_LOG: str | None = None
    EW_DATA_DIR: str | None = None
