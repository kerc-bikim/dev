"""Axis limit resolution for PPSD plots."""

from __future__ import annotations

from typing import Optional, Tuple

from ..config import settings
from .yaxis_units import YAxisType, yaxis_default_limits


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
