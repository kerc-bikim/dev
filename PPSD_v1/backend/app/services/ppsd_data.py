"""Serialize PPSD results into JSON-friendly numeric data for D3/WebGL rendering.

Replaces server-side matplotlib rendering: the browser draws the histogram
(WebGL) and axes/curves (D3) from these arrays, reproducing the previous
plot format.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import List, Optional

import numpy as np
from obspy.signal import PPSD
from obspy.signal.spectral_estimation import (
    get_idc_infra_hi_noise,
    get_idc_infra_low_noise,
    get_nhnm,
    get_nlnm,
)

from ..models.schemas import CompareRequest, PlotOptions, PPSDRequest, YAxisType
from .axis_limits import auto_x_limits, resolve_axis_limits
from .yaxis_units import (
    convert_db_curve,
    convert_histogram,
    is_infrasound_channel,
    yaxis_default_limits,
    yaxis_ylabel,
)

# International standard infrasound noise models (IDC / Brown et al. 2012),
# already expressed as pressure PSD in dB rel. Pa^2/Hz.
LOW_NOISE_LABEL = "IDC infrasound LNM"
HIGH_NOISE_LABEL = "IDC infrasound HNM"

logger = logging.getLogger(__name__)


def _title_time(dt: datetime) -> str:
    """Format a datetime for chart titles without a timezone suffix (+00:00)."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def _x_from_period(period: np.ndarray, xaxis: str) -> np.ndarray:
    period = np.asarray(period, dtype=float)
    if xaxis == "frequency":
        return 1.0 / period
    return period


def _edges_from_centers(centers: np.ndarray) -> np.ndarray:
    log_c = np.log10(centers)
    mids = 0.5 * (log_c[1:] + log_c[:-1])
    first = 2 * log_c[0] - mids[0]
    last = 2 * log_c[-1] - mids[-1]
    return np.power(10.0, np.concatenate([[first], mids, [last]]))


def _x_label(xaxis: str) -> str:
    return "Frequency [Hz]" if xaxis == "frequency" else "Period [s]"


def _curve(period, db_acc, yaxis_type: YAxisType, xaxis: str) -> dict:
    period = np.asarray(period, dtype=float)
    db = convert_db_curve(period, np.asarray(db_acc, dtype=float), yaxis_type)
    x = _x_from_period(period, xaxis)
    order = np.argsort(x)
    return {"x": x[order].tolist(), "db": db[order].tolist()}


def _noise_models(
    yaxis_type: YAxisType, xaxis: str, show: bool
) -> Optional[dict]:
    if not show:
        return None
    if yaxis_type == "pressure":
        # IDC models are already pressure PSD (dB rel. Pa^2/Hz) -> no conversion.
        low_p, low_db = get_idc_infra_low_noise()
        high_p, high_db = get_idc_infra_hi_noise()
        low_x = _x_from_period(low_p, xaxis)
        high_x = _x_from_period(high_p, xaxis)
        low_order = np.argsort(low_x)
        high_order = np.argsort(high_x)
        return {
            "low": {
                "label": LOW_NOISE_LABEL,
                "x": low_x[low_order].tolist(),
                "db": np.asarray(low_db)[low_order].tolist(),
            },
            "high": {
                "label": HIGH_NOISE_LABEL,
                "x": high_x[high_order].tolist(),
                "db": np.asarray(high_db)[high_order].tolist(),
            },
        }
    nlnm_p, nlnm_db = get_nlnm()
    nhnm_p, nhnm_db = get_nhnm()
    low = _curve(nlnm_p, nlnm_db, yaxis_type, xaxis)
    high = _curve(nhnm_p, nhnm_db, yaxis_type, xaxis)
    low["label"] = "NLNM"
    high["label"] = "NHNM"
    return {"low": low, "high": high}


def _resolved_axis(
    opts_x_min,
    opts_x_max,
    opts_y_min,
    opts_y_max,
    yaxis_type: YAxisType,
    data_xmin: float,
    data_xmax: float,
    *,
    xaxis: str = "period",
    sampling_rate: Optional[float] = None,
    ppsd_length: Optional[float] = None,
) -> dict:
    rx_min, rx_max, ry_min, ry_max = resolve_axis_limits(
        opts_x_min, opts_x_max, opts_y_min, opts_y_max, yaxis_type
    )
    type_ymin, type_ymax = yaxis_default_limits(yaxis_type)
    auto_xmin, auto_xmax = auto_x_limits(
        data_xmin,
        data_xmax,
        xaxis=xaxis,
        sampling_rate=sampling_rate,
        ppsd_length=ppsd_length,
    )
    return {
        "x_min": rx_min if rx_min is not None else auto_xmin,
        "x_max": rx_max if rx_max is not None else auto_xmax,
        "y_min": ry_min if ry_min is not None else type_ymin,
        "y_max": ry_max if ry_max is not None else type_ymax,
    }


def _hist_to_nested(hist: np.ndarray) -> list:
    """2D probability array -> nested lists, NaN -> None (clipped cells)."""
    out = []
    for row in hist:
        out.append([None if not np.isfinite(v) else float(v) for v in row])
    return out


def ppsd_heatmap_data(
    ppsd: PPSD,
    req: PPSDRequest,
    options: PlotOptions | None = None,
) -> dict:
    """Build the heatmap + overlay data for a single PPSD."""
    opts = options or PlotOptions(
        percentile_low=req.percentile_low,
        percentile_high=req.percentile_high,
        show_overlay=req.show_overlay,
        clip_to_percentile=req.clip_to_percentile,
        xaxis=req.xaxis,
        yaxis_type=req.yaxis_type,
        show_noise_models=req.show_noise_models,
        show_mean=req.show_mean,
        show_mode=req.show_mode,
        cmap=req.cmap,
        x_min=req.x_min,
        x_max=req.x_max,
        y_min=req.y_min,
        y_max=req.y_max,
    )
    ytype: YAxisType = opts.yaxis_type
    # Infrasound/pressure channels store pressure PSD directly (no acceleration
    # conversion is meaningful), so always display them in pressure units.
    forced_pressure = is_infrasound_channel(ppsd.channel) and ytype != "pressure"
    if is_infrasound_channel(ppsd.channel):
        ytype = "pressure"
    # If the client's Y range was picked for a different (seismic) unit, drop it
    # so pressure defaults are used and the data isn't clipped off-screen.
    y_min_opt = None if forced_pressure else opts.y_min
    y_max_opt = None if forced_pressure else opts.y_max

    period_bins = np.asarray(ppsd.period_bin_centers)
    db_edges = np.asarray(ppsd.db_bin_edges)
    hist = ppsd.current_histogram
    if hist is None:
        ppsd.calculate_histogram()
        hist = ppsd.current_histogram
    # ObsPy's current_histogram holds raw counts; normalize to probability [%]
    # per period column (matching ObsPy's PPSD.plot: count * 100 / n_segments).
    n_used = ppsd.current_histogram_count or 1
    display = np.asarray(hist, dtype=float).copy() * (100.0 / n_used)

    if opts.clip_to_percentile:
        low_p, low_db = ppsd.get_percentile(opts.percentile_low)
        high_p, high_db = ppsd.get_percentile(opts.percentile_high)
        low_at = np.interp(period_bins, np.asarray(low_p), np.asarray(low_db))
        high_at = np.interp(period_bins, np.asarray(high_p), np.asarray(high_db))
        db_centers_acc = 0.5 * (db_edges[:-1] + db_edges[1:])
        for i in range(display.shape[0]):
            mask = (db_centers_acc < low_at[i]) | (db_centers_acc > high_at[i])
            display[i, mask] = np.nan

    display, db_edges = convert_histogram(display, period_bins, db_edges, ytype)

    if opts.xaxis == "frequency":
        x_centers = 1.0 / period_bins
        order = np.argsort(x_centers)
        x_centers = x_centers[order]
        display = display[order, :]
    else:
        x_centers = period_bins

    x_edges = _edges_from_centers(x_centers)

    with np.errstate(invalid="ignore"):
        vmax = float(np.nanmax(display)) if np.any(np.isfinite(display)) else 1.0
    if vmax <= 0:
        vmax = 1.0

    overlays: dict = {}
    if opts.show_overlay:
        p_low, db_low = ppsd.get_percentile(opts.percentile_low)
        p_high, db_high = ppsd.get_percentile(opts.percentile_high)
        overlays["percentile_low"] = {
            "perc": opts.percentile_low,
            **_curve(p_low, db_low, ytype, opts.xaxis),
        }
        overlays["percentile_high"] = {
            "perc": opts.percentile_high,
            **_curve(p_high, db_high, ytype, opts.xaxis),
        }
    if opts.show_mode:
        try:
            mode_p, mode_db = ppsd.get_mode()
            overlays["mode"] = _curve(mode_p, mode_db, ytype, opts.xaxis)
        except Exception as exc:  # pragma: no cover
            logger.warning("Could not compute mode: %s", exc)
    if opts.show_mean:
        try:
            mean_p, mean_db = ppsd.get_mean()
            overlays["mean"] = _curve(mean_p, mean_db, ytype, opts.xaxis)
        except Exception as exc:  # pragma: no cover
            logger.warning("Could not compute mean: %s", exc)

    channel_id = ".".join(
        [ppsd.network, ppsd.station, ppsd.location or "", ppsd.channel]
    )
    n_segments = len(ppsd.times_processed)
    title = (
        f"{channel_id}   "
        f"{_title_time(req.starttime)}  to  {_title_time(req.endtime)}   "
        f"({n_segments} segments)"
    )

    return {
        "kind": "heatmap",
        "xaxis": opts.xaxis,
        "xlabel": _x_label(opts.xaxis),
        "ylabel": yaxis_ylabel(ytype),
        "cmap": opts.cmap,
        "x_edges": x_edges.tolist(),
        "db_edges": db_edges.tolist(),
        "histogram": _hist_to_nested(display),
        "vmax": vmax,
        "overlays": overlays,
        "noise_models": _noise_models(ytype, opts.xaxis, opts.show_noise_models),
        "axis": _resolved_axis(
            opts.x_min, opts.x_max, y_min_opt, y_max_opt, ytype,
            float(x_edges.min()), float(x_edges.max()),
            xaxis=opts.xaxis,
            sampling_rate=float(ppsd.sampling_rate) if ppsd.sampling_rate else None,
            ppsd_length=float(ppsd.ppsd_length) if ppsd.ppsd_length else None,
        ),
        "title": title,
    }


def compare_curves_data(
    entries: List[tuple],
    req: CompareRequest,
    *,
    title: Optional[str] = None,
) -> dict:
    """Build percentile line-curve data for multiple PPSDs on one axes."""
    from ..models.schemas import ChannelTarget

    ytype: YAxisType = req.yaxis_type
    series: List[dict] = []
    x_min_data: Optional[float] = None
    x_max_data: Optional[float] = None

    for target, ppsd in entries:
        assert isinstance(target, ChannelTarget)
        color = target.color or "#333333"
        label_base = target.label or ".".join(
            filter(None, [target.network, target.station, target.location, target.channel])
        )
        curves = []
        for perc in req.percentiles:
            p_p, p_db = ppsd.get_percentile(perc)
            c = _curve(p_p, p_db, ytype, req.xaxis)
            if c["x"]:
                lo, hi = min(c["x"]), max(c["x"])
                x_min_data = lo if x_min_data is None else min(x_min_data, lo)
                x_max_data = hi if x_max_data is None else max(x_max_data, hi)
            perc_label = int(perc) if perc == int(perc) else perc
            curves.append({"perc": perc, "label": f"P{perc_label}", **c})
        series.append({"label": label_base, "color": color, "curves": curves})

    default_xmin = x_min_data if x_min_data is not None else 0.01
    default_xmax = x_max_data if x_max_data is not None else 100.0

    rates = [
        float(ppsd.sampling_rate)
        for _, ppsd in entries
        if getattr(ppsd, "sampling_rate", None)
    ]
    lengths = [
        float(ppsd.ppsd_length)
        for _, ppsd in entries
        if getattr(ppsd, "ppsd_length", None)
    ]
    # Most restrictive high-freq limit; longest segment for low-freq floor.
    compare_rate = min(rates) if rates else None
    compare_length = max(lengths) if lengths else None

    if title is None:
        title = (
            f"PPSD Compare Station   "
            f"{_title_time(req.starttime)}  to  {_title_time(req.endtime)}"
        )

    return {
        "kind": "compare",
        "xaxis": req.xaxis,
        "xlabel": _x_label(req.xaxis),
        "ylabel": yaxis_ylabel(ytype),
        "series": series,
        "noise_models": _noise_models(ytype, req.xaxis, req.show_noise_models),
        "axis": _resolved_axis(
            req.x_min, req.x_max, req.y_min, req.y_max, ytype,
            default_xmin, default_xmax,
            xaxis=req.xaxis,
            sampling_rate=compare_rate,
            ppsd_length=compare_length,
        ),
        "title": title,
    }
