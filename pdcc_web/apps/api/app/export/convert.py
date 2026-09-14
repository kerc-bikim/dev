"""StationXML 원문 → RESP / dataless SEED 산출물.

읽기는 ObsPy Inventory 뷰다. 프로젝트 xml_text 는 여기서 대입하지 않는다.
"""

from __future__ import annotations

import zipfile
from dataclasses import dataclass, field
from io import BytesIO

from obspy import read_inventory
from obspy.io.xseed import Parser

from .losses import collect_export_issues
from .seed import SeedWriteError, inventory_to_seed_bytes, prepare_seed_inventory
from .slice import SliceError, channel_count, slice_stationxml


class ExportError(Exception):
    def __init__(
        self,
        message: str,
        status_code: int = 400,
        *,
        errors: list[dict] | None = None,
        losses: list[dict] | None = None,
        drops: list[dict] | None = None,
        code: str | None = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.errors = errors or []
        self.losses = losses or []
        self.drops = drops or []
        self.code = code


@dataclass
class ExportResult:
    data: bytes
    filename: str
    media_type: str
    warnings: list[str] = field(default_factory=list)
    losses: list[dict] = field(default_factory=list)
    drops: list[dict] = field(default_factory=list)
    channel_count: int = 0


def classify_seed(data: bytes) -> str:
    types: set[str] = set()
    for rec_len in (4096, 512):
        for offset in range(0, min(len(data), rec_len * 64), rec_len):
            rec = data[offset : offset + 8]
            if len(rec) < 7:
                break
            marker = rec[6:7]
            if marker.isalpha():
                types.add(marker.decode("ascii", errors="ignore"))
        if types:
            break
    has_header = bool(types & {"V", "A", "S"})
    has_data = bool(types & {"D", "R", "Q", "M"})
    if has_data and not has_header:
        return "miniseed"
    if has_data and has_header:
        return "full"
    if has_header:
        return "dataless"
    return "unknown"


def preview_export(
    xml: str,
    *,
    kind: str,
    network: str | None = None,
    station: str | None = None,
    start: str | None = None,
    nslc: str | None = None,
) -> dict:
    try:
        sliced = slice_stationxml(
            xml, network=network, station=station, start=start, nslc=nslc
        )
    except SliceError as exc:
        raise ExportError(str(exc), exc.status_code) from exc
    errors, losses, drops = collect_export_issues(sliced, kind=kind)
    return {
        "kind": kind,
        "channel_count": channel_count(sliced),
        "errors": errors,
        "losses": losses,
        "drops": drops,
        "needs_confirm": bool(losses),
        "blocked": bool(errors),
    }


def _stem(network: str | None, station: str | None, nslc: str | None) -> str:
    parts = [p for p in (network, station) if p]
    if nslc:
        parts.append(nslc.replace(".", "_"))
    return ".".join(parts) if parts else "inventory"


def _load_inventory(xml: str):
    try:
        return read_inventory(BytesIO(xml.encode("utf-8")), format="STATIONXML")
    except Exception as exc:
        raise ExportError(f"StationXML을 읽지 못했습니다: {exc}", 422) from exc


def _to_seed(xml: str) -> tuple[bytes, list[str]]:
    inv = _load_inventory(xml)
    warnings = prepare_seed_inventory(inv)
    try:
        data = inventory_to_seed_bytes(inv)
    except SeedWriteError as exc:
        raise ExportError(str(exc), 400) from exc
    except Exception as exc:
        raise ExportError(f"SEED 응답 단계를 쓰지 못했습니다: {exc}", 400) from exc
    if classify_seed(data) != "dataless":
        raise ExportError("dataless SEED가 만들어지지 않았습니다", 500)
    return data, warnings


def _resp_files(seed: bytes) -> list[tuple[str, bytes]]:
    parser = Parser(BytesIO(seed))
    out: list[tuple[str, bytes]] = []
    for name, buf in parser.get_resp():
        buf.seek(0)
        out.append((name, buf.read()))
    if not out:
        raise ExportError("RESP 채널이 없습니다", 400)
    return out


def render_export(
    xml: str,
    *,
    kind: str,
    network: str | None = None,
    station: str | None = None,
    start: str | None = None,
    nslc: str | None = None,
    accept_losses: bool = False,
) -> ExportResult:
    if kind not in ("resp", "dataless"):
        raise ExportError("kind는 resp 또는 dataless 여야 합니다")
    preview = preview_export(
        xml, kind=kind, network=network, station=station, start=start, nslc=nslc
    )
    if preview["errors"]:
        raise ExportError(
            f"내보낼 수 없습니다. 문제 채널 {len(preview['errors'])}개",
            400,
            errors=preview["errors"],
            losses=preview["losses"],
            drops=preview["drops"],
            code="E_EXPORT",
        )
    if preview["losses"] and not accept_losses:
        raise ExportError(
            "변환 손실이 있습니다. 목록을 확인한 뒤 다시 요청하세요",
            409,
            errors=[],
            losses=preview["losses"],
            drops=preview["drops"],
            code="E_LOSS_CONFIRM",
        )
    sliced = slice_stationxml(
        xml, network=network, station=station, start=start, nslc=nslc
    )
    seed, warnings = _to_seed(sliced)
    stem = _stem(network, station, nslc)
    nchan = preview["channel_count"]
    if kind == "dataless":
        return ExportResult(
            data=seed,
            filename=f"{stem}.dataless",
            media_type="application/vnd.fdsn.seed",
            warnings=warnings,
            losses=preview["losses"],
            drops=preview["drops"],
            channel_count=nchan,
        )
    files = _resp_files(seed)
    if len(files) == 1:
        name, body = files[0]
        return ExportResult(
            data=body,
            filename=name,
            media_type="text/plain; charset=us-ascii",
            warnings=warnings,
            losses=preview["losses"],
            drops=preview["drops"],
            channel_count=nchan,
        )
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, body in files:
            zf.writestr(name, body)
    return ExportResult(
        data=buf.getvalue(),
        filename=f"{stem}.resp.zip",
        media_type="application/zip",
        warnings=warnings,
        losses=preview["losses"],
        drops=preview["drops"],
        channel_count=nchan,
    )
