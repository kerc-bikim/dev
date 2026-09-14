from __future__ import annotations

from pathlib import Path

import pytest

from app.nrl.curve import (
    CurveError,
    eval_response_curve,
    sample_rate_from_instconfig,
    wrap_stationxml_response,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "nrl"
RESP_XML = (FIXTURES / "stationxml-resp.xml").read_bytes()


def test_sample_rate_from_instconfig_uses_last_fr_token():
    cascade = (
        "sensor_Guralp_CMG-3T_LP30_HF50_SG1500_STgroundVel:"
        "datalogger_Quanterra_Q330HR_PG1_FR100_ADHR_LRbelow20_DENone"
    )
    assert sample_rate_from_instconfig(cascade) == 100.0
    assert sample_rate_from_instconfig("datalogger_Quanterra_Q330HR_FR200") == 200.0
    assert sample_rate_from_instconfig("sensor_Guralp_CMG-3T_LP30_HF50") is None


def test_wrap_keeps_fdsn_inventory_as_is():
    wrapped = wrap_stationxml_response(
        b'<FDSNStationXML xmlns="http://www.fdsn.org/xml/station/1" schemaVersion="1.2"/>',
        100.0,
    )
    assert b"FDSNStationXML" in wrapped


def test_eval_curve_from_stationxml_response():
    curve = eval_response_curve(RESP_XML, output="VEL", npts=50)
    assert curve["output"] == "VEL"
    assert curve["npts"] == 50
    assert curve["sample_rate"] == 100.0
    assert curve["max_freq"] == pytest.approx(50.0)
    assert len(curve["frequencies"]) == 50
    assert len(curve["amplitude"]) == 50
    assert len(curve["phase_deg"]) == 50
    assert all(amp > 0 for amp in curve["amplitude"])
    assert curve["frequencies"][0] < curve["frequencies"][-1]
    assert curve["input_units"] == "M/S"
    assert curve["output_units"] == "COUNTS"


def test_eval_curve_rejects_max_freq_above_nyquist():
    with pytest.raises(CurveError, match="Nyquist"):
        eval_response_curve(RESP_XML, max_freq=80, npts=50)


def test_eval_curve_output_units_change_amplitude():
    vel = eval_response_curve(RESP_XML, output="VEL", npts=50)
    acc = eval_response_curve(RESP_XML, output="ACC", npts=50)
    dis = eval_response_curve(RESP_XML, output="DIS", npts=50)
    mid = 25
    assert acc["amplitude"][mid] != vel["amplitude"][mid]
    assert dis["amplitude"][mid] != vel["amplitude"][mid]
