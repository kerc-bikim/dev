from __future__ import annotations

import re
from dataclasses import dataclass

RING_RE = re.compile(r"^(\s*#\s*)?Ring\s+(\S+)\s+(\d+)\b")
MOD_RE = re.compile(r"^(\s*#\s*)?Module\s+(\S+)\s+(\d+)\b")

MAX_RING = 50
MOD_WILDCARD = 0


@dataclass
class TableFile:
    lines: list[str]

    def rings(self) -> list[tuple[str, int, bool]]:
        out = []
        for ln in self.lines:
            m = RING_RE.match(ln)
            if m:
                out.append((m.group(2), int(m.group(3)), m.group(1) is None))
        return out

    def modules(self) -> list[tuple[str, int, bool]]:
        out = []
        for ln in self.lines:
            m = MOD_RE.match(ln)
            if m:
                out.append((m.group(2), int(m.group(3)), m.group(1) is None))
        return out

    def ring_names(self) -> set[str]:
        return {n for n, _k, on in self.rings() if on}

    def module_ids(self) -> set[int]:
        return {i for _n, i, on in self.modules() if on}

    def text(self) -> str:
        return "\n".join(self.lines).rstrip() + "\n"


def parse_earthworm_d(text: str) -> TableFile:
    return TableFile(lines=text.splitlines())


def upsert_ring(doc: TableFile, name: str, key: int) -> None:
    for i, ln in enumerate(doc.lines):
        m = RING_RE.match(ln)
        if m and m.group(2) == name:
            prefix = "# " if m.group(1) else ""
            doc.lines[i] = f"{prefix}Ring   {name}        {key}"
            return
    # insert before first Module or append
    insert_at = next((i for i, ln in enumerate(doc.lines) if MOD_RE.match(ln)), len(doc.lines))
    doc.lines.insert(insert_at, f"Ring   {name}        {key}")


def replace_startstop_rings(doc: TableFile, rings: list[tuple[str, int]]) -> None:
    """Ensure listed rings exist. Do not delete FLAG_RING. Do not change unknown keys unless listed."""
    wanted = {n: k for n, k in rings}
    for name, key in wanted.items():
        upsert_ring(doc, name, key)
    if "FLAG_RING" not in wanted:
        if not any(n == "FLAG_RING" for n, _k, _on in doc.rings()):
            upsert_ring(doc, "FLAG_RING", 2000)


def add_module(doc: TableFile, name: str, module_id: int) -> None:
    for i, ln in enumerate(doc.lines):
        m = MOD_RE.match(ln)
        if m and m.group(2) == name:
            doc.lines[i] = f"Module   {name}        {module_id}"
            return
    doc.lines.append(f"Module   {name}        {module_id}")


def comment_module(doc: TableFile, name: str) -> None:
    for i, ln in enumerate(doc.lines):
        m = MOD_RE.match(ln)
        if m and m.group(2) == name and m.group(1) is None:
            doc.lines[i] = "# " + ln.lstrip()


def next_module_id(doc: TableFile) -> int:
    used = doc.module_ids()
    used.add(MOD_WILDCARD)
    for cand in list(range(200, 256)) + list(range(1, 200)):
        if cand not in used:
            return cand
    raise ValueError("사용 가능한 Module ID 가 없습니다 (1–255)")


def parse_inst_names(global_text: str) -> list[str]:
    names = []
    for ln in global_text.splitlines():
        m = re.match(r"^Inst\s+(\S+)\s+", ln.strip())
        if m:
            names.append(m.group(1))
    return names
