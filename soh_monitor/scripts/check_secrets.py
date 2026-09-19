"""Git 에 비밀이 남았는지 검사한다.

화면·로그·이미지·저장소에 Secret 이 없어야 한다(계획서 16절 12항).
예시 파일과 시험 Fixture 의 가짜 값은 허용한다.

사용법
    python scripts/check_secrets.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SUSPECT = (
    # 자리 표시 PEM 템플릿({payload})은 허용한다. 실제 키 본문이 있으면 실패.
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----\s*[A-Za-z0-9+/=]{32,}"),
    # 식별자 일부(change-password)가 아니라 값으로 넣은 비밀만 본다.
    re.compile(r"(?i)(?:^|[\s,{])['\"]?(?:password|secret|api[_-]?key)['\"]?\s*[:=]\s*['\"][^'\"/][^'\"]{11,}['\"]"),
)

ALLOW_PARTS = (
    ".example",
    "testdata",
    "tests/",
    "mock/",
    "seed_demo.py",
    "docs/",
    "plan.md",
    ".md",
)

SKIP_DIRS = {".git", ".venv", "node_modules", "__pycache__", "dist", "artifacts"}


def _allowed(path: Path) -> bool:
    text = str(path)
    return any(token in text for token in ALLOW_PARTS)


def main() -> int:
    violations: list[str] = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.suffix in {".png", ".webp", ".mp4", ".jpg", ".sqlite", ".db"}:
            continue
        if _allowed(path):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line_number, line in enumerate(text.splitlines(), start=1):
            for pattern in SUSPECT:
                if pattern.search(line):
                    violations.append(f"{path.relative_to(ROOT)}:{line_number}: {line.strip()[:120]}")
    if violations:
        print("비밀로 보이는 값이 저장소에 있다:")
        for item in violations:
            print(f"  {item}")
        return 1
    print("비밀 검사 통과")
    return 0


if __name__ == "__main__":
    sys.exit(main())
