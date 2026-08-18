"""계측기 응답 곡선 계산과 Poles/Zeros 편집."""

from __future__ import annotations

import logging
import math
from typing import Any

import numpy as np
from obspy.core.inventory import Channel as ObspyChannel
from obspy.core.inventory.response import PolesZerosResponseStage
from sqlalchemy.orm import Session

from .audit import nslc_of, write_audit
from .crud import get_channel
from .errors import ValidationError
from .inventory import dump_response_xml, load_response
from .models import Channel

LOG = logging.getLogger("stationxml_manager.response")
OUTPUTS = {"DIS": "DISP", "VEL": "VEL", "ACC": "ACC"}
MAX_OVERLAY = 8
MAX_PZ = 64


def _nslc(ch: Channel) -> str:
    try:
        return nslc_of(ch)
    except Exception:  # noqa: BLE001
        return f"channel:{ch.id}"


def logspace_freq(min_freq: float, max_freq: float, npts: int) -> np.ndarray:
    if min_freq <= 0 or max_freq <= 0 or max_freq <= min_freq:
        raise ValidationError("주파수 범위가 올바르지 않습니다")
    if npts < 50 or npts > 1000:
        raise ValidationError("npts는 50–1000이어야 합니다")
    return np.logspace(math.log10(min_freq), math.log10(max_freq), npts)


def _parse_output(output: str) -> str:
    key = (output or "VEL").upper()
    if key == "DISP":
        key = "DIS"
    if key not in OUTPUTS:
        raise ValidationError("output은 DIS, VEL, ACC 중 하나여야 합니다")
    return key


def _nyquist(ch: Channel) -> float:
    return float(ch.sample_rate) / 2.0


def eval_response_curve(
    ch: Channel,
    *,
    output: str = "VEL",
    min_freq: float = 0.001,
    max_freq: float | None = None,
    npts: int = 200,
    frequencies: np.ndarray | None = None,
) -> dict[str, Any]:
    nslc = _nslc(ch)
    if not ch.response_xml:
        raise ValidationError(f"{nslc}: 계측기 응답이 없습니다")
    out = _parse_output(output)
    nyquist = _nyquist(ch)
    if frequencies is None:
        cap = min(nyquist, 100.0)
        used_max = cap if max_freq is None else float(max_freq)
        if used_max > nyquist + 1e-9:
            raise ValidationError("max_freq는 Nyquist 이하여야 합니다")
        frequencies = logspace_freq(float(min_freq), used_max, int(npts))
    else:
        used_max = float(frequencies[-1])
    try:
        resp = load_response(ch.response_xml)
        values = resp.get_evalresp_response_for_frequencies(
            frequencies, output=OUTPUTS[out]
        )
    except ValidationError:
        raise
    except Exception as exc:
        LOG.error("%s: 응답 곡선을 계산하지 못했습니다: %s", nslc, exc)
        raise ValidationError(
            f"{nslc}: 응답 곡선을 계산하지 못했습니다: {exc}"
        ) from exc
    units = _response_units(resp)
    amplitude = [float(abs(x)) for x in values]
    phase_deg = [float(np.angle(x, deg=True)) for x in values]
    if not all(math.isfinite(x) for x in amplitude + phase_deg):
        raise ValidationError(f"{nslc}: 응답 곡선에 유한하지 않은 값이 있습니다")
    return {
        "channel_id": ch.id,
        "nslc": nslc,
        "start_time": ch.start_time,
        "sample_rate": ch.sample_rate,
        "output": out,
        "input_units": units[0],
        "output_units": units[1],
        "frequencies": [float(x) for x in frequencies],
        "amplitude": amplitude,
        "phase_deg": phase_deg,
        "response_source": ch.response_source,
        "max_freq": used_max,
        "min_freq": float(frequencies[0]),
        "npts": int(len(frequencies)),
    }


def _response_units(resp) -> tuple[str | None, str | None]:
    sens = getattr(resp, "instrument_sensitivity", None)
    if sens is None:
        return None, None
    return (
        getattr(sens.input_units, "name", None) if sens.input_units else None,
        getattr(sens.output_units, "name", None) if sens.output_units else None,
    )


def overlay_response_curves(
    session: Session,
    ids: list[int],
    *,
    output: str = "VEL",
    min_freq: float = 0.001,
    max_freq: float | None = None,
    npts: int = 200,
) -> dict[str, Any]:
    out = _parse_output(output)
    if not ids:
        raise ValidationError("ids가 필요합니다")
    if len(ids) > MAX_OVERLAY:
        raise ValidationError("겹치기는 최대 8채널입니다")
    channels: list[Channel] = []
    errors: list[dict[str, Any]] = []
    for cid in ids:
        ch = session.query(Channel).get(cid)
        if ch is None:
            errors.append(
                {
                    "channel_id": cid,
                    "nslc": f"id:{cid}",
                    "reason": "채널을 찾을 수 없습니다",
                }
            )
            continue
        channels.append(ch)
    if not channels and errors:
        return {
            "output": out,
            "min_freq": float(min_freq),
            "max_freq": float(max_freq or 100),
            "npts": int(npts),
            "frequencies": [],
            "series": [],
            "errors": errors,
        }
    nyquists = [_nyquist(ch) for ch in channels]
    shared_max = min(min(nyquists), 100.0)
    if max_freq is not None:
        if float(max_freq) > min(nyquists) + 1e-9:
            raise ValidationError("max_freq는 Nyquist 이하여야 합니다")
        shared_max = float(max_freq)
    frequencies = logspace_freq(float(min_freq), shared_max, int(npts))
    series: list[dict[str, Any]] = []
    for ch in channels:
        try:
            curve = eval_response_curve(
                ch, output=out, frequencies=frequencies, npts=int(npts)
            )
            series.append(
                {
                    "channel_id": curve["channel_id"],
                    "nslc": curve["nslc"],
                    "start_time": curve["start_time"],
                    "sample_rate": curve["sample_rate"],
                    "amplitude": curve["amplitude"],
                    "phase_deg": curve["phase_deg"],
                    "response_source": curve["response_source"],
                }
            )
        except ValidationError as exc:
            LOG.warning("%s", exc.message)
            errors.append(
                {"channel_id": ch.id, "nslc": _nslc(ch), "reason": exc.message}
            )
    return {
        "output": out,
        "min_freq": float(min_freq),
        "max_freq": shared_max,
        "npts": int(npts),
        "frequencies": [float(x) for x in frequencies],
        "series": series,
        "errors": errors,
    }


def _complex_items(values) -> list[dict[str, float]]:
    items = []
    for value in values or []:
        items.append({"real": float(value.real), "imag": float(value.imag)})
    return items


def _parse_complex_list(values: Any, label: str) -> list[complex]:
    if not isinstance(values, list):
        raise ValidationError(f"{label}는 목록이어야 합니다")
    if len(values) > MAX_PZ:
        raise ValidationError(f"{label}는 최대 {MAX_PZ}개입니다")
    parsed: list[complex] = []
    for item in values:
        try:
            real = float(item["real"])
            imag = float(item["imag"])
        except (TypeError, KeyError, ValueError) as exc:
            raise ValidationError(f"{label} 값이 올바르지 않습니다") from exc
        if not math.isfinite(real) or not math.isfinite(imag):
            raise ValidationError(f"{label}는 유한한 실수여야 합니다")
        parsed.append(complex(real, imag))
    return parsed


def unpaired_conjugates(values: list[complex]) -> bool:
    unused = list(values)
    while unused:
        current = unused.pop(0)
        if abs(current.imag) < 1e-12:
            continue
        match = None
        for index, other in enumerate(unused):
            if (
                abs(other.real - current.real) < 1e-9
                and abs(other.imag + current.imag) < 1e-9
            ):
                match = index
                break
        if match is None:
            return True
        unused.pop(match)
    return False


def recompute_a0(
    poles: list[complex],
    zeros: list[complex],
    fnorm: float,
    pz_type: str | None,
) -> float:
    if fnorm <= 0:
        return 1.0
    if "HERTZ" in (pz_type or "").upper():
        s = 1j * fnorm
    else:
        s = 1j * 2 * math.pi * fnorm
    num = 1 + 0j
    den = 1 + 0j
    for zero in zeros:
        num *= s - zero
    for pole in poles:
        den *= s - pole
    if den == 0 or abs(num / den) == 0:
        return 1.0
    return float(1.0 / abs(num / den))


def _stage_dict(stage) -> dict[str, Any]:
    data: dict[str, Any] = {
        "stage_sequence_number": stage.stage_sequence_number,
        "type": type(stage).__name__.replace("ResponseStage", ""),
        "editable": isinstance(stage, PolesZerosResponseStage),
        "input_units": getattr(getattr(stage, "input_units", None), "name", None),
        "output_units": getattr(getattr(stage, "output_units", None), "name", None),
    }
    if isinstance(stage, PolesZerosResponseStage):
        data.update(
            {
                "pz_transfer_function_type": stage.pz_transfer_function_type,
                "normalization_frequency": stage.normalization_frequency,
                "normalization_factor": stage.normalization_factor,
                "stage_gain": stage.stage_gain,
                "stage_gain_frequency": stage.stage_gain_frequency,
                "poles": _complex_items(stage.poles),
                "zeros": _complex_items(stage.zeros),
            }
        )
    return data


def list_response_stages(ch: Channel) -> dict[str, Any]:
    nslc = _nslc(ch)
    if not ch.response_xml:
        raise ValidationError(f"{nslc}: 계측기 응답이 없습니다")
    try:
        resp = load_response(ch.response_xml)
    except Exception as exc:
        raise ValidationError(
            f"{nslc}: 저장된 응답 XML을 읽지 못했습니다: {exc}"
        ) from exc
    return {
        "channel_id": ch.id,
        "nslc": nslc,
        "response_source": ch.response_source,
        "stages": [_stage_dict(stage) for stage in (resp.response_stages or [])],
    }


def _stage_snapshot(stage) -> dict[str, Any]:
    if not isinstance(stage, PolesZerosResponseStage):
        return {"stage_sequence_number": getattr(stage, "stage_sequence_number", None)}
    return {
        "stage_sequence_number": stage.stage_sequence_number,
        "poles": _complex_items(stage.poles),
        "zeros": _complex_items(stage.zeros),
        "stage_gain": stage.stage_gain,
        "normalization_frequency": stage.normalization_frequency,
        "normalization_factor": stage.normalization_factor,
    }


def update_pz_stage(
    session: Session,
    channel_id: int,
    stage_number: int,
    payload: dict[str, Any],
    actor: str | None,
) -> dict[str, Any]:
    allowed = {"poles", "zeros", "stage_gain", "normalization_frequency"}
    extra = set(payload) - allowed
    if extra:
        raise ValidationError(
            "normalization_factor는 직접 수정할 수 없습니다"
            if "normalization_factor" in extra
            else f"허용되지 않는 필드입니다: {', '.join(sorted(extra))}"
        )
    ch = get_channel(session, channel_id)
    nslc = _nslc(ch)
    if not ch.response_xml:
        raise ValidationError(f"{nslc}: 계측기 응답이 없습니다")
    try:
        resp = load_response(ch.response_xml)
    except Exception as exc:
        raise ValidationError(
            f"{nslc}: 저장된 응답 XML을 읽지 못했습니다: {exc}"
        ) from exc
    stage = next(
        (
            item
            for item in (resp.response_stages or [])
            if item.stage_sequence_number == stage_number
        ),
        None,
    )
    if stage is None:
        raise ValidationError(f"stage {stage_number}을 찾을 수 없습니다")
    if not isinstance(stage, PolesZerosResponseStage):
        raise ValidationError(f"stage {stage_number}은 Poles/Zeros가 아닙니다")
    before = _stage_snapshot(stage)
    before["response_source"] = ch.response_source
    poles = (
        _parse_complex_list(payload["poles"], "poles")
        if "poles" in payload
        else list(stage.poles or [])
    )
    zeros = (
        _parse_complex_list(payload["zeros"], "zeros")
        if "zeros" in payload
        else list(stage.zeros or [])
    )
    if "stage_gain" in payload:
        try:
            gain = float(payload["stage_gain"])
        except (TypeError, ValueError) as exc:
            raise ValidationError("stage_gain이 올바르지 않습니다") from exc
        if not math.isfinite(gain):
            raise ValidationError("stage_gain이 올바르지 않습니다")
        stage.stage_gain = gain
    if "normalization_frequency" in payload:
        try:
            fnorm = float(payload["normalization_frequency"])
        except (TypeError, ValueError) as exc:
            raise ValidationError(
                "normalization_frequency가 올바르지 않습니다"
            ) from exc
        if fnorm <= 0 or not math.isfinite(fnorm):
            raise ValidationError("normalization_frequency가 올바르지 않습니다")
        stage.normalization_frequency = fnorm
    stage.poles = poles
    stage.zeros = zeros
    stage.normalization_factor = recompute_a0(
        poles,
        zeros,
        float(stage.normalization_frequency or 1.0),
        stage.pz_transfer_function_type,
    )
    dummy = ObspyChannel(
        code=ch.channel,
        location_code=ch.location or "",
        latitude=ch.station.latitude,
        longitude=ch.station.longitude,
        elevation=ch.station.elevation,
        depth=ch.depth or 0.0,
        azimuth=ch.azimuth,
        dip=ch.dip,
        sample_rate=ch.sample_rate,
    )
    dummy.response = resp
    original_xml = ch.response_xml
    original_source = ch.response_source

    def _restore_response() -> None:
        ch.response_xml = original_xml
        ch.response_source = original_source
        session.flush()

    try:
        xml = dump_response_xml(dummy)
        if not xml:
            raise ValidationError(f"{nslc}: 수정한 응답을 저장하지 못했습니다")
        ch.response_xml = xml
        session.flush()
        eval_response_curve(ch, output="VEL", npts=50)
    except ValidationError as exc:
        _restore_response()
        if "계산하지 못했습니다" in exc.message or "유한하지 않은" in exc.message:
            raise ValidationError(
                f"{nslc}: 수정한 응답을 계산하지 못해 저장하지 않았습니다: {exc.message}"
            ) from exc
        raise
    except Exception as exc:
        _restore_response()
        LOG.error("%s: 수정한 응답을 계산하지 못했습니다: %s", nslc, exc)
        raise ValidationError(
            f"{nslc}: 수정한 응답을 계산하지 못해 저장하지 않았습니다: {exc}"
        ) from exc
    ch.response_source = "edited"
    after = _stage_snapshot(stage)
    after["response_source"] = "edited"
    write_audit(
        session,
        action="update",
        entity_type="channel",
        entity_id=ch.id,
        source="ui",
        actor=actor,
        nslc=nslc,
        before=before,
        after=after,
        summary=f"Poles/Zeros 수정 (stage {stage_number})",
    )
    session.commit()
    session.refresh(ch)
    result = list_response_stages(ch)
    warnings = []
    if unpaired_conjugates(poles) or unpaired_conjugates(zeros):
        warnings.append("켤레가 아닌 극이 있습니다")
        LOG.warning("%s: 켤레가 아닌 극이 있습니다", nslc)
    if warnings:
        result["warnings"] = warnings
    return result


def parse_ids(raw: str | None) -> list[int]:
    if not raw or not raw.strip():
        raise ValidationError("ids가 필요합니다")
    seen: set[int] = set()
    ids: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            value = int(part)
        except ValueError as exc:
            raise ValidationError("ids는 숫자여야 합니다") from exc
        if value in seen:
            continue
        seen.add(value)
        ids.append(value)
    if not ids:
        raise ValidationError("ids가 필요합니다")
    if len(ids) > MAX_OVERLAY:
        raise ValidationError("겹치기는 최대 8채널입니다")
    return ids
