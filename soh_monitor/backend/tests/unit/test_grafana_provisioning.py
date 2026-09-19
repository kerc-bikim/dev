"""Grafana Provisioning 계약.

대시보드 JSON 과 알림 YAML 이 카탈로그·계획서와 어긋나면 화면은 뜨지만
시계열이 비거나 알림이 중복된다. Grafana 를 띄우지 않고 파일을 못 박는다.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import yaml

from app.metrics.generated import MEASUREMENTS

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.gen_grafana import (  # noqa: E402
    ALL_UIDS,
    COMMON_UIDS,
    STATION_PANEL_IDS,
    VENDOR_MEASUREMENTS,
    VENDOR_ONLY_UID,
    render_all,
)
GRAFANA = ROOT / "deploy" / "grafana"
DASHBOARD_DIR = GRAFANA / "dashboards"
ALERT_RULES = GRAFANA / "provisioning" / "alerting" / "rules.yaml"
CONTACT = GRAFANA / "provisioning" / "alerting" / "contactpoints.yaml"
DATASOURCE = GRAFANA / "provisioning" / "datasources" / "influxdb.yaml"

REQUIRED_ALERTS = (
    "Recorder Offline",
    "Edge Offline",
    "Timing Error",
    "Recording Stopped",
    "Storage Critical",
    "Edge Spool Critical",
    "Influx Write Failure",
)

MEASUREMENT_RE = re.compile(r'_measurement\s*==\s*"([^"]+)"')


def _dashboards() -> dict[str, dict]:
    return {
        path.stem: json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(DASHBOARD_DIR.glob("*.json"))
    }


def _queries(dashboard: dict) -> list[str]:
    queries: list[str] = []
    for panel in dashboard.get("panels", []):
        for target in panel.get("targets", []):
            query = target.get("query")
            if query:
                queries.append(query)
        extra = panel.get("options", {})
        # geomap 등
        if isinstance(extra, dict):
            pass
    return queries


def _measurements(text: str) -> set[str]:
    return set(MEASUREMENT_RE.findall(text))


class TestDatasourceFolder:
    def test_datasource_uid는_고정이다(self):
        payload = yaml.safe_load(DATASOURCE.read_text(encoding="utf-8"))
        ds = payload["datasources"][0]
        assert ds["uid"] == "soh-influx"
        assert ds["jsonData"]["version"] == "Flux"

    def test_폴더와_UI_수정금지(self):
        dashboards = yaml.safe_load(
            (GRAFANA / "provisioning" / "dashboards" / "dashboards.yaml").read_text(
                encoding="utf-8"
            )
        )
        provider = dashboards["providers"][0]
        assert provider["folder"] == "관측소 SOH"
        assert provider["allowUiUpdates"] is False


class Test대시보드:
    def test_일곱_개가_있다(self):
        assert set(_dashboards()) == set(ALL_UIDS)

    def test_uid는_파일명과_같다(self):
        for uid, payload in _dashboards().items():
            assert payload["uid"] == uid
            assert payload["editable"] is False
            assert payload["schemaVersion"] == 39

    def test_모든_패널_datasource는_soh_influx이다(self):
        for payload in _dashboards().values():
            for panel in payload["panels"]:
                assert panel["datasource"]["uid"] == "soh-influx"
                for target in panel.get("targets", []):
                    assert target["datasource"]["uid"] == "soh-influx"

    def test_생성기와_커밋이_같다(self):
        assert _dashboards() == render_all()

    def test_관측소_딥링크_패널이_있다(self):
        station = _dashboards()["02-station-detail"]
        ids = {panel["id"] for panel in station["panels"]}
        for panel_id in STATION_PANEL_IDS.values():
            assert panel_id in ids

    def test_kiosk는_자동_갱신한다(self):
        kiosk = _dashboards()["07-kiosk-overview"]
        assert kiosk["refresh"] == "10s"


class Test제조사격리:
    def test_공통_대시보드는_vendor_measurement를_쓰지_않는다(self):
        for uid in COMMON_UIDS:
            blob = json.dumps(_dashboards()[uid], ensure_ascii=False)
            for measurement in VENDOR_MEASUREMENTS:
                assert measurement not in blob, f"{uid} 가 {measurement} 를 쓴다"
            assert "vendor.nanometrics" not in blob, f"{uid} 에 제조사 Metric 키가 있다"
            assert "vendor." not in blob, f"{uid} 에 vendor.* 가 있다"

    def test_전용_대시보드만_vendor를_쓴다(self):
        blob = json.dumps(_dashboards()[VENDOR_ONLY_UID], ensure_ascii=False)
        assert "recorder_vendor_metric" in blob
        assert "vendor.nanometrics.centaur.buffer_used_percent" in blob


class Test카탈로그:
    def test_flux_measurement는_카탈로그에_있다(self):
        allowed = set(MEASUREMENTS)
        for uid, payload in _dashboards().items():
            for query in _queries(payload):
                found = _measurements(query)
                unknown = found - allowed
                assert not unknown, f"{uid}: 카탈로그에 없는 measurement {unknown}"


class Test알림:
    def test_규칙_7종과_복구_수신처(self):
        rules = yaml.safe_load(ALERT_RULES.read_text(encoding="utf-8"))
        titles = [rule["title"] for group in rules["groups"] for rule in group["rules"]]
        assert titles == list(REQUIRED_ALERTS)
        assert len(titles) == len(set(titles))

        contacts = yaml.safe_load(CONTACT.read_text(encoding="utf-8"))
        receiver = contacts["contactPoints"][0]["receivers"][0]
        assert receiver["disableResolveMessage"] is False

    def test_알림은_판정_결과를_다시_계산하지_않는다(self):
        text = ALERT_RULES.read_text(encoding="utf-8")
        assert text.count("recorder_health") >= 6
        assert 'r._field == "severity"' in text
        assert "scope == \"edge\"" in text
        # 하위 기록계가 Edge Offline 에 편승하지 않는다
        edge_block = text.split("title: Edge Offline", 1)[1].split("title:", 1)[0]
        assert "scope == \"edge\"" in edge_block
        assert 'scope == "device"' not in edge_block

    def test_Influx_쓰기는_침묵도_장애다(self):
        text = ALERT_RULES.read_text(encoding="utf-8")
        block = text.split("title: Influx Write Failure", 1)[1]
        assert "noDataState: Alerting" in block.split("title:", 1)[0]
