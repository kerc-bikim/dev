"""ObsPy Inventory → dataless SEED.

ObsPy 1.5 은 Inventory.write(format='SEED') 가 없다. xseed Parser 블록ette로
논리 레코드만 만든다. 프로젝트 StationXML 원문은 여기서 다시 쓰지 않는다.
"""

from __future__ import annotations

from obspy import UTCDateTime
from obspy.core.inventory import Inventory
from obspy.core.inventory.response import (
    CoefficientsTypeResponseStage,
    FIRResponseStage,
    PolesZerosResponseStage,
    PolynomialResponseStage,
    ResponseListResponseStage,
)
from obspy.io.xseed import Parser
from obspy.io.xseed.blockette import (
    Blockette010,
    Blockette030,
    Blockette031,
    Blockette033,
    Blockette034,
    Blockette050,
    Blockette051,
    Blockette052,
    Blockette053,
    Blockette054,
    Blockette057,
    Blockette058,
    Blockette059,
    Blockette061,
)

SITE_MAX = 60
FIR_NAME_MAX = 25
COMMENT_MAX = 70
NETWORK_SEED_MAX = 2


class SeedWriteError(Exception):
    pass


def _ascii_ok(value: str | None) -> bool:
    if not value:
        return True
    return all(ord(ch) < 128 for ch in value)


def _unit_name(value) -> str:
    if value is None:
        return "UNKNOWN"
    name = getattr(value, "name", None) or str(value)
    return (name or "UNKNOWN").upper()


def _pz_type(stage: PolesZerosResponseStage) -> str:
    raw = (stage.pz_transfer_function_type or "").upper()
    if "HERTZ" in raw or "HZ" in raw:
        return "B"
    if "DIGITAL" in raw or "Z-TRANSFORM" in raw:
        return "D"
    return "A"


def _coeff_type(stage: CoefficientsTypeResponseStage) -> str:
    raw = (getattr(stage, "cf_transfer_function_type", None) or "").upper()
    if "HERTZ" in raw or "HZ" in raw:
        return "B"
    if "ANALOG" in raw:
        return "A"
    return "D"


def _is_digital_stage(stage) -> bool:
    if isinstance(stage, FIRResponseStage):
        return True
    if isinstance(stage, CoefficientsTypeResponseStage):
        return _coeff_type(stage) == "D"
    if isinstance(stage, PolesZerosResponseStage):
        return _pz_type(stage) == "D"
    return False


def _comment_text(comment) -> str:
    value = getattr(comment, "value", None)
    if value is None:
        value = str(comment or "")
    text = " ".join(str(value).split())
    return text.replace("_", "-")


def _comment_times(comment, fallback_start, fallback_end):
    begin = getattr(comment, "begin_effective_time", None) or fallback_start
    end = getattr(comment, "end_effective_time", None)
    if end is None:
        end = fallback_end
    return _seed_time(begin) or UTCDateTime(1970, 1, 1), _seed_time(end)


def _channel_flags(cha) -> str:
    types = getattr(cha, "types", None) or []
    mapping = {
        "CONTINUOUS": "C",
        "GEOPHYSICAL": "G",
        "TRIGGERED": "T",
        "HEALTH": "H",
        "WEATHER": "W",
        "FLAG": "F",
    }
    flags = "".join(mapping[item] for item in types if item in mapping)
    return flags or "CG"


def _instrument_name(cha) -> str:
    parts: list[str] = []
    for eq in (cha.sensor, cha.data_logger):
        if eq is None:
            continue
        label = " ".join(p for p in (eq.manufacturer, eq.model) if p)
        if not label:
            label = (eq.description or "").strip()
        if label and label not in parts:
            parts.append(label)
    text = parts[0] if parts else "UNKNOWN"
    return text[:50]


def _seed_time(value):
    if not value:
        return ""
    if not isinstance(value, UTCDateTime):
        value = UTCDateTime(value)
    return value


def prepare_seed_inventory(inv: Inventory) -> list[str]:
    warnings: list[str] = []
    for net in inv:
        for sta in net:
            site_name = sta.site.name if sta.site else None
            if site_name and not _ascii_ok(site_name):
                if sta.site:
                    sta.site.name = sta.code
                warnings.append(
                    f"{net.code}.{sta.code}: 한글 사이트명을 관측소 코드로 대체했습니다"
                )
            elif site_name and len(site_name) > SITE_MAX and sta.site:
                sta.site.name = site_name[:SITE_MAX]
                warnings.append(f"{net.code}.{sta.code}: 사이트명을 {SITE_MAX}자로 잘랐습니다")
            if sta.description and not _ascii_ok(sta.description):
                sta.description = None
            kept = []
            for comment in sta.comments or []:
                text = _comment_text(comment)
                if not text or not _ascii_ok(text):
                    warnings.append(
                        f"{net.code}.{sta.code}: ASCII가 아닌 관측소 코멘트는 SEED에 넣지 않습니다"
                    )
                    continue
                kept.append(comment)
            sta.comments = kept
            for cha in sta:
                kept_ch = []
                for comment in cha.comments or []:
                    text = _comment_text(comment)
                    if not text or not _ascii_ok(text):
                        warnings.append(
                            f"{net.code}.{sta.code}.{cha.code}: ASCII가 아닌 채널 코멘트는 SEED에 넣지 않습니다"
                        )
                        continue
                    kept_ch.append(comment)
                cha.comments = kept_ch
    return warnings


def inventory_to_seed_bytes(
    inv: Inventory,
    *,
    organization: str = "PDCC Web",
    label: str = "dataless",
) -> bytes:
    units: dict[str, int] = {}
    abbrevs: dict[str, int] = {}
    comments: dict[str, int] = {}
    unit_blockettes: list[Blockette034] = []
    abbrev_blockettes: list[Blockette033] = []
    comment_blockettes: list[Blockette031] = []

    def unit_code(name: str | None) -> int:
        key = (name or "UNKNOWN").upper()
        if key not in units:
            units[key] = len(units) + 1
            blkt = Blockette034()
            blkt.unit_lookup_code = units[key]
            blkt.unit_name = key[:20]
            blkt.unit_description = key[:50]
            unit_blockettes.append(blkt)
        return units[key]

    def abbrev_code(name: str | None) -> int:
        key = (name or "UNKNOWN").strip() or "UNKNOWN"
        if key not in abbrevs:
            abbrevs[key] = len(abbrevs) + 1
            blkt = Blockette033()
            blkt.abbreviation_lookup_code = abbrevs[key]
            blkt.abbreviation_description = key[:50]
            abbrev_blockettes.append(blkt)
        return abbrevs[key]

    def comment_code(text: str, class_code: str) -> int:
        cleaned = (text or "")[:COMMENT_MAX] or "comment"
        key = f"{class_code}:{cleaned}"
        if key not in comments:
            comments[key] = len(comments) + 1
            blkt = Blockette031()
            blkt.comment_code_key = comments[key]
            blkt.comment_class_code = class_code
            blkt.description_of_comment = cleaned
            blkt.units_of_comment_level = 0
            comment_blockettes.append(blkt)
        return comments[key]

    starts: list[UTCDateTime] = []
    stations_out: list[list] = []
    for net in inv:
        net_code = (net.code or "XX").strip().upper() or "XX"
        if len(net_code) > NETWORK_SEED_MAX:
            raise SeedWriteError(
                f"SEED 2.4 네트워크 코드는 {NETWORK_SEED_MAX}자입니다. 지금 값은 {net_code}입니다"
            )
        net_abbrev = abbrev_code(net.description or net_code)
        for sta in net:
            channels = list(sta.channels)
            site_name = sta.site.name if sta.site and sta.site.name else sta.code
            if not _ascii_ok(site_name):
                site_name = sta.code
            sta_comments = list(sta.comments or [])
            b50 = Blockette050()
            b50.station_call_letters = sta.code
            b50.latitude = float(sta.latitude)
            b50.longitude = float(sta.longitude)
            b50.elevation = float(sta.elevation or 0.0)
            b50.number_of_channels = len(channels)
            b50.number_of_station_comments = len(sta_comments)
            b50.site_name = site_name[:SITE_MAX]
            b50.network_identifier_code = net_abbrev
            b50.word_order_32bit = 3210
            b50.word_order_16bit = 10
            b50.start_effective_date = _seed_time(sta.start_date) or UTCDateTime(1970, 1, 1)
            b50.end_effective_date = _seed_time(sta.end_date)
            b50.update_flag = "N"
            b50.network_code = net_code
            station_blkts: list = [b50]
            for comment in sta_comments:
                begin, end = _comment_times(comment, sta.start_date, sta.end_date)
                b51 = Blockette051()
                b51.beginning_effective_time = begin
                b51.end_effective_time = end
                b51.comment_code_key = comment_code(_comment_text(comment), "S")
                b51.comment_level = 0
                station_blkts.append(b51)
            for cha in channels:
                if cha.start_date:
                    starts.append(cha.start_date)
                lat = float(cha.latitude if cha.latitude is not None else sta.latitude)
                lon = float(cha.longitude if cha.longitude is not None else sta.longitude)
                elev = float(
                    cha.elevation if cha.elevation is not None else sta.elevation or 0
                )
                resp = cha.response
                first_in = None
                if resp and resp.response_stages:
                    first_in = _unit_name(getattr(resp.response_stages[0], "input_units", None))
                elif resp and resp.instrument_sensitivity:
                    first_in = _unit_name(resp.instrument_sensitivity.input_units)
                b52 = Blockette052()
                b52.location_identifier = cha.location_code or ""
                b52.channel_identifier = cha.code
                b52.subchannel_identifier = 0
                b52.instrument_identifier = abbrev_code(_instrument_name(cha))
                b52.optional_comment = ""
                b52.units_of_signal_response = unit_code(first_in or "M/S")
                b52.units_of_calibration_input = unit_code("V")
                b52.latitude = lat
                b52.longitude = lon
                b52.elevation = elev
                b52.local_depth = float(cha.depth or 0.0)
                b52.azimuth = float(cha.azimuth if cha.azimuth is not None else 0.0)
                b52.dip = float(cha.dip if cha.dip is not None else 0.0)
                b52.data_format_identifier_code = 1
                b52.data_record_length = 12
                b52.sample_rate = float(cha.sample_rate or 0.0)
                b52.max_clock_drift = float(cha.clock_drift_in_seconds_per_sample or 0.0)
                cha_comments = list(cha.comments or [])
                b52.number_of_comments = len(cha_comments)
                b52.channel_flags = _channel_flags(cha)
                b52.start_date = _seed_time(cha.start_date) or UTCDateTime(1970, 1, 1)
                b52.end_date = _seed_time(cha.end_date)
                b52.update_flag = "N"
                station_blkts.append(b52)
                if resp is None:
                    raise SeedWriteError(
                        f"{net.code}.{sta.code}.{cha.location_code or ''}.{cha.code}: 계측기 응답이 없습니다"
                    )
                for stage in resp.response_stages or []:
                    seq = int(stage.stage_sequence_number)
                    in_u = unit_code(_unit_name(getattr(stage, "input_units", None)))
                    out_u = unit_code(_unit_name(getattr(stage, "output_units", None)))
                    if isinstance(stage, PolynomialResponseStage):
                        raise SeedWriteError(
                            f"{net.code}.{sta.code}.{cha.code} 단계 {seq}: Polynomial 응답은 SEED로 쓰지 않습니다"
                        )
                    if isinstance(stage, ResponseListResponseStage):
                        raise SeedWriteError(
                            f"{net.code}.{sta.code}.{cha.code} 단계 {seq}: ResponseList는 SEED로 쓰지 않습니다"
                        )
                    if _is_digital_stage(stage) and not getattr(
                        stage, "decimation_input_sample_rate", None
                    ):
                        raise SeedWriteError(
                            f"{net.code}.{sta.code}.{cha.code} 단계 {seq}: "
                            "디지털 단계에는 데시메이션(Blockette 057)이 필요합니다"
                        )
                    if isinstance(stage, PolesZerosResponseStage):
                        zeros = list(stage.zeros or [])
                        poles = list(stage.poles or [])
                        b53 = Blockette053()
                        b53.transfer_function_types = _pz_type(stage)
                        b53.stage_sequence_number = seq
                        b53.stage_signal_input_units = in_u
                        b53.stage_signal_output_units = out_u
                        b53.A0_normalization_factor = float(stage.normalization_factor or 1.0)
                        b53.normalization_frequency = float(stage.normalization_frequency or 1.0)
                        b53.number_of_complex_zeros = len(zeros)
                        b53.real_zero = [float(z.real) for z in zeros]
                        b53.imaginary_zero = [float(z.imag) for z in zeros]
                        b53.real_zero_error = [0.0] * len(zeros)
                        b53.imaginary_zero_error = [0.0] * len(zeros)
                        b53.number_of_complex_poles = len(poles)
                        b53.real_pole = [float(p.real) for p in poles]
                        b53.imaginary_pole = [float(p.imag) for p in poles]
                        b53.real_pole_error = [0.0] * len(poles)
                        b53.imaginary_pole_error = [0.0] * len(poles)
                        station_blkts.append(b53)
                    elif isinstance(stage, CoefficientsTypeResponseStage):
                        nums = list(stage.numerator or [])
                        dens = list(stage.denominator or [])
                        b54 = Blockette054()
                        b54.response_type = _coeff_type(stage)
                        b54.stage_sequence_number = seq
                        b54.signal_input_units = in_u
                        b54.signal_output_units = out_u
                        b54.number_of_numerators = len(nums)
                        b54.numerator_coefficient = [float(x) for x in nums]
                        b54.numerator_error = [0.0] * len(nums)
                        b54.number_of_denominators = len(dens)
                        b54.denominator_coefficient = [float(x) for x in dens]
                        b54.denominator_error = [0.0] * len(dens)
                        station_blkts.append(b54)
                    elif isinstance(stage, FIRResponseStage):
                        coeffs = list(stage.coefficients or [])
                        symmetry = (getattr(stage, "symmetry", None) or "NONE").upper()
                        b61 = Blockette061()
                        b61.stage_sequence_number = seq
                        name = getattr(stage, "name", None) or "FIR"
                        b61.response_name = str(name)[:FIR_NAME_MAX] or "FIR"
                        b61.symmetry_code = {"NONE": "A", "ODD": "B", "EVEN": "C"}.get(
                            symmetry, "A"
                        )
                        b61.signal_in_units = in_u
                        b61.signal_out_units = out_u
                        b61.number_of_coefficients = len(coeffs)
                        b61.FIR_coefficient = [float(x) for x in coeffs]
                        station_blkts.append(b61)
                    if getattr(stage, "decimation_input_sample_rate", None):
                        b57 = Blockette057()
                        b57.stage_sequence_number = seq
                        b57.input_sample_rate = float(stage.decimation_input_sample_rate)
                        b57.decimation_factor = int(stage.decimation_factor or 1)
                        b57.decimation_offset = int(stage.decimation_offset or 0)
                        b57.estimated_delay = float(stage.decimation_delay or 0.0)
                        b57.correction_applied = float(stage.decimation_correction or 0.0)
                        station_blkts.append(b57)
                    if stage.stage_gain is not None:
                        b58 = Blockette058()
                        b58.stage_sequence_number = seq
                        b58.sensitivity_gain = float(stage.stage_gain)
                        b58.frequency = float(stage.stage_gain_frequency or 1.0)
                        b58.number_of_history_values = 0
                        station_blkts.append(b58)
                if resp.instrument_sensitivity is None:
                    raise SeedWriteError(
                        f"{net.code}.{sta.code}.{cha.location_code or ''}.{cha.code}: "
                        "채널 전체 감도(Blockette 058 stage 0)가 필요합니다"
                    )
                sens = resp.instrument_sensitivity
                b0 = Blockette058()
                b0.stage_sequence_number = 0
                b0.sensitivity_gain = float(sens.value)
                b0.frequency = float(sens.frequency or 1.0)
                b0.number_of_history_values = 0
                station_blkts.append(b0)
                for comment in cha_comments:
                    begin, end = _comment_times(comment, cha.start_date, cha.end_date)
                    b59 = Blockette059()
                    b59.beginning_of_effective_time = begin
                    b59.end_effective_time = end
                    b59.comment_code_key = comment_code(_comment_text(comment), "C")
                    b59.comment_level = 0
                    station_blkts.append(b59)
            stations_out.append(station_blkts)

    b30 = Blockette030()
    b30.short_descriptive_name = "Steim-2 Integer Compression Format"
    b30.data_format_identifier_code = 1
    b30.data_family_type = 50
    b30.number_of_decoder_keys = 1
    b30.decoder_keys = ["M0"]

    b10 = Blockette010()
    b10.version_of_format = 2.4
    b10.logical_record_length = 12
    b10.beginning_time = min(starts) if starts else UTCDateTime(1970, 1, 1)
    b10.end_time = UTCDateTime(2038, 1, 1)
    b10.volume_time = UTCDateTime()
    b10.originating_organization = (organization or "PDCC Web")[:80]
    b10.label = (label or "dataless")[:80]

    parser = Parser()
    parser.volume = [b10]
    parser.abbreviations = [b30] + abbrev_blockettes + unit_blockettes + comment_blockettes
    parser.stations = stations_out
    return parser.get_seed()
