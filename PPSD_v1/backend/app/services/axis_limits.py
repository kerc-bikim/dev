"""Axis limit resolution for PPSD plots."""

from __future__ import annotations

from typing import Optional, Tuple

from ..config import settings
from .yaxis_units import YAxisType, yaxis_default_limits


def sample_rate_x_limits(
    sampling_rate: float,
    ppsd_length: float,
    xaxis: str,
) -> Tuple[float, float]:
    """Return a meaningful X range from sample rate and PPSD segment length.

    Short-period / high-frequency bound is Nyquist (``2/fs`` or ``fs/2``).

    Long-period / low-frequency bound is capped so roughly ≥8 cycles fit in
    one PPSD segment, and never exceeds ObsPy's default plot upper period
    (179 s). That avoids the sparse, spike-like long-period bins that appear
    when fine ``period_step_octaves`` is used out to ``ppsd_length``.
    """
    fs = float(sampling_rate)
    length = float(ppsd_length)
    if not (fs > 0 and length > 0):
        return (0.01, 100.0)

    # ObsPy PPSD.plot default period_lim upper bound.
    display_period_max = 179.0
    min_cycles = 8.0

    nyquist = fs / 2.0
    t_min = 1.0 / nyquist  # Nyquist period = 2/fs
    t_max = min(length / min_cycles, display_period_max)
    if t_max <= t_min:
        t_max = min(max(t_min * 10.0, display_period_max), display_period_max)
    if t_max <= t_min:
        t_max = t_min * 10.0

    if xaxis == "frequency":
        return (1.0 / t_max, 1.0 / t_min)
    return (t_min, t_max)


def auto_x_limits(
    data_xmin: float,
    data_xmax: float,
    *,
    xaxis: str,
    sampling_rate: Optional[float] = None,
    ppsd_length: Optional[float] = None,
) -> Tuple[float, float]:
    """Pick auto X limits, preferring sample-rate-aware bounds clipped to data."""
    if (
        sampling_rate is None
        or ppsd_length is None
        or sampling_rate <= 0
        or ppsd_length <= 0
    ):
        return (data_xmin, data_xmax)

    sr_lo, sr_hi = sample_rate_x_limits(sampling_rate, ppsd_length, xaxis)
    # Intersect with available histogram / curve coverage.
    lo = max(sr_lo, data_xmin) if data_xmin > 0 else sr_lo
    hi = min(sr_hi, data_xmax) if data_xmax > 0 else sr_hi
    if not (lo > 0 and hi > 0 and lo < hi):
        return (data_xmin, data_xmax)
    return (lo, hi)


def resolve_axis_limits(
    x_min: Optional[float],
    x_max: Optional[float],
    y_min: Optional[float],
    y_max: Optional[float],
    yaxis_type: Optional[YAxisType] = None,
) -> Tuple[Optional[float], Optional[float], Optional[float], Optional[float]]:
    """Merge request values with .env and per-unit Y defaults."""
    type_y_min, type_y_max = (
        yaxis_default_limits(yaxis_type) if yaxis_type else (None, None)
    )
    return (
        x_min if x_min is not None else settings.PPSD_X_MIN,
        x_max if x_max is not None else settings.PPSD_X_MAX,
        y_min
        if y_min is not None
        else settings.PPSD_Y_MIN
        if settings.PPSD_Y_MIN is not None
        else type_y_min,
        y_max
        if y_max is not None
        else settings.PPSD_Y_MAX
        if settings.PPSD_Y_MAX is not None
        else type_y_max,
    )


def apply_axis_limits(
    ax,
    *,
    x_min: Optional[float],
    x_max: Optional[float],
    y_min: Optional[float],
    y_max: Optional[float],
    yaxis_type: Optional[YAxisType] = None,
    default_xmin: float,
    default_xmax: float,
    default_ymin: float,
    default_ymax: float,
) -> None:
    """Set axis limits: request/env/unit defaults, else data-derived fallback."""
    rx_min, rx_max, ry_min, ry_max = resolve_axis_limits(
        x_min, x_max, y_min, y_max, yaxis_type
    )
    x_lo = rx_min if rx_min is not None else default_xmin
    x_hi = rx_max if rx_max is not None else default_xmax
    y_lo = ry_min if ry_min is not None else default_ymin
    y_hi = ry_max if ry_max is not None else default_ymax
    if x_lo > 0 and x_hi > 0 and x_lo < x_hi:
        ax.set_xlim(x_lo, x_hi)
    if y_lo < y_hi:
        ax.set_ylim(y_lo, y_hi)
