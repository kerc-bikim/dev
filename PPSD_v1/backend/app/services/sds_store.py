"""SeisComP SDS-style storage helpers for persisted daily PPSD npz results.

Layout (mirrors SeisComP Data Structure, with a `.npz` suffix):

    <SDS>/<YEAR>/<NET>/<STA>/<CHAN>.<TYPE>/
        <NET>.<STA>.<LOC>.<CHAN>.<TYPE>.<YEAR>.<JULDAY>.npz

There is one npz per channel per UTC day. When PPSD compute parameters change,
the existing file is recomputed and overwritten (see :mod:`ppsd_service`).
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

from obspy import UTCDateTime

from ..config import settings

DEFAULT_DATA_TYPE = "D"


def _day_start(t: UTCDateTime) -> UTCDateTime:
    """Return the UTC midnight (00:00:00) at the start of the day of ``t``."""
    return UTCDateTime(t.year, t.month, t.day)


def iter_utc_days(start: UTCDateTime, end: UTCDateTime) -> Iterator[UTCDateTime]:
    """Yield UTC midnight timestamps for every day intersecting [start, end].

    The last day is included when ``end`` falls exactly on a day boundary only
    if the window has non-zero length up to that instant; a window ending at
    exactly midnight does not pull in the following (empty) day.
    """
    if end <= start:
        return
    day = _day_start(start)
    last = _day_start(end - 1e-6)
    while day <= last:
        yield day
        day = day + 86400


def sds_npz_path(
    network: str,
    station: str,
    location: str,
    channel: str,
    day: UTCDateTime,
    data_type: str = DEFAULT_DATA_TYPE,
    root: Path | None = None,
) -> Path:
    """Build the SDS-style npz path for a single UTC day of a channel."""
    sds_root = root or settings.PPSD_SDS_DIR
    year = f"{day.year:04d}"
    julday = f"{day.julday:03d}"
    loc = location or ""
    chan_dir = f"{channel}.{data_type}"
    filename = f"{network}.{station}.{loc}.{channel}.{data_type}.{year}.{julday}.npz"
    return sds_root / year / network / station / chan_dir / filename
