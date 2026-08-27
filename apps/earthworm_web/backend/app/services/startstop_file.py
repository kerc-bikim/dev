from __future__ import annotations

import re
from dataclasses import dataclass, field

PROC_RE = re.compile(r"^(\s*#\s*)?Process\s+\"([^\"]+)\"\s*$")
CLASS_RE = re.compile(r"^(\s*#\s*)?Class/Priority\s+(\S+)\s+(\S+)")
RING_RE = re.compile(r"^(\s*#\s*)?Ring\s+(\S+)\s+(\d+)\s*$")
NRING_RE = re.compile(r"^(\s*#\s*)?nRing\s+(\d+)")


@dataclass
class ProcessBlock:
    command: str
    class_name: str = "OTHER"
    priority: str = "0"
    extra: list[str] = field(default_factory=list)
    enabled: bool = True

    @property
    def name(self) -> str:
        return self.command.split()[0] if self.command.strip() else ""

    @property
    def args(self) -> str:
        parts = self.command.split()
        return " ".join(parts[1:])


@dataclass
class StartstopFile:
    preamble: list[str]
    rings: list[tuple[str, int, bool]]  # name, size, enabled
    nring_present: bool
    other: list[str]
    processes: list[ProcessBlock]
    style_blank: str = ""

    def process_named(self, name: str) -> ProcessBlock | None:
        for p in self.processes:
            if p.name == name:
                return p
        return None


def parse_startstop(text: str) -> StartstopFile:
    lines = text.splitlines()
    rings: list[tuple[str, int, bool]] = []
    nring_present = False
    preamble: list[str] = []
    other: list[str] = []
    processes: list[ProcessBlock] = []
    i = 0
    saw_ring = False
    while i < len(lines):
        raw = lines[i]
        mring = RING_RE.match(raw)
        if mring:
            saw_ring = True
            rings.append((mring.group(2), int(mring.group(3)), mring.group(1) is None))
            i += 1
            continue
        if NRING_RE.match(raw):
            nring_present = True
            other.append(raw)
            i += 1
            continue
        mproc = PROC_RE.match(raw)
        if mproc:
            enabled = mproc.group(1) is None
            cmd = mproc.group(2)
            extra: list[str] = []
            class_name, priority = "OTHER", "0"
            i += 1
            while i < len(lines):
                nxt = lines[i]
                cm = CLASS_RE.match(nxt)
                if cm:
                    class_name, priority = cm.group(2), cm.group(3)
                    i += 1
                    continue
                stripped = nxt.strip()
                if PROC_RE.match(nxt) or RING_RE.match(nxt) or NRING_RE.match(nxt):
                    break
                if stripped == "":
                    i += 1
                    break
                extra.append(nxt)
                i += 1
            processes.append(
                ProcessBlock(
                    command=cmd,
                    class_name=class_name,
                    priority=priority,
                    extra=extra,
                    enabled=enabled,
                )
            )
            continue
        if not saw_ring and not processes:
            preamble.append(raw)
        else:
            other.append(raw)
        i += 1
    return StartstopFile(
        preamble=preamble,
        rings=rings,
        nring_present=nring_present,
        other=other,
        processes=processes,
    )


def serialize_startstop(doc: StartstopFile) -> str:
    out: list[str] = []
    out.extend(doc.preamble)
    if doc.preamble and doc.preamble[-1].strip() != "":
        out.append("")
    if doc.nring_present:
        # keep nRing line if it was in `other`; otherwise emit count
        has = any(NRING_RE.match(x or "") for x in doc.other)
        if not has:
            out.append(f"nRing  {len([r for r in doc.rings if r[2]])}")
    for name, size, enabled in doc.rings:
        line = f"Ring   {name}  {size}"
        out.append(line if enabled else f"# {line}")
    extras = [ln for ln in doc.other if not RING_RE.match(ln) and not PROC_RE.match(ln)]
    # drop leftover Class/Priority that belonged to parsed processes
    filtered = []
    for ln in extras:
        if CLASS_RE.match(ln):
            continue
        filtered.append(ln)
    # keep nMessageQueue / KillDelay etc.
    kept = []
    skip_blank_run = False
    for ln in filtered:
        if ln.strip() == "" and skip_blank_run:
            continue
        kept.append(ln)
        skip_blank_run = ln.strip() == ""
    body_misc = [
        ln
        for ln in kept
        if not PROC_RE.match(ln)
        and "Process" not in ln
        and not ln.strip().startswith("Class/Priority")
    ]
    if body_misc:
        out.append("")
        out.extend(body_misc)
    out.append("")
    for p in doc.processes:
        prefix = "" if p.enabled else "# "
        out.append(f'{prefix}Process          "{p.command}"')
        cls_prefix = "" if p.enabled else "#  "
        out.append(f"{cls_prefix}Class/Priority    {p.class_name} {p.priority}")
        for extra in p.extra:
            out.append(extra)
        out.append("")
    text = "\n".join(out).rstrip() + "\n"
    return text


def set_process_enabled(doc: StartstopFile, name: str, enabled: bool) -> ProcessBlock:
    block = doc.process_named(name)
    if block is None:
        raise KeyError(f"Process {name} 없음")
    block.enabled = enabled
    return block


def upsert_process(doc: StartstopFile, command: str, enabled: bool = False) -> ProcessBlock:
    name = command.split()[0]
    existing = doc.process_named(name)
    if existing:
        existing.command = command
        existing.enabled = enabled
        return existing
    block = ProcessBlock(command=command, enabled=enabled)
    doc.processes.append(block)
    return block


def set_rings(doc: StartstopFile, rings: list[tuple[str, int]]) -> None:
    doc.rings = [(n, s, True) for n, s in rings]
