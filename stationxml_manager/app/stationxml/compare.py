"""화이트리스트 필드를 추출하고 의미 동등을 비교한다."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable

from lxml import etree

from .whitelist import (
    BASE_NODE_ATTRS,
    CHANNEL_EQUIPMENT_TAGS,
    CHANNEL_GEO_FIELDS,
    CHANNEL_SCALAR_FIELDS,
    CHANNEL_TEXT_FIELDS,
    DECIMAL_REL_TOL,
    DOCUMENT_TEXT_FIELDS,
    EQUIPMENT_TEXT_FIELDS,
    FDSN_NS,
    NSMAP,
    SITE_TEXT_FIELDS,
    STATION_GEO_FIELDS,
    STATION_TEXT_FIELDS,
    UNCERTAIN_DOUBLE_ATTRS,
    fqn,
)


@dataclass(frozen=True)
class WhitelistDiff:
    path: str
    before: Any
    after: Any


def _normalize_time(value: str | None) -> str | None:
    """초 소수부가 0이면 생략해 ObsPy 의 .000000Z 와 원문 Z 를 같게 본다."""
    if not value:
        return None
    raw = value.strip()
    candidate = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return raw
    if parsed.tzinfo is not None:
        parsed = parsed.replace(tzinfo=None)
    if parsed.microsecond:
        return parsed.strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"
    return parsed.strftime("%Y-%m-%dT%H:%M:%SZ")


def _text(el: etree._Element | None) -> str | None:
    if el is None or el.text is None:
        return None
    text = el.text.strip()
    return text if text else None


def _child(el: etree._Element, tag: str) -> etree._Element | None:
    found = el.find(f"fsx:{tag}", NSMAP)
    if found is None:
        found = el.find(fqn(tag))
    return found


def _children(el: etree._Element, tag: str) -> list[etree._Element]:
    found = el.findall(f"fsx:{tag}", NSMAP)
    if found:
        return list(found)
    return list(el.findall(fqn(tag)))


def _attrs(el: etree._Element, names: Iterable[str]) -> dict[str, str | None]:
    return {name: el.get(name) for name in names}


def _uncertain_double(el: etree._Element | None) -> dict[str, str | None] | None:
    if el is None:
        return None
    return {"value": _text(el), **_attrs(el, UNCERTAIN_DOUBLE_ATTRS)}


def _c14n(el: etree._Element) -> str:
    return etree.tostring(el, method="c14n").decode("utf-8")


def _foreign_children(el: etree._Element) -> list[str]:
    """FDSN 네임스페이스가 아닌 자식의 C14N (커스텀 extra)."""
    out: list[str] = []
    for child in el:
        ns = etree.QName(child).namespace
        if ns == FDSN_NS:
            continue
        out.append(_c14n(child))
    return out


def _comment(el: etree._Element) -> dict[str, Any]:
    return {
        "id": el.get("id"),
        "subject": el.get("subject"),
        "value": _text(_child(el, "Value")),
        "beginEffectiveTime": _text(_child(el, "BeginEffectiveTime")),
        "endEffectiveTime": _text(_child(el, "EndEffectiveTime")),
    }


def _identifier(el: etree._Element) -> dict[str, str | None]:
    return {"type": el.get("type"), "value": _text(el)}


def _operator(el: etree._Element) -> dict[str, Any]:
    agencies = [_text(a) for a in _children(el, "Agency")]
    return {
        "agencies": [a for a in agencies if a is not None],
        "website": _text(_child(el, "WebSite")),
    }


def _equipment(el: etree._Element) -> dict[str, Any]:
    body = {tag: _text(_child(el, tag)) for tag in EQUIPMENT_TEXT_FIELDS}
    body["extra"] = _foreign_children(el)
    return body


def _base_node(el: etree._Element) -> dict[str, Any]:
    data: dict[str, Any] = _attrs(el, BASE_NODE_ATTRS)
    data["startDate"] = _normalize_time(data.get("startDate"))
    data["endDate"] = _normalize_time(data.get("endDate"))
    data["Description"] = _text(_child(el, "Description"))
    data["Identifier"] = [_identifier(x) for x in _children(el, "Identifier")]
    data["Comment"] = [_comment(x) for x in _children(el, "Comment")]
    data["Operator"] = [_operator(x) for x in _children(el, "Operator")]
    return data


def _site(el: etree._Element | None) -> dict[str, str | None] | None:
    if el is None:
        return None
    return {tag: _text(_child(el, tag)) for tag in SITE_TEXT_FIELDS}


def _channel(el: etree._Element) -> dict[str, Any]:
    data = _base_node(el)
    data["locationCode"] = el.get("locationCode")
    for tag in CHANNEL_TEXT_FIELDS:
        data[tag] = _text(_child(el, tag))
    for tag in CHANNEL_GEO_FIELDS:
        data[tag] = _uncertain_double(_child(el, tag))
    for tag in CHANNEL_SCALAR_FIELDS:
        data[tag] = _uncertain_double(_child(el, tag))
    data["Type"] = [_text(t) for t in _children(el, "Type")]
    ratio = _child(el, "SampleRateRatio")
    if ratio is not None:
        data["SampleRateRatio"] = {
            "NumberSamples": _text(_child(ratio, "NumberSamples")),
            "NumberSeconds": _text(_child(ratio, "NumberSeconds")),
        }
    cal = _child(el, "CalibrationUnits")
    if cal is not None:
        data["CalibrationUnits"] = {
            "Name": _text(_child(cal, "Name")),
            "Description": _text(_child(cal, "Description")),
        }
    for tag in CHANNEL_EQUIPMENT_TAGS:
        kids = _children(el, tag)
        if kids:
            data[tag] = [_equipment(k) for k in kids]
    response = _child(el, "Response")
    data["Response"] = _c14n(response) if response is not None else None
    data["extra"] = _foreign_children(el)
    return data


def _station(el: etree._Element) -> dict[str, Any]:
    data = _base_node(el)
    for tag in STATION_TEXT_FIELDS:
        if tag == "Description":
            continue
        value = _text(_child(el, tag))
        if tag in {"CreationDate", "TerminationDate"}:
            value = _normalize_time(value)
        data[tag] = value
    for tag in STATION_GEO_FIELDS:
        data[tag] = _uncertain_double(_child(el, tag))
    site = _child(el, "Site")
    data["Site"] = _site(site)
    data["Equipment"] = [_equipment(x) for x in _children(el, "Equipment")]
    data["ExternalReference"] = [
        {
            "URI": _text(_child(x, "URI")),
            "Description": _text(_child(x, "Description")),
        }
        for x in _children(el, "ExternalReference")
    ]
    data["channels"] = {}
    for cha in _children(el, "Channel"):
        loc = cha.get("locationCode") or ""
        code = cha.get("code") or ""
        start = _normalize_time(cha.get("startDate")) or ""
        data["channels"][f"{loc}.{code}#{start}"] = _channel(cha)
    data["extra"] = _foreign_children(el)
    return data


def _network(el: etree._Element) -> dict[str, Any]:
    data = _base_node(el)
    data["stations"] = {}
    for sta in _children(el, "Station"):
        code = sta.get("code") or ""
        start = _normalize_time(sta.get("startDate")) or ""
        data["stations"][f"{code}#{start}"] = _station(sta)
    data["extra"] = _foreign_children(el)
    return data


def _xml_comments_from_tree(xml_bytes: bytes) -> list[str]:
    parser = etree.XMLParser(remove_comments=False, remove_blank_text=False)
    root = etree.fromstring(xml_bytes, parser)
    out: list[str] = []
    for node in root.xpath("//comment()"):
        text = (node.text or "").strip()
        if text:
            out.append(text)
    return out


def extract_whitelist(xml: str | bytes) -> dict[str, Any]:
    """원문 XML에서 화이트리스트 스냅샷을 만든다."""
    xml_bytes = xml.encode("utf-8") if isinstance(xml, str) else xml
    parser = etree.XMLParser(remove_comments=False, remove_blank_text=False)
    root = etree.fromstring(xml_bytes, parser)
    if etree.QName(root).localname != "FDSNStationXML":
        raise ValueError("루트가 FDSNStationXML 이 아닙니다")
    doc: dict[str, Any] = {
        "schemaVersion": root.get("schemaVersion"),
        "xml_comments": _xml_comments_from_tree(xml_bytes),
    }
    for tag in DOCUMENT_TEXT_FIELDS:
        el = root.find(f"fsx:{tag}", NSMAP)
        if el is None:
            el = root.find(fqn(tag))
        doc[tag] = _text(el)
        if tag in {"Created"}:
            doc[tag] = _normalize_time(doc[tag])
    doc["networks"] = {}
    for net in root.findall("fsx:Network", NSMAP):
        code = net.get("code") or ""
        start = _normalize_time(net.get("startDate")) or ""
        doc["networks"][f"{code}#{start}"] = _network(net)
    return doc


def _as_decimal(value: str | None) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(value)
    except InvalidOperation:
        return None


def values_equal(before: Any, after: Any) -> bool:
    """문자열 숫자는 상대 오차 DECIMAL_REL_TOL 로 비교한다."""
    if before == after:
        return True
    if isinstance(before, dict) and isinstance(after, dict):
        if set(before) != set(after):
            return False
        return all(values_equal(before[k], after[k]) for k in before)
    if isinstance(before, list) and isinstance(after, list):
        if len(before) != len(after):
            return False
        return all(values_equal(a, b) for a, b in zip(before, after))
    if before is None or after is None:
        return False
    da = _as_decimal(str(before))
    db = _as_decimal(str(after))
    if da is None or db is None:
        return False
    if da == db:
        return True
    scale = max(abs(da), abs(db))
    if scale == 0:
        return True
    return abs(da - db) <= Decimal(str(DECIMAL_REL_TOL)) * scale


def _walk_diffs(path: str, before: Any, after: Any, acc: list[WhitelistDiff]) -> None:
    if isinstance(before, dict) and isinstance(after, dict):
        for key in sorted(set(before) | set(after)):
            child = f"{path}/{key}" if path else key
            _walk_diffs(child, before.get(key), after.get(key), acc)
        return
    if isinstance(before, list) and isinstance(after, list):
        n = max(len(before), len(after))
        for i in range(n):
            b = before[i] if i < len(before) else None
            a = after[i] if i < len(after) else None
            _walk_diffs(f"{path}[{i}]", b, a, acc)
        return
    if not values_equal(before, after):
        acc.append(WhitelistDiff(path=path, before=before, after=after))


def diff_whitelist(
    before_xml: str | bytes,
    after_xml: str | bytes,
    *,
    ignore: Iterable[str] = (),
) -> list[WhitelistDiff]:
    """화이트리스트 차이를 경로 목록으로 돌려준다."""
    ignore_set = set(ignore)
    acc: list[WhitelistDiff] = []
    _walk_diffs("", extract_whitelist(before_xml), extract_whitelist(after_xml), acc)
    if not ignore_set:
        return acc
    filtered: list[WhitelistDiff] = []
    for diff in acc:
        parts = diff.path.replace("[", "/").replace("]", "").split("/")
        if any(token in parts for token in ignore_set):
            continue
        filtered.append(diff)
    return filtered
