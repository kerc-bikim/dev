from __future__ import annotations

import re
from datetime import datetime, timezone

from lxml import etree

from .xmlutil import (
    child_text,
    dumps,
    el,
    local,
    namespaced_copy,
    parse_root,
    qname,
    set_child,
)

CHANNEL_CODE_RE = re.compile(r"^[A-Za-z0-9]{3}$")
STATION_CODE_RE = re.compile(r"^[A-Za-z0-9]{1,5}$")
NETWORK_CODE_RE = re.compile(r"^[A-Za-z0-9]{1,8}$")


class InventoryError(Exception):
    def __init__(self, message: str, status_code: int = 400, code: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.code = code


def orientation(code: str) -> tuple[float, float]:
    last = (code or "")[-1:].upper()
    if last == "Z":
        return 0.0, -90.0
    if last == "N":
        return 0.0, 0.0
    if last == "E":
        return 90.0, 0.0
    return 0.0, 0.0


def station_path(network: str, station: str, start: str, project_id: int) -> str:
    return f"sta:{project_id}:{network}.{station}#{start}"


def empty_inventory(network: str, *, operator: str | None = None) -> str:
    created = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    root = el("FDSNStationXML", schemaVersion="1.2")
    root.append(el("Source", "PDCC"))
    root.append(el("Created", created))
    net = el("Network", code=network)
    if operator:
        net.append(el("Description", operator))
        op = el("Operator")
        op.append(el("Agency", operator))
        net.append(op)
    root.append(net)
    return dumps(root)


def _network(root: etree._Element, code: str) -> etree._Element:
    for net in root.findall(qname("Network")):
        if net.get("code") == code:
            return net
    raise InventoryError(f"네트워크 {code}가 없습니다", 404)


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except ValueError as exc:
        raise InventoryError("시각 형식이 올바르지 않습니다", 400, "E_TIME") from exc


def _overlaps(a_start: str, a_end: str | None, b_start: str, b_end: str | None) -> bool:
    start_a = _parse_time(a_start)
    start_b = _parse_time(b_start)
    if start_a is None or start_b is None:
        return False
    end_a = _parse_time(a_end) if a_end else datetime.max.replace(tzinfo=start_a.tzinfo)
    end_b = _parse_time(b_end) if b_end else datetime.max.replace(tzinfo=start_b.tzinfo)
    if end_a.tzinfo is None and start_a.tzinfo is not None:
        end_a = end_a.replace(tzinfo=start_a.tzinfo)
    if end_b.tzinfo is None and start_b.tzinfo is not None:
        end_b = end_b.replace(tzinfo=start_b.tzinfo)
    return start_a < end_b and start_b < end_a


def add_station(
    xml: str,
    *,
    network: str,
    station: str,
    site_name: str,
    start: str,
    latitude: float,
    longitude: float,
    elevation: float,
    depth: float,
    channels: list[str],
    location: str = "00",
    sample_rate: float = 20.0,
    end: str | None = None,
    operator: str | None = None,
    response_el: etree._Element | None = None,
    comments: list[str] | None = None,
    sensor_desc: str | None = None,
    datalogger_desc: str | None = None,
) -> str:
    if not STATION_CODE_RE.match(station):
        raise InventoryError("관측소 코드는 1–5자의 영문·숫자여야 합니다", 400, "E_CODE_STA")
    if latitude < -90 or latitude > 90:
        raise InventoryError("위도는 -90 ~ 90 이어야 합니다", 400, "E_LAT")
    if longitude < -180 or longitude > 180:
        raise InventoryError("경도는 -180 ~ 180 이어야 합니다", 400, "E_LON")
    if end:
        start_t = _parse_time(start)
        end_t = _parse_time(end)
        if start_t and end_t and end_t <= start_t:
            raise InventoryError("종료가 시작보다 앞섭니다", 400, "E_TIME_ORDER")
    if not channels:
        raise InventoryError("채널이 필요합니다", 400, "E_REQ")
    for code in channels:
        if not CHANNEL_CODE_RE.match(code):
            raise InventoryError("채널 코드는 3자여야 합니다", 400, "E_CODE_CHA")

    root = parse_root(xml)
    net = _network(root, network)
    for existing in net.findall(qname("Station")):
        if existing.get("code") != station:
            continue
        if _overlaps(existing.get("startDate", ""), existing.get("endDate"), start, end):
            raise InventoryError("같은 관측소의 기간이 겹칩니다", 400, "E_EPOCH_OVERLAP")

    sta_attrs = {"code": station, "startDate": start}
    if end:
        sta_attrs["endDate"] = end
    sta = el("Station", **sta_attrs)
    sta.append(el("Latitude", str(latitude)))
    sta.append(el("Longitude", str(longitude)))
    sta.append(el("Elevation", str(elevation)))
    site = el("Site")
    site.append(el("Name", site_name))
    sta.append(site)
    if operator:
        op = el("Operator")
        op.append(el("Agency", operator))
        sta.append(op)

    loc = location if location is not None else "00"
    for code in channels:
        azimuth, dip = orientation(code)
        cha_attrs = {"code": code, "locationCode": loc, "startDate": start}
        if end:
            cha_attrs["endDate"] = end
        cha = el("Channel", **cha_attrs)
        cha.append(el("Latitude", str(latitude)))
        cha.append(el("Longitude", str(longitude)))
        cha.append(el("Elevation", str(elevation)))
        cha.append(el("Depth", str(depth)))
        cha.append(el("Azimuth", str(azimuth)))
        cha.append(el("Dip", str(dip)))
        cha.append(el("SampleRate", str(sample_rate)))
        if sensor_desc:
            sensor = el("Sensor")
            sensor.append(el("Description", sensor_desc))
            cha.append(sensor)
        if datalogger_desc:
            logger = el("DataLogger")
            logger.append(el("Description", datalogger_desc))
            cha.append(logger)
        for comment in comments or []:
            node = el("Comment")
            node.append(el("Value", comment))
            cha.append(node)
        if response_el is not None:
            cha.append(namespaced_copy(response_el))
        sta.append(cha)
    net.append(sta)
    return dumps(root)


def iter_stations(xml: str, network: str | None = None) -> list[etree._Element]:
    root = parse_root(xml)
    stations: list[etree._Element] = []
    for net in root.findall(qname("Network")):
        if network and net.get("code") != network:
            continue
        stations.extend(net.findall(qname("Station")))
    return stations


def find_channel(
    xml: str,
    *,
    network: str,
    station: str,
    location: str,
    channel: str,
    start: str | None = None,
) -> etree._Element:
    root = parse_root(xml)
    net = _network(root, network)
    for sta in net.findall(qname("Station")):
        if sta.get("code") != station:
            continue
        if start and sta.get("startDate") != start:
            continue
        for cha in sta.findall(qname("Channel")):
            if cha.get("code") == channel and (cha.get("locationCode") or "") == location:
                return cha
    raise InventoryError("채널을 찾을 수 없습니다", 404)


def list_inventory(xml: str, network: str, project_id: int) -> list[dict]:
    stations: list[dict] = []
    for sta in iter_stations(xml, network):
        channels = []
        for cha in sta.findall(qname("Channel")):
            loc = cha.get("locationCode") or ""
            has_response = cha.find(qname("Response")) is not None
            channels.append(
                {
                    "location": loc,
                    "code": cha.get("code"),
                    "start": cha.get("startDate"),
                    "end": cha.get("endDate"),
                    "latitude": _float(child_text(cha, "Latitude")),
                    "longitude": _float(child_text(cha, "Longitude")),
                    "elevation": _float(child_text(cha, "Elevation")),
                    "depth": _float(child_text(cha, "Depth")),
                    "azimuth": _float(child_text(cha, "Azimuth")),
                    "dip": _float(child_text(cha, "Dip")),
                    "sample_rate": _float(child_text(cha, "SampleRate")),
                    "has_response": has_response,
                    "nslc": f"{loc}.{cha.get('code')}" if loc else cha.get("code"),
                }
            )
        stations.append(
            {
                "code": sta.get("code"),
                "start": sta.get("startDate"),
                "end": sta.get("endDate"),
                "site_name": _site_name(sta),
                "latitude": _float(child_text(sta, "Latitude")),
                "longitude": _float(child_text(sta, "Longitude")),
                "elevation": _float(child_text(sta, "Elevation")),
                "station_path": station_path(
                    network, sta.get("code") or "", sta.get("startDate") or "", project_id
                ),
                "channels": channels,
            }
        )
    return stations


def _set_end_date(node: etree._Element, end: str | None) -> None:
    if end:
        node.set("endDate", end)
    elif "endDate" in node.attrib:
        del node.attrib["endDate"]


def update_station(
    xml: str,
    *,
    network: str,
    station: str,
    start: str,
    latitude: float | None = None,
    longitude: float | None = None,
    elevation: float | None = None,
    site_name: str | None = None,
    end: str | None = None,
    set_end: bool = False,
    propagate: bool = True,
) -> str:
    if latitude is not None and (latitude < -90 or latitude > 90):
        raise InventoryError("위도는 -90 ~ 90 이어야 합니다", 400, "E_LAT")
    if longitude is not None and (longitude < -180 or longitude > 180):
        raise InventoryError("경도는 -180 ~ 180 이어야 합니다", 400, "E_LON")
    if set_end and end:
        start_t = _parse_time(start)
        end_t = _parse_time(end)
        if start_t and end_t and end_t <= start_t:
            raise InventoryError("종료가 시작보다 앞섭니다", 400, "E_TIME_ORDER")
    root = parse_root(xml)
    net = _network(root, network)
    target = None
    for sta in net.findall(qname("Station")):
        if sta.get("code") == station and (not start or sta.get("startDate") == start):
            target = sta
            break
    if target is None:
        raise InventoryError("관측소를 찾을 수 없습니다", 404)
    if set_end:
        _set_end_date(target, end)
        others = [
            sta
            for sta in net.findall(qname("Station"))
            if sta is not target and sta.get("code") == station
        ]
        for other in others:
            if _overlaps(start, end, other.get("startDate", ""), other.get("endDate")):
                raise InventoryError("같은 관측소의 기간이 겹칩니다", 400, "E_EPOCH_OVERLAP")
    if latitude is not None:
        set_child(target, "Latitude", str(latitude))
    if longitude is not None:
        set_child(target, "Longitude", str(longitude))
    if elevation is not None:
        set_child(target, "Elevation", str(elevation))
    if site_name is not None:
        site = target.find(qname("Site"))
        if site is None:
            site = el("Site")
            target.append(site)
        set_child(site, "Name", site_name)
    if propagate:
        for cha in target.findall(qname("Channel")):
            if latitude is not None:
                set_child(cha, "Latitude", str(latitude))
            if longitude is not None:
                set_child(cha, "Longitude", str(longitude))
            if elevation is not None:
                set_child(cha, "Elevation", str(elevation))
            if set_end:
                _set_end_date(cha, end)
    return dumps(root)


def update_channel(
    xml: str,
    *,
    network: str,
    station: str,
    start: str,
    location: str,
    channel: str,
    new_location: str | None = None,
    new_code: str | None = None,
    depth: float | None = None,
    azimuth: float | None = None,
    dip: float | None = None,
    sample_rate: float | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    elevation: float | None = None,
    end: str | None = None,
    set_end: bool = False,
) -> str:
    loc = location or ""
    code = channel.strip().upper()
    next_loc = loc if new_location is None else new_location.strip()
    next_code = code if new_code is None else new_code.strip().upper()
    if new_code is not None and not CHANNEL_CODE_RE.match(next_code):
        raise InventoryError("채널 코드는 3자여야 합니다", 400, "E_CODE_CHA")
    if new_location is not None and len(next_loc) > 2:
        raise InventoryError("location은 0–2자여야 합니다", 400, "E_CODE_LOC")
    if azimuth is not None and (azimuth < 0 or azimuth > 360):
        raise InventoryError("방위각은 0 ~ 360 이어야 합니다", 400, "E_AZIMUTH")
    if dip is not None and (dip < -90 or dip > 90):
        raise InventoryError("경사는 -90 ~ 90 이어야 합니다", 400, "E_DIP")
    if sample_rate is not None and sample_rate <= 0:
        raise InventoryError("샘플링은 0보다 커야 합니다", 400, "E_RATE")
    if depth is not None and depth < 0:
        raise InventoryError("깊이는 0 이상이어야 합니다", 400, "E_DEPTH")
    if latitude is not None and (latitude < -90 or latitude > 90):
        raise InventoryError("위도는 -90 ~ 90 이어야 합니다", 400, "E_LAT")
    if longitude is not None and (longitude < -180 or longitude > 180):
        raise InventoryError("경도는 -180 ~ 180 이어야 합니다", 400, "E_LON")
    root = parse_root(xml)
    net = _network(root, network)
    sta = None
    for node in net.findall(qname("Station")):
        if node.get("code") == station and (not start or node.get("startDate") == start):
            sta = node
            break
    if sta is None:
        raise InventoryError("관측소를 찾을 수 없습니다", 404)
    target = _find_channel_el(sta, loc, code)
    if target is None:
        raise InventoryError("채널을 찾을 수 없습니다", 404)
    if next_loc != loc or next_code != code:
        clash = _find_channel_el(sta, next_loc, next_code)
        if clash is not None and clash is not target:
            raise InventoryError("같은 채널 코드가 이미 있습니다", 400, "E_CODE_CHA")
        target.set("locationCode", next_loc)
        target.set("code", next_code)
    if depth is not None:
        set_child(target, "Depth", str(depth))
    if azimuth is not None:
        set_child(target, "Azimuth", str(azimuth))
    if dip is not None:
        set_child(target, "Dip", str(dip))
    if sample_rate is not None:
        set_child(target, "SampleRate", str(sample_rate))
    if latitude is not None:
        set_child(target, "Latitude", str(latitude))
    if longitude is not None:
        set_child(target, "Longitude", str(longitude))
    if elevation is not None:
        set_child(target, "Elevation", str(elevation))
    if set_end:
        _set_end_date(target, end)
    return dumps(root)


def validate_inventory(xml: str, network: str, project_id: int) -> list[dict]:
    issues: list[dict] = []
    root = parse_root(xml)
    try:
        net = _network(root, network)
    except InventoryError:
        return [
            {
                "code": "E_CODE_NET",
                "message": f"네트워크 {network}가 없습니다",
                "path": network,
                "field": "network",
                "station": None,
                "start": None,
                "nslc": None,
            }
        ]
    stations = list(net.findall(qname("Station")))
    for i, sta in enumerate(stations):
        code = sta.get("code") or ""
        start = sta.get("startDate") or ""
        prefix = f"{code}#{start}"
        lat = _float(child_text(sta, "Latitude"))
        lon = _float(child_text(sta, "Longitude"))
        if lat is not None and (lat < -90 or lat > 90):
            issues.append(_issue("E_LAT", "위도는 -90 ~ 90 이어야 합니다", prefix, "latitude", code, start, None))
        if lon is not None and (lon < -180 or lon > 180):
            issues.append(_issue("E_LON", "경도는 -180 ~ 180 이어야 합니다", prefix, "longitude", code, start, None))
        if start:
            end = sta.get("endDate")
            if end:
                try:
                    start_t = _parse_time(start)
                    end_t = _parse_time(end)
                except InventoryError as exc:
                    issues.append(
                        _issue(exc.code or "E_TIME", str(exc), prefix, "end", code, start, None)
                    )
                else:
                    if start_t and end_t and end_t <= start_t:
                        issues.append(
                            _issue("E_TIME_ORDER", "종료가 시작보다 앞섭니다", prefix, "end", code, start, None)
                        )
        for other in stations[i + 1 :]:
            if other.get("code") != code:
                continue
            try:
                overlap = _overlaps(start, sta.get("endDate"), other.get("startDate", ""), other.get("endDate"))
            except InventoryError:
                overlap = False
            if overlap:
                issues.append(
                    _issue(
                        "E_EPOCH_OVERLAP",
                        "같은 관측소의 기간이 겹칩니다",
                        prefix,
                        "start",
                        code,
                        start,
                        None,
                    )
                )
        channels = list(sta.findall(qname("Channel")))
        for j, cha in enumerate(channels):
            loc = cha.get("locationCode") or ""
            cha_code = cha.get("code") or ""
            nslc = f"{loc}.{cha_code}" if loc else cha_code
            cha_prefix = f"{prefix}/{nslc}"
            az = _float(child_text(cha, "Azimuth"))
            dip = _float(child_text(cha, "Dip"))
            rate = _float(child_text(cha, "SampleRate"))
            depth = _float(child_text(cha, "Depth"))
            cha_lat = _float(child_text(cha, "Latitude"))
            if az is not None and (az < 0 or az > 360):
                issues.append(_issue("E_AZIMUTH", "방위각은 0 ~ 360 이어야 합니다", cha_prefix, "azimuth", code, start, nslc))
            if dip is not None and (dip < -90 or dip > 90):
                issues.append(_issue("E_DIP", "경사는 -90 ~ 90 이어야 합니다", cha_prefix, "dip", code, start, nslc))
            if rate is not None and rate <= 0:
                issues.append(_issue("E_RATE", "샘플링은 0보다 커야 합니다", cha_prefix, "sample_rate", code, start, nslc))
            if depth is not None and depth < 0:
                issues.append(_issue("E_DEPTH", "깊이는 0 이상이어야 합니다", cha_prefix, "depth", code, start, nslc))
            if cha_lat is not None and (cha_lat < -90 or cha_lat > 90):
                issues.append(_issue("E_LAT", "위도는 -90 ~ 90 이어야 합니다", cha_prefix, "latitude", code, start, nslc))
            if cha_code and not CHANNEL_CODE_RE.match(cha_code):
                issues.append(_issue("E_CODE_CHA", "채널 코드는 3자여야 합니다", cha_prefix, "code", code, start, nslc))
            for other in channels[j + 1 :]:
                if (other.get("locationCode") or "") != loc or (other.get("code") or "") != cha_code:
                    continue
                try:
                    overlap = _overlaps(
                        cha.get("startDate") or start,
                        cha.get("endDate"),
                        other.get("startDate") or start,
                        other.get("endDate"),
                    )
                except InventoryError:
                    overlap = False
                if overlap:
                    issues.append(
                        _issue(
                            "E_EPOCH_OVERLAP",
                            "같은 채널의 기간이 겹칩니다",
                            cha_prefix,
                            "start",
                            code,
                            start,
                            nslc,
                        )
                    )
    return issues


def _issue(
    code: str,
    message: str,
    path: str,
    field: str,
    station: str | None,
    start: str | None,
    nslc: str | None,
) -> dict:
    return {
        "code": code,
        "message": message,
        "path": path,
        "field": field,
        "station": station,
        "start": start,
        "nslc": nslc,
    }


def field_snapshot(xml: str, network: str, project_id: int) -> dict[str, str]:
    out: dict[str, str] = {}
    for sta in list_inventory(xml, network, project_id):
        prefix = f"{sta['code']}#{sta['start']}"
        out[f"{prefix}/latitude"] = "" if sta["latitude"] is None else str(sta["latitude"])
        out[f"{prefix}/longitude"] = "" if sta["longitude"] is None else str(sta["longitude"])
        out[f"{prefix}/elevation"] = "" if sta["elevation"] is None else str(sta["elevation"])
        out[f"{prefix}/site_name"] = sta["site_name"] or ""
        out[f"{prefix}/end"] = sta["end"] or ""
        for cha in sta["channels"]:
            nslc = cha["nslc"]
            out[f"{prefix}/{nslc}.has_response"] = "1" if cha["has_response"] else "0"
            out[f"{prefix}/{nslc}.azimuth"] = "" if cha["azimuth"] is None else str(cha["azimuth"])
            out[f"{prefix}/{nslc}.dip"] = "" if cha["dip"] is None else str(cha["dip"])
            out[f"{prefix}/{nslc}.depth"] = "" if cha["depth"] is None else str(cha["depth"])
            out[f"{prefix}/{nslc}.sample_rate"] = (
                "" if cha["sample_rate"] is None else str(cha["sample_rate"])
            )
            out[f"{prefix}/{nslc}.location"] = cha["location"] or ""
            out[f"{prefix}/{nslc}.code"] = cha["code"] or ""
    return out


def diff_fields(left: dict[str, str], right: dict[str, str]) -> list[dict]:
    keys = sorted(set(left) | set(right))
    rows = []
    for key in keys:
        a = left.get(key, "")
        b = right.get(key, "")
        if a != b:
            rows.append({"path": key, "a": a, "b": b})
    return rows


def apply_field_choices(
    server_xml: str,
    draft_xml: str,
    *,
    network: str,
    choices: dict[str, str],
) -> str:
    root_server = parse_root(server_xml)
    root_draft = parse_root(draft_xml)
    by_choice = {path: which for path, which in choices.items() if which in {"mine", "server"}}
    for path, which in by_choice.items():
        if which != "mine":
            continue
        station, _, rest = path.partition("#")
        start, _, field = rest.partition("/")
        sta_s = _find_station_el(root_server, network, station, start)
        sta_d = _find_station_el(root_draft, network, station, start)
        if sta_s is None or sta_d is None:
            continue
        if field in {"latitude", "longitude", "elevation"}:
            tag = field[:1].upper() + field[1:]
            text = child_text(sta_d, tag)
            if text is not None:
                set_child(sta_s, tag, text)
                for cha in sta_s.findall(qname("Channel")):
                    set_child(cha, tag, text)
        elif field == "end":
            _set_end_date(sta_s, sta_d.get("endDate"))
        elif field == "site_name":
            site_d = sta_d.find(qname("Site"))
            name = child_text(site_d, "Name") if site_d is not None else None
            if name is not None:
                site_s = sta_s.find(qname("Site"))
                if site_s is None:
                    site_s = el("Site")
                    sta_s.append(site_s)
                set_child(site_s, "Name", name)
        elif "." in field:
            nslc, _, attr = field.rpartition(".")
            loc, code = _split_nslc(nslc)
            cha_s = _find_channel_el(sta_s, loc, code)
            cha_d = _find_channel_el(sta_d, loc, code)
            if cha_s is None or cha_d is None:
                continue
            if attr == "has_response":
                existing = cha_s.find(qname("Response"))
                if existing is not None:
                    cha_s.remove(existing)
                src = cha_d.find(qname("Response"))
                if src is not None:
                    cha_s.append(namespaced_copy(src))
            elif attr in {"azimuth", "dip", "depth", "sample_rate"}:
                tag = {
                    "azimuth": "Azimuth",
                    "dip": "Dip",
                    "depth": "Depth",
                    "sample_rate": "SampleRate",
                }[attr]
                text = child_text(cha_d, tag)
                if text is not None:
                    set_child(cha_s, tag, text)
            elif attr == "location":
                cha_s.set("locationCode", cha_d.get("locationCode") or "")
            elif attr == "code":
                cha_s.set("code", cha_d.get("code") or "")
    return dumps(root_server)


def _split_nslc(nslc: str) -> tuple[str, str]:
    if "." in nslc:
        loc, _, code = nslc.rpartition(".")
        return loc, code
    return "", nslc


def _find_station_el(root: etree._Element, network: str, station: str, start: str) -> etree._Element | None:
    for net in root.findall(qname("Network")):
        if net.get("code") != network:
            continue
        for sta in net.findall(qname("Station")):
            if sta.get("code") == station and sta.get("startDate") == start:
                return sta
    return None


def _find_channel_el(sta: etree._Element, location: str, code: str) -> etree._Element | None:
    for cha in sta.findall(qname("Channel")):
        if cha.get("code") == code and (cha.get("locationCode") or "") == location:
            return cha
    return None


def _site_name(sta: etree._Element) -> str | None:
    site = sta.find(qname("Site"))
    if site is None:
        return None
    return child_text(site, "Name")


def _float(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def apply_response(
    xml: str,
    *,
    network: str,
    station: str,
    start: str,
    location: str,
    channel: str,
    response_xml: bytes,
    comments: list[str],
    sample_rate: float | None,
    replace_existing: bool,
) -> str:
    root = parse_root(xml)
    net = _network(root, network)
    target = None
    for sta in net.findall(qname("Station")):
        if sta.get("code") != station:
            continue
        if sta.get("startDate") != start:
            continue
        for cha in sta.findall(qname("Channel")):
            if cha.get("code") == channel and (cha.get("locationCode") or "") == location:
                target = cha
                break
    if target is None:
        raise InventoryError("채널을 찾을 수 없습니다", 404)
    existing = target.find(qname("Response"))
    if existing is not None and not replace_existing:
        raise InventoryError("이미 응답이 있습니다", 409)
    if existing is not None:
        target.remove(existing)
    try:
        resp_root = etree.fromstring(response_xml)
    except etree.XMLSyntaxError as exc:
        raise InventoryError("StationXML-Response XML이 올바르지 않습니다") from exc
    if local(resp_root.tag) == "FDSNStationXML":
        inner = resp_root.find(f".//{qname('Response')}")
        if inner is None:
            raise InventoryError("StationXML-Response XML이 아닙니다")
        resp_root = inner
    elif local(resp_root.tag) != "Response":
        raise InventoryError("StationXML-Response XML이 아닙니다")
    target.append(namespaced_copy(resp_root))
    if sample_rate:
        set_child(target, "SampleRate", str(sample_rate))
    for comment in comments:
        node = el("Comment")
        node.append(el("Value", comment))
        target.append(node)
    return dumps(root)


def response_payload(xml: str) -> bytes | None:
    root = parse_root(xml)
    found = root.find(f".//{qname('Response')}")
    if found is None:
        return None
    return etree.tostring(found)
