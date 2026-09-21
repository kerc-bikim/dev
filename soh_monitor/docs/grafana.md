# Grafana Provisioning

대시보드와 알림은 Git 이 원본이다. Grafana UI 에서 고친 내용은 컨테이너를
다시 만들면 사라진다. 변경은 `scripts/gen_grafana.py` 와
`deploy/grafana/provisioning/alerting/` 을 통해서만 한다.

## 구성

| 경로 | 역할 |
|------|------|
| `deploy/grafana/provisioning/datasources/influxdb.yaml` | InfluxDB Flux, UID `soh-influx` |
| `deploy/grafana/provisioning/dashboards/dashboards.yaml` | 폴더 `관측소 SOH`, `allowUiUpdates: false` |
| `deploy/grafana/dashboards/*.json` | 대시보드. UID = 파일명 |
| `deploy/grafana/provisioning/alerting/` | 알림 7종 · 수신처 · 정책 |

생성: `python scripts/gen_grafana.py`  
검사: `python scripts/gen_grafana.py --check` (`make contracts-check` 에 포함)

## 대시보드

| UID | 내용 |
|-----|------|
| `01-fleet-overview` | 집계 · Geomap · 분류 행렬 · 현재 장애 |
| `02-station-detail` | 관측소 변수, 전 분류 시계열 |
| `03-centaur-ctr-detail` | 제조사 전용 Metric 만 |
| `04-edge-fleet` | Edge 통신 · Spool · 인증서 |
| `05-collector-operations` | Poll 처리량 · Influx 쓰기 |
| `06-data-quality` | 샘플 경과 · Gap · 채널 활성 |
| `07-kiosk-overview` | 관제. 10초 갱신, 장애 우선 |

공통 대시보드는 카탈로그 measurement 만 쓴다. `recorder_vendor_metric` 과
`vendor.*` 키는 `03-centaur-ctr-detail` 에만 있다.

## 알림

Grafana 는 장비별 임계값을 다시 계산하지 않는다. 백엔드가 적재한
`recorder_health.severity` 만 본다.

| 이름 | 조건 |
|------|------|
| Recorder Offline | scope=device, connectivity, severity=2 |
| Edge Offline | scope=edge, connectivity, severity≥1 |
| Timing Error | scope=device, timing, severity=2 |
| Recording Stopped | `recorder_storage.recording_status` = 2 |
| Storage Critical | scope=device, storage, severity=2 |
| Edge Spool Critical | scope=edge, storage, severity=2 |
| Influx Write Failure | scope=collector. 점 없음(noData)도 장애 |

Edge Offline 은 하위 기록계를 올리지 않는다. 하위는 이미 UNKNOWN /
EDGE UNREACHABLE 로 접혀 있다.

복구 알림은 켠다 (`disableResolveMessage: false`). 수신 주소는
`SOH_ALERT_EMAIL` (기본 `soh-ops@localhost`).

## Deep Link

관리 Web 은 nginx `/grafana/` 를 쓴다. 원본 `:3000` 으로 바로 가지 않는다.

| 화면 | 링크 |
|------|------|
| 관측소 상세 탭 | `/grafana/d/02-station-detail?var-station=&viewPanel=` |
| Edge 상세 | `/grafana/d/04-edge-fleet?var-edge=` |
| 통합 현황 / 장애 | `01-fleet-overview`, 관제는 `07-kiosk-overview?kiosk` |

패널 ID 는 `scripts/gen_grafana.py` 의 `STATION_PANEL_IDS` 와
`frontend/src/lib/grafana.ts` 가 같아야 한다.

## 숫자 의미

`recorder_health.severity`: 0=OK, 1=WARNING, 2=CRITICAL, 3=UNKNOWN,
4=DISABLED, 5=MAINTENANCE.
