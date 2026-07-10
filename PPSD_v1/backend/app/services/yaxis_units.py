"""Convert ObsPy PPSD values (acceleration PSD in dB) to other Y-axis units."""

from __future__ import annotations

from typing import Literal, Tuple

import numpy as np

YAxisType = Literal[
    "acceleration",
    "velocity",
    "velocity_nm",
    "displacement",
    "pressure",
]

YAXIS_LABELS: dict[str, str] = {
    "displacement": "PSD [dB rel. m²/Hz]",
    "velocity": "PSD [dB rel. (m/s)²/Hz]",
    "velocity_nm": "PSD [dB rel. (nm/s)²/Hz]",
    "acceleration": "PSD [dB rel. (m/s²)²/Hz]",
    "pressure": "PSD [dB rel. Pa²/Hz]",
}

# Default Y-axis display range [dB] per unit type (when not overridden in request/.env)
YAXIS_DEFAULT_LIMITS: dict[str, tuple[float, float]] = {
    "velocity": (-220.0, -40.0),
    "velocity_nm": (-40.0, 140.0),  # velocity range + 180 dB (nm/s scale)
    "acceleration": (-210.0, -30.0),
    "displacement": (-120.0, 40.0),
    "pressure": (-20.0, 100.0),
}

# (nm/s)²/Hz vs (m/s)²/Hz: 1 nm/s = 1e-9 m/s → power PSD differs by 10*log10(1e18) = 180 dB
NM_PER_M = 1e9
DB_PER_UNIT_SCALE = 20.0 * np.log10(NM_PER_M)  # 180 dB for velocity nm vs m


def yaxis_ylabel(yaxis_type: YAxisType) -> str:
    return YAXIS_LABELS.get(yaxis_type, YAXIS_LABELS["acceleration"])


def yaxis_default_limits(
    yaxis_type: YAxisType,
) -> tuple[float, float]:
    """Return (y_min, y_max) defaults for the given Y-axis unit type."""
    return YAXIS_DEFAULT_LIMITS.get(
        yaxis_type, YAXIS_DEFAULT_LIMITS["acceleration"]
    )


def _pressure_db_offset() -> float:
    from ..config import settings

    return float(settings.PPSD_PRESSURE_DB_OFFSET)


def db_offset_from_acceleration(
    period: np.ndarray, yaxis_type: YAxisType
) -> np.ndarray:
    """dB in target unit = dB_acceleration - offset(period)."""
    period = np.asarray(period, dtype=float)
    if yaxis_type == "acceleration":
        return np.zeros_like(period)
    if yaxis_type == "pressure":
        return np.full_like(period, -_pressure_db_offset())
    with np.errstate(divide="ignore", invalid="ignore"):
        omega = 2.0 * np.pi / period
        if yaxis_type == "velocity":
            return 20.0 * np.log10(omega)
        if yaxis_type == "velocity_nm":
            # acc → m/s PSD, then m/s → nm/s PSD (+180 dB in power)
            return 20.0 * np.log10(omega) - DB_PER_UNIT_SCALE
        if yaxis_type == "displacement":
            return 40.0 * np.log10(omega)
    raise ValueError(f"Unknown yaxis_type: {yaxis_type}")


def convert_db_curve(
    period: np.ndarray, db_acc: np.ndarray, yaxis_type: YAxisType
) -> np.ndarray:
    return np.asarray(db_acc, dtype=float) - db_offset_from_acceleration(
        period, yaxis_type
    )


def convert_histogram(
    hist: np.ndarray,
    period_bins: np.ndarray,
    db_edges: np.ndarray,
    yaxis_type: YAxisType,
) -> Tuple[np.ndarray, np.ndarray]:
    """Re-bin histogram from acceleration PSD dB to the requested Y unit."""
    hist = np.asarray(hist, dtype=float)
    period_bins = np.asarray(period_bins, dtype=float)
    db_edges = np.asarray(db_edges, dtype=float)

    if yaxis_type == "acceleration":
        return hist, db_edges

    n_period, n_db = hist.shape
    db_centers = 0.5 * (db_edges[:-1] + db_edges[1:])
    step = float(db_edges[1] - db_edges[0])
    offsets = db_offset_from_acceleration(period_bins, yaxis_type)

    tgt = db_centers[None, :] - offsets[:, None]
    finite = np.isfinite(tgt)
    new_lo = float(np.min(tgt[finite])) if np.any(finite) else float(db_edges[0])
    new_hi = float(np.max(tgt[finite])) if np.any(finite) else float(db_edges[-1])
    pad = step * 2
    start = np.floor((new_lo - pad) / step) * step
    end = np.ceil((new_hi + pad) / step) * step
    new_edges = np.arange(start, end + step * 0.5, step)
    new_hist = np.zeros((n_period, len(new_edges) - 1), dtype=float)

    for i in range(n_period):
        for j in range(n_db):
            prob = hist[i, j]
            if prob <= 0:
                continue
            tgt_db = db_centers[j] - offsets[i]
            k = int(np.searchsorted(new_edges, tgt_db) - 1)
            if 0 <= k < new_hist.shape[1]:
                new_hist[i, k] += prob

    return new_hist, new_edges
