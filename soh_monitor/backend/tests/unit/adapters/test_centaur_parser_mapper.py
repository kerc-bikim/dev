"""Centaur CTR 파서·변환기 검증.

여기서 막고 싶은 사고
  * 단위를 무시해 1000배 틀린 값이 조용히 적재되는 것
  * 모르는 상태 문자열이 정상으로 오인되는 것
  * 값 없음이 0 으로 채워지는 것
  * 새 펌웨어가 추가한 채널이 조용히 버려지는 것
"""
from __future__ import annotations

import pytest

from app.adapters.centaur_ctr.mapper import map_soh, unknown_channels
from app.adapters.centaur_ctr.parser import ParseError, parse_soh, parse_timestamp
from app.domain.enums import Severity, SupportState
from app.metrics.catalog import validate_sample


def _soh(channels: dict, *, shape: str = "channel_list", units: dict | None = None):
    units = units or {}
    if shape == "channel_list":
        payload = {
            "instrumentId": "centaur-6__0242",
            "timestamp": "2026-08-27T03:00:00.000Z",
            "channels": [
                {"name": name, "value": value, "units": units.get(name)}
                for name, value in channels.items()
            ],
        }
    elif shape == "flat_map":
        payload = {
            "instrumentId": "centaur-6__0242",
            "soh": {
                name: {"value": value, "units": units.get(name)}
                for name, value in channels.items()
            },
        }
    elif shape == "instrument_map":
        payload = {
            "centaur-6__0242": {
                name: {"value": value, "time": "2026-09-21T00:00:00.742000000Z", "units": units.get(name)}
                for name, value in channels.items()
            }
        }
    else:
        payload = {"instrumentId": "centaur-6__0242", **channels}
    return parse_soh(payload)


class Test파서:
    @pytest.mark.parametrize("shape", ["channel_list", "flat_map", "plain", "instrument_map"])
    def test_네_가지_응답_형태를_모두_읽는다(self, shape):
        """실장비 4.9.2 는 instrument_map 이다. 나머지는 가상·구형 Fixture 다."""
        soh = _soh({"powerSupply/voltage": 12.6}, shape=shape)
        assert soh.raw("powerSupply/voltage") == 12.6
        assert soh.instrument_id == "centaur-6__0242"

    def test_객체가_아니면_거부한다(self):
        with pytest.raises(ParseError):
            parse_soh([1, 2, 3])

    def test_채널이_하나도_없으면_거부한다(self):
        with pytest.raises(ParseError, match="채널"):
            parse_soh({"instrumentId": "centaur-6__0242", "timestamp": "2026-01-01T00:00:00Z"})

    def test_응답_속성을_채널로_오인하지_않는다(self):
        soh = parse_soh({"instrumentId": "x", "timestamp": "2026-01-01T00:00:00Z", "temperature": 30})
        assert set(soh.channels) == {"temperature"}

    @pytest.mark.parametrize(
        "raw",
        ["2026-08-27T03:00:00.000Z", "2026-08-27T03:00:00+00:00", "2026-08-27T03:00:00"],
    )
    def test_시각_해석(self, raw):
        parsed = parse_timestamp(raw)
        assert parsed is not None
        assert parsed.tzinfo is not None

    def test_나노초_공백_시각을_읽는다(self):
        parsed = parse_timestamp("2026-09-21 00:00:00.000000000")
        assert parsed is not None
        assert parsed.year == 2026
        assert parsed.tzinfo is not None

    def test_실응답_URI_단위를_마이크로볼트로_본다(self):
        soh = _soh(
            {"digitizer/sensor/soh/voltage#_1": "297096"},
            units={"digitizer/sensor/soh/voltage#_1": "http://nmx.ca/05/units/microvolts"},
        )
        sample = next(s for s in map_soh(soh).samples if s.metric_key == "sensor.mass_position_v")
        assert sample.dimensions == {"sensor_port": "A", "axis": "W"}
        assert sample.value_float == pytest.approx(0.2971)

    def test_위치_문자열을_위경도로_나눈다(self):
        soh = _soh({"instrument/earthLocation": "37.970971N 124.635521E 48m"})
        samples = {s.metric_key: s for s in map_soh(soh).samples}
        assert samples["gnss.latitude"].value_float == pytest.approx(37.970971)
        assert samples["gnss.longitude"].value_float == pytest.approx(124.635521)
        assert samples["gnss.elevation_m"].value_float == pytest.approx(48.0)

    def test_과학적_표기_전압을_읽는다(self):
        soh = _soh(
            {"powerSupply/voltage": "1.4203617974999998E1"},
            units={"powerSupply/voltage": "http://nmx.ca/05/units/volts"},
        )
        assert map_soh(soh).samples[0].value_float == pytest.approx(14.204, abs=0.001)

    def test_gps_status_unlocked는_정상으로_취급하지_않는다(self):
        soh = _soh(
            {
                "gps/status": "http://nmx.ca/11/soh/gps/status/unlocked",
                "gps/numberOfSatellites": "9",
                "timeStatus": "http://nmx.ca/05/soh/timing/timestatus/timeOK",
            }
        )
        result = map_soh(soh)
        samples = {s.metric_key: s for s in result.samples}
        assert samples["timing.status"].value_status is Severity.OK
        assert samples["gnss.satellite_count"].value_int == 9
        assert "gnss.antenna_status" not in samples
        assert unknown_channels(soh, result) == ()


class Test단위변환:
    def test_외부SOH는_마이크로볼트에서_볼트로_바뀐다(self):
        soh = _soh(
            {"externalSoh/voltage#_1": 1_600_000},
            units={"externalSoh/voltage#_1": "microVolts"},
        )
        sample = map_soh(soh).samples[0]
        assert sample.metric_key == "external_soh.value"
        assert sample.value_float == pytest.approx(1.6)
        assert sample.dimensions == {"channel": "EX1"}

    def test_응답이_알려_준_단위를_우선한다(self):
        """같은 채널이 펌웨어에 따라 V 또는 mV 로 올 수 있다."""
        as_volts = _soh({"powerSupply/voltage": 12.6}, units={"powerSupply/voltage": "V"})
        as_millivolts = _soh(
            {"powerSupply/voltage": 12600}, units={"powerSupply/voltage": "mV"}
        )
        first = map_soh(as_volts).samples[0].value_float
        second = map_soh(as_millivolts).samples[0].value_float
        assert first == pytest.approx(12.6)
        assert second == pytest.approx(12.6)

    def test_온도가_밀리섭씨로_오면_변환한다(self):
        soh = _soh({"temperature": 32500}, units={"temperature": "millidegreesCelsius"})
        sample = map_soh(soh).samples[0]
        assert sample.value_float == pytest.approx(32.5)

    def test_소비전력은_전압과_전류로_계산한다(self):
        soh = _soh({"powerSupply/voltage": 12.0, "system/current": 0.35})
        samples = {s.metric_key: s for s in map_soh(soh).samples}
        assert samples["power.consumption_w"].value_float == pytest.approx(4.2)

    def test_전류만_있으면_소비전력을_만들지_않는다(self):
        soh = _soh({"system/current": 0.35})
        keys = {s.metric_key for s in map_soh(soh).samples}
        assert "power.consumption_w" not in keys

    def test_Mass_Position_축_순서는_매뉴얼을_따른다(self):
        """8.2절: Nanometrics 지진계는 VM1=W, VM2=V, VM3=U 다."""
        soh = _soh(
            {
                "digitizer/sensor/massPosition#_0_1": 100_000,
                "digitizer/sensor/massPosition#_0_2": 200_000,
                "digitizer/sensor/massPosition#_0_3": 300_000,
            }
        )
        by_axis = {
            s.dimensions["axis"]: s.value_float
            for s in map_soh(soh).samples
            if s.metric_key == "sensor.mass_position_v"
        }
        assert by_axis == {"W": pytest.approx(0.1), "V": pytest.approx(0.2), "U": pytest.approx(0.3)}

    def test_센서_포트는_A와_B로_옮긴다(self):
        soh = _soh(
            {"digitizer/sensor/status#_0": "ok", "digitizer/sensor/status#_1": "error"}
        )
        by_port = {
            s.dimensions["sensor_port"]: s.value_status
            for s in map_soh(soh).samples
            if s.metric_key == "sensor.status"
        }
        assert by_port == {"A": Severity.OK, "B": Severity.CRITICAL}


class Test상태변환:
    def test_모르는_문자열은_UNKNOWN이며_보강_대상으로_남는다(self):
        soh = _soh({"timeStatus": "quantum drift compensating"})
        result = map_soh(soh)
        sample = result.samples[0]
        assert sample.value_status is Severity.UNKNOWN
        assert sample.raw_value == "quantum drift compensating"
        assert result.unmapped_values["timing.status"] == "quantum drift compensating"

    def test_예전_펌웨어의_수치_코드도_읽는다(self):
        soh = _soh({"timeStatus": 2, "timing/phaseLock": 0})
        samples = {s.metric_key: s for s in map_soh(soh).samples}
        assert samples["timing.status"].value_status is Severity.OK
        assert samples["timing.phase_lock"].value_status is Severity.CRITICAL

    def test_아카이브_비활성은_장애가_아니라_수집_제외다(self):
        soh = _soh({"dataArchive/status": "disabled"})
        assert map_soh(soh).samples[0].value_status is Severity.DISABLED


class Test값없음:
    def test_SD_미장착은_0이_아니라_확인_불가다(self):
        """매뉴얼 7.4절: 카드가 마운트되지 않으면 여유 공간이 -1 이다."""
        soh = _soh({"media/freeSpace/removableSD": -1, "media/status/removableSD": "not present"})
        samples = {s.metric_key: s for s in map_soh(soh).samples}
        free = samples["storage.sd_free_bytes"]
        assert free.has_value is False
        assert free.support_state is SupportState.UNKNOWN
        assert free.raw_value == "-1"
        assert samples["storage.sd_status"].value_status is Severity.WARNING

    def test_숫자가_아닌_값은_확인_불가로_남긴다(self):
        soh = _soh({"powerSupply/voltage": "n/a"})
        sample = map_soh(soh).samples[0]
        assert sample.has_value is False
        assert sample.support_state is SupportState.UNKNOWN
        assert sample.raw_value == "n/a"

    def test_없는_채널은_샘플을_만들지_않는다(self):
        soh = _soh({"powerSupply/voltage": 12.0})
        keys = {s.metric_key for s in map_soh(soh).samples}
        assert "device.temperature_c" not in keys
        assert "storage.used_percent" not in keys


class Test미지의채널:
    def test_옮기지_못한_채널_이름을_남긴다(self):
        """새 펌웨어가 채널을 추가했다는 신호다. 조용히 버리면 알 수 없다."""
        soh = _soh({"powerSupply/voltage": 12.0, "newFirmware/mysteryChannel": 42})
        result = map_soh(soh)
        assert unknown_channels(soh, result) == ("newFirmware/mysteryChannel",)

    def test_모두_옮겼으면_비어_있다(self):
        soh = _soh({"powerSupply/voltage": 12.0, "temperature": 30.0})
        result = map_soh(soh)
        assert unknown_channels(soh, result) == ()


def test_모든_샘플은_카탈로그_검증을_통과한다():
    """Adapter 가 카탈로그와 어긋난 샘플을 만들면 여기서 걸린다."""
    soh = _soh(
        {
            "instrumentStatus": "ok",
            "config/commitState": "committed",
            "instrument/systemInfo/firmwareStatus": "ok",
            "systemSoftwareVersion": "3.2.8",
            "temperature": 31.2,
            "powerSupply/voltage": 12.6,
            "system/current": 0.36,
            "timeStatus": "time ok",
            "timing/phaseLock": "fine lock",
            "timing/timeQuality": 100,
            "timing/timeError": 420,
            "timing/timeUncertainty": 1300,
            "timing/lastLockTime": "2026-08-27T02:59:30.000Z",
            "gps/numberOfSatellites": 9,
            "instrument/earthLocation": {
                "latitude": 37.56,
                "longitude": 126.98,
                "elevation": 45.0,
            },
            "controller/store/storePercentageUsed": 61.4,
            "controller/store/storeRecordingStatus": "recording",
            "dataArchive/status": "ok",
            "dataArchive/status/events": "ok",
            "media/status/removableSD": "ok",
            "media/freeSpace/removableSD": 25_000_000_000,
            "digitizer/sensor/status#_0": "ok",
            "sensor/controlLines/state#_0": "expected",
            "digitizer/sensor/massPosition#_0_1": 120_000,
            "externalSoh/voltage#_1": 1_600_000,
        }
    )
    samples = map_soh(soh).samples
    assert len(samples) > 20
    for sample in samples:
        validate_sample(sample)
