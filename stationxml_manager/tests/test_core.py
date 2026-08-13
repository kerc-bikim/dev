from __future__ import annotations

from io import BytesIO

import pytest
from obspy import UTCDateTime
from obspy.core.inventory import Channel, Inventory, Network, Station
from obspy.core.inventory.response import InstrumentSensitivity, Response
from obspy.core.inventory.util import Equipment, Site
from sqlalchemy.orm import Session, sessionmaker

from app.catalog import seed_catalog
from app.columns import resolve_header
from app.crud import (
    create_catalog_item,
    delete_catalog_item,
    export_stationxml_bytes,
    import_hierarchy,
    list_channels,
    update_station,
)
from app.db import Base, make_engine
from app.errors import ValidationError
from app.excel_io import read_excel, write_excel
from app.validation import infer_az_dip, validate_lat_lon, validate_sample_rate, validate_time_order
from app.xml_io import read_stationxml


@pytest.fixture
def session(tmp_path) -> Session:
    engine = make_engine(f"sqlite:///{tmp_path}/test.db")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False)
    s = SessionLocal()
    seed_catalog(s)
    yield s
    s.close()


def test_header_aliases():
    assert resolve_header("위도") == "latitude"
    assert resolve_header("센서ID") == "sensor_id"
    assert resolve_header("unknown") is None


def test_validation_helpers():
    validate_lat_lon(37.5, 127.0)
    with pytest.raises(ValidationError):
        validate_lat_lon(120, 127)
    validate_sample_rate(100)
    with pytest.raises(ValidationError):
        validate_sample_rate(0)
    validate_time_order(UTCDateTime(2020, 1, 1), UTCDateTime(2021, 1, 1), "시작", "끝")
    with pytest.raises(ValidationError):
        validate_time_order(UTCDateTime(2021, 1, 1), UTCDateTime(2020, 1, 1), "시작", "끝")
    assert infer_az_dip("HHZ") == (0.0, -90.0)
    assert infer_az_dip("HHE") == (90.0, 0.0)


def _sample_hierarchy():
    return {
        "warnings": [],
        "catalog": {"sensors": [], "dataloggers": []},
        "networks": {
            "XX": {
                "code": "XX",
                "description": "테스트망",
                "operator_agency": "테스트",
                "restricted_status": "open",
                "stations": {
                    "AAA": {
                        "code": "AAA",
                        "latitude": 37.5,
                        "longitude": 127.1,
                        "elevation": 80.0,
                        "site_name": "첫번째",
                        "site_description": None,
                        "site_town": None,
                        "site_region": None,
                        "site_country": "KR",
                        "vault": None,
                        "geology": None,
                        "description": None,
                        "creation_date": "2020-01-01T00:00:00.000000Z",
                        "termination_date": None,
                        "channels": [
                            {
                                "location": "",
                                "channel": "HHZ",
                                "start_time": "2020-01-01T00:00:00.000000Z",
                                "end_time": None,
                                "sample_rate": 100.0,
                                "depth": 0.0,
                                "azimuth": 0.0,
                                "dip": -90.0,
                                "description": None,
                                "comment": "비고",
                                "channel_types": "GEOPHYSICAL,CONTINUOUS",
                                "clock_drift": None,
                                "latitude": None,
                                "longitude": None,
                                "elevation": None,
                                "sensor_id": "Guralp_CMG-3T",
                                "sensor_serial": "S1",
                                "sensor_type": None,
                                "sensor_install_date": None,
                                "sensor_remove_date": None,
                                "datalogger_id": "REFTEK_RT130_100sps",
                                "datalogger_serial": "D1",
                                "datalogger_type": None,
                                "datalogger_install_date": None,
                                "datalogger_remove_date": None,
                            }
                        ],
                    }
                },
            }
        },
    }


def test_import_and_station_edit(session):
    result = import_hierarchy(session, _sample_hierarchy(), replace_all=False, source="ui", actor="테스터")
    assert result["created"] == 1
    ch = list_channels(session)[0]
    assert ch.station.site_name == "첫번째"
    update_station(session, ch.station.id, {"site_name": "수정됨"}, "테스터")
    ch = list_channels(session)[0]
    assert ch.station.site_name == "수정됨"


def test_bad_sensor_id(session):
    data = _sample_hierarchy()
    data["networks"]["XX"]["stations"]["AAA"]["channels"][0]["sensor_id"] = "NOPE"
    with pytest.raises(ValidationError, match="알 수 없는 센서ID"):
        import_hierarchy(session, data, replace_all=False, source="excel", actor=None)


def test_sample_rate_mismatch(session):
    data = _sample_hierarchy()
    data["networks"]["XX"]["stations"]["AAA"]["channels"][0]["sample_rate"] = 200
    with pytest.raises(ValidationError, match="샘플링레이트"):
        import_hierarchy(session, data, replace_all=False, source="excel", actor=None)


def test_catalog_delete_in_use(session):
    import_hierarchy(session, _sample_hierarchy(), replace_all=False, source="ui", actor=None)
    from app.models import EquipmentCatalog

    row = session.query(EquipmentCatalog).filter_by(code="Guralp_CMG-3T").one()
    with pytest.raises(ValidationError, match="사용하는 채널"):
        delete_catalog_item(session, row.id, None)


def test_catalog_create_and_delete(session):
    item = create_catalog_item(
        session,
        {
            "kind": "sensor",
            "code": "Test_Sensor",
            "manufacturer": "TestCo",
            "model": "T1",
        },
        "테스터",
    )
    delete_catalog_item(session, item.id, "테스터")


def test_conflicting_site_name_excel(session, tmp_path):
    from openpyxl import Workbook

    path = tmp_path / "bad.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "channels"
    ws.append(["네트워크", "관측소", "채널", "위도", "경도", "시작시간", "샘플링레이트", "관측소명"])
    ws.append(["XX", "AAA", "HHZ", 37.5, 127.0, "2020-01-01", 100, "A"])
    ws.append(["XX", "AAA", "HHN", 37.5, 127.0, "2020-01-01", 100, "B"])
    wb.save(path)
    with pytest.raises(ValidationError, match="관측소명"):
        read_excel(path)


def test_unknown_excel_header(tmp_path):
    from openpyxl import Workbook

    path = tmp_path / "bad.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.append(["네트워크", "관측소", "채널", "위도", "경도", "시작시간", "샘플링레이트", "담당자"])
    ws.append(["XX", "AAA", "HHZ", 37.5, 127.0, "2020-01-01", 100, "홍길동"])
    wb.save(path)
    with pytest.raises(ValidationError, match="알 수 없는 엑셀 열"):
        read_excel(path)


def test_excel_reimport_keeps_response(session):
    inv = _inventory_with_response()
    buf = BytesIO()
    inv.write(buf, format="STATIONXML")
    buf.seek(0)
    hierarchy = read_stationxml(buf, session)
    import_hierarchy(session, hierarchy, replace_all=False, source="xml", actor=None)
    ch = list_channels(session)[0]
    assert ch.response_xml
    original = ch.response_xml

    xlsx = write_excel(session)
    excel_h = read_excel(BytesIO(xlsx))
    import_hierarchy(session, excel_h, replace_all=False, source="excel", actor=None)
    ch = list_channels(session)[0]
    assert ch.response_xml == original


def test_xml_response_roundtrip(session):
    inv = _inventory_with_response()
    buf = BytesIO()
    inv.write(buf, format="STATIONXML")
    buf.seek(0)
    hierarchy = read_stationxml(buf, session)
    import_hierarchy(session, hierarchy, replace_all=True, source="xml", actor=None)
    update_station(session, list_channels(session)[0].station.id, {"site_name": "변경"}, None)
    exported = export_stationxml_bytes(session)
    from obspy import read_inventory

    back = read_inventory(BytesIO(exported), format="STATIONXML")
    cha = back[0][0][0]
    assert cha.response is not None
    assert cha.sensor.manufacturer == "Guralp"


def _inventory_with_response() -> Inventory:
    resp = Response(
        instrument_sensitivity=InstrumentSensitivity(
            value=1.5e9,
            frequency=1.0,
            input_units="M/S",
            output_units="COUNTS",
        )
    )
    cha = Channel(
        code="HHZ",
        location_code="",
        latitude=37.5,
        longitude=127.1,
        elevation=80.0,
        depth=0.0,
        azimuth=0.0,
        dip=-90.0,
        sample_rate=100.0,
        start_date=UTCDateTime(2020, 1, 1),
        sensor=Equipment(manufacturer="Guralp", model="CMG-3T", serial_number="S1"),
        data_logger=Equipment(manufacturer="REF TEK", model="RT 130", serial_number="D1"),
    )
    cha.response = resp
    sta = Station(
        code="AAA",
        latitude=37.5,
        longitude=127.1,
        elevation=80.0,
        creation_date=UTCDateTime(2020, 1, 1),
        site=Site(name="첫번째"),
        channels=[cha],
    )
    net = Network(code="XX", stations=[sta], description="테스트망")
    return Inventory(networks=[net], source="test")
