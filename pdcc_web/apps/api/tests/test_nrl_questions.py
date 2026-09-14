from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.nrl.questions import build_wizard

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "nrl"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture
def prefixes() -> list[dict]:
    return _load("prefix-lookup.json")


def test_cmg3t_skips_single_value_sensor_type(prefixes):
    data = _load("cmg-3t.json")
    result = build_wizard(data["configurations"], {}, prefixes)
    keys = [q["key"] for q in result["questions"]]
    assert "Sensor_Type" not in keys
    assert result["locked"]["Sensor_Type"] == "groundVel"
    assert keys == ["High-Frequency_Corner", "Long-Period_Corner", "Sensitivity"]
    assert result["match_count"] == 30
    lp = next(q for q in result["questions"] if q["key"] == "Long-Period_Corner")
    assert "What is the long-period corner?" == lp["question"]
    assert "120 s" in lp["options"]


def test_q330hr_all_params_are_questions(prefixes):
    data = _load("q330hr.json")
    result = build_wizard(data["configurations"], {}, prefixes)
    keys = [q["key"] for q in result["questions"]]
    assert result["locked"] == {}
    assert set(keys) == {
        "Preamp_Gain",
        "Final_Sample_Rate",
        "ADC_Type",
        "Linear_Filter_Rates",
        "Decimation_Filter",
    }
    assert result["match_count"] == 176


def test_answers_narrow_cmg3t(prefixes):
    data = _load("cmg-3t.json")
    result = build_wizard(
        data["configurations"],
        {"Long-Period_Corner": "120 s", "High-Frequency_Corner": "50 Hz"},
        prefixes,
    )
    assert "Long-Period_Corner" not in [q["key"] for q in result["questions"]]
    assert result["match_count"] < 30
    for match in result["matches"]:
        assert match["parameters"]["Long-Period_Corner"] == "120 s"
        assert match["parameters"]["High-Frequency_Corner"] == "50 Hz"


def test_full_answers_single_instconfig(prefixes):
    data = _load("cmg-3t.json")
    result = build_wizard(
        data["configurations"],
        {
            "Long-Period_Corner": "30 s",
            "High-Frequency_Corner": "50 Hz",
            "Sensitivity": "1500 V/m/s",
        },
        prefixes,
    )
    assert result["questions"] == []
    assert result["match_count"] == 1
    assert result["matches"][0]["instconfig"] == (
        "sensor_Guralp_CMG-3T_LP30_HF50_SG1500_STgroundVel"
    )
