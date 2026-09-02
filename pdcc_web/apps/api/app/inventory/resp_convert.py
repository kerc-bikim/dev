"""StationXML 원문 → RESP, RESP → 불완전 StationXML.

RESP는 NRL `/combine format=resp`가 아니라 현재 편집 XML에서 만든다.
감도를 고친 값이 빠지면 안 된다. 프로젝트 xml_text 문자열은 여기서 대입하지 않는다.
"""

from __future__ import annotations

import zipfile
from io import BytesIO

from obspy import UTCDateTime, read_inventory
from obspy.core.inventory import Site

from .seed_convert import convert_warning, convert_xml_to_dataless, _ensure_schema_12
from .xmlbuild import InventoryError, NETWORK_CODE_RE
from .xmlslice import channel_count, slice_stationxml

RESP_MEDIA = "text/plain; charset=us-ascii"
RESP_ZIP_MEDIA = "application/zip"
MISSING_ELEV = 123456.0
DEFAULT_START = "1970-01-01T00:00:00"


def resp_filename(name: str) -> str:
    text = (name or "RESP").replace('"', "").replace("/", "_")
    return text[:200] or "RESP"


def _resp_files_from_seed(seed: bytes) -> list[tuple[str, bytes]]:
    from obspy.io.xseed import Parser

    parser = Parser(BytesIO(seed))
    out: list[tuple[str, bytes]] = []
    for name, buf in parser.get_resp():
        buf.seek(0)
        out.append((resp_filename(name), buf.read()))
    if not out:
        raise InventoryError("RESP 채널이 없습니다", 400, "E_EXPORT")
    return out


def pack_resp_files(
    files: list[tuple[str, bytes]],
    *,
    network: str,
    station: str | None = None,
) -> tuple[bytes, str, str]:
    if len(files) == 1:
        name, data = files[0]
        return data, name, RESP_MEDIA
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, data in files:
            zf.writestr(name, data)
    parts = [p for p in ((network or "").strip(), (station or "").strip()) if p]
    stem = ".".join(parts) if parts else "inventory"
    return buf.getvalue(), f"{stem}.resp.zip", RESP_ZIP_MEDIA


def xml_to_resp_files(
    xml: str,
    *,
    network: str | None = None,
    station: str | None = None,
    start: str | None = None,
    nslc: str | None = None,
    organization: str | None = None,
    label: str | None = None,
) -> tuple[list[tuple[str, bytes]], str, int]:
    sliced = slice_stationxml(
        xml, network=network, station=station, start=start, nslc=nslc
    )
    seed, engine = convert_xml_to_dataless(
        sliced, organization=organization, label=label or network
    )
    files = _resp_files_from_seed(seed)
    return files, engine, channel_count(sliced)


def convert_xml_to_resp(
    xml: str,
    *,
    network: str | None = None,
    station: str | None = None,
    start: str | None = None,
    nslc: str | None = None,
    organization: str | None = None,
    label: str | None = None,
) -> tuple[bytes, str, str, str, int]:
    files, engine, nchan = xml_to_resp_files(
        xml,
        network=network,
        station=station,
        start=start,
        nslc=nslc,
        organization=organization,
        label=label,
    )
    sta = station
    if not sta:
        codes: list[str] = []
        for name, _body in files:
            parts = name.split(".")
            if len(parts) >= 5 and parts[0] == "RESP" and parts[2] not in codes:
                codes.append(parts[2])
        sta = codes[0] if len(codes) == 1 else None
    data, filename, media = pack_resp_files(files, network=network or "XX", station=sta)
    return data, filename, media, engine, nchan


def _is_missing_coord(value) -> bool:
    if value is None:
        return True
    try:
        number = float(value)
    except (TypeError, ValueError):
        return True
    return abs(number) >= MISSING_ELEV


def _zero_or_missing(value) -> bool:
    if _is_missing_coord(value):
        return True
    try:
        return float(value) == 0.0
    except (TypeError, ValueError):
        return True


def _fill_resp_inventory(inv) -> list[dict]:
    notes: list[dict] = []
    filled_net = False
    filled_geo = False
    filled_time = False
    for net in inv:
        code = (net.code or "").strip().upper()
        if not code or not NETWORK_CODE_RE.match(code):
            net.code = "XX"
            filled_net = True
        else:
            net.code = code
        for sta in net:
            if not (sta.code or "").strip():
                sta.code = "RESP"
            if sta.site is None or not (sta.site.name or "").strip():
                sta.site = Site(name="RESP 가져오기")
            if _zero_or_missing(sta.latitude):
                sta.latitude = 0.0
                filled_geo = True
            if _zero_or_missing(sta.longitude):
                sta.longitude = 0.0
                filled_geo = True
            if _is_missing_coord(sta.elevation):
                sta.elevation = 0.0
                filled_geo = True
            channel_starts = [ch.start_date for ch in sta if ch.start_date is not None]
            if sta.start_date is None:
                sta.start_date = min(channel_starts) if channel_starts else UTCDateTime(DEFAULT_START)
                filled_time = True
            for cha in sta:
                if _zero_or_missing(cha.latitude):
                    cha.latitude = float(sta.latitude or 0.0)
                    filled_geo = True
                if _zero_or_missing(cha.longitude):
                    cha.longitude = float(sta.longitude or 0.0)
                    filled_geo = True
                if _is_missing_coord(cha.elevation):
                    cha.elevation = float(sta.elevation or 0.0)
                    filled_geo = True
                if _is_missing_coord(getattr(cha, "depth", None)):
                    cha.depth = 0.0
                if cha.start_date is None:
                    cha.start_date = sta.start_date
                    filled_time = True
    notes.append(
        convert_warning(
            "W_RESP_INCOMPLETE",
            "RESP에는 응답만 있습니다. 네트워크 코드, 좌표, 기간을 채워 주세요.",
        )
    )
    if filled_net:
        notes.append(
            convert_warning("W_RESP_NETWORK", "네트워크 코드가 없어 XX로 채웠습니다")
        )
    if filled_geo:
        notes.append(
            convert_warning("W_RESP_COORDS", "좌표가 없어 0으로 채웠습니다. 관측소 폼에서 고치세요")
        )
    if filled_time:
        notes.append(
            convert_warning("W_RESP_TIME", "기간이 없어 채널·관측소 시작을 채웠습니다")
        )
    return notes


def convert_resp_to_xml(raw: bytes) -> tuple[str, list[dict]]:
    if not raw or not raw.strip():
        raise InventoryError("파일이 비어 있습니다", 400, "E_IMPORT")
    try:
        inv = read_inventory(BytesIO(raw), format="RESP")
    except Exception as exc:
        raise InventoryError(
            "RESP를 읽지 못했습니다. 파일이 손상되었거나 형식이 아닙니다",
            400,
            "E_IMPORT",
        ) from exc
    if inv is None or len(inv) == 0:
        raise InventoryError("RESP에 채널이 없습니다", 400, "E_IMPORT")
    notes = _fill_resp_inventory(inv)
    buf = BytesIO()
    try:
        inv.write(buf, format="STATIONXML")
    except Exception as exc:
        raise InventoryError("변환된 StationXML을 쓰지 못했습니다", 500, "E_IMPORT") from exc
    xml = buf.getvalue().decode("utf-8")
    if not xml.strip():
        raise InventoryError("변환 결과가 비어 있습니다", 400, "E_IMPORT")
    xml, schema_notes = _ensure_schema_12(xml)
    notes.extend(schema_notes)
    notes.insert(
        0,
        convert_warning("W_RESP_CONVERT", "RESP를 StationXML 1.2로 변환했습니다 (obspy)"),
    )
    return xml, notes
