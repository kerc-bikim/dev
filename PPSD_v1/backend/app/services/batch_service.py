"""Batch and compare orchestration with parallel execution."""

from __future__ import annotations

import hashlib
import json
import logging
import time
from concurrent.futures import as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

from obspy.signal import PPSD

from ..config import settings
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
from .plotting import render_compare, render_ppsd
from .pool import get_executor
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


def _png_path(job_id: str, suffix: str) -> Path:
    return settings.CACHE_DIR / f"{job_id}_{suffix}.png"


def _render_key_from_options(options: PlotOptions) -> str:
    payload = {
        "pl": options.percentile_low,
        "ph": options.percentile_high,
        "ov": options.show_overlay,
        "cl": options.clip_to_percentile,
        "xa": options.xaxis,
        "yt": options.yaxis_type,
        "nm": options.show_noise_models,
        "mn": options.show_mean,
        "md": options.show_mode,
        "cm": options.cmap,
        "xmin": options.x_min,
        "xmax": options.x_max,
        "ymin": options.y_min,
        "ymax": options.y_max,
    }
    blob = json.dumps(payload, sort_keys=True).encode("utf-8")
    return hashlib.sha1(blob).hexdigest()[:10]


def _compare_render_key(req: CompareRequest) -> str:
    payload = {
        "targets": [
            {
                "n": t.network,
                "s": t.station,
                "l": t.location,
                "c": t.channel,
                "color": t.color,
                "label": t.label,
            }
            for t in req.targets
        ],
        "t1": req.starttime.isoformat(),
        "t2": req.endtime.isoformat(),
        "p": req.percentiles,
        "xa": req.xaxis,
        "yt": req.yaxis_type,
        "nm": req.show_noise_models,
        "xmin": req.x_min,
        "xmax": req.x_max,
        "ymin": req.y_min,
        "ymax": req.y_max,
    }
    blob = json.dumps(payload, sort_keys=True).encode("utf-8")
    return hashlib.sha1(blob).hexdigest()[:16]


def _compare_time_render_key(req: CompareTimeRequest) -> str:
    payload = {
        "kind": "time",
        "target": {
            "n": req.target.network,
            "s": req.target.station,
            "l": req.target.location,
            "c": req.target.channel,
        },
        "windows": [
            {
                "t1": w.starttime.isoformat(),
                "t2": w.endtime.isoformat(),
                "color": w.color,
                "label": w.label,
            }
            for w in req.windows
        ],
        "p": req.percentiles,
        "xa": req.xaxis,
        "yt": req.yaxis_type,
        "nm": req.show_noise_models,
        "xmin": req.x_min,
        "xmax": req.x_max,
        "ymin": req.y_min,
        "ymax": req.y_max,
    }
    blob = json.dumps(payload, sort_keys=True).encode("utf-8")
    return hashlib.sha1(blob).hexdigest()[:16]


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
        f"{window.starttime.strftime('%Y-%m-%d %H:%M')} – "
        f"{window.endtime.strftime('%Y-%m-%d %H:%M')} UTC"
    )


def _window_target(
    base: ChannelTarget, window: CompareTimeWindow
) -> ChannelTarget:
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


@dataclass
class _ComputeRenderResult:
    target: ChannelTarget
    status: str
    job_id: Optional[str] = None
    image_url: Optional[str] = None
    stats: Optional[PPSDStats] = None
    error: Optional[str] = None
    ppsd: Optional[PPSD] = None


def _compute_and_render_one(
    target: ChannelTarget,
    starttime: datetime,
    endtime: datetime,
    options: PlotOptions,
) -> _ComputeRenderResult:
    req = _to_ppsd_request(target, starttime, endtime, options)
    try:
        result: PPSDResult = compute_or_load(req)
        plot_key = _render_key_from_options(options)
        png_path = _png_path(result.job_id, plot_key)
        if not png_path.exists():
            png_path.write_bytes(render_ppsd(result.ppsd, req, options))
        return _ComputeRenderResult(
            target=target,
            status="ok",
            job_id=result.job_id,
            image_url=f"/api/ppsd/{result.job_id}/{plot_key}.png",
            stats=result.stats,
        )
    except FDSNError as exc:
        return _ComputeRenderResult(
            target=target, status="error", error=str(exc)
        )
    except Exception as exc:  # pragma: no cover
        logger.exception("Batch item failed for %s", target)
        return _ComputeRenderResult(
            target=target, status="error", error=str(exc)
        )


def _compute_one(
    target: ChannelTarget,
    starttime: datetime,
    endtime: datetime,
    options: PlotOptions,
) -> _ComputeRenderResult:
    req = _to_ppsd_request(target, starttime, endtime, options)
    try:
        result = compute_or_load(req)
        return _ComputeRenderResult(
            target=target,
            status="ok",
            job_id=result.job_id,
            stats=result.stats,
            ppsd=result.ppsd,
        )
    except FDSNError as exc:
        return _ComputeRenderResult(
            target=target, status="error", error=str(exc)
        )
    except Exception as exc:  # pragma: no cover
        logger.exception("Compare item failed for %s", target)
        return _ComputeRenderResult(
            target=target, status="error", error=str(exc)
        )


def _to_batch_item(r: _ComputeRenderResult) -> BatchPPSDItem:
    return BatchPPSDItem(
        target=r.target,
        status=r.status,  # type: ignore[arg-type]
        job_id=r.job_id,
        image_url=r.image_url,
        stats=r.stats,
        error=r.error,
    )


def run_batch(req: BatchPPSDRequest) -> BatchPPSDResponse:
    t0 = time.perf_counter()
    executor = get_executor()
    futures = {
        executor.submit(
            _compute_and_render_one,
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
        show_noise_models=req.show_noise_models,
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
    results: List[_ComputeRenderResult] = []
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

    render_key = _compare_render_key(req)
    png_path = settings.CACHE_DIR / f"compare_{render_key}.png"
    if not png_path.exists():
        png_bytes = render_compare(
            [(r.target, r.ppsd) for r in ok_results],  # type: ignore[list-item]
            req,
        )
        png_path.write_bytes(png_bytes)

    items = [_to_batch_item(r) for r in results]
    return CompareResponse(
        image_url=f"/api/ppsd/compare/{render_key}.png",
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
    results: List[_ComputeRenderResult] = []
    for fut in as_completed(futures):
        results.append(fut.result())
    results.sort(key=lambda r: r.target.label or "")

    ok_results = [r for r in results if r.status == "ok" and r.ppsd is not None]
    if not ok_results:
        raise FDSNError("No time windows could be computed for comparison.")

    render_key = _compare_time_render_key(req)
    png_path = settings.CACHE_DIR / f"compare_{render_key}.png"
    if not png_path.exists():
        title = f"PPSD Compare Time   {_channel_id(req.target)}"
        png_bytes = render_compare(
            [(r.target, r.ppsd) for r in ok_results],  # type: ignore[list-item]
            plot_req,
            title=title,
        )
        png_path.write_bytes(png_bytes)

    items = [_to_batch_item(r) for r in results]
    return CompareResponse(
        image_url=f"/api/ppsd/compare/{render_key}.png",
        items=items,
        elapsed_seconds=round(time.perf_counter() - t0, 3),
    )
