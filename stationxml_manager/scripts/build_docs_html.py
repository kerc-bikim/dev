"""README.md / PLAN.md / DATALESS_SEED.md를 docs.html에 내장해 file://에서도 보이게 한다."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS_HTML = ROOT / "docs.html"
MARKERS = ("/* EMBEDDED_DOCS_BEGIN */", "/* EMBEDDED_DOCS_END */")
FILES = ("README.md", "PLAN.md", "DATALESS_SEED.md", "RESPONSE_CHART.md")


def embedded_js(docs: dict[str, str]) -> str:
    payload = json.dumps(docs, ensure_ascii=False, indent=2).replace("<", "\\u003c")
    return f"{MARKERS[0]}\n    const EMBEDDED_DOCS = {payload};\n    {MARKERS[1]}"


def main() -> None:
    docs = {name: (ROOT / name).read_text(encoding="utf-8") for name in FILES}
    html = DOCS_HTML.read_text(encoding="utf-8")
    start = html.find(MARKERS[0])
    end = html.find(MARKERS[1])
    if start < 0 or end < 0 or end <= start:
        raise SystemExit("docs.html에서 EMBEDDED_DOCS 마커를 찾지 못했습니다")
    end += len(MARKERS[1])
    updated = html[:start] + embedded_js(docs) + html[end:]
    DOCS_HTML.write_text(updated, encoding="utf-8")
    print(f"내장 문서 갱신: {DOCS_HTML}")
    for name, text in docs.items():
        print(f"  {name}: {len(text)} chars")


if __name__ == "__main__":
    main()
