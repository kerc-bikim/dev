"""Grafana 11 대시보드 JSON 을 생성한다.

대시보드는 Git 이 원본이다. Grafana UI 에서 고친 내용은 재배포 때 사라진다.
`--check` 는 커밋된 JSON 이 이 스크립트 출력과 같은지 검사한다.

사용법
    python scripts/gen_grafana.py
    python scripts/gen_grafana.py --check
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_DIR = ROOT / "deploy" / "grafana" / "dashboards"

DS: dict[str, str] = {"type": "influxdb", "uid": "soh-influx"}

# 관리 Web Deep Link 가 쓰는 패널 ID. 바꾸면 frontend/src/lib/grafana.ts 도 맞춘다.
STATION_PANEL_IDS: dict[str, int] = {
    "summary": 1,
    "power": 10,
    "timing": 20,
    "sensor": 30,
    "storage": 40,
    "data": 50,
    "external": 60,
}

VENDOR_ONLY_UID = "03-centaur-ctr-detail"
COMMON_UIDS = (
    "01-fleet-overview",
    "02-station-detail",
    "04-edge-fleet",
    "05-collector-operations",
    "06-data-quality",
    "07-kiosk-overview",
)
ALL_UIDS = COMMON_UIDS + (VENDOR_ONLY_UID,)

VENDOR_MEASUREMENTS = frozenset({"recorder_vendor_metric"})
VENDOR_METRIC_PREFIX = "vendor."


def flux(measurement: str, field: str, extra: str = "") -> str:
    lines = [
        "from(bucket: v.defaultBucket)",
        "  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)",
        f'  |> filter(fn: (r) => r._measurement == "{measurement}")',
        f'  |> filter(fn: (r) => r._field == "{field}")',
    ]
    if extra:
        lines.append(extra.rstrip())
    return "\n".join(lines) + "\n"


def station_filter() -> str:
    return '  |> filter(fn: (r) => r.station_code =~ /^${station:regex}$/)'


def edge_filter() -> str:
    return '  |> filter(fn: (r) => r.edge_code =~ /^${edge:regex}$/ or r.edge_id =~ /^${edge:regex}$/)'


def _defaults(unit: str | None = None) -> dict[str, Any]:
    defaults: dict[str, Any] = {
        "color": {"mode": "palette-classic"},
        "custom": {
            "axisBorderShow": False,
            "axisCenteredZero": False,
            "drawStyle": "line",
            "fillOpacity": 15,
            "lineWidth": 2,
            "pointSize": 5,
            "showPoints": "never",
            "spanNulls": False,
            "thresholdsStyle": {"mode": "off"},
        },
        "mappings": [],
        "thresholds": {
            "mode": "absolute",
            "steps": [{"color": "green", "value": None}],
        },
    }
    if unit:
        defaults["unit"] = unit
    return defaults


def panel(
    *,
    panel_id: int,
    title: str,
    query: str,
    x: int,
    y: int,
    w: int = 12,
    h: int = 8,
    panel_type: str = "timeseries",
    unit: str | None = None,
    description: str = "",
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "id": panel_id,
        "type": panel_type,
        "title": title,
        "description": description,
        "datasource": DS,
        "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "targets": [
            {
                "datasource": DS,
                "query": query,
                "refId": "A",
            }
        ],
        "fieldConfig": {"defaults": _defaults(unit), "overrides": []},
        "options": {
            "legend": {"calcs": [], "displayMode": "list", "placement": "bottom", "showLegend": True},
            "tooltip": {"mode": "multi", "sort": "desc"},
        },
    }
    if panel_type == "stat":
        body["options"] = {
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
            "orientation": "auto",
            "textMode": "auto",
            "colorMode": "background",
            "graphMode": "area",
            "justifyMode": "auto",
        }
        body["fieldConfig"]["defaults"]["thresholds"] = {
            "mode": "absolute",
            "steps": [
                {"color": "green", "value": None},
                {"color": "yellow", "value": 1},
                {"color": "red", "value": 2},
            ],
        }
    if panel_type == "table":
        body["options"] = {"showHeader": True, "cellHeight": "sm", "footer": {"show": False}}
        body["fieldConfig"] = {"defaults": {"custom": {"align": "auto", "filterable": True}}, "overrides": []}
    return body


def geomap_panel(panel_id: int, title: str, query: str, x: int, y: int, w: int = 12, h: int = 12) -> dict[str, Any]:
    return {
        "id": panel_id,
        "type": "geomap",
        "title": title,
        "datasource": DS,
        "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "targets": [{"datasource": DS, "query": query, "refId": "A"}],
        "options": {
            "view": {"allLayers": True, "id": "coords", "lat": 36.5, "lon": 127.8, "zoom": 6},
            "controls": {
                "mouseWheelZoom": True,
                "showAttribution": True,
                "showDebug": False,
                "showMeasure": False,
                "showScale": False,
                "showZoom": True,
            },
            "basemap": {"name": "Layer 0", "type": "default"},
            "layers": [
                {
                    "location": {
                        "mode": "coords",
                        "latitude": "latitude",
                        "longitude": "longitude",
                    },
                    "name": "관측소",
                    "tooltip": True,
                    "type": "markers",
                    "style": {
                        "color": {"fixed": "dark-red"},
                        "opacity": 0.8,
                        "rotation": {"fixed": 0},
                        "size": {"fixed": 8, "max": 15, "min": 4},
                        "symbol": {"fixed": "img/icons/marker/circle.svg", "mode": "fixed"},
                    },
                }
            ],
            "tooltip": {"mode": "details"},
        },
        "fieldConfig": {"defaults": {}, "overrides": []},
    }


def variable(name: str, label: str, tag: str) -> dict[str, Any]:
    return {
        "name": name,
        "label": label,
        "type": "query",
        "datasource": DS,
        "query": (
            "import \"influxdata/influxdb/schema\"\n"
            f'schema.tagValues(bucket: v.defaultBucket, tag: "{tag}")'
        ),
        "refresh": 2,
        "sort": 1,
        "includeAll": True,
        "multi": False,
        "current": {"text": "All", "value": "$__all"},
        "options": [],
    }


def dashboard(
    *,
    uid: str,
    title: str,
    panels: list[dict[str, Any]],
    variables: list[dict[str, Any]] | None = None,
    refresh: str = "30s",
    time_from: str = "now-6h",
    tags: list[str] | None = None,
    description: str = "",
) -> dict[str, Any]:
    return {
        "annotations": {"list": []},
        "description": description,
        "editable": False,
        "fiscalYearStartMonth": 0,
        "graphTooltip": 1,
        "id": None,
        "links": [],
        "liveNow": False,
        "panels": panels,
        "refresh": refresh,
        "schemaVersion": 39,
        "tags": tags or ["soh"],
        "templating": {"list": variables or []},
        "time": {"from": time_from, "to": "now"},
        "timepicker": {},
        "timezone": "browser",
        "title": title,
        "uid": uid,
        "version": 1,
        "weekStart": "",
    }


def fleet_overview() -> dict[str, Any]:
    health = flux("recorder_health", "severity", '  |> filter(fn: (r) => r.category == "overall")\n  |> last()')
    matrix = flux(
        "recorder_health",
        "severity",
        '  |> filter(fn: (r) => r.category != "overall")\n'
        "  |> last()\n"
        '  |> keep(columns: ["station_code", "category", "_value"])',
    )
    incidents = flux(
        "recorder_health",
        "severity",
        '  |> filter(fn: (r) => r.category == "overall")\n'
        "  |> last()\n"
        "  |> filter(fn: (r) => r._value >= 1 and r._value <= 3)\n"
        '  |> keep(columns: ["station_code", "region", "_value"])\n'
        "  |> sort(columns: [\"_value\"], desc: true)",
    )
    geo = (
        "from(bucket: v.defaultBucket)\n"
        "  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)\n"
        '  |> filter(fn: (r) => r._measurement == "recorder_gnss")\n'
        '  |> filter(fn: (r) => r._field == "latitude" or r._field == "longitude")\n'
        "  |> last()\n"
        '  |> pivot(rowKey: ["_time", "station_code"], columnKey: ["_field"], valueColumn: "_value")\n'
    )
    return dashboard(
        uid="01-fleet-overview",
        title="함대 현황",
        description="전체 관측소 상태 집계·지도·분류 행렬·현재 장애.",
        tags=["soh", "fleet"],
        panels=[
            panel(
                panel_id=1,
                title="종합 심각도",
                query=health,
                x=0,
                y=0,
                w=8,
                h=6,
                panel_type="stat",
                description="0=OK 1=WARNING 2=CRITICAL 3=UNKNOWN. Grafana 는 백엔드가 적재한 severity 만 본다.",
            ),
            panel(
                panel_id=5,
                title="통신 지연",
                query=flux("recorder_poll", "latency_ms"),
                x=8,
                y=0,
                w=8,
                h=6,
                unit="ms",
            ),
            panel(
                panel_id=6,
                title="통신 가능",
                query=flux("recorder_poll", "reachable"),
                x=16,
                y=0,
                w=8,
                h=6,
            ),
            geomap_panel(2, "관측소 위치", geo, x=0, y=6, w=12, h=12),
            panel(
                panel_id=3,
                title="분류별 상태 행렬",
                query=matrix,
                x=12,
                y=6,
                w=12,
                h=12,
                panel_type="table",
                description="관측소 × 분류. 숫자는 recorder_health.severity.",
            ),
            panel(
                panel_id=4,
                title="현재 장애",
                query=incidents,
                x=0,
                y=18,
                w=24,
                h=8,
                panel_type="table",
                description="WARNING 이상. UNKNOWN 은 확인 불가로 남긴다. Edge 하위 억제분은 scope=device 만 본다.",
            ),
        ],
    )


def station_detail() -> dict[str, Any]:
    sf = station_filter()
    panels = [
        panel(
            panel_id=STATION_PANEL_IDS["summary"],
            title="종합 상태",
            query=flux("recorder_health", "severity", f'{sf}\n  |> filter(fn: (r) => r.category == "overall")'),
            x=0,
            y=0,
            w=8,
            h=7,
            panel_type="stat",
        ),
        panel(
            panel_id=2,
            title="응답 시간",
            query=flux("recorder_poll", "latency_ms", sf),
            x=8,
            y=0,
            w=8,
            h=7,
            unit="ms",
        ),
        panel(
            panel_id=3,
            title="장비 온도",
            query=flux("recorder_device", "temperature_c", sf),
            x=16,
            y=0,
            w=8,
            h=7,
            unit="celsius",
        ),
        panel(
            panel_id=STATION_PANEL_IDS["power"],
            title="입력 전압",
            query=flux("recorder_power", "input_voltage_v", sf),
            x=0,
            y=7,
            w=8,
            h=8,
            unit="volt",
        ),
        panel(
            panel_id=11,
            title="전류",
            query=flux("recorder_power", "current_a", sf),
            x=8,
            y=7,
            w=8,
            h=8,
            unit="amp",
        ),
        panel(
            panel_id=12,
            title="소비 전력",
            query=flux("recorder_power", "consumption_w", sf),
            x=16,
            y=7,
            w=8,
            h=8,
            unit="watt",
        ),
        panel(
            panel_id=STATION_PANEL_IDS["timing"],
            title="시각 품질",
            query=flux("recorder_timing", "quality_percent", sf),
            x=0,
            y=15,
            w=8,
            h=8,
            unit="percent",
        ),
        panel(
            panel_id=21,
            title="시각 오차",
            query=flux("recorder_timing", "error_ns", sf),
            x=8,
            y=15,
            w=8,
            h=8,
            unit="ns",
        ),
        panel(
            panel_id=22,
            title="GNSS 위성 수",
            query=flux("recorder_gnss", "satellite_count", sf),
            x=16,
            y=15,
            w=8,
            h=8,
        ),
        panel(
            panel_id=STATION_PANEL_IDS["sensor"],
            title="질량 위치",
            query=flux("recorder_sensor", "mass_position_v", sf),
            x=0,
            y=23,
            w=12,
            h=8,
            unit="volt",
        ),
        panel(
            panel_id=31,
            title="센서 상태",
            query=flux("recorder_sensor", "status", sf),
            x=12,
            y=23,
            w=12,
            h=8,
        ),
        panel(
            panel_id=STATION_PANEL_IDS["storage"],
            title="저장소 사용률",
            query=flux("recorder_storage", "used_percent", sf),
            x=0,
            y=31,
            w=8,
            h=8,
            unit="percent",
        ),
        panel(
            panel_id=41,
            title="기록 상태",
            query=flux("recorder_storage", "recording_status", sf),
            x=8,
            y=31,
            w=8,
            h=8,
        ),
        panel(
            panel_id=42,
            title="아카이브 연속",
            query=flux("recorder_archive", "continuous_status", sf),
            x=16,
            y=31,
            w=8,
            h=8,
        ),
        panel(
            panel_id=STATION_PANEL_IDS["data"],
            title="최신 샘플 경과",
            query=flux("recorder_acquisition", "latest_sample_age_seconds", sf),
            x=0,
            y=39,
            w=12,
            h=8,
            unit="s",
        ),
        panel(
            panel_id=51,
            title="공백 길이",
            query=flux("recorder_acquisition", "gap_duration_seconds", sf),
            x=12,
            y=39,
            w=12,
            h=8,
            unit="s",
        ),
        panel(
            panel_id=STATION_PANEL_IDS["external"],
            title="외부 SOH",
            query=flux("recorder_external_soh", "value", sf),
            x=0,
            y=47,
            w=12,
            h=8,
        ),
        panel(
            panel_id=61,
            title="외부 스위치",
            query=flux("recorder_external_soh", "switch_state", sf),
            x=12,
            y=47,
            w=12,
            h=8,
        ),
    ]
    return dashboard(
        uid="02-station-detail",
        title="관측소 상세",
        description="관측소 변수로 전 분류 시계열을 본다. 제조사 전용 Metric 은 없다.",
        tags=["soh", "station"],
        variables=[variable("station", "관측소", "station_code")],
        panels=panels,
    )


def centaur_detail() -> dict[str, Any]:
    sf = station_filter()
    vendor = (
        flux(
            "recorder_vendor_metric",
            "value",
            f"{sf}\n  |> filter(fn: (r) => r.metric_key =~ /vendor\\..*/)",
        )
    )
    buffer_q = flux(
        "recorder_vendor_metric",
        "value",
        f'{sf}\n  |> filter(fn: (r) => r.metric_key == "vendor.nanometrics.centaur.buffer_used_percent")',
    )
    vco_q = flux(
        "recorder_vendor_metric",
        "value",
        f'{sf}\n  |> filter(fn: (r) => r.metric_key == "vendor.nanometrics.centaur.vco_control")',
    )
    return dashboard(
        uid=VENDOR_ONLY_UID,
        title="Centaur CTR 전용",
        description="제조사 전용 Metric 만 담는다. 공통 대시보드와 분리한다.",
        tags=["soh", "vendor"],
        variables=[variable("station", "관측소", "station_code")],
        panels=[
            panel(panel_id=1, title="제조사 전용 Metric", query=vendor, x=0, y=0, w=24, h=9),
            panel(
                panel_id=2,
                title="디지타이저 버퍼 사용률",
                query=buffer_q,
                x=0,
                y=9,
                w=12,
                h=8,
                unit="percent",
            ),
            panel(panel_id=3, title="VCO 제어 전압", query=vco_q, x=12, y=9, w=12, h=8),
        ],
    )


def edge_fleet() -> dict[str, Any]:
    ef = edge_filter()
    scope = '  |> filter(fn: (r) => r.scope == "edge")'
    return dashboard(
        uid="04-edge-fleet",
        title="Edge 함대",
        description="Edge 통신·Spool·자체 상태. 기록계 장애가 아니라 수집기 자체다.",
        tags=["soh", "edge"],
        variables=[variable("edge", "Edge", "edge_code")],
        panels=[
            panel(
                panel_id=1,
                title="Edge 통신",
                query=flux("recorder_health", "severity", f'{scope}\n  |> filter(fn: (r) => r.category == "connectivity")\n{ef}'),
                x=0,
                y=0,
                w=12,
                h=8,
                panel_type="stat",
            ),
            panel(
                panel_id=2,
                title="Spool 사용률",
                query=flux("recorder_health", "spool_used_percent", f"{scope}\n{ef}"),
                x=12,
                y=0,
                w=12,
                h=8,
                unit="percent",
            ),
            panel(
                panel_id=3,
                title="수집기 자체",
                query=flux("recorder_health", "severity", f'{scope}\n  |> filter(fn: (r) => r.category == "device")\n{ef}'),
                x=0,
                y=8,
                w=8,
                h=8,
                panel_type="stat",
            ),
            panel(
                panel_id=4,
                title="대기 Batch",
                query=flux("recorder_health", "pending_batches", f"{scope}\n{ef}"),
                x=8,
                y=8,
                w=8,
                h=8,
            ),
            panel(
                panel_id=5,
                title="인증서 남은 날",
                query=flux("recorder_health", "certificate_days_remaining", f"{scope}\n{ef}"),
                x=16,
                y=8,
                w=8,
                h=8,
            ),
        ],
    )


def collector_ops() -> dict[str, Any]:
    return dashboard(
        uid="05-collector-operations",
        title="수집기 운영",
        description="Poll 처리량·성공·지연·Influx 쓰기. 장비 SOH 가 아니라 우리 수집 경로다.",
        tags=["soh", "ops"],
        panels=[
            panel(
                panel_id=1,
                title="통신 가능 (처리량)",
                query=flux("recorder_poll", "reachable"),
                x=0,
                y=0,
                w=12,
                h=8,
            ),
            panel(
                panel_id=2,
                title="응답 시간",
                query=flux("recorder_poll", "latency_ms"),
                x=12,
                y=0,
                w=12,
                h=8,
                unit="ms",
            ),
            panel(
                panel_id=3,
                title="연속 실패",
                query=flux("recorder_poll", "consecutive_failures"),
                x=0,
                y=8,
                w=12,
                h=8,
            ),
            panel(
                panel_id=4,
                title="Influx 쓰기 실패",
                query=flux(
                    "recorder_health",
                    "failed_writes",
                    '  |> filter(fn: (r) => r.scope == "collector")',
                ),
                x=12,
                y=8,
                w=12,
                h=8,
            ),
            panel(
                panel_id=5,
                title="수집기 심각도",
                query=flux(
                    "recorder_health",
                    "severity",
                    '  |> filter(fn: (r) => r.scope == "collector")',
                ),
                x=0,
                y=16,
                w=24,
                h=7,
                panel_type="stat",
            ),
        ],
    )


def data_quality() -> dict[str, Any]:
    sf = station_filter()
    return dashboard(
        uid="06-data-quality",
        title="데이터 품질",
        description="채널별 샘플 경과·공백·활성. 센서 상태만으로는 파형 정지를 못 잡는다.",
        tags=["soh", "quality"],
        variables=[variable("station", "관측소", "station_code")],
        panels=[
            panel(
                panel_id=1,
                title="최신 샘플 경과",
                query=flux("recorder_acquisition", "latest_sample_age_seconds", sf),
                x=0,
                y=0,
                w=12,
                h=8,
                unit="s",
            ),
            panel(
                panel_id=2,
                title="공백 길이",
                query=flux("recorder_acquisition", "gap_duration_seconds", sf),
                x=12,
                y=0,
                w=12,
                h=8,
                unit="s",
            ),
            panel(
                panel_id=3,
                title="채널 활성",
                query=flux("recorder_acquisition", "channel_active", sf),
                x=0,
                y=8,
                w=12,
                h=8,
            ),
            panel(
                panel_id=4,
                title="가용 판정",
                query=flux("recorder_health", "severity", f'{sf}\n  |> filter(fn: (r) => r.category == "acquisition")'),
                x=12,
                y=8,
                w=12,
                h=8,
                panel_type="stat",
            ),
        ],
    )


def kiosk() -> dict[str, Any]:
    worst = flux(
        "recorder_health",
        "severity",
        '  |> filter(fn: (r) => r.category == "overall")\n'
        "  |> last()\n"
        "  |> filter(fn: (r) => r._value >= 1)\n"
        "  |> sort(columns: [\"_value\"], desc: true)",
    )
    geo = (
        "from(bucket: v.defaultBucket)\n"
        "  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)\n"
        '  |> filter(fn: (r) => r._measurement == "recorder_gnss")\n'
        '  |> filter(fn: (r) => r._field == "latitude" or r._field == "longitude")\n'
        "  |> last()\n"
        '  |> pivot(rowKey: ["_time", "station_code"], columnKey: ["_field"], valueColumn: "_value")\n'
    )
    return dashboard(
        uid="07-kiosk-overview",
        title="관제 현황",
        description="대형 화면용. 장애 우선 정렬, 자동 갱신.",
        refresh="10s",
        time_from="now-1h",
        tags=["soh", "kiosk"],
        panels=[
            panel(
                panel_id=1,
                title="CRITICAL",
                query=flux(
                    "recorder_health",
                    "severity",
                    '  |> filter(fn: (r) => r.category == "overall")\n  |> last()\n  |> filter(fn: (r) => r._value == 2)',
                ),
                x=0,
                y=0,
                w=8,
                h=6,
                panel_type="stat",
            ),
            panel(
                panel_id=2,
                title="WARNING",
                query=flux(
                    "recorder_health",
                    "severity",
                    '  |> filter(fn: (r) => r.category == "overall")\n  |> last()\n  |> filter(fn: (r) => r._value == 1)',
                ),
                x=8,
                y=0,
                w=8,
                h=6,
                panel_type="stat",
            ),
            panel(
                panel_id=3,
                title="UNKNOWN",
                query=flux(
                    "recorder_health",
                    "severity",
                    '  |> filter(fn: (r) => r.category == "overall")\n  |> last()\n  |> filter(fn: (r) => r._value == 3)',
                ),
                x=16,
                y=0,
                w=8,
                h=6,
                panel_type="stat",
            ),
            panel(
                panel_id=4,
                title="장애 우선 관측소",
                query=worst,
                x=0,
                y=6,
                w=12,
                h=12,
                panel_type="table",
            ),
            geomap_panel(5, "위치", geo, x=12, y=6, w=12, h=12),
        ],
    )


BUILDERS = {
    "01-fleet-overview": fleet_overview,
    "02-station-detail": station_detail,
    "03-centaur-ctr-detail": centaur_detail,
    "04-edge-fleet": edge_fleet,
    "05-collector-operations": collector_ops,
    "06-data-quality": data_quality,
    "07-kiosk-overview": kiosk,
}


def render_all() -> dict[str, dict[str, Any]]:
    return {uid: builder() for uid, builder in BUILDERS.items()}


def write_all() -> None:
    DASHBOARD_DIR.mkdir(parents=True, exist_ok=True)
    for uid, payload in render_all().items():
        path = DASHBOARD_DIR / f"{uid}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {path.relative_to(ROOT)}")


def check() -> int:
    expected = render_all()
    errors: list[str] = []
    for uid, payload in expected.items():
        path = DASHBOARD_DIR / f"{uid}.json"
        if not path.exists():
            errors.append(f"{path.relative_to(ROOT)} 가 없다")
            continue
        current = json.loads(path.read_text(encoding="utf-8"))
        if current != payload:
            errors.append(f"{path.relative_to(ROOT)} 가 생성기와 다르다. python scripts/gen_grafana.py")
    extra = {p.stem for p in DASHBOARD_DIR.glob("*.json")} - set(expected)
    for uid in sorted(extra):
        errors.append(f"{uid}.json 은 생성기에 없다")
    if errors:
        print("Grafana 대시보드 불일치:")
        for item in errors:
            print(f"  {item}")
        return 1
    print(f"Grafana 대시보드 일치 ({len(expected)}개)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Grafana 대시보드 생성")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        return check()
    write_all()
    return 0


if __name__ == "__main__":
    sys.exit(main())
