"""DB CRUD, import upsert, NRL 적용."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session, joinedload

from .audit import nslc_of, to_dict, write_audit
from .catalog import assert_equipment_ids, catalog_in_use, catalog_map, get_by_code
from .errors import AppError, ValidationError
from .inventory import build_inventory, dump_response_xml, inventory_to_bytes
from .models import Channel, EquipmentCatalog, Network, Station
from .validation import (
    infer_az_dip,
    parse_float,
    parse_time,
    sample_rates_match,
    validate_lat_lon,
    validate_sample_rate,
    validate_time_order,
)


def list_networks(session: Session) -> list[Network]:
    return session.query(Network).order_by(Network.code).all()


def get_network(session: Session, network_id: int) -> Network:
    net = session.query(Network).get(network_id)
    if net is None:
        raise AppError("네트워크를 찾을 수 없습니다", 404)
    return net


def update_network(session: Session, network_id: int, payload: dict[str, Any], actor: str | None, source: str = "ui") -> Network:
    net = get_network(session, network_id)
    before = to_dict(net)
    for key in ("code", "description", "operator_agency", "restricted_status"):
        if key in payload:
            setattr(net, key, payload[key] if payload[key] not in ("",) else None)
    session.flush()
    write_audit(
        session,
        action="update",
        entity_type="network",
        entity_id=net.id,
        source=source,
        actor=actor,
        nslc=net.code,
        before=before,
        after=to_dict(net),
    )
    session.commit()
    session.refresh(net)
    return net


def list_stations(session: Session, network_id: int | None = None) -> list[Station]:
    q = session.query(Station).options(joinedload(Station.network)).order_by(Station.code)
    if network_id is not None:
        q = q.filter(Station.network_id == network_id)
    return q.all()


def get_station(session: Session, station_id: int) -> Station:
    sta = session.query(Station).get(station_id)
    if sta is None:
        raise AppError("관측소를 찾을 수 없습니다", 404)
    return sta


def create_station(session: Session, payload: dict[str, Any], actor: str | None) -> Station:
    net = _require_network(session, payload)
    sta = Station(network_id=net.id, **_station_fields(payload))
    session.add(sta)
    session.flush()
    write_audit(
        session,
        action="create",
        entity_type="station",
        entity_id=sta.id,
        source="ui",
        actor=actor,
        nslc=f"{net.code}.{sta.code}",
        before=None,
        after=to_dict(sta),
    )
    session.commit()
    session.refresh(sta)
    return sta


def update_station(session: Session, station_id: int, payload: dict[str, Any], actor: str | None, source: str = "ui") -> Station:
    sta = get_station(session, station_id)
    before = to_dict(sta)
    fields = _station_fields(payload, partial=True)
    for key, value in fields.items():
        setattr(sta, key, value)
    session.flush()
    write_audit(
        session,
        action="update",
        entity_type="station",
        entity_id=sta.id,
        source=source,
        actor=actor,
        nslc=f"{sta.network.code}.{sta.code}",
        before=before,
        after=to_dict(sta),
    )
    session.commit()
    session.refresh(sta)
    return sta


def delete_station(session: Session, station_id: int, actor: str | None) -> None:
    sta = get_station(session, station_id)
    before = to_dict(sta)
    nslc = f"{sta.network.code}.{sta.code}"
    session.delete(sta)
    write_audit(
        session,
        action="delete",
        entity_type="station",
        entity_id=station_id,
        source="ui",
        actor=actor,
        nslc=nslc,
        before=before,
        after=None,
    )
    session.commit()


def list_channels(
    session: Session,
    network: str | None = None,
    station: str | None = None,
    channel: str | None = None,
) -> list[Channel]:
    q = (
        session.query(Channel)
        .join(Station)
        .join(Network)
        .options(joinedload(Channel.station).joinedload(Station.network))
        .order_by(Network.code, Station.code, Channel.location, Channel.channel, Channel.start_time)
    )
    if network:
        q = q.filter(Network.code == network)
    if station:
        q = q.filter(Station.code == station)
    if channel:
        q = q.filter(Channel.channel == channel)
    return q.all()


def get_channel(session: Session, channel_id: int) -> Channel:
    ch = session.query(Channel).get(channel_id)
    if ch is None:
        raise AppError("채널을 찾을 수 없습니다", 404)
    return ch


def create_channel(session: Session, payload: dict[str, Any], actor: str | None) -> Channel:
    sta = _require_station(session, payload)
    fields = _channel_fields(session, payload, sta)
    ch = Channel(station_id=sta.id, **fields)
    session.add(ch)
    session.flush()
    write_audit(
        session,
        action="create",
        entity_type="channel",
        entity_id=ch.id,
        source="ui",
        actor=actor,
        nslc=nslc_of(ch),
        before=None,
        after=to_dict(ch),
    )
    session.commit()
    session.refresh(ch)
    return ch


def update_channel(session: Session, channel_id: int, payload: dict[str, Any], actor: str | None) -> Channel:
    ch = get_channel(session, channel_id)
    before = to_dict(ch)
    fields = _channel_fields(session, payload, ch.station, partial=True, existing=ch)
    for key, value in fields.items():
        setattr(ch, key, value)
    session.flush()
    write_audit(
        session,
        action="update",
        entity_type="channel",
        entity_id=ch.id,
        source="ui",
        actor=actor,
        nslc=nslc_of(ch),
        before=before,
        after=to_dict(ch),
    )
    session.commit()
    session.refresh(ch)
    return ch


def delete_channel(session: Session, channel_id: int, actor: str | None) -> None:
    ch = get_channel(session, channel_id)
    before = to_dict(ch)
    nslc = nslc_of(ch)
    session.delete(ch)
    write_audit(
        session,
        action="delete",
        entity_type="channel",
        entity_id=channel_id,
        source="ui",
        actor=actor,
        nslc=nslc,
        before=before,
        after=None,
    )
    session.commit()


def import_hierarchy(
    session: Session,
    hierarchy: dict[str, Any],
    *,
    replace_all: bool,
    source: str,
    actor: str | None,
) -> dict[str, Any]:
    warnings: list[str] = list(hierarchy.get("warnings") or [])
    _upsert_catalog(session, hierarchy.get("catalog") or {}, actor)

    if replace_all:
        for ch in session.query(Channel).all():
            write_audit(
                session,
                action="delete",
                entity_type="channel",
                entity_id=ch.id,
                source=source,
                actor=actor,
                nslc=nslc_of(ch),
                before=to_dict(ch),
                after=None,
                summary="전체 교체 import",
            )
        session.query(Channel).delete()
        session.query(Station).delete()
        session.query(Network).delete()
        session.flush()

    created = updated = 0
    for net_data in hierarchy["networks"].values():
        net = (
            session.query(Network).filter_by(code=net_data["code"]).one_or_none()
            or Network(code=net_data["code"])
        )
        net.description = net_data.get("description")
        net.operator_agency = net_data.get("operator_agency")
        net.restricted_status = net_data.get("restricted_status")
        session.add(net)
        session.flush()
        for sta_data in net_data["stations"].values():
            if sta_data.get("elevation_warning"):
                warnings.append(
                    f"{net_data['code']}.{sta_data['code']}: 고도가 0입니다. 실제 고도를 확인하세요"
                )
            sta = (
                session.query(Station)
                .filter_by(network_id=net.id, code=sta_data["code"])
                .one_or_none()
            )
            if sta is None:
                sta = Station(network_id=net.id, code=sta_data["code"])
            for key in (
                "latitude",
                "longitude",
                "elevation",
                "site_name",
                "site_description",
                "site_town",
                "site_region",
                "site_country",
                "vault",
                "geology",
                "description",
                "creation_date",
                "termination_date",
            ):
                if key in sta_data:
                    setattr(sta, key, sta_data[key])
            session.add(sta)
            session.flush()
            for ch_data in sta_data["channels"]:
                assert_equipment_ids(
                    session,
                    ch_data.get("sensor_id"),
                    ch_data.get("datalogger_id"),
                    ch_data["sample_rate"],
                    ch_data.get("_excel_row"),
                )
                existing = (
                    session.query(Channel)
                    .filter_by(
                        station_id=sta.id,
                        location=ch_data.get("location") or "",
                        channel=ch_data["channel"],
                        start_time=ch_data["start_time"],
                    )
                    .one_or_none()
                )
                incoming_response = ch_data.get("response_xml")
                incoming_source = ch_data.get("response_source") or (
                    "imported" if incoming_response else None
                )
                if existing is None:
                    payload = {k: v for k, v in ch_data.items() if not k.startswith("_")}
                    if not incoming_response:
                        payload["response_xml"] = None
                        payload["response_source"] = "none"
                    else:
                        payload["response_source"] = incoming_source or "imported"
                    ch = Channel(station_id=sta.id, **payload)
                    session.add(ch)
                    session.flush()
                    write_audit(
                        session,
                        action="import",
                        entity_type="channel",
                        entity_id=ch.id,
                        source=source,
                        actor=actor,
                        nslc=nslc_of(ch),
                        before=None,
                        after=to_dict(ch),
                    )
                    created += 1
                else:
                    before = to_dict(existing)
                    keep_xml = existing.response_xml
                    keep_src = existing.response_source
                    for key, value in ch_data.items():
                        if key.startswith("_") or key in ("response_xml", "response_source"):
                            continue
                        setattr(existing, key, value)
                    if incoming_response:
                        existing.response_xml = incoming_response
                        existing.response_source = incoming_source or "imported"
                    else:
                        existing.response_xml = keep_xml
                        existing.response_source = keep_src
                    session.flush()
                    write_audit(
                        session,
                        action="import",
                        entity_type="channel",
                        entity_id=existing.id,
                        source=source,
                        actor=actor,
                        nslc=nslc_of(existing),
                        before=before,
                        after=to_dict(existing),
                    )
                    updated += 1
    session.commit()
    return {"created": created, "updated": updated, "warnings": warnings}


def export_stationxml_bytes(session: Session) -> bytes:
    nets = (
        session.query(Network)
        .options(joinedload(Network.stations).joinedload(Station.channels))
        .order_by(Network.code)
        .all()
    )
    cat = catalog_map(session)
    inv = build_inventory(nets, cat)
    return inventory_to_bytes(inv, validate=True)


def apply_nrl(session: Session, channel_id: int, actor: str | None) -> Channel:
    ch = get_channel(session, channel_id)
    sensor = get_by_code(session, "sensor", ch.sensor_id)
    logger = get_by_code(session, "datalogger", ch.datalogger_id)
    if sensor is None or not sensor.nrl_keys:
        raise ValidationError("센서 카탈로그에 NRL 키가 없습니다")
    if logger is None or not logger.nrl_keys:
        raise ValidationError("기록계 카탈로그에 NRL 키가 없습니다")
    if not sample_rates_match(ch.sample_rate, logger.sample_rate):
        raise ValidationError("기록계 샘플링레이트와 채널 샘플링레이트가 다릅니다")
    try:
        from obspy.clients.nrl import NRL

        nrl = NRL()
        response = nrl.get_response(
            sensor_keys=[p.strip() for p in sensor.nrl_keys.split("|") if p.strip()],
            datalogger_keys=[p.strip() for p in logger.nrl_keys.split("|") if p.strip()],
        )
    except Exception as exc:
        raise AppError(f"NRL 응답을 가져오지 못했습니다: {exc}", 502) from exc

    from obspy.core.inventory import Channel as ObspyChannel

    dummy = ObspyChannel(
        code=ch.channel,
        location_code=ch.location or "",
        latitude=ch.station.latitude,
        longitude=ch.station.longitude,
        elevation=ch.station.elevation,
        depth=ch.depth or 0.0,
        azimuth=ch.azimuth,
        dip=ch.dip,
        sample_rate=ch.sample_rate,
    )
    dummy.response = response
    xml = dump_response_xml(dummy)
    before = to_dict(ch)
    ch.response_xml = xml
    ch.response_source = "nrl"
    session.flush()
    write_audit(
        session,
        action="nrl",
        entity_type="channel",
        entity_id=ch.id,
        source="ui",
        actor=actor,
        nslc=nslc_of(ch),
        before=before,
        after=to_dict(ch),
        summary="NRL 응답 적용",
    )
    session.commit()
    session.refresh(ch)
    return ch


def list_catalog(session: Session, kind: str | None = None) -> list[EquipmentCatalog]:
    q = session.query(EquipmentCatalog).order_by(EquipmentCatalog.kind, EquipmentCatalog.code)
    if kind:
        q = q.filter(EquipmentCatalog.kind == kind)
    return q.all()


def create_catalog_item(session: Session, payload: dict[str, Any], actor: str | None) -> EquipmentCatalog:
    kind = payload["kind"]
    code = payload["code"].strip()
    if get_by_code(session, kind, code):
        raise ValidationError(f"이미 있는 장비 ID입니다: {code}")
    row = EquipmentCatalog(
        kind=kind,
        code=code,
        manufacturer=payload["manufacturer"].strip(),
        model=payload["model"].strip(),
        sample_rate=payload.get("sample_rate"),
        nrl_keys=(payload.get("nrl_keys") or None),
    )
    session.add(row)
    session.flush()
    write_audit(
        session,
        action="create",
        entity_type="catalog",
        entity_id=row.id,
        source="ui",
        actor=actor,
        nslc=f"{kind}:{code}",
        before=None,
        after=_catalog_dict(row),
    )
    session.commit()
    session.refresh(row)
    return row


def update_catalog_item(
    session: Session, item_id: int, payload: dict[str, Any], actor: str | None
) -> EquipmentCatalog:
    row = session.query(EquipmentCatalog).get(item_id)
    if row is None:
        raise AppError("카탈로그 항목을 찾을 수 없습니다", 404)
    before = _catalog_dict(row)
    for key in ("manufacturer", "model", "sample_rate", "nrl_keys"):
        if key in payload:
            setattr(row, key, payload[key] if payload[key] not in ("",) else None)
    session.flush()
    write_audit(
        session,
        action="update",
        entity_type="catalog",
        entity_id=row.id,
        source="ui",
        actor=actor,
        nslc=f"{row.kind}:{row.code}",
        before=before,
        after=_catalog_dict(row),
    )
    session.commit()
    session.refresh(row)
    return row


def delete_catalog_item(session: Session, item_id: int, actor: str | None) -> None:
    row = session.query(EquipmentCatalog).get(item_id)
    if row is None:
        raise AppError("카탈로그 항목을 찾을 수 없습니다", 404)
    used = catalog_in_use(session, row.kind, row.code)
    if used:
        raise ValidationError(
            f"'{row.code}'를 사용하는 채널이 있어 삭제할 수 없습니다: {', '.join(used)}"
        )
    before = _catalog_dict(row)
    session.delete(row)
    write_audit(
        session,
        action="delete",
        entity_type="catalog",
        entity_id=item_id,
        source="ui",
        actor=actor,
        nslc=f"{row.kind}:{row.code}",
        before=before,
        after=None,
    )
    session.commit()


def list_history(session: Session, limit: int = 200, nslc: str | None = None):
    from .models import AuditLog

    q = session.query(AuditLog).order_by(AuditLog.id.desc())
    if nslc:
        q = q.filter(AuditLog.nslc.contains(nslc))
    return q.limit(limit).all()


def _catalog_dict(row: EquipmentCatalog) -> dict[str, Any]:
    return {
        "id": row.id,
        "kind": row.kind,
        "code": row.code,
        "manufacturer": row.manufacturer,
        "model": row.model,
        "sample_rate": row.sample_rate,
        "nrl_keys": row.nrl_keys,
    }


def _upsert_catalog(session: Session, catalog: dict[str, Any], actor: str | None) -> None:
    for kind, key in (("sensor", "sensors"), ("datalogger", "dataloggers")):
        for item in catalog.get(key) or []:
            row = get_by_code(session, kind, item["code"])
            if row is None:
                row = EquipmentCatalog(kind=kind, code=item["code"])
                session.add(row)
            row.manufacturer = item.get("manufacturer") or row.manufacturer or ""
            row.model = item.get("model") or row.model or ""
            if kind == "datalogger":
                row.sample_rate = item.get("sample_rate")
            row.nrl_keys = item.get("nrl_keys")
    session.flush()


def _require_network(session: Session, payload: dict[str, Any]) -> Network:
    if payload.get("network_id"):
        return get_network(session, int(payload["network_id"]))
    code = payload.get("network") or payload.get("network_code")
    if not code:
        raise ValidationError("네트워크가 필요합니다")
    net = session.query(Network).filter_by(code=code).one_or_none()
    if net is None:
        net = Network(code=code)
        session.add(net)
        session.flush()
    return net


def _require_station(session: Session, payload: dict[str, Any]) -> Station:
    if payload.get("station_id"):
        return get_station(session, int(payload["station_id"]))
    net = _require_network(session, payload)
    code = payload.get("station") or payload.get("station_code")
    if not code:
        raise ValidationError("관측소가 필요합니다")
    sta = session.query(Station).filter_by(network_id=net.id, code=code).one_or_none()
    if sta is None:
        raise ValidationError("관측소를 먼저 추가하세요")
    return sta


def _station_fields(payload: dict[str, Any], partial: bool = False) -> dict[str, Any]:
    lat = parse_float(payload.get("latitude"), "위도")
    lon = parse_float(payload.get("longitude"), "경도")
    if not partial:
        if lat is None or lon is None:
            raise ValidationError("위도/경도는 필수입니다")
        validate_lat_lon(lat, lon)
    elif lat is not None and lon is not None:
        validate_lat_lon(lat, lon)
    elif lat is not None or lon is not None:
        # validate against provided piece only when both present; if one present check range
        if lat is not None:
            validate_lat_lon(lat, 0.0)
        if lon is not None:
            validate_lat_lon(0.0, lon)
    elev = parse_float(payload.get("elevation"), "고도")
    if elev is None and not partial:
        elev = 0.0
    creation = parse_time(payload.get("creation_date"), "설치일")
    termination = parse_time(payload.get("termination_date"), "철거일")
    validate_time_order(creation, termination, "설치일", "철거일")
    data = {
        "code": payload.get("code") or payload.get("station"),
        "latitude": lat,
        "longitude": lon,
        "elevation": elev,
        "site_name": payload.get("site_name"),
        "site_description": payload.get("site_description"),
        "site_town": payload.get("site_town"),
        "site_region": payload.get("site_region"),
        "site_country": payload.get("site_country"),
        "vault": payload.get("vault"),
        "geology": payload.get("geology"),
        "description": payload.get("description") or payload.get("station_description"),
        "creation_date": creation.isoformat() if creation else payload.get("creation_date"),
        "termination_date": termination.isoformat() if termination else payload.get("termination_date"),
    }
    if partial:
        return {k: v for k, v in data.items() if k in payload or (k == "description" and "station_description" in payload) or k in ("latitude", "longitude", "elevation") and payload.get(k) is not None}
    data["code"] = payload.get("code") or payload.get("station")
    if not data["code"]:
        raise ValidationError("관측소 코드는 필수입니다")
    return data


def _channel_fields(
    session: Session,
    payload: dict[str, Any],
    station: Station,
    partial: bool = False,
    existing: Channel | None = None,
) -> dict[str, Any]:
    channel = payload.get("channel") or (existing.channel if existing else None)
    if not channel and not partial:
        raise ValidationError("채널 코드는 필수입니다")
    start = parse_time(payload.get("start_time"), "시작시간")
    if start is None and not partial:
        raise ValidationError("시작시간은 필수입니다")
    end = parse_time(payload.get("end_time"), "끝시간")
    validate_time_order(start or (parse_time(existing.start_time, "시작시간") if existing else None), end, "시작시간", "끝시간")
    rate = parse_float(payload.get("sample_rate"), "샘플링레이트")
    if rate is None and not partial:
        raise ValidationError("샘플링레이트는 필수입니다")
    if rate is not None:
        validate_sample_rate(rate)
    az = parse_float(payload.get("azimuth"), "방위각")
    dip = parse_float(payload.get("dip"), "경사")
    if channel and (az is None or dip is None) and not partial:
        inf_az, inf_dip = infer_az_dip(channel)
        az = inf_az if az is None else az
        dip = inf_dip if dip is None else dip
    sensor_id = payload.get("sensor_id")
    datalogger_id = payload.get("datalogger_id")
    check_rate = rate if rate is not None else (existing.sample_rate if existing else None)
    if check_rate is not None:
        assert_equipment_ids(
            session,
            sensor_id if "sensor_id" in payload or not partial else (existing.sensor_id if existing else None),
            datalogger_id if "datalogger_id" in payload or not partial else (existing.datalogger_id if existing else None),
            check_rate,
        )
    loc = payload.get("location")
    if loc is None and not partial:
        loc = ""
    data = {
        "location": loc,
        "channel": channel,
        "start_time": start.isoformat() if start else None,
        "end_time": end.isoformat() if end else payload.get("end_time"),
        "sample_rate": rate,
        "depth": parse_float(payload.get("depth"), "심도") or (0.0 if not partial else None),
        "azimuth": az,
        "dip": dip,
        "description": payload.get("description") or payload.get("channel_description"),
        "comment": payload.get("comment"),
        "channel_types": payload.get("channel_types"),
        "clock_drift": parse_float(payload.get("clock_drift"), "시각오차"),
        "latitude": parse_float(payload.get("latitude") or payload.get("channel_latitude"), "채널위도"),
        "longitude": parse_float(payload.get("longitude") or payload.get("channel_longitude"), "채널경도"),
        "elevation": parse_float(payload.get("elevation") or payload.get("channel_elevation"), "채널고도"),
        "sensor_id": sensor_id or None,
        "sensor_serial": payload.get("sensor_serial"),
        "sensor_type": payload.get("sensor_type"),
        "sensor_install_date": _iso(payload.get("sensor_install_date"), "센서설치일"),
        "sensor_remove_date": _iso(payload.get("sensor_remove_date"), "센서철거일"),
        "datalogger_id": datalogger_id or None,
        "datalogger_serial": payload.get("datalogger_serial"),
        "datalogger_type": payload.get("datalogger_type"),
        "datalogger_install_date": _iso(payload.get("datalogger_install_date"), "기록계설치일"),
        "datalogger_remove_date": _iso(payload.get("datalogger_remove_date"), "기록계철거일"),
    }
    if partial:
        allowed = {k: v for k, v in data.items() if k in payload or k in ("description",) and "channel_description" in payload}
        return {k: v for k, v in allowed.items() if v is not None or k in payload}
    return {k: v for k, v in data.items() if v is not None or k in ("location", "end_time", "comment")}


def _iso(value: Any, field: str) -> str | None:
    parsed = parse_time(value, field)
    return parsed.isoformat() if parsed else None
