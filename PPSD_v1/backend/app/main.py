from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.ppsd import router as ppsd_router
from .api.stations import router as stations_router
from .config import settings
from .models.schemas import HealthResponse, PlotDefaultsResponse
from .services.yaxis_units import yaxis_default_limits

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

app = FastAPI(
    title="PPSD Web Viewer",
    version="0.1.0",
    description=(
        "Compute IRIS MUSTANG-style PPSD plots from an FDSNWS data source, "
        "with configurable percentile overlays and clipping."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(stations_router)
app.include_router(ppsd_router)


@app.get("/api/health", response_model=HealthResponse)
def health():
    return HealthResponse(status="ok", fdsnws_url=settings.FDSNWS_URL)


@app.get("/api/plot-defaults", response_model=PlotDefaultsResponse)
def plot_defaults():
    ytype = settings.PPSD_YAXIS_TYPE  # type: ignore[assignment]
    type_y_min, type_y_max = yaxis_default_limits(ytype)
    return PlotDefaultsResponse(
        x_min=settings.PPSD_X_MIN,
        x_max=settings.PPSD_X_MAX,
        y_min=settings.PPSD_Y_MIN if settings.PPSD_Y_MIN is not None else type_y_min,
        y_max=settings.PPSD_Y_MAX if settings.PPSD_Y_MAX is not None else type_y_max,
        yaxis_type=ytype,  # type: ignore[arg-type]
    )
