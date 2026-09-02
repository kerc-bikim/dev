"""StationXML 원문에서 관측소·채널만 잘라 낸다. Inventory.write 를 쓰지 않는다."""

from __future__ import annotations

from lxml import etree

from ..inventory.xmlutil import dumps, local, parse_root

KINDS = ("resp", "dataless")
SCOPES = ("project", "station", "channel")


class SliceError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def parse_nslc(nslc: str) -> tuple[str, str]:
    text = (nslc or "").strip()
    if not text:
        raise SliceError("채널이 필요합니다")
    if "." in text:
        location, channel = text.rsplit(".", 1)
        return location, channel
    return "", text


def _time_key(value: str | None) -> str:
    if not value:
        return ""
    return value.replace("Z", "")[:19]


def slice_stationxml(
    xml: str,
    *,
    network: str | None = None,
    station: str | None = None,
    start: str | None = None,
    nslc: str | None = None,
) -> str:
    if not (xml or "").strip():
        raise SliceError("StationXML이 없습니다")
    root = parse_root(xml)
    location = channel = None
    if nslc:
        location, channel = parse_nslc(nslc)
    kept_net = 0
    for net in list(root):
        if local(net.tag) != "Network":
            continue
        if network and net.get("code") != network:
            root.remove(net)
            continue
        kept_sta = 0
        for sta in list(net):
            if local(sta.tag) != "Station":
                continue
            if station and sta.get("code") != station:
                net.remove(sta)
                continue
            if start and _time_key(sta.get("startDate")) != _time_key(start):
                net.remove(sta)
                continue
            if channel is not None:
                kept_ch = 0
                for cha in list(sta):
                    if local(cha.tag) != "Channel":
                        continue
                    loc = cha.get("locationCode") or ""
                    if loc != location or cha.get("code") != channel:
                        sta.remove(cha)
                    else:
                        kept_ch += 1
                if kept_ch == 0:
                    net.remove(sta)
                    continue
            kept_sta += 1
        if kept_sta == 0:
            root.remove(net)
        else:
            kept_net += 1
    if kept_net == 0:
        raise SliceError("내보낼 관측소·채널이 없습니다", 404)
    return dumps(root)


def channel_count(xml: str) -> int:
    root = parse_root(xml)
    return sum(1 for el in root.iter() if local(el.tag) == "Channel")


def iter_channels(xml: str) -> list[etree._Element]:
    root = parse_root(xml)
    return [el for el in root.iter() if local(el.tag) == "Channel"]
