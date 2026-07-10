"""Matplotlib rendering of PPSDs, MUSTANG-style with percentile options."""

from __future__ import annotations

import io
import logging

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
from obspy.signal import PPSD
from obspy.signal.spectral_estimation import get_nlnm, get_nhnm

from ..models.schemas import CompareRequest, PlotOptions, PPSDRequest, YAxisType
from .axis_limits import apply_axis_limits
from .yaxis_units import convert_db_curve, convert_histogram, yaxis_default_limits, yaxis_ylabel

logger = logging.getLogger(__name__)

LINE_STYLES = ["-", "--", ":", "-."]


def _x_from_period(period: np.ndarray, xaxis: str) -> np.ndarray:
    period = np.asarray(period)
    if xaxis == "frequency":
        return 1.0 / period
    return period


def _plot_db_curve(
    ax,
    periods: np.ndarray,
    db_acc: np.ndarray,
    yaxis_type: YAxisType,
    xaxis: str,
    **plot_kw,
) -> tuple[np.ndarray, np.ndarray]:
    periods = np.asarray(periods)
    db = convert_db_curve(periods, db_acc, yaxis_type)
    x = _x_from_period(periods, xaxis)
    ax.plot(x, db, **plot_kw)
    return x, db


def render_compare(
    entries: list[tuple],
    req: CompareRequest,
    *,
    title: str | None = None,
) -> bytes:
    """Render percentile curves from multiple PPSDs on one axes."""
    from ..models.schemas import ChannelTarget

    fig, ax = plt.subplots(figsize=(11.0, 6.5), dpi=120)
    ytype: YAxisType = req.yaxis_type

    x_label = "Frequency [Hz]" if req.xaxis == "frequency" else "Period [s]"
    db_min, db_max = None, None
    x_min_data, x_max_data = None, None

    for target, ppsd in entries:
        assert isinstance(target, ChannelTarget)
        color = target.color or "#333333"
        label_base = target.label or ".".join(
            filter(None, [target.network, target.station, target.location, target.channel])
        )
        for i, perc in enumerate(req.percentiles):
            p_p, p_db = ppsd.get_percentile(perc)
            x, db = _plot_db_curve(
                ax,
                np.asarray(p_p),
                np.asarray(p_db),
                ytype,
                req.xaxis,
                color=color,
                linestyle=LINE_STYLES[i % len(LINE_STYLES)],
                linewidth=1.6,
                label=f"{label_base}  P{int(perc) if perc == int(perc) else perc}",
            )
            if x_min_data is None:
                x_min_data, x_max_data = float(x.min()), float(x.max())
            else:
                x_min_data = min(x_min_data, float(x.min()))
                x_max_data = max(x_max_data, float(x.max()))
            if db_min is None:
                db_min, db_max = float(db.min()), float(db.max())
            else:
                db_min = min(db_min, float(db.min()))
                db_max = max(db_max, float(db.max()))

    if req.show_noise_models:
        nlnm_p, nlnm_db = get_nlnm()
        nhnm_p, nhnm_db = get_nhnm()
        x1, db1 = _plot_db_curve(
            ax, np.asarray(nlnm_p), np.asarray(nlnm_db), ytype, req.xaxis,
            color="0.45", linewidth=1.2, linestyle="--", label="NLNM",
        )
        x2, db2 = _plot_db_curve(
            ax, np.asarray(nhnm_p), np.asarray(nhnm_db), ytype, req.xaxis,
            color="0.45", linewidth=1.2, linestyle="--", label="NHNM",
        )
        for db in (db1, db2):
            if db_min is None:
                db_min, db_max = float(db.min()), float(db.max())
            else:
                db_min = min(db_min, float(db.min()))
                db_max = max(db_max, float(db.max()))

    ax.set_xscale("log")
    ax.set_xlabel(x_label)
    ax.set_ylabel(yaxis_ylabel(ytype))
    default_xmin = x_min_data if x_min_data is not None else 0.01
    default_xmax = x_max_data if x_max_data is not None else 100.0
    type_ymin, type_ymax = yaxis_default_limits(ytype)
    apply_axis_limits(
        ax,
        x_min=req.x_min,
        x_max=req.x_max,
        y_min=req.y_min,
        y_max=req.y_max,
        yaxis_type=ytype,
        default_xmin=default_xmin,
        default_xmax=default_xmax,
        default_ymin=type_ymin,
        default_ymax=type_ymax,
    )
    ax.grid(True, which="both", linestyle=":", alpha=0.35)
    if title is None:
        title = (
            f"PPSD Compare Station   "
            f"{req.starttime.isoformat()}  to  {req.endtime.isoformat()}"
        )
    ax.set_title(title, fontsize=10)
    ax.legend(loc="upper right", fontsize=7, framealpha=0.9, ncol=1)

    buf = io.BytesIO()
    fig.tight_layout()
    fig.savefig(buf, format="png", dpi=120, bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()


def _histogram_stack(ppsd: PPSD) -> np.ndarray:
    hist = ppsd.current_histogram
    if hist is None:
        ppsd.calculate_histogram()
        hist = ppsd.current_histogram
    return np.asarray(hist, dtype=float)


def _edges_from_centers(centers: np.ndarray) -> np.ndarray:
    log_c = np.log10(centers)
    mids = 0.5 * (log_c[1:] + log_c[:-1])
    first = 2 * log_c[0] - mids[0]
    last = 2 * log_c[-1] - mids[-1]
    return np.power(10.0, np.concatenate([[first], mids, [last]]))


def render_ppsd(
    ppsd: PPSD,
    req: PPSDRequest,
    options: PlotOptions | None = None,
) -> bytes:
    """Render the PPSD to a PNG byte string according to the request options."""
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

    period_bins = np.asarray(ppsd.period_bin_centers)
    db_edges = np.asarray(ppsd.db_bin_edges)
    hist = _histogram_stack(ppsd)
    display = hist.copy()

    if opts.clip_to_percentile:
        low_curve_p, low_curve_db = ppsd.get_percentile(opts.percentile_low)
        high_curve_p, high_curve_db = ppsd.get_percentile(opts.percentile_high)
        low_at_bins = np.interp(
            period_bins,
            np.asarray(low_curve_p),
            np.asarray(low_curve_db),
        )
        high_at_bins = np.interp(
            period_bins,
            np.asarray(high_curve_p),
            np.asarray(high_curve_db),
        )
        db_centers_acc = 0.5 * (db_edges[:-1] + db_edges[1:])
        for i in range(display.shape[0]):
            mask = (db_centers_acc < low_at_bins[i]) | (db_centers_acc > high_at_bins[i])
            display[i, mask] = np.nan

    display, db_edges = convert_histogram(display, period_bins, db_edges, ytype)

    if opts.xaxis == "frequency":
        x_centers = 1.0 / period_bins
        x_label = "Frequency [Hz]"
        order = np.argsort(x_centers)
        x_centers = x_centers[order]
        display = display[order, :]
    else:
        x_centers = period_bins
        x_label = "Period [s]"

    x_edges = _edges_from_centers(x_centers)

    fig, ax = plt.subplots(figsize=(10.0, 6.0), dpi=120)
    cmap = plt.get_cmap(opts.cmap).copy()
    cmap.set_bad(color=(0, 0, 0, 0))

    with np.errstate(invalid="ignore"):
        vmax = float(np.nanmax(display)) if np.any(~np.isnan(display)) else 1.0
    if vmax <= 0:
        vmax = 1.0

    mesh = ax.pcolormesh(
        x_edges,
        db_edges,
        display.T * 100.0,
        cmap=cmap,
        vmin=0.0,
        vmax=vmax * 100.0,
        shading="flat",
    )
    ax.set_xscale("log")
    ax.set_xlabel(x_label)
    ax.set_ylabel(yaxis_ylabel(ytype))
    type_ymin, type_ymax = yaxis_default_limits(ytype)
    apply_axis_limits(
        ax,
        x_min=opts.x_min,
        x_max=opts.x_max,
        y_min=opts.y_min,
        y_max=opts.y_max,
        yaxis_type=ytype,
        default_xmin=float(x_edges.min()),
        default_xmax=float(x_edges.max()),
        default_ymin=type_ymin,
        default_ymax=type_ymax,
    )
    ax.grid(True, which="both", linestyle=":", alpha=0.35)

    if opts.show_noise_models:
        nlnm_p, nlnm_db = get_nlnm()
        nhnm_p, nhnm_db = get_nhnm()
        _plot_db_curve(
            ax, np.asarray(nlnm_p), np.asarray(nlnm_db), ytype, opts.xaxis,
            color="0.4", linewidth=1.2, linestyle="--", label="NLNM",
        )
        _plot_db_curve(
            ax, np.asarray(nhnm_p), np.asarray(nhnm_db), ytype, opts.xaxis,
            color="0.4", linewidth=1.2, linestyle="--",
        )

    if opts.show_overlay:
        for perc, style in (
            (opts.percentile_low, dict(color="#e74c3c", linewidth=1.5)),
            (opts.percentile_high, dict(color="#e74c3c", linewidth=1.5)),
        ):
            p_x, p_db = ppsd.get_percentile(perc)
            _plot_db_curve(
                ax,
                np.asarray(p_x),
                np.asarray(p_db),
                ytype,
                opts.xaxis,
                label=f"{int(perc)}th pct",
                **style,
            )

    if opts.show_mode:
        try:
            mode_p, mode_db = ppsd.get_mode()
            _plot_db_curve(
                ax, mode_p, mode_db, ytype, opts.xaxis,
                color="#1abc9c", linewidth=1.2, label="mode",
            )
        except Exception as exc:  # pragma: no cover
            logger.warning("Could not compute mode: %s", exc)

    if opts.show_mean:
        try:
            mean_p, mean_db = ppsd.get_mean()
            _plot_db_curve(
                ax, mean_p, mean_db, ytype, opts.xaxis,
                color="#f39c12", linewidth=1.2, label="mean",
            )
        except Exception as exc:  # pragma: no cover
            logger.warning("Could not compute mean: %s", exc)

    cbar = fig.colorbar(mesh, ax=ax, pad=0.02)
    cbar.set_label("Probability [%]")

    channel_id = ".".join(
        [ppsd.network, ppsd.station, ppsd.location or "", ppsd.channel]
    )
    n_segments = len(ppsd.times_processed)
    title = (
        f"{channel_id}   "
        f"{req.starttime.isoformat()}  to  {req.endtime.isoformat()}   "
        f"({n_segments} segments)"
    )
    ax.set_title(title, fontsize=10)
    ax.legend(loc="upper right", fontsize=8, framealpha=0.85)

    buf = io.BytesIO()
    fig.tight_layout()
    fig.savefig(buf, format="png", dpi=120, bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()
