from __future__ import annotations

from io import BytesIO
from typing import Any

from obspy import UTCDateTime, read_inventory
from obspy.core.inventory import Channel, Inventory, Network, Station
from obspy.core.inventory.util import Comment, Equipment, Operator, Site

from .errors import AppError
from .models import Channel as ChannelRow
from .models import Network as NetworkRow
from .models import Station as StationRow
from .validation import infer_az_dip, parse_time


def _equipment(
    manufacturer: str | None,
    model: str | None,
    serial: str | None,
    type_: str | None,
    install: str | None,
    remove: str | None,
) -> Equipment | None:
    if not any([manufacturer, model, serial, type_]):
        return None
    kwargs: dict[str, Any] = {}
    if manufacturer:
        kwargs["manufacturer"] = manufacturer
    if model:
        kwargs["model"] = model
    if serial:
        kwargs["serial_number"] = serial
    if type_:
        kwargs["type"] = type_
    if install:
        kwargs["installation_date"] = parse_time(install, "설치일")
    if remove:
        kwargs["removal_date"] = parse_time(remove, "철거일")
    return Equipment(**kwargs)


def dump_response_xml(channel: Channel) -> str | None:
    if channel.response is None:
        return None
    inv = Inventory(
        networks=[
            Network(
                code="XX",
                stations=[
                    Station(
                        code="TMP",
                        latitude=0.0,
                        longitude=0.0,
                        elevation=0.0,
                        creation_date=UTCDateTime(1970, 1, 1),
                        site=Site(name="tmp"),
                        channels=[channel],
                    )
                ],
            )
        ],
        source="stationxml_manager",
    )
    buf = BytesIO()
    inv.write(buf, format="STATIONXML")
    return buf.getvalue().decode("utf-8")


def load_response(xml: str):
    inv = read_inventory(BytesIO(xml.encode("utf-8")), format="STATIONXML")
    return inv[0][0][0].response


def build_inventory(
    networks: list[NetworkRow],
    catalog: dict[str, dict[str, Any]],
) -> Inventory:
    obspy_nets: list[Network] = []
    for net_row in networks:
        start = None
        for sta in net_row.stations:
            for ch in sta.channels:
                t = parse_time(ch.start_time, "시작시간")
                if t is not None and (start is None or t < start):
                    start = t
        operators = []
        if net_row.operator_agency:
            operators.append(Operator(agency=net_row.operator_agency))
        net = Network(
            code=net_row.code,
            stations=[],
            description=net_row.description or None,
            restricted_status=net_row.restricted_status or None,
            start_date=start,
            operators=operators or None,
        )
        for sta_row in net_row.stations:
            creation = parse_time(sta_row.creation_date, "설치일")
            if creation is None:
                creation = min(
                    (
                        parse_time(ch.start_time, "시작시간")
                        for ch in sta_row.channels
                        if ch.start_time
                    ),
                    default=UTCDateTime(1970, 1, 1),
                )
            sta = Station(
                code=sta_row.code,
                latitude=sta_row.latitude,
                longitude=sta_row.longitude,
                elevation=sta_row.elevation,
                creation_date=creation,
                termination_date=parse_time(sta_row.termination_date, "철거일"),
                site=Site(
                    name=sta_row.site_name or sta_row.code,
                    description=sta_row.site_description or None,
                    town=sta_row.site_town or None,
                    region=sta_row.site_region or None,
                    country=sta_row.site_country or None,
                ),
                vault=sta_row.vault or None,
                geology=sta_row.geology or None,
                description=sta_row.description or None,
                channels=[],
            )
            for ch_row in sta_row.channels:
                sta.channels.append(
                    _channel_from_row(ch_row, sta_row, catalog, net_row.code)
                )
            net.stations.append(sta)
        obspy_nets.append(net)
    return Inventory(networks=obspy_nets, source="stationxml_manager")


def _channel_from_row(
    ch_row: ChannelRow,
    sta_row: StationRow,
    catalog: dict[str, dict[str, Any]],
    network_code: str,
) -> Channel:
    az, dip = ch_row.azimuth, ch_row.dip
    if az is None or dip is None:
        az, dip = infer_az_dip(ch_row.channel)
    lat = ch_row.latitude if ch_row.latitude is not None else sta_row.latitude
    lon = ch_row.longitude if ch_row.longitude is not None else sta_row.longitude
    elev = ch_row.elevation if ch_row.elevation is not None else sta_row.elevation
    types = None
    if ch_row.channel_types:
        types = [p.strip() for p in ch_row.channel_types.split(",") if p.strip()]
    cha = Channel(
        code=ch_row.channel,
        location_code=ch_row.location or "",
        latitude=lat,
        longitude=lon,
        elevation=elev,
        depth=ch_row.depth or 0.0,
        azimuth=az,
        dip=dip,
        sample_rate=ch_row.sample_rate,
        start_date=parse_time(ch_row.start_time, "시작시간"),
        end_date=parse_time(ch_row.end_time, "끝시간"),
        description=ch_row.description or None,
        types=types,
    )
    if ch_row.clock_drift is not None:
        try:
            cha.clock_drift_in_seconds_per_sample = float(ch_row.clock_drift)
        except (TypeError, ValueError, AttributeError):
            pass
    if ch_row.comment:
        cha.comments = [Comment(value=ch_row.comment)]
    sensor_meta = catalog.get("sensor", {}).get(ch_row.sensor_id or "")
    logger_meta = catalog.get("datalogger", {}).get(ch_row.datalogger_id or "")
    cha.sensor = _equipment(
        sensor_meta.manufacturer if sensor_meta else None,
        sensor_meta.model if sensor_meta else None,
        ch_row.sensor_serial,
        ch_row.sensor_type,
        ch_row.sensor_install_date,
        ch_row.sensor_remove_date,
    )
    cha.data_logger = _equipment(
        logger_meta.manufacturer if logger_meta else None,
        logger_meta.model if logger_meta else None,
        ch_row.datalogger_serial,
        ch_row.datalogger_type,
        ch_row.datalogger_install_date,
        ch_row.datalogger_remove_date,
    )
    if ch_row.response_xml:
        nslc = (
            f"{network_code}.{sta_row.code}.{ch_row.location or '--'}.{ch_row.channel}"
        )
        try:
            cha.response = load_response(ch_row.response_xml)
        except Exception as exc:
            reason = f"{nslc}: 저장된 응답 XML을 읽지 못했습니다: {exc}"
            raise AppError(
                reason, 400, errors=[{"nslc": nslc, "reason": reason}]
            ) from exc
    return cha


def inventory_to_bytes(inv: Inventory, validate: bool = True) -> bytes:
    buf = BytesIO()
    inv.write(buf, format="STATIONXML", validate=validate)
    return buf.getvalue()
