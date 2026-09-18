"""백업 묶음에서 설정 DB 를 되돌린다.

Grafana 대시보드와 Influx Task 는 Git 이 원본이다. 묶음에 있는 사본은
대조에 쓰고, 운영 반영은 저장소 배포로 한다. 비밀 값은 묶음에 없으므로
secrets/ 를 따로 채운 뒤 기동한다.

사용법
    python scripts/ops_restore.py --archive soh-backup-....tar.gz --database sqlite:////tmp/soh.db
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path


def _extract(archive: Path, dest: Path) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "r:gz") as handle:
        handle.extractall(dest, filter="data")
    # tar 가 파일만 담겼거나 디렉터리 한 겹일 수 있다.
    if (dest / "manifest.json").exists():
        return dest
    children = [path for path in dest.iterdir() if path.is_dir()]
    if len(children) == 1 and (children[0] / "manifest.json").exists():
        return children[0]
    raise FileNotFoundError("묶음에 manifest.json 이 없다")


def restore_sqlite(bundle: Path, target_url: str) -> None:
    source = bundle / "db" / "soh.sqlite"
    if not source.exists():
        raise FileNotFoundError("SQLite 백업이 없다")
    path = target_url.split(":///", 1)[-1]
    if path.startswith("//"):
        path = path[1:]
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target.unlink()
    raw = sqlite3.connect(source)
    try:
        dump = sqlite3.connect(target)
        try:
            raw.backup(dump)
        finally:
            dump.close()
    finally:
        raw.close()


def restore_postgres(bundle: Path, target_url: str) -> None:
    dump = bundle / "db" / "postgres.sql"
    if not dump.exists():
        raise FileNotFoundError("PostgreSQL 덤프가 없다")
    subprocess.run(["psql", target_url, "-f", str(dump)], check=True)


def verify_code_assets(bundle: Path) -> dict:
    dashboards = list((bundle / "grafana" / "dashboards").glob("*.json")) if (bundle / "grafana").exists() else []
    tasks = list((bundle / "influx").glob("downsample_*.flux"))
    inventory = json.loads((bundle / "secrets.inventory.json").read_text(encoding="utf-8"))
    return {
        "dashboards": len(dashboards),
        "influxTasks": len(tasks),
        "secretNames": inventory.get("names", []),
    }


def restore(*, archive: Path, database_url: str) -> dict:
    with tempfile.TemporaryDirectory(prefix="soh-restore-") as tmp:
        root = _extract(archive, Path(tmp) / "bundle")
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        kind = manifest.get("database")
        if kind == "sqlite" or database_url.startswith("sqlite"):
            restore_sqlite(root, database_url)
        elif kind == "postgres" or database_url.startswith("postgresql"):
            restore_postgres(root, database_url)
        else:
            raise ValueError(f"복구할 수 없는 database 종류: {kind}")
        assets = verify_code_assets(root)
        return {"manifest": manifest, "assets": assets}


def main() -> int:
    parser = argparse.ArgumentParser(description="SOH 백업 묶음 복구")
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--database", required=True)
    args = parser.parse_args()
    try:
        report = restore(archive=args.archive, database_url=args.database)
    except Exception as exc:  # noqa: BLE001
        print(f"복구 실패: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
