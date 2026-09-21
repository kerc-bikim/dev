"""설정 DB·Grafana·Influx Task·비밀 목록을 한 묶음으로 백업한다.

값 있는 Secret 파일은 묶음에 넣지 않는다. 이름만 적는다. 키를 백업 파일에
넣으면 그 파일이 곧 유출이다.

사용법
    python scripts/ops_backup.py --out /var/backups/soh
    python scripts/ops_backup.py --out /tmp/soh-bak --database sqlite:////tmp/soh.db
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SECRET_NAMES = (
    "postgres_password",
    "influx_password",
    "influx_token",
    "session_secret",
    "device_credential_key",
    "grafana_admin_password",
)

GRAFANA_PATHS = (
    ROOT / "deploy" / "grafana" / "dashboards",
    ROOT / "deploy" / "grafana" / "provisioning",
)
INFLUX_TASKS = ROOT / "deploy" / "influxdb" / "init"


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _copy_tree(src: Path, dest: Path) -> None:
    if not src.exists():
        return
    dest.mkdir(parents=True, exist_ok=True)
    if src.is_file():
        shutil.copy2(src, dest / src.name)
        return
    shutil.copytree(src, dest, dirs_exist_ok=True)


def backup_database(url: str, dest_dir: Path) -> str:
    dest_dir.mkdir(parents=True, exist_ok=True)
    if url.startswith("sqlite"):
        path = url.split(":///", 1)[-1]
        if path.startswith("//"):
            path = path[1:]
        source = Path(path)
        if not source.exists():
            raise FileNotFoundError(f"SQLite 파일이 없다: {source}")
        # 사용 중인 DB 도 일관된 사본을 남긴다.
        target = dest_dir / "soh.sqlite"
        raw = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
        try:
            dump = sqlite3.connect(target)
            try:
                raw.backup(dump)
            finally:
                dump.close()
        finally:
            raw.close()
        return "sqlite"
    if url.startswith("postgresql"):
        dump = dest_dir / "postgres.sql"
        command = ["pg_dump", "--no-owner", "--no-acl", url]
        try:
            with dump.open("w", encoding="utf-8") as handle:
                subprocess.run(command, check=True, stdout=handle)
        except (FileNotFoundError, subprocess.CalledProcessError) as exc:
            raise RuntimeError(
                "pg_dump 를 실행하지 못했다. PostgreSQL 클라이언트와 접속 정보를 확인한다."
            ) from exc
        return "postgres"
    raise ValueError(f"지원하지 않는 DATABASE_URL: {url}")


def write_secret_inventory(dest: Path, secret_dir: Path | None) -> dict:
    present: list[str] = []
    missing: list[str] = []
    for name in SECRET_NAMES:
        path = (secret_dir / name) if secret_dir else None
        if path is not None and path.exists() and path.stat().st_size > 0:
            present.append(name)
        else:
            missing.append(name)
    payload = {
        "names": list(SECRET_NAMES),
        "present": present,
        "missing": missing,
        "note": "값은 넣지 않는다. 비밀은 별도 금고(또는 secrets/ 디렉터리)에 둔다.",
    }
    dest.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def make_bundle(*, out_dir: Path, database_url: str, secret_dir: Path | None) -> Path:
    stamp = utc_stamp()
    work = out_dir / f"soh-backup-{stamp}"
    work.mkdir(parents=True, exist_ok=True)
    kind = backup_database(database_url, work / "db")
    for path in GRAFANA_PATHS:
        _copy_tree(path, work / "grafana" / path.name)
    _copy_tree(INFLUX_TASKS, work / "influx")
    inventory = write_secret_inventory(work / "secrets.inventory.json", secret_dir)
    manifest = {
        "createdAt": stamp,
        "database": kind,
        "includes": ["db", "grafana", "influx", "secrets.inventory.json"],
        "secretInventory": inventory,
        "grafanaUidSource": "deploy/grafana/dashboards",
    }
    (work / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    archive = out_dir / f"soh-backup-{stamp}.tar.gz"
    shutil.make_archive(str(work), "gztar", root_dir=work)
    return archive


def main() -> int:
    parser = argparse.ArgumentParser(description="SOH 백업 묶음 생성")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--database", default="", help="sqlite:///... 또는 postgresql://...")
    parser.add_argument("--secret-dir", type=Path, default=None)
    args = parser.parse_args()
    url = args.database or __import__("os").environ.get(
        "SOH_DATABASE_URL_OVERRIDE", "sqlite:////tmp/soh_local.db"
    )
    try:
        archive = make_bundle(out_dir=args.out, database_url=url, secret_dir=args.secret_dir)
    except Exception as exc:  # noqa: BLE001
        print(f"백업 실패: {exc}", file=sys.stderr)
        return 1
    print(archive)
    return 0


if __name__ == "__main__":
    sys.exit(main())
