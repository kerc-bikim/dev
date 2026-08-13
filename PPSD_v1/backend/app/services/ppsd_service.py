"""PPSD computation with SeisComP SDS-style daily npz storage.

A request is split into UTC day chunks. Each day is computed once and stored as
an SDS-style npz file (see :mod:`sds_store`); subsequent requests reuse or
accumulate those day files. Days covered by a request are merged into a single
in-memory PPSD via ``PPSD.load_npz`` + ``PPSD.add_npz``.

There is one npz per channel per UTC day. When PPSD compute parameters change,
the existing file is recomputed and overwritten.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np
from obspy import UTCDateTime
from obspy.signal import PPSD

from ..models.schemas import PPSDRequest, PPSDStats
from .fdsn_client import FDSNError, get_waveforms_with_response
from .sds_store import iter_utc_days, sds_npz_path
from .yaxis_units import is_infrasound_channel

logger = logging.getLogger(__name__)

# dB binning for infrasound pressure PSD (dB rel. Pa^2/Hz). Wide enough to cover
# the IDC global infrasound noise models (~-100 .. +40 dB) plus margin so real
# values are never folded into the edge bins.
INFRASOUND_DB_BINS = (-120.0, 80.0, 1.0)

_DUMMY_METADATA = {"poles": [], "zeros": [], "sensitivity": 1.0}


def _expected_handling(channel: str | None) -> str:
    """Special-handling tag expected for a channel ('infrasound' or '')."""
    return "infrasound" if is_infrasound_channel(channel) else ""


def _ppsd_ctor_kwargs(req: PPSDRequest) -> dict:
    """Keyword arguments shared by all PPSD(...) constructors for a request."""
    return {
        "ppsd_length": req.ppsd_length,
        "overlap": req.overlap,
        "period_step_octaves": req.period_step_octaves,
        "period_smoothing_width_octaves": req.period_smoothing_width_octaves,
    }


def _read_npz_scalar(data, key: str):
    """Read a scalar value from an np.load() archive."""
    value = data[key]
    return value.item() if hasattr(value, "item") else value


def _expected_period_binning(req: PPSDRequest, sampling_rate: float) -> np.ndarray:
    """Build the period-binning matrix that ``req`` would produce at ``sampling_rate``."""
    from obspy.core.trace import Stats

    stats = Stats()
    stats.network = req.network
    stats.station = req.station
    stats.location = req.location or ""
    stats.channel = req.channel
    stats.sampling_rate = sampling_rate

    ctor = _ppsd_ctor_kwargs(req)
    if is_infrasound_channel(req.channel):
        ref = PPSD(
            stats,
            metadata=_DUMMY_METADATA,
            special_handling="infrasound",
            db_bins=INFRASOUND_DB_BINS,
            **ctor,
        )
    else:
        ref = PPSD(stats, metadata=_DUMMY_METADATA, **ctor)
    return ref._period_binning


def _npz_matches_request(path, req: PPSDRequest) -> bool:
    """Return True when an on-disk npz was computed with the same parameters as ``req``."""
    try:
        with np.load(str(path), allow_pickle=True) as data:
            stored_length = float(_read_npz_scalar(data, "ppsd_length"))
            stored_overlap = float(_read_npz_scalar(data, "overlap"))
            if abs(stored_length - req.ppsd_length) > 1e-6:
                return False
            if abs(stored_overlap - req.overlap) > 1e-6:
                return False

            if "special_handling" in data.files:
                stored_handling = _read_npz_scalar(data, "special_handling")
                if stored_handling is None or stored_handling == "":
                    stored_handling = ""
                else:
                    stored_handling = str(stored_handling)
            else:
                stored_handling = ""
            if stored_handling != _expected_handling(req.channel):
                return False

            if "_period_binning" not in data.files:
                return False
            stored_binning = np.asarray(data["_period_binning"], dtype=float)
            sampling_rate = float(_read_npz_scalar(data, "sampling_rate"))
            expected = _expected_period_binning(req, sampling_rate)
            if stored_binning.shape != expected.shape:
                return False
            return np.allclose(stored_binning, expected, rtol=1e-6, atol=1e-9)
    except Exception as exc:  # pragma: no cover
        logger.warning("Could not validate cached PPSD %s: %s", path, exc)
        return False


@dataclass
class PPSDResult:
    ppsd: PPSD
    stats: PPSDStats
    job_id: str


def _job_id(req: PPSDRequest, days: List[UTCDateTime]) -> str:
    """Stable identifier for a request based on channel + covered UTC days."""
    payload = {
        "n": req.network,
        "s": req.station,
        "l": req.location,
        "c": req.channel,
        "days": [d.strftime("%Y-%m-%d") for d in days],
    }
    blob = json.dumps(payload, sort_keys=True).encode("utf-8")
    return hashlib.sha1(blob).hexdigest()[:16]


def _compute_day(req: PPSDRequest, day: UTCDateTime) -> Optional[PPSD]:
    """Compute a full-UTC-day PPSD for the channel, or None if no data."""
    t1 = day
    t2 = day + 86400
    try:
        st, inv = get_waveforms_with_response(
            network=req.network,
            station=req.station,
            location=req.location,
            channel=req.channel,
            starttime=t1,
            endtime=t2,
        )
    except FDSNError as exc:
        logger.info("No data for %s.%s %s: %s", req.network, req.station, day.date, exc)
        return None

    st.merge(method=1, fill_value=0)
    if len(st) == 0:
        return None

    tr = st[0]
    ctor = _ppsd_ctor_kwargs(req)
    if is_infrasound_channel(req.channel):
        # Pressure/infrasound: remove response but do NOT differentiate to
        # acceleration, and use a pressure-appropriate dB range.
        ppsd = PPSD(
            tr.stats,
            metadata=inv,
            special_handling="infrasound",
            db_bins=INFRASOUND_DB_BINS,
            **ctor,
        )
    else:
        ppsd = PPSD(tr.stats, metadata=inv, **ctor)
    ppsd.add(st)
    if len(ppsd.times_processed) == 0:
        return None
    return ppsd


def _get_or_build_day(req: PPSDRequest, day: UTCDateTime) -> Tuple[Optional[str], bool]:
    """Return (npz_path, from_cache) for a day, computing+saving if needed.

    npz_path is None when there is no data for that day. An existing flat SDS
    file is reused only when its stored compute parameters match ``req``;
    otherwise it is recomputed and overwritten.
    """
    path = sds_npz_path(req.network, req.station, req.location, req.channel, day)
    if path.exists() and _npz_matches_request(path, req):
        return str(path), True

    ppsd = _compute_day(req, day)
    if ppsd is None:
        return None, False

    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        ppsd.save_npz(str(path))
    except Exception as exc:  # pragma: no cover
        logger.warning("Failed to persist SDS PPSD %s: %s", path, exc)
    return str(path), False


def _merge_days(paths: List[str]) -> PPSD:
    """Load the first day npz and accumulate the rest into one PPSD."""
    ppsd = PPSD.load_npz(paths[0])
    for extra in paths[1:]:
        try:
            ppsd.add_npz(extra)
        except Exception as exc:  # pragma: no cover
            logger.warning("Failed to merge SDS PPSD %s: %s", extra, exc)
    return ppsd


def compute_or_load(req: PPSDRequest) -> PPSDResult:
    days = list(iter_utc_days(UTCDateTime(req.starttime), UTCDateTime(req.endtime)))
    if not days:
        raise FDSNError("Requested time window is empty.")

    paths: List[str] = []
    all_cached = True
    for day in days:
        path, from_cache = _get_or_build_day(req, day)
        if path is not None:
            paths.append(path)
            all_cached = all_cached and from_cache

    if not paths:
        raise FDSNError(
            "PPSD could not process any segment. No data was available for the "
            "requested day(s), or the window is too short/gappy."
        )

    ppsd = _merge_days(paths)
    segments = len(ppsd.times_processed)
    if segments == 0:
        raise FDSNError(
            "PPSD has no processed segments (data window too short or gappy)."
        )

    channel_id = ".".join(
        [ppsd.network, ppsd.station, ppsd.location or "", ppsd.channel]
    )
    stats = PPSDStats(
        segments_used=segments,
        starttime=UTCDateTime(min(ppsd.times_processed)).datetime,
        endtime=UTCDateTime(max(ppsd.times_processed)).datetime,
        channel_id=channel_id,
        sampling_rate=float(ppsd.sampling_rate) if ppsd.sampling_rate else None,
        from_cache=all_cached,
    )
    return PPSDResult(ppsd=ppsd, stats=stats, job_id=_job_id(req, days))
