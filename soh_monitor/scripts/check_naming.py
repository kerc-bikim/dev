"""제조사 중립 명명 검사 (계획서 M1.5).

Centaur 는 첫 번째 지원 기록계일 뿐 플랫폼이 아니다. 공통 계층에 `centaur_` 로
시작하는 테이블·Measurement·API 경로가 생기면, Gen5 나 타 제조사를 붙일 때
DB 마이그레이션과 Grafana 대시보드를 전면 수정해야 한다. 그 사고를 기계적으로 막는다.

허용 위치
  * backend/app/adapters/<vendor>/**   제조사 구현체 내부
  * contracts/metrics/status-mappings.yaml  Adapter 키 기준 Mapping
  * 문서, 테스트 Fixture

사용법
    python scripts/check_naming.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

VENDOR_WORDS = ("centaur", "nanometrics", "gen5", "strataos")

# 제조사 이름이 구조적 식별자에 들어가면 안 되는 자리.
FORBIDDEN_PATTERNS = (
    re.compile(r'__tablename__\s*=\s*["\'][^"\']*(?:' + "|".join(VENDOR_WORDS) + r')', re.I),
    re.compile(r'measurement\s*[:=]\s*["\'][^"\']*(?:' + "|".join(VENDOR_WORDS) + r')', re.I),
    re.compile(r'op\.create_table\(\s*["\'][^"\']*(?:' + "|".join(VENDOR_WORDS) + r')', re.I),
    re.compile(r'APIRouter\([^)]*prefix\s*=\s*["\'][^"\']*(?:' + "|".join(VENDOR_WORDS) + r')', re.I),
)

# 공통 계층. 이 경로에서만 검사한다.
SCAN_TARGETS = (
    ("backend/app", (".py",)),
    ("contracts/metrics/catalog.yaml", ()),
    ("contracts/metrics/capabilities.yaml", ()),
    ("contracts/edge", (".json",)),
    ("deploy/grafana", (".json", ".yml", ".yaml")),
)

# 제조사 구현체와 그 시험자료는 제외한다.
EXCLUDED_PARTS = ("adapters/centaur_ctr", "adapters/mock_recorder", "testdata", "__pycache__")


def _iter_files() -> list[Path]:
    files: list[Path] = []
    for target, suffixes in SCAN_TARGETS:
        base = ROOT / target
        if base.is_file():
            files.append(base)
            continue
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            if suffixes and path.suffix not in suffixes:
                continue
            if any(part in str(path) for part in EXCLUDED_PARTS):
                continue
            files.append(path)
    return files


def main() -> int:
    violations: list[str] = []

    for path in _iter_files():
        text = path.read_text(encoding="utf-8", errors="replace")
        for line_number, line in enumerate(text.splitlines(), start=1):
            for pattern in FORBIDDEN_PATTERNS:
                if pattern.search(line):
                    violations.append(
                        f"{path.relative_to(ROOT)}:{line_number}: {line.strip()}"
                    )

    # 카탈로그의 표준 Metric 키에도 제조사 이름이 들어가면 안 된다. vendor.* 는 예외다.
    catalog_path = ROOT / "contracts" / "metrics" / "catalog.yaml"
    if catalog_path.exists():
        for line_number, line in enumerate(
            catalog_path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            match = re.match(r"\s*-?\s*key:\s*(\S+)", line)
            if not match:
                continue
            key = match.group(1)
            if key.startswith("vendor."):
                continue
            if any(word in key.lower() for word in VENDOR_WORDS):
                violations.append(
                    f"contracts/metrics/catalog.yaml:{line_number}: "
                    f"표준 Metric 키에 제조사 이름이 있다 ({key}). vendor.* 로 옮긴다"
                )

    if violations:
        print("제조사 중립 명명 위반:")
        for violation in violations:
            print(f"  {violation}")
        print(
            "\n공통 계층(테이블·Measurement·API 경로·표준 Metric 키)에는 제조사 이름을 쓰지 않는다.\n"
            "제조사 고유 정보는 Adapter 구현체와 vendor.* Metric 안에만 둔다."
        )
        return 1

    scanned = len(_iter_files())
    print(f"명명 검사 통과 ({scanned}개 파일)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
