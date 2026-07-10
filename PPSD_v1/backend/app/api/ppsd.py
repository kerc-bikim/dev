from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from ..config import settings
from ..models.schemas import (
    BatchPPSDRequest,
    BatchPPSDResponse,
    CompareRequest,
    CompareResponse,
    CompareTimeRequest,
    PPSDRequest,
    PPSDResponse,
)
from ..services.batch_service import run_batch, run_compare, run_compare_time
from ..services.fdsn_client import FDSNError
from ..services.plotting import render_ppsd
from ..services.ppsd_service import compute_or_load

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["ppsd"])


def _png_path(job_id: str, suffix: str) -> Path:
    return settings.CACHE_DIR / f"{job_id}_{suffix}.png"


def _render_key(req: PPSDRequest) -> str:
    """Short hash discriminating plot options for the PNG file name."""
    payload = {
        "pl": req.percentile_low,
        "ph": req.percentile_high,
        "ov": req.show_overlay,
        "cl": req.clip_to_percentile,
        "xa": req.xaxis,
        "yt": req.yaxis_type,
        "nm": req.show_noise_models,
        "mn": req.show_mean,
        "md": req.show_mode,
        "cm": req.cmap,
        "xmin": req.x_min,
        "xmax": req.x_max,
        "ymin": req.y_min,
        "ymax": req.y_max,
    }
    blob = json.dumps(payload, sort_keys=True).encode("utf-8")
    return hashlib.sha1(blob).hexdigest()[:10]


@router.post("/ppsd", response_model=PPSDResponse)
def create_ppsd(req: PPSDRequest):
    try:
        result = compute_or_load(req)
    except FDSNError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover
        logger.exception("PPSD computation failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    plot_key = _render_key(req)
    png_path = _png_path(result.job_id, plot_key)
    if not png_path.exists():
        png_path.write_bytes(render_ppsd(result.ppsd, req))

    return PPSDResponse(
        job_id=result.job_id,
        image_url=f"/api/ppsd/{result.job_id}/{plot_key}.png",
        stats=result.stats,
    )


@router.post("/ppsd/batch", response_model=BatchPPSDResponse)
async def create_ppsd_batch(req: BatchPPSDRequest):
    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(None, run_batch, req)
    except Exception as exc:  # pragma: no cover
        logger.exception("Batch PPSD failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/ppsd/compare", response_model=CompareResponse)
async def create_ppsd_compare(req: CompareRequest):
    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(None, run_compare, req)
    except FDSNError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover
        logger.exception("Compare PPSD failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/ppsd/compare-time", response_model=CompareResponse)
async def create_ppsd_compare_time(req: CompareTimeRequest):
    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(None, run_compare_time, req)
    except FDSNError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover
        logger.exception("Compare time PPSD failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/ppsd/{job_id}/{plot_key}.png")
def get_ppsd_image(job_id: str, plot_key: str):
    png_path = _png_path(job_id, plot_key)
    if not png_path.exists():
        raise HTTPException(status_code=404, detail="Image not found")
    return FileResponse(png_path, media_type="image/png")


@router.get("/ppsd/compare/{render_key}.png")
def get_compare_image(render_key: str):
    png_path = settings.CACHE_DIR / f"compare_{render_key}.png"
    if not png_path.exists():
        raise HTTPException(status_code=404, detail="Compare image not found")
    return FileResponse(png_path, media_type="image/png")
