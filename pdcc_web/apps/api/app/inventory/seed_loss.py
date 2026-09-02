"""SEED 내보내기 전 변환 손실 표 (M3-09).

70자 코멘트, 25자 FIR 이름, Identifier·Equipment·확장 필드 제거를 미리 보여 준다.
이 표를 본 뒤에만 `POST /export/seed` 가 진행된다.
"""

from __future__ import annotations

import hashlib

from lxml import etree

from .seed_convert import COMMENT_MAX, FIR_NAME_MAX
from .validator import summarize, validate_project
from .xmlutil import FDSN_NS, child_text, local, parse_root, qname

NOTICES = (
    "StationXML 확장 필드는 제거됩니다",
    "긴 설명·코멘트는 잘립니다",
    "Identifier, 일부 Equipment 상세는 매핑되지 않을 수 있습니다",
    "왕복 변환 후 XML이 바이트 단위로 같지 않을 수 있습니다",
    "SEED 2.4 네트워크 코드는 2자, 깊이는 0.1 m 단위입니다",
)

DROP_TAGS = {
    "WaterLevel": "WaterLevel은 SEED에 없어 제거됩니다",
    "Vault": "Vault는 SEED에 없어 제거됩니다",
    "Geology": "Geology는 SEED에 없어 제거됩니다",
    "DataAvailability": "DataAvailability는 SEED에 없어 제거됩니다",
    "ExternalReference": "ExternalReference는 SEED에 없어 제거됩니다",
    "SourceID": "SourceID는 SEED에 없어 제거됩니다",
}

EQUIPMENT_KEEP = {"Type", "Description"}


def _extra_decimal(value: str, places: int) -> bool:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    text = f"{number:.10f}".rstrip("0")
    if "." not in text:
        return False
    return len(text.split(".", 1)[1]) > places


def _one_decimal(value: str) -> str:
    try:
        return f"{float(value):.1f}"
    except (TypeError, ValueError):
        return value


def loss_ack_token(xml: str) -> str:
    return hashlib.sha256((xml or "").encode("utf-8")).hexdigest()[:24]


def _path(net: str, sta: str | None = None, cha: etree._Element | None = None) -> str:
    parts = [net]
    if sta:
        parts.append(sta)
    if cha is not None:
        loc = cha.get("locationCode") or ""
        code = cha.get("code") or ""
        parts.append(f"{loc}.{code}" if loc else code)
    return " / ".join(parts)


def _nslc(cha: etree._Element | None) -> str | None:
    if cha is None:
        return None
    loc = cha.get("locationCode") or ""
    code = cha.get("code") or ""
    return f"{loc}.{code}" if loc else code


def _row(
    *,
    kind: str,
    code: str,
    path: str,
    field: str,
    message: str,
    original: str = "",
    seed_value: str = "",
    limit: int | None = None,
    nslc: str | None = None,
    station: str | None = None,
) -> dict:
    return {
        "kind": kind,
        "code": code,
        "path": path,
        "field": field,
        "original": original,
        "seed_value": seed_value,
        "limit": limit,
        "message": message,
        "nslc": nslc,
        "station": station,
    }


def scan_seed_loss(xml: str) -> list[dict]:
    try:
        root = parse_root(xml)
    except etree.XMLSyntaxError:
        return []
    rows: list[dict] = []
    for net in root.findall(qname("Network")):
        net_code = net.get("code") or ""
        if len(net_code) > 2:
            rows.append(
                _row(
                    kind="error",
                    code="E_SEED_NET",
                    path=net_code,
                    field="network",
                    original=net_code,
                    message="SEED 2.4 네트워크 코드는 2자입니다. StationXML 코드를 2자로 바꾸세요",
                )
            )
        rows.extend(_scan_container(net, net_code, None, None))
        for sta in net.findall(qname("Station")):
            sta_code = sta.get("code") or ""
            rows.extend(_scan_container(sta, net_code, sta_code, None))
            for cha in sta.findall(qname("Channel")):
                rows.extend(_scan_container(cha, net_code, sta_code, cha))
                rows.extend(_scan_response(cha, net_code, sta_code))
    return rows


def seed_loss_report(xml: str, network: str, project_id: int) -> dict:
    rows = scan_seed_loss(xml)
    issues = validate_project(xml, network, project_id, mode="full")
    summary = summarize(issues, xml_source="project", mode="full", network=network)
    seed_errors = [row for row in rows if row["kind"] == "error"]
    return {
        "notices": list(NOTICES),
        "rows": rows,
        "trunc_count": sum(1 for row in rows if row["kind"] == "truncate"),
        "drop_count": sum(1 for row in rows if row["kind"] == "drop"),
        "ack": loss_ack_token(xml),
        "can_export_seed": summary["can_export_seed"] and not seed_errors,
        "error_count": summary["error_count"],
        "filename": summary["filename"],
        "comment_max": COMMENT_MAX,
        "fir_name_max": FIR_NAME_MAX,
    }


def _scan_container(
    node: etree._Element,
    net: str,
    sta: str | None,
    cha: etree._Element | None,
) -> list[dict]:
    rows: list[dict] = []
    path = _path(net, sta, cha)
    nslc = _nslc(cha)
    if local(node.tag) == "Station":
        site = node.find(qname("Site"))
        name = child_text(site, "Name") if site is not None else ""
        if name and any(ord(ch) >= 128 for ch in name):
            rows.append(
                _row(
                    kind="drop",
                    code="W_SEED_SITE",
                    path=path,
                    field="site",
                    original=name,
                    seed_value=sta or "",
                    message="한글 사이트명은 SEED에 넣을 수 없어 관측소 코드로 대체됩니다",
                    station=sta,
                )
            )
    if local(node.tag) == "Channel":
        depth = child_text(node, "Depth") or ""
        if _extra_decimal(depth, 1):
            rows.append(
                _row(
                    kind="truncate",
                    code="W_SEED_PREC",
                    path=path,
                    field="depth",
                    original=depth,
                    seed_value=_one_decimal(depth),
                    limit=1,
                    message="SEED 2.4 깊이는 0.1 m 단위입니다",
                    nslc=nslc,
                    station=sta,
                )
            )
    for comment in node.findall(qname("Comment")):
        value = child_text(comment, "Value") or ""
        if len(value) > COMMENT_MAX:
            rows.append(
                _row(
                    kind="truncate",
                    code="W_SEED_TRUNC",
                    path=path,
                    field="comment",
                    original=value,
                    seed_value=value[:COMMENT_MAX],
                    limit=COMMENT_MAX,
                    message=f"코멘트가 {COMMENT_MAX}자로 잘립니다",
                    nslc=nslc,
                    station=sta,
                )
            )
    for ident in node.findall(qname("Identifier")):
        text = (ident.text or "").strip()
        itype = ident.get("type") or "Identifier"
        rows.append(
            _row(
                kind="drop",
                code="W_SEED_DROP",
                path=path,
                field="identifier",
                original=f"{itype}: {text}" if text else itype,
                message="Identifier는 SEED에 매핑되지 않아 제거됩니다",
                nslc=nslc,
                station=sta,
            )
        )
    for tag, message in DROP_TAGS.items():
        for found in node.findall(qname(tag)):
            text = (found.text or "").strip() or tag
            rows.append(
                _row(
                    kind="drop",
                    code="W_SEED_DROP",
                    path=path,
                    field=tag.lower(),
                    original=text,
                    message=message,
                    nslc=nslc,
                    station=sta,
                )
            )
    source_id = node.get("sourceID")
    if source_id:
        rows.append(
            _row(
                kind="drop",
                code="W_SEED_DROP",
                path=path,
                field="sourceid",
                original=source_id,
                message="SourceID는 SEED에 없어 제거됩니다",
                nslc=nslc,
                station=sta,
            )
        )
    for eq in node.findall(qname("Equipment")):
        for child in eq:
            ctag = local(child.tag)
            if ctag in EQUIPMENT_KEEP:
                continue
            text = (child.text or "").strip() or ctag
            rows.append(
                _row(
                    kind="drop",
                    code="W_SEED_DROP",
                    path=path,
                    field="equipment",
                    original=f"{ctag}: {text}",
                    message="Equipment 상세는 SEED에 매핑되지 않을 수 있습니다",
                    nslc=nslc,
                    station=sta,
                )
            )
    for child in node:
        tag = child.tag
        if not isinstance(tag, str) or not tag.startswith("{"):
            continue
        ns = tag[1:].split("}", 1)[0]
        if ns == FDSN_NS:
            continue
        rows.append(
            _row(
                kind="drop",
                code="W_SEED_DROP",
                path=path,
                field="extension",
                original=local(tag),
                message="StationXML 확장 필드는 제거됩니다",
                nslc=nslc,
                station=sta,
            )
        )
    return rows


def _scan_response(cha: etree._Element, net: str, sta: str) -> list[dict]:
    rows: list[dict] = []
    path = _path(net, sta, cha)
    nslc = _nslc(cha)
    resp = cha.find(qname("Response"))
    if resp is None:
        return rows
    for stage in resp.findall(qname("Stage")):
        coef = stage.find(qname("Coefficients"))
        fir = stage.find(qname("FIR"))
        digital = False
        if coef is not None:
            kind = (child_text(coef, "CfTransferFunctionType") or "").upper()
            digital = "DIGITAL" in kind or kind == "D"
        if fir is not None:
            digital = True
        if digital and stage.find(qname("Decimation")) is None:
            rows.append(
                _row(
                    kind="error",
                    code="E_SEED_DECIM",
                    path=path,
                    field="decimation",
                    original=stage.get("number") or "",
                    message="SEED 2.4 디지털 단계에는 데시메이션이 필요합니다",
                    nslc=nslc,
                    station=sta,
                )
            )
    names: list[str] = []
    for fir in resp.findall(f".//{qname('FIR')}"):
        names.append(child_text(fir, "Name") or fir.get("name") or "")
    for coef in resp.findall(f".//{qname('Coefficients')}"):
        names.append(child_text(coef, "Name") or coef.get("name") or "")
    seen: set[str] = set()
    for name in names:
        if not name or len(name) <= FIR_NAME_MAX or name in seen:
            continue
        seen.add(name)
        rows.append(
            _row(
                kind="truncate",
                code="W_SEED_FIR",
                path=path,
                field="fir",
                original=name,
                seed_value=name[:FIR_NAME_MAX],
                limit=FIR_NAME_MAX,
                message=f"FIR 이름이 {FIR_NAME_MAX}자로 잘립니다",
                nslc=nslc,
                station=sta,
            )
        )
    return rows
