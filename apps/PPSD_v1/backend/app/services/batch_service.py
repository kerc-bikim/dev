"""Batch and compare orchestration with parallel execution."""

from __future__ import annotations

import logging
import time
from concurrent.futures import as_completed
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

from obspy.signal import PPSD

from ..models.schemas import (
    BatchPPSDItem,
    BatchPPSDRequest,
    BatchPPSDResponse,
    ChannelTarget,
    CompareRequest,
    CompareResponse,
    CompareTimeRequest,
    CompareTimeWindow,
    PlotOptions,
    PPSDRequest,
    PPSDStats,
)
from .fdsn_client import FDSNError
from .pool import get_executor
from .ppsd_data import compare_curves_data, ppsd_heatmap_data
from .ppsd_service import PPSDResult, compute_or_load

logger = logging.getLogger(__name__)

DEFAULT_COLORS = [
    "#e74c3c",
    "#3498db",
    "#2ecc71",
    "#f39c12",
    "#9b59b6",
    "#1abc9c",
    "#e67e22",
    "#34495e",
    "#e91e63",
    "#00bcd4",
]


def _to_ppsd_request(
    target: ChannelTarget,
    starttime: datetime,
    endtime: datetime,
    options: PlotOptions,
) -> PPSDRequest:
    return PPSDRequest(
        network=target.network,
        station=target.station,
        location=target.location,
        channel=target.channel,
        starttime=starttime,
        endtime=endtime,
        percentile_low=options.percentile_low,
        percentile_high=options.percentile_high,
        show_overlay=options.show_overlay,
        clip_to_percentile=options.clip_to_percentile,
        xaxis=options.xaxis,
        yaxis_type=options.yaxis_type,
        show_noise_models=options.show_noise_models,
        show_mean=options.show_mean,
        show_mode=options.show_mode,
        cmap=options.cmap,
        x_min=options.x_min,
        x_max=options.x_max,
        y_min=options.y_min,
        y_max=options.y_max,
        ppsd_length=options.ppsd_length,
        overlap=options.overlap,
        period_step_octaves=options.period_step_octaves,
        period_smoothing_width_octaves=options.period_smoothing_width_octaves,
    )


def _assign_colors(targets: List[ChannelTarget]) -> List[ChannelTarget]:
    out: List[ChannelTarget] = []
    for i, t in enumerate(targets):
        if t.color:
            out.append(t)
        else:
            out.append(
                t.model_copy(update={"color": DEFAULT_COLORS[i % len(DEFAULT_COLORS)]})
            )
    return out


def _assign_window_colors(
    windows: List[CompareTimeWindow],
) -> List[CompareTimeWindow]:
    out: List[CompareTimeWindow] = []
    for i, w in enumerate(windows):
        if w.color:
            out.append(w)
        else:
            out.append(
                w.model_copy(
                    update={"color": DEFAULT_COLORS[i % len(DEFAULT_COLORS)]}
                )
            )
    return out


def _window_label(window: CompareTimeWindow) -> str:
    if window.label:
        return window.label
    return (
        f"{window.starttime.strftime('%Y-%m-%d %H:%M')} - "
        f"{window.endtime.strftime('%Y-%m-%d %H:%M')} UTC"
    )


def _window_target(base: ChannelTarget, window: CompareTimeWindow) -> ChannelTarget:
    return base.model_copy(
        update={"label": _window_label(window), "color": window.color}
    )


def _channel_id(target: ChannelTarget) -> str:
    loc = target.location or "--"
    return f"{target.network}.{target.station}.{loc}.{target.channel}"


def _compare_time_plot_request(req: CompareTimeRequest) -> CompareRequest:
    first = req.windows[0]
    return CompareRequest(
        targets=[req.target],
        starttime=first.starttime,
        endtime=first.endtime,
        percentiles=req.percentiles,
        xaxis=req.xaxis,
        yaxis_type=req.yaxis_type,
        show_noise_models=req.show_noise_models,
        x_min=req.x_min,
        x_max=req.x_max,
        y_min=req.y_min,
        y_max=req.y_max,
    )


@dataclass
class _ComputeResult:
    target: ChannelTarget
    status: str
    job_id: Optional[str] = None
    data: Optional[Dict[str, Any]] = None
    stats: Optional[PPSDStats] = None
    error: Optional[str] = None
    ppsd: Optional[PPSD] = None


def _compute_and_data_one(
    target: ChannelTarget,
    starttime: datetime,
    endtime: datetime,
    options: PlotOptions,
) -> _ComputeResult:
    req = _to_ppsd_request(target, starttime, endtime, options)
    try:
        result: PPSDResult = compute_or_load(req)
        data = ppsd_heatmap_data(result.ppsd, req, options)
        return _ComputeResult(
            target=target,
            status="ok",
            job_id=result.job_id,
            data=data,
            stats=result.stats,
        )
    except FDSNError as exc:
        return _ComputeResult(target=target, status="error", error=str(exc))
    except Exception as exc:  # pragma: no cover
        logger.exception("Batch item failed for %s", target)
        return _ComputeResult(target=target, status="error", error=str(exc))


def _compute_one(
    target: ChannelTarget,
    starttime: datetime,
    endtime: datetime,
    options: PlotOptions,
) -> _ComputeResult:
    req = _to_ppsd_request(target, starttime, endtime, options)
    try:
        result = compute_or_load(req)
        return _ComputeResult(
            target=target,
            status="ok",
            job_id=result.job_id,
            stats=result.stats,
            ppsd=result.ppsd,
        )
    except FDSNError as exc:
        return _ComputeResult(target=target, status="error", error=str(exc))
    except Exception as exc:  # pragma: no cover
        logger.exception("Compare item failed for %s", target)
        return _ComputeResult(target=target, status="error", error=str(exc))


def _to_batch_item(r: _ComputeResult) -> BatchPPSDItem:
    return BatchPPSDItem(
        target=r.target,
        status=r.status,  # type: ignore[arg-type]
        job_id=r.job_id,
        data=r.data,
        stats=r.stats,
        error=r.error,
    )


def run_batch(req: BatchPPSDRequest) -> BatchPPSDResponse:
    t0 = time.perf_counter()
    executor = get_executor()
    futures = {
        executor.submit(
            _compute_and_data_one,
            target,
            req.starttime,
            req.endtime,
            req.options,
        ): target
        for target in req.targets
    }
    items: List[BatchPPSDItem] = []
    for fut in as_completed(futures):
        items.append(_to_batch_item(fut.result()))
    items.sort(
        key=lambda it: (
            it.target.network,
            it.target.station,
            it.target.location,
            it.target.channel,
        )
    )
    return BatchPPSDResponse(
        items=items,
        elapsed_seconds=round(time.perf_counter() - t0, 3),
    )


def run_compare(req: CompareRequest) -> CompareResponse:
    t0 = time.perf_counter()
    targets = _assign_colors(req.targets)
    default_options = PlotOptions(
        xaxis=req.xaxis,
        yaxis_type=req.yaxis_type,
        show_noise_models=req.show_noise_models,
        ppsd_length=req.ppsd_length,
        overlap=req.overlap,
        period_step_octaves=req.period_step_octaves,
        period_smoothing_width_octaves=req.period_smoothing_width_octaves,
    )
    executor = get_executor()
    futures = {
        executor.submit(
            _compute_one,
            target,
            req.starttime,
            req.endtime,
            default_options,
        ): target
        for target in targets
    }
    results: List[_ComputeResult] = []
    for fut in as_completed(futures):
        results.append(fut.result())
    results.sort(
        key=lambda r: (
            r.target.network,
            r.target.station,
            r.target.location,
            r.target.channel,
        )
    )

    ok_results = [r for r in results if r.status == "ok" and r.ppsd is not None]
    if not ok_results:
        raise FDSNError("No targets could be computed for comparison.")

    data = compare_curves_data(
        [(r.target, r.ppsd) for r in ok_results],  # type: ignore[list-item]
        req,
    )

    items = [_to_batch_item(r) for r in results]
    return CompareResponse(
        data=data,
        items=items,
        elapsed_seconds=round(time.perf_counter() - t0, 3),
    )


def run_compare_time(req: CompareTimeRequest) -> CompareResponse:
    t0 = time.perf_counter()
    windows = _assign_window_colors(req.windows)
    plot_req = _compare_time_plot_request(req)
    default_options = PlotOptions(
        xaxis=req.xaxis,
        yaxis_type=req.yaxis_type,
        show_noise_models=req.show_noise_models,
        x_min=req.x_min,
        x_max=req.x_max,
        y_min=req.y_min,
        y_max=req.y_max,
        ppsd_length=req.ppsd_length,
        overlap=req.overlap,
        period_step_octaves=req.period_step_octaves,
        period_smoothing_width_octaves=req.period_smoothing_width_octaves,
    )
    executor = get_executor()
    futures = {
        executor.submit(
            _compute_one,
            _window_target(req.target, window),
            window.starttime,
            window.endtime,
            default_options,
        ): window
        for window in windows
    }
    results: List[_ComputeResult] = []
    for fut in as_completed(futures):
        results.append(fut.result())
    results.sort(key=lambda r: r.target.label or "")

    ok_results = [r for r in results if r.status == "ok" and r.ppsd is not None]
    if not ok_results:
        raise FDSNError("No time windows could be computed for comparison.")

    title = f"PPSD Compare Time   {_channel_id(req.target)}"
    data = compare_curves_data(
        [(r.target, r.ppsd) for r in ok_results],  # type: ignore[list-item]
        plot_req,
        title=title,
    )

    items = [_to_batch_item(r) for r in results]
    return CompareResponse(
        data=data,
        items=items,
        elapsed_seconds=round(time.perf_counter() - t0, 3),
    )
