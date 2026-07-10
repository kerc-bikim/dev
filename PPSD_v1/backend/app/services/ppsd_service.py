"""PPSD computation and cache layer."""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

from obspy import UTCDateTime
from obspy.signal import PPSD

from ..config import settings
from ..models.schemas import PPSDRequest, PPSDStats
from .fdsn_client import FDSNError, get_waveforms_with_response

logger = logging.getLogger(__name__)


@dataclass
class PPSDResult:
    ppsd: PPSD
    stats: PPSDStats
    job_id: str


def _cache_key(req: PPSDRequest) -> str:
    """Deterministic cache key using only data-identifying parameters.

    Plotting-only options (percentiles, overlay, xaxis, colormap) are excluded
    so different plots reuse the same underlying PPSD computation.
    """
    payload = {
        "n": req.network,
        "s": req.station,
        "l": req.location,
        "c": req.channel,
        "t1": UTCDateTime(req.starttime).isoformat(),
        "t2": UTCDateTime(req.endtime).isoformat(),
    }
    blob = json.dumps(payload, sort_keys=True).encode("utf-8")
    return hashlib.sha1(blob).hexdigest()[:16]


def _cache_path(job_id: str) -> Path:
    return settings.CACHE_DIR / f"{job_id}.npz"


def _load_cached(job_id: str) -> Optional[PPSD]:
    path = _cache_path(job_id)
    if not path.exists():
        return None
    try:
        return PPSD.load_npz(str(path))
    except Exception as exc:  # pragma: no cover
        logger.warning("Failed to load cached PPSD %s: %s", path, exc)
        try:
            path.unlink()
        except OSError:
            pass
        return None


def _save_cached(job_id: str, ppsd: PPSD) -> None:
    path = _cache_path(job_id)
    try:
        ppsd.save_npz(str(path))
    except Exception as exc:  # pragma: no cover
        logger.warning("Failed to persist PPSD cache %s: %s", path, exc)


def _compute(req: PPSDRequest) -> Tuple[PPSD, int]:
    t1 = UTCDateTime(req.starttime)
    t2 = UTCDateTime(req.endtime)

    st, inv = get_waveforms_with_response(
        network=req.network,
        station=req.station,
        location=req.location,
        channel=req.channel,
        starttime=t1,
        endtime=t2,
    )
    st.merge(method=1, fill_value=0)

    tr = st[0]
    ppsd = PPSD(tr.stats, metadata=inv)
    ok = ppsd.add(st)
    if not ok and len(ppsd.times_processed) == 0:
        raise FDSNError(
            "PPSD could not process any segment. "
            "The requested window may be too short or the data is gapped."
        )
    return ppsd, len(ppsd.times_processed)


def compute_or_load(req: PPSDRequest) -> PPSDResult:
    job_id = _cache_key(req)
    cached = _load_cached(job_id)
    from_cache = cached is not None
    if cached is not None:
        ppsd = cached
        segments = len(ppsd.times_processed)
    else:
        ppsd, segments = _compute(req)
        _save_cached(job_id, ppsd)

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
        from_cache=from_cache,
    )
    return PPSDResult(ppsd=ppsd, stats=stats, job_id=job_id)
