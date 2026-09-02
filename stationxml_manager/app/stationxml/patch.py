"""원문 StationXML 트리를 패치해 저장한다. Inventory.write() 로 문서를 갈아엎지 않는다."""

from __future__ import annotations

from io import BytesIO

from lxml import etree
from obspy import read_inventory

from .whitelist import FDSN_NS, NSMAP, SCHEMA_VERSION, fqn


def parse_stationxml(xml: str | bytes) -> etree._Element:
    xml_bytes = xml.encode("utf-8") if isinstance(xml, str) else xml
    parser = etree.XMLParser(remove_comments=False, remove_blank_text=False)
    return etree.fromstring(xml_bytes, parser)


def serialize_stationxml(root: etree._Element) -> str:
    return etree.tostring(
        root,
        xml_declaration=True,
        encoding="UTF-8",
        pretty_print=True,
    ).decode("utf-8")


def identity_roundtrip(xml: str | bytes) -> str:
    """편집 없이 파싱 후 직렬화한다. 화이트리스트 의미는 유지되어야 한다."""
    return serialize_stationxml(parse_stationxml(xml))


def _find_station(
    root: etree._Element,
    network_code: str,
    station_code: str,
    start_date: str | None = None,
) -> etree._Element:
    for net in root.findall("fsx:Network", NSMAP):
        if net.get("code") != network_code:
            continue
        for sta in net.findall("fsx:Station", NSMAP):
            if sta.get("code") != station_code:
                continue
            if start_date is None or sta.get("startDate") == start_date:
                return sta
    raise KeyError(f"관측소를 찾지 못했습니다: {network_code}.{station_code}")


def _find_channel(
    root: etree._Element,
    network_code: str,
    station_code: str,
    location_code: str,
    channel_code: str,
    start_date: str | None = None,
) -> etree._Element:
    sta = _find_station(root, network_code, station_code, start_date)
    for cha in sta.findall("fsx:Channel", NSMAP):
        loc = cha.get("locationCode") or ""
        if loc != location_code:
            continue
        if cha.get("code") != channel_code:
            continue
        if start_date is None or cha.get("startDate") == start_date:
            return cha
    raise KeyError(
        f"채널을 찾지 못했습니다: {network_code}.{station_code}.{location_code}.{channel_code}"
    )


def set_station_latitude(
    xml: str | bytes,
    network_code: str,
    station_code: str,
    latitude: str | float,
    *,
    start_date: str | None = None,
    propagate_channels: bool = False,
) -> str:
    """관측소 Latitude 텍스트만 바꾼다. 기본은 채널 좌표를 건드리지 않는다."""
    root = parse_stationxml(xml)
    sta = _find_station(root, network_code, station_code, start_date)
    lat = sta.find("fsx:Latitude", NSMAP)
    if lat is None:
        lat = etree.SubElement(sta, fqn("Latitude"))
    lat.text = str(latitude)
    if propagate_channels:
        for cha in sta.findall("fsx:Channel", NSMAP):
            ch_lat = cha.find("fsx:Latitude", NSMAP)
            if ch_lat is not None:
                ch_lat.text = str(latitude)
    return serialize_stationxml(root)


def replace_channel_response(
    xml: str | bytes,
    network_code: str,
    station_code: str,
    location_code: str,
    channel_code: str,
    response_xml: str | bytes,
    *,
    start_date: str | None = None,
) -> str:
    """채널 Response 서브트리만 교체한다. Sensor extra 등 다른 노드는 유지한다."""
    root = parse_stationxml(xml)
    cha = _find_channel(
        root,
        network_code,
        station_code,
        location_code,
        channel_code,
        start_date,
    )
    new_root = parse_stationxml(response_xml)
    new_resp = new_root
    if etree.QName(new_root).localname != "Response":
        found = new_root.find(".//fsx:Response", NSMAP)
        if found is None:
            found = new_root.find(f".//{fqn('Response')}")
        if found is None:
            raise ValueError("교체할 Response 요소가 없습니다")
        new_resp = found
    cloned = etree.fromstring(etree.tostring(new_resp))
    old = cha.find("fsx:Response", NSMAP)
    if old is not None:
        old.getparent().replace(old, cloned)
    else:
        cha.append(cloned)
    return serialize_stationxml(root)


def roundtrip_via_obspy_write(xml: str | bytes) -> str:
    """ObsPy Inventory.write 전체 재생성. 프로덕션 저장 경로가 아니다.

    Agency 2개, XML 주석, Source/Module 원문 등이 손실되는 회귀 기준점이다.
    """
    xml_bytes = xml.encode("utf-8") if isinstance(xml, str) else xml
    inv = read_inventory(BytesIO(xml_bytes), format="STATIONXML")
    buf = BytesIO()
    inv.write(buf, format="STATIONXML", validate=False)
    return buf.getvalue().decode("utf-8")


def ensure_schema_version(xml: str | bytes, version: str = SCHEMA_VERSION) -> str:
    root = parse_stationxml(xml)
    root.set("schemaVersion", version)
    if etree.QName(root).namespace != FDSN_NS:
        pass
    return serialize_stationxml(root)
