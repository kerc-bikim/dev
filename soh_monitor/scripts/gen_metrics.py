"""표준 Metric 카탈로그에서 백엔드 상수와 프론트 타입을 생성한다.

카탈로그·백엔드·프론트가 서로 다른 Metric 이름을 쓰는 사고를 막는 것이 목적이다.
`--check` 로 실행하면 생성물이 최신인지만 검사한다. CI 에서 이 검사를 게이트로 쓴다.

사용법
    python scripts/gen_metrics.py
    python scripts/gen_metrics.py --check
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.metrics.catalog import load_catalog  # noqa: E402

BACKEND_TARGET = ROOT / "backend" / "app" / "metrics" / "generated.py"
FRONTEND_TARGET = ROOT / "frontend" / "src" / "generated" / "metrics.ts"

HEADER_PY = '''"""자동 생성 파일. 직접 고치지 않는다.

원본: contracts/metrics/catalog.yaml
생성: python scripts/gen_metrics.py
"""
from __future__ import annotations

from typing import Final

'''

HEADER_TS = """// 자동 생성 파일. 직접 고치지 않는다.
// 원본: contracts/metrics/catalog.yaml
// 생성: python scripts/gen_metrics.py

"""


def _const_name(metric_key: str) -> str:
    return metric_key.replace(".", "_").upper()


def render_backend() -> str:
    catalog = load_catalog()
    lines = [HEADER_PY]
    lines.append(f"CATALOG_VERSION: Final[int] = {catalog.version}\n\n")

    lines.append("class MetricKey:\n")
    lines.append('    """표준 Metric 키 상수. 문자열 오타를 컴파일 시점에 가깝게 잡기 위한 것."""\n\n')
    for metric in catalog.metrics.values():
        lines.append(f'    {_const_name(metric.key)}: Final[str] = "{metric.key}"\n')
    lines.append("\n\n")

    lines.append("ALL_METRIC_KEYS: Final[tuple[str, ...]] = (\n")
    for key in catalog.metrics:
        lines.append(f'    "{key}",\n')
    lines.append(")\n\n")

    lines.append("REQUIRED_METRIC_KEYS: Final[tuple[str, ...]] = (\n")
    for metric in catalog.metrics.values():
        if metric.required:
            lines.append(f'    "{metric.key}",\n')
    lines.append(")\n\n")

    lines.append("MEASUREMENTS: Final[tuple[str, ...]] = (\n")
    for measurement in catalog.measurements():
        lines.append(f'    "{measurement}",\n')
    lines.append(")\n\n")

    lines.append("CATEGORIES: Final[tuple[str, ...]] = (\n")
    for category in sorted(catalog.categories.values(), key=lambda c: c.order):
        lines.append(f'    "{category.key}",\n')
    lines.append(")\n\n")

    lines.append("CAPABILITY_KEYS: Final[tuple[str, ...]] = (\n")
    for capability_key in sorted(catalog.capabilities):
        lines.append(f'    "{capability_key}",\n')
    lines.append(")\n")

    return "".join(lines)


def render_frontend() -> str:
    catalog = load_catalog()
    lines = [HEADER_TS]
    lines.append(f"export const CATALOG_VERSION = {catalog.version};\n\n")

    lines.append("export const METRIC_KEYS = [\n")
    for key in catalog.metrics:
        lines.append(f'  "{key}",\n')
    lines.append("] as const;\n\n")
    lines.append("export type MetricKey = (typeof METRIC_KEYS)[number];\n\n")

    lines.append("export const METRIC_CATEGORIES = [\n")
    for category in sorted(catalog.categories.values(), key=lambda c: c.order):
        lines.append(f'  {{ key: "{category.key}", displayName: "{category.display_name}" }},\n')
    lines.append("] as const;\n\n")
    lines.append("export type MetricCategory = (typeof METRIC_CATEGORIES)[number]['key'];\n\n")

    lines.append("export const SEVERITIES = [\n")
    for severity in ("OK", "WARNING", "CRITICAL", "UNKNOWN", "DISABLED", "MAINTENANCE"):
        lines.append(f'  "{severity}",\n')
    lines.append("] as const;\n\n")
    lines.append("export type Severity = (typeof SEVERITIES)[number];\n\n")

    lines.append("export const SUPPORT_STATES = [\n")
    for state in (
        "SUPPORTED_ENABLED",
        "SUPPORTED_DISABLED",
        "UNSUPPORTED",
        "UNKNOWN",
        "ERROR",
    ):
        lines.append(f'  "{state}",\n')
    lines.append("] as const;\n\n")
    lines.append("export type SupportState = (typeof SUPPORT_STATES)[number];\n\n")

    lines.append("export interface MetricDefinition {\n")
    lines.append("  key: MetricKey;\n")
    lines.append("  category: MetricCategory;\n")
    lines.append("  displayName: string;\n")
    lines.append(
        '  valueType: "boolean" | "integer" | "float" | "status" | "text" | "timestamp";\n'
    )
    lines.append("  unit: string | null;\n")
    lines.append("  dimensions: string[];\n")
    lines.append("  capability: string | null;\n")
    lines.append("}\n\n")

    lines.append("export const METRIC_DEFINITIONS: MetricDefinition[] = [\n")
    for metric in catalog.metrics.values():
        unit = f'"{metric.unit}"' if metric.unit else "null"
        capability = f'"{metric.capability}"' if metric.capability else "null"
        dimensions = ", ".join(f'"{d}"' for d in metric.dimensions)
        lines.append(
            "  {\n"
            f'    key: "{metric.key}",\n'
            f'    category: "{metric.category}",\n'
            f'    displayName: "{metric.display_name}",\n'
            f'    valueType: "{metric.value_type.value}",\n'
            f"    unit: {unit},\n"
            f"    dimensions: [{dimensions}],\n"
            f"    capability: {capability},\n"
            "  },\n"
        )
    lines.append("];\n")

    return "".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="표준 Metric 카탈로그 생성기")
    parser.add_argument("--check", action="store_true", help="생성물이 최신인지만 검사한다")
    args = parser.parse_args()

    targets = {BACKEND_TARGET: render_backend(), FRONTEND_TARGET: render_frontend()}

    if args.check:
        stale = []
        for path, expected in targets.items():
            actual = path.read_text(encoding="utf-8") if path.exists() else ""
            if actual != expected:
                stale.append(path)
        if stale:
            for path in stale:
                print(f"생성물이 카탈로그와 다르다: {path.relative_to(ROOT)}")
            print("python scripts/gen_metrics.py 를 실행하고 결과를 커밋한다")
            return 1
        print("생성물이 카탈로그와 일치한다")
        return 0

    for path, content in targets.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        print(f"생성: {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
