from __future__ import annotations

import logging
import math
import re
from io import BytesIO
from typing import Any

import numpy as np
from lxml import etree
from obspy import read_inventory

from .client import NrlError

log = logging.getLogger("pdcc.nrl.curve")

FDSN_NS = "http://www.fdsn.org/xml/station/1"
OUTPUTS = {"DIS": "DISP", "VEL": "VEL", "ACC": "ACC"}
FR_RE = re.compile(r"(?:^|_|:)FR(\d+)(?:_|$|:)")
DEFAULT_SAMPLE_RATE = 100.0


class CurveError(NrlError):
    pass


def parse_output(output: str) -> str:
    key = (output or "VEL").upper()
    if key == "DISP":
        key = "DIS"
    if key not in OUTPUTS:
        raise CurveError("output은 DIS, VEL, ACC 중 하나여야 합니다", 400)
    return key


def sample_rate_from_instconfig(instconfig: str) -> float | None:
    matches = FR_RE.findall(instconfig)
    if not matches:
        return None
    return float(matches[-1])


def _local(tag: str) -> str:
    if tag.startswith("{"):
        return tag.split("}", 1)[1]
    return tag


def sample_rate_from_response_xml(root: etree._Element) -> float | None:
    rates: list[float] = []
    for el in root.iter():
        if _local(el.tag) != "Decimation":
            continue
        inp: float | None = None
        factor = 1.0
        for child in el:
            name = _local(child.tag)
            if name == "InputSampleRate" and child.text:
                inp = float(child.text)
            elif name == "Factor" and child.text:
                factor = float(child.text) or 1.0
        if inp is not None:
            rates.append(inp / factor)
    return rates[-1] if rates else None


def resolve_sample_rate(xml_root: etree._Element, instconfig_rate: float | None) -> float:
    if instconfig_rate and instconfig_rate > 0:
        return float(instconfig_rate)
    xml_rate = sample_rate_from_response_xml(xml_root)
    if xml_rate and xml_rate > 0:
        return float(xml_rate)
    return DEFAULT_SAMPLE_RATE


def wrap_stationxml_response(xml: bytes, sample_rate: float) -> bytes:
    try:
        root = etree.fromstring(xml)
    except etree.XMLSyntaxError as exc:
        raise CurveError("StationXML-Response XML이 올바르지 않습니다", 400) from exc
    local = etree.QName(root).localname
    if local == "FDSNStationXML":
        return xml
    if local != "Response":
        raise CurveError("StationXML-Response XML이 아닙니다", 400)

    ns = etree.QName(root).namespace or FDSN_NS
    if etree.QName(root).namespace is None:
        rooted = etree.tostring(root)
        rooted = rooted.replace(b"<Response", f'<Response xmlns="{ns}"'.encode("ascii"), 1)
        root = etree.fromstring(rooted)

    def el(tag: str, text: str | None = None, **attrs: str) -> etree._Element:
        node = etree.Element(f"{{{ns}}}{tag}", nsmap={None: ns})
        for key, value in attrs.items():
            node.set(key, value)
        if text is not None:
            node.text = text
        return node

    inv = el("FDSNStationXML", schemaVersion="1.2")
    inv.append(el("Source", "PDCC"))
    inv.append(el("Created", "1970-01-01T00:00:00"))
    network = el("Network", code="XX")
    station = el("Station", code="TMP", startDate="1970-01-01T00:00:00")
    station.append(el("Latitude", "0"))
    station.append(el("Longitude", "0"))
    station.append(el("Elevation", "0"))
    site = el("Site")
    site.append(el("Name", "tmp"))
    station.append(site)
    channel = el("Channel", code="HHZ", locationCode="", startDate="1970-01-01T00:00:00")
    channel.append(el("Latitude", "0"))
    channel.append(el("Longitude", "0"))
    channel.append(el("Elevation", "0"))
    channel.append(el("Depth", "0"))
    channel.append(el("Azimuth", "0"))
    channel.append(el("Dip", "-90"))
    channel.append(el("SampleRate", str(sample_rate)))
    channel.append(root)
    station.append(channel)
    network.append(station)
    inv.append(network)
    return etree.tostring(inv, xml_declaration=True, encoding="UTF-8")


def logspace_freq(min_freq: float, max_freq: float, npts: int) -> np.ndarray:
    if min_freq <= 0 or max_freq <= 0 or max_freq <= min_freq:
        raise CurveError("주파수 범위가 올바르지 않습니다", 400)
    if npts < 50 or npts > 1000:
        raise CurveError("npts는 50–1000이어야 합니다", 400)
    return np.logspace(math.log10(min_freq), math.log10(max_freq), npts)


def _unit_name(value) -> str | None:
    if value is None:
        return None
    name = getattr(value, "name", None)
    if name:
        return str(name)
    text = str(value).strip()
    return text or None


def _response_units(resp) -> tuple[str | None, str | None]:
    sens = getattr(resp, "instrument_sensitivity", None)
    if sens is None:
        return None, None
    return _unit_name(getattr(sens, "input_units", None)), _unit_name(
        getattr(sens, "output_units", None)
    )


def eval_response_curve(
    xml: bytes,
    *,
    output: str = "VEL",
    min_freq: float = 0.001,
    max_freq: float | None = None,
    npts: int = 200,
    sample_rate: float | None = None,
    instconfig: str | None = None,
) -> dict[str, Any]:
    out = parse_output(output)
    try:
        root = etree.fromstring(xml)
    except etree.XMLSyntaxError as exc:
        raise CurveError("StationXML-Response XML이 올바르지 않습니다", 400) from exc
    rate = resolve_sample_rate(root, sample_rate)
    nyquist = rate / 2.0
    cap = min(nyquist, 100.0)
    used_max = cap if max_freq is None else float(max_freq)
    if used_max > nyquist + 1e-9:
        raise CurveError("max_freq는 Nyquist 이하여야 합니다", 400)
    frequencies = logspace_freq(float(min_freq), used_max, int(npts))
    wrapped = wrap_stationxml_response(xml, rate)
    try:
        inv = read_inventory(BytesIO(wrapped), format="STATIONXML")
        resp = inv[0][0][0].response
        values = resp.get_evalresp_response_for_frequencies(
            frequencies, output=OUTPUTS[out]
        )
    except CurveError:
        raise
    except Exception as exc:
        log.warning("response curve failed: %s", exc)
        raise CurveError("응답 곡선을 계산하지 못했습니다", 422) from exc
    units = _response_units(resp)
    return {
        "instconfig": instconfig,
        "output": out,
        "input_units": units[0],
        "output_units": units[1],
        "sample_rate": rate,
        "frequencies": [float(x) for x in frequencies],
        "amplitude": [float(abs(x)) for x in values],
        "phase_deg": [float(np.angle(x, deg=True)) for x in values],
        "min_freq": float(frequencies[0]),
        "max_freq": used_max,
        "npts": int(len(frequencies)),
    }
