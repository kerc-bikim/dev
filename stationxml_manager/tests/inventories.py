"""테스트용 합성 Inventory."""

from __future__ import annotations

from io import BytesIO

from obspy import UTCDateTime
from obspy.core.inventory import Channel, Inventory, Network, Station
from obspy.core.inventory.response import (
    CoefficientsTypeResponseStage,
    InstrumentSensitivity,
    PolesZerosResponseStage,
    Response,
)
from obspy.core.inventory.util import Equipment, Site

from app.crud import import_hierarchy
from app.xml_io import read_stationxml


def pz_response() -> Response:
    pz = PolesZerosResponseStage(
        stage_sequence_number=1,
        stage_gain=2000.0,
        stage_gain_frequency=1.0,
        input_units="M/S",
        output_units="V",
        pz_transfer_function_type="LAPLACE (RADIANS/SECOND)",
        normalization_frequency=1.0,
        zeros=[0j],
        poles=[-4.39823 + 4.48709j, -4.39823 - 4.48709j],
        normalization_factor=1.0,
    )
    digital = CoefficientsTypeResponseStage(
        stage_sequence_number=2,
        stage_gain=419430.0,
        stage_gain_frequency=1.0,
        input_units="V",
        output_units="COUNTS",
        cf_transfer_function_type="DIGITAL",
        numerator=[1.0],
        denominator=[],
        decimation_input_sample_rate=100.0,
        decimation_factor=1,
        decimation_offset=0,
        decimation_delay=0.0,
        decimation_correction=0.0,
    )
    return Response(
        response_stages=[pz, digital],
        instrument_sensitivity=InstrumentSensitivity(
            value=8.3886e8,
            frequency=1.0,
            input_units="M/S",
            output_units="COUNTS",
        ),
    )


def fir_only_response() -> Response:
    digital = CoefficientsTypeResponseStage(
        stage_sequence_number=1,
        stage_gain=1.0,
        stage_gain_frequency=1.0,
        input_units="V",
        output_units="COUNTS",
        cf_transfer_function_type="DIGITAL",
        numerator=[1.0, 0.5],
        denominator=[],
        decimation_input_sample_rate=100.0,
        decimation_factor=1,
        decimation_offset=0,
        decimation_delay=0.0,
        decimation_correction=0.0,
    )
    return Response(
        response_stages=[digital],
        instrument_sensitivity=InstrumentSensitivity(
            value=1.0,
            frequency=1.0,
            input_units="V",
            output_units="COUNTS",
        ),
    )


def make_channel(
    code: str = "HHZ",
    sample_rate: float = 100.0,
    response: Response | None = None,
    start: str = "2020-01-01",
) -> Channel:
    cha = Channel(
        code=code,
        location_code="",
        latitude=37.5,
        longitude=127.1,
        elevation=80.0,
        depth=0.0,
        azimuth=0.0 if code.endswith("Z") else 0.0,
        dip=-90.0 if code.endswith("Z") else 0.0,
        sample_rate=sample_rate,
        start_date=UTCDateTime(start),
        sensor=Equipment(manufacturer="Guralp", model="CMG-3T", serial_number="S1"),
        data_logger=Equipment(manufacturer="REF TEK", model="RT 130", serial_number="D1"),
    )
    if response is not None:
        cha.response = response
    return cha


def make_inventory(
    channels: list[Channel],
    network: str = "XX",
    station: str = "AAA",
    site_name: str = "첫번째",
) -> Inventory:
    sta = Station(
        code=station,
        latitude=37.5,
        longitude=127.1,
        elevation=80.0,
        creation_date=UTCDateTime(2020, 1, 1),
        site=Site(name=site_name),
        channels=channels,
    )
    return Inventory(networks=[Network(code=network, stations=[sta], description="테스트망")], source="test")


def inventory_with_pz(
    *,
    channel: str = "HHZ",
    sample_rate: float = 100.0,
    network: str = "XX",
    station: str = "AAA",
    site_name: str = "첫번째",
) -> Inventory:
    return make_inventory(
        [make_channel(channel, sample_rate, pz_response())],
        network=network,
        station=station,
        site_name=site_name,
    )


def inventory_with_fir() -> Inventory:
    return make_inventory([make_channel("HHN", 100.0, fir_only_response())])


def stationxml_bytes(inv: Inventory) -> bytes:
    buf = BytesIO()
    inv.write(buf, format="STATIONXML")
    return buf.getvalue()


def import_inventory(session, inv: Inventory, source: str = "xml"):
    return import_hierarchy(
        session,
        read_stationxml(BytesIO(stationxml_bytes(inv)), session),
        replace_all=False,
        source=source,
        actor="tester",
    )
