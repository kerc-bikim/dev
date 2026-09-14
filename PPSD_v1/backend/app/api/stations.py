from __future__ import annotations

import logging
from typing import List

from fastapi import APIRouter, HTTPException, Query

from ..models.schemas import ChannelInfo, NetworkInfo, StationInfo
from ..services.fdsn_client import (
    FDSNError,
    list_channels,
    list_networks,
    list_stations,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["stations"])


@router.get("/networks", response_model=List[NetworkInfo])
def get_networks():
    try:
        return list_networks()
    except FDSNError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/stations", response_model=List[StationInfo])
def get_stations(network: str = Query(..., min_length=1)):
    try:
        return list_stations(network=network)
    except FDSNError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/channels", response_model=List[ChannelInfo])
def get_channels(
    network: str = Query(..., min_length=1),
    station: str = Query(..., min_length=1),
    location: str | None = Query(
        None, description="FDSN location code; empty for --; * and ? wildcards allowed"
    ),
    channel: str | None = Query(
        None, description="FDSN channel code; * and ? wildcards allowed"
    ),
):
    try:
        return list_channels(
            network=network,
            station=station,
            location=location,
            channel=channel,
        )
    except FDSNError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
