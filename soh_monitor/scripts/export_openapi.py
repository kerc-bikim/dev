"""OpenAPI 스키마와 프론트 경로 상수를 추출한다.

프론트가 존재하지 않는 경로를 호출하거나, 백엔드가 경로를 바꿨는데 화면이 옛 경로를
쓰는 사고를 막는다. `--check` 는 CI 게이트다.

사용법
    python scripts/export_openapi.py
    python scripts/export_openapi.py --check
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.api.app import create_app  # noqa: E402

OPENAPI_TARGET = ROOT / "contracts" / "openapi.json"
PATHS_TARGET = ROOT / "frontend" / "src" / "generated" / "api-paths.ts"

# 계획서 9절 MVP API. 이 목록이 OpenAPI 에 없으면 CI 가 실패한다.
REQUIRED_PATHS = (
    "/healthz",
    "/readyz",
    "/api/v1/auth/login",
    "/api/v1/auth/logout",
    "/api/v1/auth/me",
    "/api/v1/stations",
    "/api/v1/stations/{station_id}",
    "/api/v1/stations/import",
    "/api/v1/stations/{station_id}/current-health",
    "/api/v1/stations/{station_id}/devices",
    "/api/v1/devices/{device_id}",
    "/api/v1/devices/{device_id}/probe",
    "/api/v1/devices/{device_id}/test-connection",
    "/api/v1/devices/{device_id}/poll-now",
    "/api/v1/devices/{device_id}/capabilities",
    "/api/v1/devices/{device_id}/soh-preview",
    "/api/v1/collection-profiles",
    "/api/v1/metric-profiles",
    "/api/v1/metric-catalog",
    "/api/v1/adapters",
    "/api/v1/fleet/summary",
    "/api/v1/fleet/topology",
    "/api/v1/incidents",
    "/api/v1/incidents/{incident_id}/acknowledge",
    "/api/v1/maintenance-windows",
    "/api/v1/maintenance-windows/{window_id}/close",
    "/api/v1/audit-logs",
    "/api/v1/edges",
    "/api/v1/edges/{edge_id}",
    "/api/v1/edges/{edge_id}/enrollment-token",
    "/api/v1/edges/{edge_id}/assignments",
    "/api/v1/edges/{edge_id}/assignments/{device_id}",
    "/api/v1/edges/{edge_id}/health",
    "/api/v1/edges/{edge_id}/revoke",
    "/api/v1/edge/enroll",
    "/api/v1/edge/heartbeat",
    "/api/v1/edge/config",
    "/api/v1/edge/ingest/batches",
    "/api/v1/edge/tasks/{task_id}/result",
)


HEADER_TS = """// 자동 생성 파일. 직접 고치지 않는다.
// 원본: FastAPI OpenAPI (app.api.app)
// 생성: python scripts/export_openapi.py

"""


def _schema() -> dict:
    app = create_app()
    return app.openapi()


def _ts_constant(path: str) -> str:
    name = path.strip("/").replace("api/v1/", "").replace("{", "").replace("}", "")
    name = name.replace("-", "_").replace("/", "_") or "root"
    parts = [part for part in name.split("_") if part]
    camel = parts[0]
    for part in parts[1:]:
        camel += part[:1].upper() + part[1:]
    return camel


def render_ts(paths: list[str]) -> str:
    lines = [HEADER_TS, "export const API_PATHS = {\n"]
    seen: set[str] = set()
    for path in paths:
        key = _ts_constant(path)
        if key in seen:
            continue
        seen.add(key)
        lines.append(f"  {key}: {json.dumps(path)},\n")
    lines.append("} as const;\n\n")
    lines.append("export type ApiPath = (typeof API_PATHS)[keyof typeof API_PATHS];\n")
    return "".join(lines)


def write_outputs(schema: dict) -> None:
    OPENAPI_TARGET.parent.mkdir(parents=True, exist_ok=True)
    OPENAPI_TARGET.write_text(json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    paths = sorted(schema.get("paths") or {})
    PATHS_TARGET.parent.mkdir(parents=True, exist_ok=True)
    PATHS_TARGET.write_text(render_ts(paths), encoding="utf-8")


def check(schema: dict) -> list[str]:
    problems: list[str] = []
    available = set(schema.get("paths") or {})
    missing = [path for path in REQUIRED_PATHS if path not in available]
    if missing:
        problems.append("OpenAPI 에 없는 필수 경로: " + ", ".join(missing))

    if OPENAPI_TARGET.exists():
        stored = json.loads(OPENAPI_TARGET.read_text(encoding="utf-8"))
        if stored.get("paths", {}).keys() != (schema.get("paths") or {}).keys():
            problems.append("contracts/openapi.json 경로 목록이 현재 API 와 다르다")
    else:
        problems.append("contracts/openapi.json 이 없다")

    expected_ts = render_ts(sorted(schema.get("paths") or {}))
    if not PATHS_TARGET.exists():
        problems.append("frontend/src/generated/api-paths.ts 가 없다")
    elif PATHS_TARGET.read_text(encoding="utf-8") != expected_ts:
        problems.append("frontend/src/generated/api-paths.ts 가 현재 API 와 다르다")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    schema = _schema()
    if args.check:
        problems = check(schema)
        if problems:
            print("\n".join(problems), file=sys.stderr)
            return 1
        print("OpenAPI 경로가 최신이다")
        return 0
    write_outputs(schema)
    print(f"wrote {OPENAPI_TARGET.relative_to(ROOT)}")
    print(f"wrote {PATHS_TARGET.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
