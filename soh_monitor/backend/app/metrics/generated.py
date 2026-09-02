"""자동 생성 파일. 직접 고치지 않는다.

원본: contracts/metrics/catalog.yaml
생성: python scripts/gen_metrics.py
"""
from __future__ import annotations

from typing import Final

CATALOG_VERSION: Final[int] = 1

class MetricKey:
    """표준 Metric 키 상수. 문자열 오타를 컴파일 시점에 가깝게 잡기 위한 것."""

    CONNECTIVITY_REACHABLE: Final[str] = "connectivity.reachable"
    CONNECTIVITY_LATENCY_MS: Final[str] = "connectivity.latency_ms"
    CONNECTIVITY_CONSECUTIVE_FAILURES: Final[str] = "connectivity.consecutive_failures"
    CONNECTIVITY_ERROR_CODE: Final[str] = "connectivity.error_code"
    DEVICE_OVERALL_STATUS: Final[str] = "device.overall_status"
    DEVICE_CONFIGURATION_STATUS: Final[str] = "device.configuration_status"
    DEVICE_FIRMWARE_STATUS: Final[str] = "device.firmware_status"
    DEVICE_FIRMWARE_VERSION: Final[str] = "device.firmware_version"
    DEVICE_TEMPERATURE_C: Final[str] = "device.temperature_c"
    POWER_INPUT_VOLTAGE_V: Final[str] = "power.input_voltage_v"
    POWER_CURRENT_A: Final[str] = "power.current_a"
    POWER_CONSUMPTION_W: Final[str] = "power.consumption_w"
    TIMING_STATUS: Final[str] = "timing.status"
    TIMING_PHASE_LOCK: Final[str] = "timing.phase_lock"
    TIMING_QUALITY_PERCENT: Final[str] = "timing.quality_percent"
    TIMING_ERROR_NS: Final[str] = "timing.error_ns"
    TIMING_UNCERTAINTY_NS: Final[str] = "timing.uncertainty_ns"
    TIMING_LAST_LOCK_AT: Final[str] = "timing.last_lock_at"
    GNSS_SATELLITE_COUNT: Final[str] = "gnss.satellite_count"
    GNSS_ANTENNA_STATUS: Final[str] = "gnss.antenna_status"
    GNSS_LATITUDE: Final[str] = "gnss.latitude"
    GNSS_LONGITUDE: Final[str] = "gnss.longitude"
    GNSS_ELEVATION_M: Final[str] = "gnss.elevation_m"
    SENSOR_STATUS: Final[str] = "sensor.status"
    SENSOR_CONTROL_STATE: Final[str] = "sensor.control_state"
    SENSOR_MASS_POSITION_V: Final[str] = "sensor.mass_position_v"
    STORAGE_USED_PERCENT: Final[str] = "storage.used_percent"
    STORAGE_RECORDING_STATUS: Final[str] = "storage.recording_status"
    STORAGE_SD_STATUS: Final[str] = "storage.sd_status"
    STORAGE_SD_FREE_BYTES: Final[str] = "storage.sd_free_bytes"
    ARCHIVE_CONTINUOUS_STATUS: Final[str] = "archive.continuous_status"
    ARCHIVE_EVENT_STATUS: Final[str] = "archive.event_status"
    EXTERNAL_SOH_VALUE: Final[str] = "external_soh.value"
    EXTERNAL_SOH_SWITCH_STATE: Final[str] = "external_soh.switch_state"
    ACQUISITION_LATEST_SAMPLE_AGE_SECONDS: Final[str] = "acquisition.latest_sample_age_seconds"
    ACQUISITION_GAP_DURATION_SECONDS: Final[str] = "acquisition.gap_duration_seconds"
    ACQUISITION_CHANNEL_ACTIVE: Final[str] = "acquisition.channel_active"
    ENVIRONMENT_OUTDOOR_TEMPERATURE_C: Final[str] = "environment.outdoor_temperature_c"
    ENVIRONMENT_HUMIDITY_PERCENT: Final[str] = "environment.humidity_percent"
    ENVIRONMENT_PRESSURE_PA: Final[str] = "environment.pressure_pa"
    HEALTH_SEVERITY: Final[str] = "health.severity"
    HEALTH_IS_STALE: Final[str] = "health.is_stale"
    VENDOR_NANOMETRICS_CENTAUR_BUFFER_USED_PERCENT: Final[str] = "vendor.nanometrics.centaur.buffer_used_percent"
    VENDOR_NANOMETRICS_CENTAUR_VCO_CONTROL: Final[str] = "vendor.nanometrics.centaur.vco_control"


ALL_METRIC_KEYS: Final[tuple[str, ...]] = (
    "connectivity.reachable",
    "connectivity.latency_ms",
    "connectivity.consecutive_failures",
    "connectivity.error_code",
    "device.overall_status",
    "device.configuration_status",
    "device.firmware_status",
    "device.firmware_version",
    "device.temperature_c",
    "power.input_voltage_v",
    "power.current_a",
    "power.consumption_w",
    "timing.status",
    "timing.phase_lock",
    "timing.quality_percent",
    "timing.error_ns",
    "timing.uncertainty_ns",
    "timing.last_lock_at",
    "gnss.satellite_count",
    "gnss.antenna_status",
    "gnss.latitude",
    "gnss.longitude",
    "gnss.elevation_m",
    "sensor.status",
    "sensor.control_state",
    "sensor.mass_position_v",
    "storage.used_percent",
    "storage.recording_status",
    "storage.sd_status",
    "storage.sd_free_bytes",
    "archive.continuous_status",
    "archive.event_status",
    "external_soh.value",
    "external_soh.switch_state",
    "acquisition.latest_sample_age_seconds",
    "acquisition.gap_duration_seconds",
    "acquisition.channel_active",
    "environment.outdoor_temperature_c",
    "environment.humidity_percent",
    "environment.pressure_pa",
    "health.severity",
    "health.is_stale",
    "vendor.nanometrics.centaur.buffer_used_percent",
    "vendor.nanometrics.centaur.vco_control",
)

REQUIRED_METRIC_KEYS: Final[tuple[str, ...]] = (
    "connectivity.reachable",
    "connectivity.latency_ms",
    "connectivity.consecutive_failures",
    "health.severity",
    "health.is_stale",
)

MEASUREMENTS: Final[tuple[str, ...]] = (
    "recorder_acquisition",
    "recorder_archive",
    "recorder_device",
    "recorder_environment",
    "recorder_external_soh",
    "recorder_gnss",
    "recorder_health",
    "recorder_poll",
    "recorder_power",
    "recorder_sensor",
    "recorder_storage",
    "recorder_timing",
    "recorder_vendor_metric",
)

CATEGORIES: Final[tuple[str, ...]] = (
    "connectivity",
    "device",
    "power",
    "timing",
    "gnss",
    "sensor",
    "storage",
    "archive",
    "external_soh",
    "acquisition",
    "environment",
    "health",
    "vendor",
)

CAPABILITY_KEYS: Final[tuple[str, ...]] = (
    "acquisition.data_check",
    "archive.continuous",
    "archive.event",
    "device.configuration_status",
    "device.firmware_status",
    "device.overall_status",
    "device.temperature",
    "environment.weather_station",
    "external_soh.analog",
    "gnss.receiver",
    "power.current",
    "power.input_voltage",
    "sensor.control_lines",
    "sensor.mass_position",
    "sensor.status",
    "storage.internal",
    "storage.removable",
    "timing.quality",
    "timing.status",
    "vendor.nanometrics.centaur",
)
