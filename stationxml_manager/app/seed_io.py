"""Dataless SEED 읽기·쓰기.

ObsPy 1.4.1은 Inventory.write(format="SEED")를 지원하지 않는다.
읽기는 read_inventory(format="SEED"), 쓰기는 xseed Parser 블록ette로
논리 레코드를 만든다 (커스텀 바이너리 writer가 아니라 ObsPy 직렬화).
"""

from __future__ import annotations

import logging
from io import BytesIO
from typing import Any

from obspy import UTCDateTime, read_inventory
from obspy.core.inventory import Inventory
from obspy.core.inventory.response import (
    CoefficientsTypeResponseStage,
    FIRResponseStage,
    PolesZerosResponseStage,
    ResponseStage,
)
from obspy.io.xseed import Parser
from obspy.io.xseed.blockette import (
    Blockette010,
    Blockette030,
    Blockette033,
    Blockette034,
    Blockette050,
    Blockette052,
    Blockette053,
    Blockette054,
    Blockette057,
    Blockette058,
    Blockette061,
)
from sqlalchemy.orm import Session, joinedload

from .catalog import catalog_map
from .crud import list_channels
from .errors import AppError, ValidationError
from .inventory import build_inventory, load_response
from .models import Network
from .xml_io import inventory_to_hierarchy

LOG = logging.getLogger("stationxml_manager.export")
SEED_SUFFIXES = {".seed", ".dataless", ".dlsv"}
DATA_TYPES = {"D", "R", "Q", "M"}
HEADER_TYPES = {"V", "A", "S"}
SEED_MARKERS = HEADER_TYPES | DATA_TYPES
WRITABLE_STAGES = (
    PolesZerosResponseStage,
    CoefficientsTypeResponseStage,
    FIRResponseStage,
)
MAX_BLOCKETTE_BYTES = 9999


def _looks_seq(buf: bytes) -> bool:
    return len(buf) >= 6 and buf[:6].isdigit()


def _record_length(data: bytes) -> int:
    if len(data) < 8 or not _looks_seq(data) or not data[6:7].isalpha():
        return 4096
    for rec_len in (4096, 512, 256):
        nxt = rec_len
        if (
            len(data) >= nxt + 8
            and _looks_seq(data[nxt : nxt + 6])
            and data[nxt + 6 : nxt + 7].isalpha()
        ):
            return rec_len
    for rec_len in (4096, 512, 256):
        if len(data) % rec_len == 0:
            return rec_len
    return 4096


def classify_seed(data: bytes) -> str:
    types: set[str] = set()
    rec_len = _record_length(data)
    for offset in range(0, max(0, len(data) - 6), rec_len):
        if not _looks_seq(data[offset : offset + 6]):
            continue
        marker = data[offset + 6 : offset + 7]
        if marker.isalpha():
            kind = marker.decode("ascii", errors="ignore")
            if kind in SEED_MARKERS:
                types.add(kind)
    has_header = bool(types & HEADER_TYPES)
    has_data = bool(types & DATA_TYPES)
    if has_data and not has_header:
        return "miniseed"
    if has_data and has_header:
        return "full"
    if has_header:
        return "dataless"
    return "unknown"


def read_seed(path_or_buf, session: Session) -> dict[str, Any]:
    if hasattr(path_or_buf, "read"):
        data = path_or_buf.read()
        if isinstance(data, str):
            data = data.encode("utf-8")
        raw = data
    else:
        with open(path_or_buf, "rb") as handle:
            raw = handle.read()
    kind = classify_seed(raw)
    if kind == "miniseed":
        raise ValidationError(
            "스테이션 헤더가 없는 MiniSEED는 가져올 수 없습니다. dataless SEED를 올리세요"
        )
    try:
        inv = read_inventory(BytesIO(raw), format="SEED")
    except ValidationError:
        raise
    except Exception as exc:
        raise ValidationError(f"SEED 파일을 읽지 못했습니다: {exc}") from exc
    if inv is None or len(inv) == 0:
        raise ValidationError(
            "스테이션 헤더가 없는 MiniSEED는 가져올 수 없습니다. dataless SEED를 올리세요"
        )
    for net in inv:
        code = (net.code or "").strip()
        if not code:
            raise ValidationError("네트워크 코드(B50 F16)가 필요합니다")
    hierarchy = inventory_to_hierarchy(inv, session)
    if kind == "full":
        hierarchy["warnings"].append("파형 레코드는 무시하고 메타데이터만 가져왔습니다")
    return hierarchy


def _ascii_ok(value: str | None) -> bool:
    if not value:
        return True
    return all(ord(char) < 128 for char in value)


def _stage_writable(stage) -> bool:
    if isinstance(stage, WRITABLE_STAGES):
        return True
    return type(stage) is ResponseStage


def _stage_blockette_too_long(stage) -> bool:
    if isinstance(stage, CoefficientsTypeResponseStage):
        count = len(list(stage.numerator or [])) + len(list(stage.denominator or []))
        return count * 24 + 120 > MAX_BLOCKETTE_BYTES
    if isinstance(stage, FIRResponseStage):
        return len(list(stage.coefficients or [])) * 14 + 80 > MAX_BLOCKETTE_BYTES
    if isinstance(stage, PolesZerosResponseStage):
        count = len(list(stage.poles or [])) + len(list(stage.zeros or []))
        return count * 48 + 120 > MAX_BLOCKETTE_BYTES
    return False


def collect_dataless_errors(session: Session) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    channels = list(list_channels(session))
    if not channels:
        return [{"nslc": "", "reason": "내보낼 채널이 없습니다"}]
    for ch in channels:
        net = ch.station.network.code if ch.station and ch.station.network else ""
        nslc = f"{net}.{ch.station.code}.{ch.location or '--'}.{ch.channel}"
        if len(net) != 2:
            errors.append(
                {
                    "nslc": nslc,
                    "reason": f"{net or '?'}: 네트워크 코드는 2자여야 합니다",
                }
            )
        if len(ch.station.code) > 5:
            errors.append(
                {"nslc": nslc, "reason": f"{nslc}: 관측소 코드는 5자 이하여야 합니다"}
            )
        if len(ch.channel) != 3:
            errors.append(
                {"nslc": nslc, "reason": f"{nslc}: 채널 코드는 3자여야 합니다"}
            )
        if len(ch.location or "") > 2:
            errors.append(
                {"nslc": nslc, "reason": f"{nslc}: 위치코드는 2자 이하여야 합니다"}
            )
        if not ch.response_xml:
            errors.append({"nslc": nslc, "reason": f"{nslc}: 계측기 응답이 없습니다"})
            continue
        try:
            resp = load_response(ch.response_xml)
        except Exception as exc:
            errors.append(
                {
                    "nslc": nslc,
                    "reason": f"{nslc}: 저장된 응답 XML을 읽지 못했습니다: {exc}",
                }
            )
            continue
        for stage in resp.response_stages or []:
            if not _stage_writable(stage):
                errors.append(
                    {
                        "nslc": nslc,
                        "reason": (
                            f"{nslc}: SEED로 쓸 수 없는 응답 단계 "
                            f"{type(stage).__name__}"
                        ),
                    }
                )
            elif _stage_blockette_too_long(stage):
                errors.append(
                    {
                        "nslc": nslc,
                        "reason": f"{nslc}: SEED 응답 단계가 너무 깁니다",
                    }
                )
    return errors


def _prepare_seed_inventory(inv: Inventory) -> list[str]:
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
            if sta.description and not _ascii_ok(sta.description):
                sta.description = None
    return warnings


def export_dataless_bytes(session: Session) -> tuple[bytes, list[str]]:
    errors = collect_dataless_errors(session)
    if errors:
        for item in errors:
            LOG.error("%s", item["reason"])
        raise AppError(
            f"Dataless SEED를 만들 수 없습니다. 문제 채널 {len(errors)}개",
            400,
            errors=errors,
        )
    from .models import Station

    nets = (
        session.query(Network)
        .options(joinedload(Network.stations).joinedload(Station.channels))
        .order_by(Network.code)
        .all()
    )
    inv = build_inventory(nets, catalog_map(session))
    warnings = _prepare_seed_inventory(inv)
    try:
        data = inventory_to_seed_bytes(inv)
    except AppError:
        raise
    except Exception as exc:
        LOG.error("SEED 응답 단계를 쓰지 못했습니다: %s", exc)
        raise AppError(f"SEED 응답 단계를 쓰지 못했습니다: {exc}", 400) from exc
    LOG.info(
        "dataless %s channels", sum(len(sta.channels) for net in inv for sta in net)
    )
    return data, warnings


def _unit_name(value) -> str:
    if value is None:
        return "UNKNOWN"
    name = getattr(value, "name", None) or str(value)
    return (name or "UNKNOWN").upper()


def _pz_type(stage: PolesZerosResponseStage) -> str:
    raw = (stage.pz_transfer_function_type or "").upper()
    if "HERTZ" in raw:
        return "B"
    if "DIGITAL" in raw or "Z-TRANSFORM" in raw:
        return "D"
    return "A"


def _coeff_type(stage: CoefficientsTypeResponseStage) -> str:
    raw = (getattr(stage, "cf_transfer_function_type", None) or "").upper()
    if "ANALOG" in raw:
        return "A"
    return "D"


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
        if label and label not in parts:
            parts.append(label)
    return " + ".join(parts)[:50] if parts else "UNKNOWN"


def _seed_time(value) -> UTCDateTime | str:
    if not value:
        return ""
    if not isinstance(value, UTCDateTime):
        value = UTCDateTime(value)
    return value


def _append_blockette(station_blkts: list, blkt, nslc: str) -> None:
    encoded = blkt.get_seed()
    if len(encoded) > MAX_BLOCKETTE_BYTES:
        seq = getattr(blkt, "stage_sequence_number", "?")
        reason = f"{nslc}: SEED 응답 단계가 너무 깁니다 (stage {seq})"
        raise AppError(reason, 400, errors=[{"nslc": nslc, "reason": reason}])
    station_blkts.append(blkt)


def inventory_to_seed_bytes(inv: Inventory) -> bytes:
    """Inventory를 dataless SEED 바이트로 직렬화한다."""
    units: dict[str, int] = {}
    abbrevs: dict[str, int] = {}
    unit_blockettes: list[Blockette034] = []
    abbrev_blockettes: list[Blockette033] = []

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

    starts: list[UTCDateTime] = []
    stations_out: list[list] = []
    for net in inv:
        net_abbrev = abbrev_code(net.description or net.code)
        for sta in net:
            channels = list(sta.channels)
            site_name = sta.site.name if sta.site and sta.site.name else sta.code
            b50 = Blockette050()
            b50.station_call_letters = sta.code
            b50.latitude = float(sta.latitude)
            b50.longitude = float(sta.longitude)
            b50.elevation = float(sta.elevation or 0.0)
            b50.number_of_channels = len(channels)
            b50.number_of_station_comments = 0
            b50.site_name = site_name
            b50.network_identifier_code = net_abbrev
            b50.word_order_32bit = 3210
            b50.word_order_16bit = 10
            b50.start_effective_date = _seed_time(sta.creation_date) or UTCDateTime(
                1970, 1, 1
            )
            b50.end_effective_date = _seed_time(sta.termination_date)
            b50.update_flag = "N"
            b50.network_code = net.code
            station_blkts: list = [b50]
            for cha in channels:
                if cha.start_date:
                    starts.append(cha.start_date)
                lat = float(cha.latitude if cha.latitude is not None else sta.latitude)
                lon = float(
                    cha.longitude if cha.longitude is not None else sta.longitude
                )
                elev = float(
                    cha.elevation if cha.elevation is not None else sta.elevation or 0
                )
                resp = cha.response
                first_in = None
                if resp and resp.response_stages:
                    first_in = _unit_name(
                        getattr(resp.response_stages[0], "input_units", None)
                    )
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
                b52.sample_rate = float(cha.sample_rate)
                b52.max_clock_drift = float(
                    cha.clock_drift_in_seconds_per_sample or 0.0
                )
                b52.number_of_comments = 0
                b52.channel_flags = _channel_flags(cha)
                b52.start_date = _seed_time(cha.start_date) or UTCDateTime(1970, 1, 1)
                b52.end_date = _seed_time(cha.end_date)
                b52.update_flag = "N"
                station_blkts.append(b52)
                nslc = f"{net.code}.{sta.code}.{cha.location_code or '--'}.{cha.code}"
                if resp is None:
                    reason = f"{nslc}: 계측기 응답이 없습니다"
                    raise AppError(
                        reason, 400, errors=[{"nslc": nslc, "reason": reason}]
                    )
                for stage in resp.response_stages or []:
                    if not _stage_writable(stage):
                        reason = (
                            f"{nslc}: SEED로 쓸 수 없는 응답 단계 "
                            f"{type(stage).__name__}"
                        )
                        raise AppError(
                            reason, 400, errors=[{"nslc": nslc, "reason": reason}]
                        )
                    seq = int(stage.stage_sequence_number)
                    in_u = unit_code(_unit_name(getattr(stage, "input_units", None)))
                    out_u = unit_code(_unit_name(getattr(stage, "output_units", None)))
                    if isinstance(stage, PolesZerosResponseStage):
                        zeros = list(stage.zeros or [])
                        poles = list(stage.poles or [])
                        b53 = Blockette053()
                        b53.transfer_function_types = _pz_type(stage)
                        b53.stage_sequence_number = seq
                        b53.stage_signal_input_units = in_u
                        b53.stage_signal_output_units = out_u
                        b53.A0_normalization_factor = float(
                            stage.normalization_factor or 1.0
                        )
                        b53.normalization_frequency = float(
                            stage.normalization_frequency or 1.0
                        )
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
                        _append_blockette(station_blkts, b53, nslc)
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
                        _append_blockette(station_blkts, b54, nslc)
                    elif isinstance(stage, FIRResponseStage):
                        coeffs = list(stage.coefficients or [])
                        symmetry = (getattr(stage, "symmetry", None) or "NONE").upper()
                        b61 = Blockette061()
                        b61.stage_sequence_number = seq
                        b61.response_name = "FIR"
                        b61.symmetry_code = {"NONE": "A", "ODD": "B", "EVEN": "C"}.get(
                            symmetry, "A"
                        )
                        b61.signal_in_units = in_u
                        b61.signal_out_units = out_u
                        b61.number_of_coefficients = len(coeffs)
                        b61.FIR_coefficient = [float(x) for x in coeffs]
                        _append_blockette(station_blkts, b61, nslc)
                    if getattr(stage, "decimation_input_sample_rate", None):
                        b57 = Blockette057()
                        b57.stage_sequence_number = seq
                        b57.input_sample_rate = float(
                            stage.decimation_input_sample_rate
                        )
                        b57.decimation_factor = int(stage.decimation_factor or 1)
                        b57.decimation_offset = int(stage.decimation_offset or 0)
                        b57.estimated_delay = float(stage.decimation_delay or 0.0)
                        b57.correction_applied = float(
                            stage.decimation_correction or 0.0
                        )
                        _append_blockette(station_blkts, b57, nslc)
                    if stage.stage_gain is not None:
                        b58 = Blockette058()
                        b58.stage_sequence_number = seq
                        b58.sensitivity_gain = float(stage.stage_gain)
                        b58.frequency = float(stage.stage_gain_frequency or 1.0)
                        b58.number_of_history_values = 0
                        _append_blockette(station_blkts, b58, nslc)
                if resp.instrument_sensitivity is not None:
                    sens = resp.instrument_sensitivity
                    b0 = Blockette058()
                    b0.stage_sequence_number = 0
                    b0.sensitivity_gain = float(sens.value)
                    b0.frequency = float(sens.frequency or 1.0)
                    b0.number_of_history_values = 0
                    _append_blockette(station_blkts, b0, nslc)
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
    b10.originating_organization = "stationxml_manager"
    b10.label = "dataless"

    parser = Parser()
    parser.volume = [b10]
    parser.abbreviations = [b30] + abbrev_blockettes + unit_blockettes
    parser.stations = stations_out
    return parser.get_seed()


def looks_like_seed_name(name: str) -> bool:
    lower = name.lower()
    return any(lower.endswith(suffix) for suffix in SEED_SUFFIXES)
