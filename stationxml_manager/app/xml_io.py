"""StationXML 가져오기."""

from __future__ import annotations

from io import BytesIO
from typing import Any

from obspy import read_inventory
from obspy.core.inventory.util import Equipment
from sqlalchemy.orm import Session

from .catalog import find_by_manufacturer_model
from .errors import ValidationError
from .inventory import dump_response_xml
from .validation import (
    canonical_time,
    infer_az_dip,
    validate_lat_lon,
    validate_sample_rate,
    validate_time_order,
)


def _eq_manuf_model(eq: Equipment | None) -> tuple[str | None, str | None]:
    if eq is None:
        return None, None
    return eq.manufacturer or None, eq.model or None


def _time_iso(value) -> str | None:
    return canonical_time(value, "시간")


def read_stationxml(path_or_buf, session: Session) -> dict[str, Any]:
    if hasattr(path_or_buf, "read"):
        data = path_or_buf.read()
        inv = read_inventory(BytesIO(data), format="STATIONXML")
    else:
        inv = read_inventory(str(path_or_buf), format="STATIONXML")

    warnings: list[str] = []
    networks: dict[str, Any] = {}
    for net in inv:
        net_entry = {
            "code": net.code,
            "description": net.description or None,
            "operator_agency": None,
            "restricted_status": getattr(net, "restricted_status", None),
            "stations": {},
        }
        if net.operators:
            net_entry["operator_agency"] = net.operators[0].agency
        for sta in net:
            validate_lat_lon(float(sta.latitude), float(sta.longitude))
            elevation = float(sta.elevation) if sta.elevation is not None else 0.0
            site = sta.site
            sta_entry = {
                "code": sta.code,
                "latitude": float(sta.latitude),
                "longitude": float(sta.longitude),
                "elevation": elevation,
                "elevation_warning": elevation == 0,
                "site_name": site.name if site else None,
                "site_description": site.description if site else None,
                "site_town": site.town if site else None,
                "site_region": site.region if site else None,
                "site_country": site.country if site else None,
                "vault": sta.vault,
                "geology": sta.geology,
                "description": sta.description,
                "creation_date": _time_iso(sta.creation_date),
                "termination_date": _time_iso(sta.termination_date),
                "channels": [],
            }
            for cha in sta:
                if cha.sample_rate is None:
                    raise ValidationError(
                        f"{net.code}.{sta.code}.{cha.location_code}.{cha.code}: 샘플링레이트가 없습니다"
                    )
                validate_sample_rate(float(cha.sample_rate))
                start = cha.start_date or sta.creation_date
                if start is None:
                    raise ValidationError(
                        f"{net.code}.{sta.code}.{cha.location_code}.{cha.code}: 시작시간이 없습니다"
                    )
                validate_time_order(start, cha.end_date, "시작시간", "끝시간")
                az = float(cha.azimuth) if cha.azimuth is not None else None
                dip = float(cha.dip) if cha.dip is not None else None
                if az is None or dip is None:
                    inf_az, inf_dip = infer_az_dip(cha.code)
                    az = inf_az if az is None else az
                    dip = inf_dip if dip is None else dip
                sensor_id = None
                man, model = _eq_manuf_model(cha.sensor)
                matched = find_by_manufacturer_model(session, "sensor", man, model)
                if matched:
                    sensor_id = matched.code
                elif man or model:
                    warnings.append(
                        f"{net.code}.{sta.code}.{cha.location_code or '--'}.{cha.code}: "
                        f"센서 {man} {model} 을 카탈로그에서 찾지 못했습니다"
                    )
                datalogger_id = None
                dman, dmodel = _eq_manuf_model(cha.data_logger)
                dmatched = find_by_manufacturer_model(
                    session, "datalogger", dman, dmodel, float(cha.sample_rate)
                )
                if dmatched:
                    datalogger_id = dmatched.code
                elif dman or dmodel:
                    warnings.append(
                        f"{net.code}.{sta.code}.{cha.location_code or '--'}.{cha.code}: "
                        f"기록계 {dman} {dmodel} 을 카탈로그에서 찾지 못했습니다"
                    )
                comment = None
                if cha.comments:
                    comment = cha.comments[0].value
                types = None
                if cha.types:
                    types = ",".join(cha.types)
                response_xml = dump_response_xml(cha)
                clock_drift = getattr(cha, "clock_drift", None)
                sta_entry["channels"].append(
                    {
                        "location": cha.location_code or "",
                        "channel": cha.code,
                        "start_time": canonical_time(start, "시작시간"),
                        "end_time": _time_iso(cha.end_date),
                        "sample_rate": float(cha.sample_rate),
                        "depth": float(cha.depth) if cha.depth is not None else 0.0,
                        "azimuth": az,
                        "dip": dip,
                        "description": cha.description,
                        "comment": comment,
                        "channel_types": types,
                        "clock_drift": float(clock_drift) if clock_drift is not None else None,
                        "latitude": float(cha.latitude) if cha.latitude is not None else None,
                        "longitude": float(cha.longitude) if cha.longitude is not None else None,
                        "elevation": float(cha.elevation) if cha.elevation is not None else None,
                        "sensor_id": sensor_id,
                        "sensor_serial": cha.sensor.serial_number if cha.sensor else None,
                        "sensor_type": cha.sensor.type if cha.sensor else None,
                        "sensor_install_date": _time_iso(
                            cha.sensor.installation_date if cha.sensor else None
                        ),
                        "sensor_remove_date": _time_iso(
                            cha.sensor.removal_date if cha.sensor else None
                        ),
                        "datalogger_id": datalogger_id,
                        "datalogger_serial": cha.data_logger.serial_number if cha.data_logger else None,
                        "datalogger_type": cha.data_logger.type if cha.data_logger else None,
                        "datalogger_install_date": _time_iso(
                            cha.data_logger.installation_date if cha.data_logger else None
                        ),
                        "datalogger_remove_date": _time_iso(
                            cha.data_logger.removal_date if cha.data_logger else None
                        ),
                        "response_xml": response_xml,
                        "response_source": "imported" if response_xml else "none",
                    }
                )
            net_entry["stations"][sta.code] = sta_entry
        networks[net.code] = net_entry
    return {"networks": networks, "warnings": warnings, "catalog": {"sensors": [], "dataloggers": []}}
