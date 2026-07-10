from __future__ import annotations

from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator

YAxisType = Literal[
    "acceleration",
    "velocity",
    "velocity_nm",
    "displacement",
    "pressure",
]


class NetworkInfo(BaseModel):
    code: str
    description: Optional[str] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    total_stations: Optional[int] = None


class StationInfo(BaseModel):
    network: str
    code: str
    name: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    elevation: Optional[float] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None


class ChannelInfo(BaseModel):
    network: str
    station: str
    location: str = ""
    channel: str
    sample_rate: Optional[float] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    azimuth: Optional[float] = None
    dip: Optional[float] = None


class ChannelTarget(BaseModel):
    network: str
    station: str
    location: str = ""
    channel: str
    label: Optional[str] = None
    color: Optional[str] = Field(
        None, description="Hex color for compare plots, e.g. #e74c3c"
    )


class PlotOptions(BaseModel):
    percentile_low: float = Field(10.0, ge=0.0, le=100.0)
    percentile_high: float = Field(90.0, ge=0.0, le=100.0)
    show_overlay: bool = True
    clip_to_percentile: bool = False
    xaxis: Literal["period", "frequency"] = "period"
    yaxis_type: YAxisType = "acceleration"
    show_noise_models: bool = True
    show_mean: bool = False
    show_mode: bool = False
    cmap: str = Field("viridis", description="matplotlib colormap name")
    x_min: Optional[float] = Field(
        None, description="X-axis minimum (period [s] or frequency [Hz])"
    )
    x_max: Optional[float] = Field(None, description="X-axis maximum")
    y_min: Optional[float] = Field(None, description="Y-axis minimum [dB]")
    y_max: Optional[float] = Field(None, description="Y-axis maximum [dB]")

    @field_validator("percentile_high")
    @classmethod
    def _check_percentiles(cls, v: float, info) -> float:
        low = info.data.get("percentile_low")
        if low is not None and v <= low:
            raise ValueError(
                "percentile_high must be greater than percentile_low"
            )
        return v

    @field_validator("x_max")
    @classmethod
    def _check_x_range(cls, v: Optional[float], info) -> Optional[float]:
        xmin = info.data.get("x_min")
        if v is not None and xmin is not None and v <= xmin:
            raise ValueError("x_max must be greater than x_min")
        return v

    @field_validator("y_max")
    @classmethod
    def _check_y_range(cls, v: Optional[float], info) -> Optional[float]:
        ymin = info.data.get("y_min")
        if v is not None and ymin is not None and v <= ymin:
            raise ValueError("y_max must be greater than y_min")
        return v


class PPSDRequest(BaseModel):
    network: str = Field(..., description="Network code, e.g. IU")
    station: str = Field(..., description="Station code, e.g. ANMO")
    location: str = Field("", description="Location code, blank string is allowed")
    channel: str = Field(..., description="Channel code, e.g. BHZ")
    starttime: datetime
    endtime: datetime
    percentile_low: float = Field(10.0, ge=0.0, le=100.0)
    percentile_high: float = Field(90.0, ge=0.0, le=100.0)
    show_overlay: bool = True
    clip_to_percentile: bool = False
    xaxis: Literal["period", "frequency"] = "period"
    yaxis_type: YAxisType = "acceleration"
    show_noise_models: bool = True
    show_mean: bool = False
    show_mode: bool = False
    cmap: str = Field("viridis", description="matplotlib colormap name")
    x_min: Optional[float] = Field(None, description="X-axis minimum")
    x_max: Optional[float] = Field(None, description="X-axis maximum")
    y_min: Optional[float] = Field(None, description="Y-axis minimum [dB]")
    y_max: Optional[float] = Field(None, description="Y-axis maximum [dB]")

    @field_validator("percentile_high")
    @classmethod
    def _check_percentiles(cls, v: float, info) -> float:
        low = info.data.get("percentile_low")
        if low is not None and v <= low:
            raise ValueError(
                "percentile_high must be greater than percentile_low"
            )
        return v

    @field_validator("endtime")
    @classmethod
    def _check_times(cls, v: datetime, info) -> datetime:
        start = info.data.get("starttime")
        if start is not None and v <= start:
            raise ValueError("endtime must be after starttime")
        return v

    @field_validator("x_max")
    @classmethod
    def _check_x_range(cls, v: Optional[float], info) -> Optional[float]:
        xmin = info.data.get("x_min")
        if v is not None and xmin is not None and v <= xmin:
            raise ValueError("x_max must be greater than x_min")
        return v

    @field_validator("y_max")
    @classmethod
    def _check_y_range(cls, v: Optional[float], info) -> Optional[float]:
        ymin = info.data.get("y_min")
        if v is not None and ymin is not None and v <= ymin:
            raise ValueError("y_max must be greater than y_min")
        return v


class PPSDStats(BaseModel):
    segments_used: int
    starttime: datetime
    endtime: datetime
    channel_id: str
    sampling_rate: Optional[float] = None
    from_cache: bool = False


class PPSDResponse(BaseModel):
    job_id: str
    image_url: str
    stats: PPSDStats


class HealthResponse(BaseModel):
    status: str
    fdsnws_url: str


class PlotDefaultsResponse(BaseModel):
    """Default plot options from server .env (used to pre-fill the UI)."""
    x_min: Optional[float] = None
    x_max: Optional[float] = None
    y_min: Optional[float] = None
    y_max: Optional[float] = None
    yaxis_type: YAxisType = "acceleration"


class ErrorResponse(BaseModel):
    detail: str


class BatchPPSDRequest(BaseModel):
    targets: List[ChannelTarget] = Field(..., min_length=1)
    starttime: datetime
    endtime: datetime
    options: PlotOptions = Field(default_factory=PlotOptions)

    @field_validator("endtime")
    @classmethod
    def _check_times(cls, v: datetime, info) -> datetime:
        start = info.data.get("starttime")
        if start is not None and v <= start:
            raise ValueError("endtime must be after starttime")
        return v

    @field_validator("targets")
    @classmethod
    def _check_target_count(cls, v: List[ChannelTarget]) -> List[ChannelTarget]:
        from ..config import settings

        if len(v) > settings.MAX_TARGETS:
            raise ValueError(
                f"At most {settings.MAX_TARGETS} targets allowed per request"
            )
        return v


class BatchPPSDItem(BaseModel):
    target: ChannelTarget
    status: Literal["ok", "error"]
    job_id: Optional[str] = None
    image_url: Optional[str] = None
    stats: Optional[PPSDStats] = None
    error: Optional[str] = None


class BatchPPSDResponse(BaseModel):
    items: List[BatchPPSDItem]
    elapsed_seconds: float


class CompareRequest(BaseModel):
    targets: List[ChannelTarget] = Field(..., min_length=1)
    starttime: datetime
    endtime: datetime
    percentiles: List[float] = Field(default_factory=lambda: [10.0, 50.0, 90.0])
    xaxis: Literal["period", "frequency"] = "period"
    yaxis_type: YAxisType = "acceleration"
    show_noise_models: bool = True
    x_min: Optional[float] = None
    x_max: Optional[float] = None
    y_min: Optional[float] = None
    y_max: Optional[float] = None

    @field_validator("endtime")
    @classmethod
    def _check_times(cls, v: datetime, info) -> datetime:
        start = info.data.get("starttime")
        if start is not None and v <= start:
            raise ValueError("endtime must be after starttime")
        return v

    @field_validator("percentiles")
    @classmethod
    def _check_percentiles(cls, v: List[float]) -> List[float]:
        if not v:
            raise ValueError("At least one percentile is required")
        for p in v:
            if p < 0 or p > 100:
                raise ValueError("Percentiles must be between 0 and 100")
        return sorted(set(v))

    @field_validator("x_max")
    @classmethod
    def _check_x_range(cls, v: Optional[float], info) -> Optional[float]:
        xmin = info.data.get("x_min")
        if v is not None and xmin is not None and v <= xmin:
            raise ValueError("x_max must be greater than x_min")
        return v

    @field_validator("y_max")
    @classmethod
    def _check_y_range(cls, v: Optional[float], info) -> Optional[float]:
        ymin = info.data.get("y_min")
        if v is not None and ymin is not None and v <= ymin:
            raise ValueError("y_max must be greater than y_min")
        return v

    @field_validator("targets")
    @classmethod
    def _check_target_count(cls, v: List[ChannelTarget]) -> List[ChannelTarget]:
        from ..config import settings

        if len(v) > settings.MAX_TARGETS:
            raise ValueError(
                f"At most {settings.MAX_TARGETS} targets allowed per request"
            )
        return v


class CompareTimeWindow(BaseModel):
    starttime: datetime
    endtime: datetime
    label: Optional[str] = None
    color: Optional[str] = Field(
        None, description="Hex color for compare plots, e.g. #e74c3c"
    )

    @field_validator("endtime")
    @classmethod
    def _check_times(cls, v: datetime, info) -> datetime:
        start = info.data.get("starttime")
        if start is not None and v <= start:
            raise ValueError("endtime must be after starttime")
        return v


class CompareTimeRequest(BaseModel):
    target: ChannelTarget
    windows: List[CompareTimeWindow] = Field(..., min_length=1)
    percentiles: List[float] = Field(default_factory=lambda: [10.0, 50.0, 90.0])
    xaxis: Literal["period", "frequency"] = "period"
    yaxis_type: YAxisType = "acceleration"
    show_noise_models: bool = True
    x_min: Optional[float] = None
    x_max: Optional[float] = None
    y_min: Optional[float] = None
    y_max: Optional[float] = None

    @field_validator("percentiles")
    @classmethod
    def _check_percentiles(cls, v: List[float]) -> List[float]:
        if not v:
            raise ValueError("At least one percentile is required")
        for p in v:
            if p < 0 or p > 100:
                raise ValueError("Percentiles must be between 0 and 100")
        return sorted(set(v))

    @field_validator("x_max")
    @classmethod
    def _check_x_range(cls, v: Optional[float], info) -> Optional[float]:
        xmin = info.data.get("x_min")
        if v is not None and xmin is not None and v <= xmin:
            raise ValueError("x_max must be greater than x_min")
        return v

    @field_validator("y_max")
    @classmethod
    def _check_y_range(cls, v: Optional[float], info) -> Optional[float]:
        ymin = info.data.get("y_min")
        if v is not None and ymin is not None and v <= ymin:
            raise ValueError("y_max must be greater than y_min")
        return v

    @field_validator("windows")
    @classmethod
    def _check_window_count(
        cls, v: List[CompareTimeWindow]
    ) -> List[CompareTimeWindow]:
        from ..config import settings

        if len(v) > settings.MAX_TARGETS:
            raise ValueError(
                f"At most {settings.MAX_TARGETS} time windows allowed per request"
            )
        return v


class CompareResponse(BaseModel):
    image_url: str
    items: List[BatchPPSDItem]
    elapsed_seconds: float
