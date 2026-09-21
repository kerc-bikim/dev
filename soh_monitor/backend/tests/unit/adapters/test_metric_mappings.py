"""펌웨어별 원본 경로는 표로 흡수한다. 코드 분기를 늘리지 않는다."""
from __future__ import annotations

from pathlib import Path

from app.adapters.centaur_ctr.mapper import MAPPING_TABLE_PATH, map_soh
from app.adapters.centaur_ctr.parser import ChannelValue, ParsedSoh
from app.adapters.metric_mappings import firmware_matches, load_mapping_table
from app.metrics.catalog import validate_sample


def test_펌웨어_범위_매칭():
    assert firmware_matches("*", "3.2.8") is True
    assert firmware_matches("2.9.*", "2.9.4") is True
    assert firmware_matches("2.9.*", "3.2.8") is False
    assert firmware_matches("<=2.9.99", "2.9.4") is True
    assert firmware_matches("<=2.9.99", "3.0.0") is False
    assert firmware_matches("2.9.*", None) is False


def test_카탈로그에_없는_키는_표를_거절한다(tmp_path: Path):
    path = tmp_path / "bad.yaml"
    path.write_text(
        "adapter_key: nanometrics.centaur.ctr\nrules:\n"
        "  - source_path: x\n    canonical_metric_key: not.a.metric\n",
        encoding="utf-8",
    )
    try:
        load_mapping_table(path)
    except Exception as exc:
        assert "카탈로그" in str(exc)
    else:
        raise AssertionError("잘못된 표가 통과했다")


def test_별칭_경로가_표준_Metric을_만든다():
    soh = ParsedSoh(
        instrument_id="centaur-3__0088",
        reported_at=None,
        channels={
            "systemSoftwareVersion": ChannelValue("2.9.4"),
            "power/voltage": ChannelValue(12.5, "V"),
            "gps/satellites": ChannelValue(9),
        },
    )
    result = map_soh(soh)
    samples = {(sample.metric_key): sample for sample in result.samples}
    assert samples["power.input_voltage_v"].value_float == 12.5
    assert samples["gnss.satellite_count"].value_int == 9
    for sample in result.samples:
        validate_sample(sample)
    assert "power/voltage" in result.consumed


def test_범위_밖_펌웨어는_별칭을_쓰지_않는다():
    soh = ParsedSoh(
        instrument_id="centaur-6__0242",
        reported_at=None,
        channels={
            "systemSoftwareVersion": ChannelValue("3.2.8"),
            "power/voltage": ChannelValue(12.5, "V"),
        },
    )
    result = map_soh(soh)
    assert not any(sample.metric_key == "power.input_voltage_v" for sample in result.samples)


def test_기본_경로가_있으면_별칭을_덮지_않는다():
    soh = ParsedSoh(
        instrument_id="centaur-3__0088",
        reported_at=None,
        channels={
            "systemSoftwareVersion": ChannelValue("2.9.4"),
            "powerSupply/voltage": ChannelValue(13.1, "V"),
            "power/voltage": ChannelValue(1.0, "V"),
        },
    )
    result = map_soh(soh)
    voltages = [s.value_float for s in result.samples if s.metric_key == "power.input_voltage_v"]
    assert voltages == [13.1]


def test_CTR_매핑표가_있다():
    table = load_mapping_table(MAPPING_TABLE_PATH)
    assert table.adapter_key == "nanometrics.centaur.ctr"
    assert table.rules
