from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException

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
from ..services.ppsd_data import ppsd_heatmap_data
from ..services.ppsd_service import compute_or_load

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["ppsd"])


@router.post("/ppsd", response_model=PPSDResponse)
def create_ppsd(req: PPSDRequest):
    try:
        result = compute_or_load(req)
    except FDSNError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover
        logger.exception("PPSD computation failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    data = ppsd_heatmap_data(result.ppsd, req)
    return PPSDResponse(job_id=result.job_id, data=data, stats=result.stats)


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
