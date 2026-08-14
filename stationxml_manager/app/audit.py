from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from .models import AuditLog, Channel, Network, Station


def nslc_of(channel: Channel) -> str:
    sta = channel.station
    net = sta.network.code if sta is not None else "?"
    loc = channel.location or "--"
    return f"{net}.{sta.code}.{loc}.{channel.channel}"


def to_dict(obj: Network | Station | Channel | dict[str, Any]) -> dict[str, Any]:
    if isinstance(obj, dict):
        return obj
    if isinstance(obj, Network):
        return {
            "id": obj.id,
            "code": obj.code,
            "description": obj.description,
            "operator_agency": obj.operator_agency,
            "restricted_status": obj.restricted_status,
        }
    if isinstance(obj, Station):
        return {
            "id": obj.id,
            "network_id": obj.network_id,
            "network_code": obj.network.code if obj.network else None,
            "code": obj.code,
            "latitude": obj.latitude,
            "longitude": obj.longitude,
            "elevation": obj.elevation,
            "site_name": obj.site_name,
            "site_description": obj.site_description,
            "site_town": obj.site_town,
            "site_region": obj.site_region,
            "site_country": obj.site_country,
            "vault": obj.vault,
            "geology": obj.geology,
            "description": obj.description,
            "creation_date": obj.creation_date,
            "termination_date": obj.termination_date,
        }
    skip_response = {c.key for c in Channel.__table__.columns} - {"response_xml"}
    data = {k: getattr(obj, k) for k in skip_response}
    data["has_response"] = bool(obj.response_xml)
    data["response_source"] = obj.response_source
    if obj.station is not None:
        data["network_code"] = obj.station.network.code
        data["station_code"] = obj.station.code
        data["site_name"] = obj.station.site_name
        data["nslc"] = nslc_of(obj)
    return data


def diff_summary(before: dict[str, Any] | None, after: dict[str, Any] | None) -> str:
    before = before or {}
    after = after or {}
    keys = sorted(set(before) | set(after) - {"id", "has_response", "response_xml"})
    parts: list[str] = []
    for key in keys:
        old = before.get(key)
        new = after.get(key)
        if old != new:
            parts.append(f"{key} {old!s} → {new!s}")
    return ", ".join(parts) if parts else "변경 없음"


def write_audit(
    session: Session,
    *,
    action: str,
    entity_type: str,
    entity_id: int | None,
    source: str,
    actor: str | None,
    nslc: str | None,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    summary: str | None = None,
) -> AuditLog:
    log = AuditLog(
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        source=source,
        actor=actor or None,
        nslc=nslc,
        before_json=json.dumps(before, ensure_ascii=False, default=str) if before else None,
        after_json=json.dumps(after, ensure_ascii=False, default=str) if after else None,
        summary=summary or diff_summary(before, after),
    )
    session.add(log)
    return log
