from __future__ import annotations

import os
import re
import shutil
import stat
from pathlib import Path

from ..config import settings

SAFE_TOKEN = re.compile(r"^[A-Za-z0-9_.*\-]+$")
SAFE_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,31}$")
CONTROL_BINS = {
    "startstop",
    "status",
    "pau",
    "restart",
    "stopmodule",
    "reconfigure",
    "sniffwave",
    "sniffring",
    "pidpau",
    "copystatus",
    "getmenu",
}

PRIORITY_IO_BINS = (
    "export_generic",
    "export_scnl",
    "import_generic",
    "import_pasv",
    "tbuf2mseed",
    "mseed2tbuf",
    "ew2ringserver",
    "slink2ew",
    "wave_serverV",
    "ew2mseed",
    "ewmseedarchiver",
    "q3302ew",
)


def fixtures_dir() -> Path:
    return Path(settings.FIXTURES_DIR)


def seed_earthworm_home(dest: Path) -> Path:
    """Install fixture tree + stub CLIs under dest (EW_HOME)."""
    dest = Path(dest)
    version = "earthworm_8.0"
    src = fixtures_dir() / version
    tree = dest / version
    env_dir = tree / "environment"
    params_src = src / "params"
    env_dir.mkdir(parents=True, exist_ok=True)
    (tree / "params").mkdir(parents=True, exist_ok=True)
    (tree / "bin").mkdir(parents=True, exist_ok=True)
    for name in (
        "ew_linux.bash",
        "earthworm.d",
        "earthworm_global.d",
        "earthworm_commonvars.d",
    ):
        shutil.copy2(src / "environment" / name, env_dir / name)
    for p in params_src.glob("*"):
        if p.is_file():
            shutil.copy2(p, tree / "params" / p.name)
    bash = env_dir / "ew_linux.bash"
    run_dir = dest / "run_working"
    bash.write_text(
        "\n".join(
            [
                "# Earthworm Linux environment — edited by Earthworm Web Control",
                f"export EW_HOME={dest}",
                f"export EW_VERSION={version}",
                f"export EW_RUN_DIR={run_dir}",
                f'export EW_PARAMS="{run_dir}/params/"',
                f'export EW_LOG="{run_dir}/log/"',
                f'export EW_DATA_DIR="{run_dir}/data/"',
                "export EW_INSTALLATION=INST_UNKNOWN",
                "export SYS_NAME=$(hostname)",
                f'export PATH="{dest}/{version}/bin:${{PATH}}"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    stub_src = fixtures_dir() / "ew_web_stub.py"
    names = [
        "startstop",
        "status",
        "pau",
        "restart",
        "stopmodule",
        "reconfigure",
        "sniffwave",
        "sniffring",
        "pidpau",
        "getmenu",
        "statmgr",
        "pick_ew",
        "binder_ew",
        "eqproc",
        "tankplayer",
        *PRIORITY_IO_BINS,
    ]
    bin_dir = tree / "bin"
    for name in names:
        target = bin_dir / name
        shutil.copy2(stub_src, target)
        target.chmod(target.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return dest


def ensure_default_home() -> Path:
    dest = Path(settings.DEFAULT_EW_HOME)
    startstop = dest / "earthworm_8.0" / "bin" / "startstop"
    if not startstop.is_file():
        seed_earthworm_home(dest)
    return dest


def default_bash_path() -> Path:
    if settings.BASH_PATH:
        return Path(settings.BASH_PATH)
    home = ensure_default_home() if settings.AUTO_SEED else Path("/opt/earthworm")
    return home / "earthworm_8.0" / "environment" / "ew_linux.bash"


def reject_root() -> None:
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        raise PermissionError("root 로 실행하지 마세요. Earthworm 과 같은 일반 유저를 쓰세요.")
