# 관측소 SOH 통합 모니터링 — 계획서

Nanometrics **Centaur CTR** 계열 기록계의 SOH(State of Health)를 설정한 분 주기로 수집해 InfluxDB에 적재하고, Grafana로 관측소를 통합 감시하는 시스템의 **구현 전 확정 계획**이다.

| 항목 | 내용 |
|------|------|
| 1차 대상 장비 | Nanometrics Centaur CTR2 / CTR3 / CTR4 (3채널 · 6채널) |
| 수집 인터페이스 | Centaur HTTP SOH API `GET /api/v1/instruments/soh` |
| 확장 대상 | Centaur Gen5(StrataOS), 타 제조사 기록계 |
| 수집 경로 | 중앙 직접 수집(DIRECT) + 지역 Edge Collector(EDGE) |
| 저장 | 설정·이력 PostgreSQL · 시계열 InfluxDB |
| 표출 | 관리 Web(React) + Grafana |
| 스택 | 백엔드 FastAPI · 프론트엔드 React + Vite + TypeScript (이 저장소 `earthworm_web` / `stationxml_manager` 와 동일) |
| 배포 | Docker Compose 기반 모노레포 (중앙 / Edge 분리) |
| UI 언어 | 한국어 |

구현 착수 순서와 완료 판정은 [15절 세부 작업 마일스톤](#15-세부-작업-마일스톤)을 따른다. 근거는 [19절](#19-근거-centaur-사용자-가이드).

현재 상태: **M0(저장소 골격)·M1(계약 확정)·M2(Centaur CTR Adapter)·M3(중앙 직접 수집) 완료.** 작업별 실제 진행 상태는 [`docs/progress.md`](docs/progress.md) 에 있다. 이 문서는 계획 원본이며, 구현이 계획과 달라진 부분은 `progress.md` 에 기록한다.

---

## 1. 목표

1. 수십 대의 Centaur CTR에서 설정한 분 주기로 SOH를 수집한다.
2. 운영 판단에 필요한 항목만 표준화해 InfluxDB에 적재한다.
3. 관측소 등록·수집 항목 설정·임계값 설정을 화면에서 처리한다. 장비 추가 시 코드를 고치지 않는다.
4. Grafana에서 전체 관측소 상태를 한 화면에서 파악한다.
5. 관측소망이 중앙에서 직접 닿지 않는 지역은 Edge Collector로 수집한다.
6. 중앙이 끊겨도 지역 수집이 멈추지 않고, 복구 후 누락분이 자동 채워진다.
7. Gen5와 타 제조사 기록계를 **Adapter 추가만으로** 같은 화면·같은 대시보드에 편입한다.

### 비목표 (MVP 제외)

- Gen5 실제 Adapter, 타 제조사 실제 Adapter (계약과 확장 지점만 준비)
- Adapter 런타임 Hot Reload / 동적 플러그인 로딩
- Edge 자동 HA Failover (수동 절체까지만)
- Kubernetes, 다중 조직 Tenant
- 기록계 원격 설정 변경·펌웨어 업그레이드
- 장애 예측·이상탐지 분석

---

## 2. 아키텍처

```
지역 A 내부망                              중앙
┌───────────────────────────┐        ┌──────────────────────────────┐
│ Centaur CTR × N           │        │ nginx (443)                  │
│        ▲ HTTP SOH         │        │  ├─ web (React 정적)         │
│        │                  │        │  ├─ api (FastAPI)            │
│ edge-agent                │        │  └─ grafana                  │
│  ├─ CTR Adapter           │        │                              │
│  ├─ scheduler             │  HTTPS │ collector (DIRECT 수집)      │
│  ├─ local spool (SQLite)  │ ─────► │ postgres · influxdb          │
│  └─ uploader / heartbeat  │Outbound└──────────────────────────────┘
└───────────────────────────┘         Inbound 연결 없음
```

수집 경로는 두 가지이며 **같은 Adapter와 같은 표준 Metric**을 쓴다.

```
DIRECT : collector ──────────────► Centaur CTR ──► 표준 Metric ──► InfluxDB
EDGE   : edge-agent ─► Centaur CTR ──► 표준 Metric ──► spool ──► 중앙 Ingest ──► InfluxDB
```

핵심 경계는 하나다.

```
제조사 원본 SOH → Recorder Adapter → 표준 Metric → 상태 판정 → InfluxDB / Grafana
```

`collector`, `edge-agent`, 상태 판정 엔진, DB 스키마, Grafana 대시보드는 제조사 원본 필드명을 **알지 못한다.** 그래서 Gen5·타 제조사 추가 범위가 Adapter와 일부 상세 패널로 한정된다.

---

## 3. 기술 스택 결정

| 영역 | 선택 | 근거 |
|------|------|------|
| 백엔드 | Python 3.11 + FastAPI + Pydantic v2 | 이 저장소 `earthworm_web` · `stationxml_manager` · PPSD 와 동일. 운영 인력이 같은 스택을 유지 |
| 동시 수집 | `asyncio` + `httpx.AsyncClient` + Semaphore | 100대 × 1분 주기여도 평균 초당 2건 미만. 비동기 I/O로 충분 |
| Edge Agent | 동일 Python 코드베이스, 별도 이미지 | Adapter 코드를 중앙과 100% 공유 |
| 설정 DB | PostgreSQL 16 | 관계 무결성, Advisory Lock으로 중복 Poll 방지 |
| 시계열 DB | InfluxDB 2.x | Grafana 연동, 보존정책·다운샘플링 |
| Edge Spool | SQLite(WAL) + gzip Segment | 별도 DB 서버 없이 전원 차단 복구 보장 |
| 프론트엔드 | React 18 + Vite + TypeScript + TanStack Query | 저장소 관례 |
| 시각화 | Grafana 11 (코드 Provisioning) | 대시보드를 Git으로 관리 |
| 배포 | Docker Compose | 중앙/Edge 각각 단일 명령 실행 |

> Go가 아니라 FastAPI를 택한 이유는 성능이 아니라 **저장소 일관성과 유지보수 인력**이다. 이 규모에서 병목은 언어가 아니라 기록계 응답 지연이며, 그것은 비동기 처리와 Timeout으로 해결한다.

---

## 4. 모노레포 구조

이 저장소의 최상위 프로젝트 관례(`earthworm_web/`, `stationxml_manager/`)에 맞춰 `soh_monitor/` 하위에 둔다.

```
soh_monitor/
├─ plan.md / plan.html / README.md
├─ contracts/                       # 모든 계약의 단일 원본
│  ├─ metrics/catalog.yaml          # 표준 Metric 카탈로그
│  ├─ metrics/status-mappings.yaml  # 제조사 상태문자열 → 표준 상태
│  ├─ openapi/openapi.yaml          # FastAPI에서 생성 후 커밋
│  ├─ adapter/manifest.schema.json
│  └─ edge/{config,ingest}.schema.json
│
├─ backend/
│  ├─ app/
│  │  ├─ main_api.py                # api 프로세스
│  │  ├─ main_collector.py          # collector 프로세스 (DIRECT)
│  │  ├─ main_edge.py               # edge-agent 프로세스
│  │  ├─ domain/                    # station device edge metric profile health incident
│  │  ├─ adapters/
│  │  │  ├─ contract.py             # RecorderAdapter 추상 계약
│  │  │  ├─ registry.py
│  │  │  ├─ centaur_ctr/            # 1차 구현
│  │  │  │  ├─ adapter.py client.py parser.py mapper.py capabilities.py
│  │  │  │  ├─ manifest.json
│  │  │  │  └─ testdata/*.json      # 익명화 실장비 응답
│  │  │  └─ mock_recorder/          # 확장성 검증용 가상 제조사
│  │  ├─ collector/                 # scheduler poller retry lease
│  │  ├─ edgeagent/                 # configsync spool uploader heartbeat
│  │  ├─ health/                    # evaluator state_machine rules
│  │  ├─ repository/                # postgres influx spool
│  │  ├─ api/                       # routers deps schemas
│  │  ├─ auth/ audit/ config/ observability/
│  │  └─ migrations/                # Alembic
│  ├─ tests/{unit,integration,fixtures}
│  ├─ requirements.txt
│  └─ pytest.ini
│
├─ frontend/
│  ├─ src/{app,api,components,features,pages,routes,schemas,generated}
│  └─ package.json vite.config.ts tsconfig.json
│
├─ mock/centaur_mock/               # 가상 Centaur CTR 서버
├─ deploy/
│  ├─ docker/Dockerfile.{backend,web,edge}
│  ├─ compose/compose.{central,edge,dev,test}.yml
│  ├─ grafana/{provisioning,dashboards}
│  ├─ influxdb/init/
│  ├─ nginx/nginx.conf
│  └─ examples/{central,edge}.env.example
├─ scripts/                         # build_plan_html.py, gen_api_client.sh, seed_demo.py
├─ tests/{e2e,load}
├─ docs/{architecture,adapter-development,edge-deployment,operations}
└─ Makefile
```

모듈 의존 방향은 한 방향으로 고정한다.

```
domain ◄── adapters
       ◄── collector / edgeagent
       ◄── health
       ◄── api
       ◄── repository
```

- Adapter는 DB를 모른다. 원본 → 표준 Metric 변환만 한다.
- Collector는 제조사 JSON 구조를 모른다.
- Health Engine은 CTR 원본 경로를 모른다.
- Frontend는 기록계·InfluxDB에 직접 접속하지 않는다.

---

## 5. 표준 SOH Metric 카탈로그

`contracts/metrics/catalog.yaml`이 단일 원본이며, 여기서 백엔드 상수·프론트 타입·DB Seed를 생성한다.

### 공통 Metric (MVP 적재 대상)

| 분류 | Metric | 단위 | Centaur CTR 원본 |
|------|--------|------|------------------|
| 연결 | `connectivity.reachable` | bool | 수집기 생성 |
| 연결 | `connectivity.latency_ms` | ms | 수집기 생성 |
| 연결 | `connectivity.consecutive_failures` | count | 수집기 생성 |
| 장비 | `device.overall_status` | status | `instrumentStatus` |
| 장비 | `device.configuration_status` | status | `config/commitState` |
| 장비 | `device.firmware_status` | status | `instrument/systemInfo/firmwareStatus` |
| 장비 | `device.firmware_version` | text | `systemSoftwareVersion` |
| 장비 | `device.temperature_c` | °C | `temperature` |
| 전원 | `power.input_voltage_v` | V | `powerSupply/voltage` |
| 전원 | `power.current_a` | A | `system/current` |
| 전원 | `power.consumption_w` | W | 전압 × 전류 |
| 시각 | `timing.status` | status | `timeStatus` |
| 시각 | `timing.phase_lock` | status | `timing/phaseLock` |
| 시각 | `timing.quality_percent` | % | `timing/timeQuality` |
| 시각 | `timing.error_ns` | ns | `timing/timeError` |
| 시각 | `timing.uncertainty_ns` | ns | `timing/timeUncertainty` |
| 시각 | `timing.last_lock_at` | UTC | `timing/lastLockTime` |
| GNSS | `gnss.satellite_count` | count | `gps/numberOfSatellites` |
| GNSS | `gnss.latitude` / `gnss.longitude` / `gnss.elevation_m` | deg / m | `instrument/earthLocation` |
| 센서 | `sensor.status` | status | `digitizer/sensor/status#_0`, `#_1` |
| 센서 | `sensor.control_state` | status | `sensor/controlLines/state#_0`, `#_1` |
| 센서 | `sensor.mass_position_v` | V | 축별 Mass Position — **M-1에서 실장비 경로 확정** |
| 저장소 | `storage.used_percent` | % | `controller/store/storePercentageUsed` |
| 저장소 | `storage.recording_status` | status | `controller/store/storeRecordingStatus` |
| 저장소 | `storage.sd_status` | status | `media/status/removableSD` |
| 저장소 | `storage.sd_free_bytes` | bytes | `media/freeSpace/removableSD` (미장착 시 −1) |
| 아카이브 | `archive.continuous_status` | status | `dataArchive/status` |
| 아카이브 | `archive.event_status` | status | `dataArchive/status/events` |
| 외부 SOH | `external_soh.value` | 설정 단위 | `externalSoh/voltage#_1`~`#_3` (µV) |
| 데이터 | `acquisition.latest_sample_age_seconds` | s | SeedLink/FDSN 별도 검사 |
| 데이터 | `acquisition.gap_duration_seconds` | s | SeedLink/FDSN 별도 검사 |
| 데이터 | `acquisition.channel_active` | bool | SeedLink/FDSN 별도 검사 |

### 표준 상태 값

```
OK · WARNING · CRITICAL · UNKNOWN · DISABLED · MAINTENANCE
```

`UNSUPPORTED`(장비가 그 기능이 없음)와 `UNKNOWN`(수집 실패로 모름)을 절대 `OK`로 접지 않는다. Grafana에도 두 값을 구분해 표시한다.

### 제조사 전용 Metric

공통에 억지로 끼워 넣지 않고 별도 이름공간에 둔다. 공통 대시보드는 이를 쓰지 않는다.

```
vendor.nanometrics.centaur.vco_control
vendor.nanometrics.centaur.buffer_used_percent
```

### 센서 상태 판정 주의

Centaur의 센서 상태는 사실상 **Mass Position 임계값**이 근거다. 센서 미연결이나 파형 정지를 잡지 못한다(펌웨어 릴리스 노트에 명시된 알려진 제약). 따라서 `sensor.status = OK`만으로 정상이라 판단하지 않고, SeedLink/FDSN 기반 `acquisition.*` 검사를 함께 본다.

---

## 6. 데이터 모델

### PostgreSQL 주요 테이블

```
manufacturers            device_models          adapter_definitions
adapter_versions         adapter_metric_mappings

stations                 devices                device_endpoints
sensors                  sensor_axes            external_soh_channels
device_capabilities

collection_profiles      metric_definitions     profile_metrics
device_metric_overrides

edge_collectors          edge_assignments       edge_ingest_batches
edge_runtime_states

poll_runs                device_runtime_states  health_states
incidents                incident_events        maintenance_windows

users                    roles                  audit_logs
```

핵심 제약:

- `devices.collection_mode ∈ {DIRECT, EDGE}`, `EDGE`면 `edge_id` 필수
- `edge_assignments`는 활성 상태에서 `device_id` Unique — 두 Edge가 같은 장비를 동시 수집하지 못한다
- 기록계 접속 비밀번호는 `device_endpoints.credential_reference`로만 저장(암호화 저장소 참조). 평문 컬럼 없음
- 관측소 삭제는 물리 삭제 대신 `retired`
- 제조사별 전용 테이블을 만들지 않는다

### InfluxDB

Measurement:

```
recorder_poll  recorder_device  recorder_power  recorder_timing  recorder_gnss
recorder_sensor  recorder_storage  recorder_archive  recorder_external_soh
recorder_acquisition  recorder_health  recorder_vendor_metric  edge_health
```

Tag:

```
station_id station_code device_id manufacturer product_family generation model
sensor_port channel axis region collection_mode
```

IP·펌웨어 버전은 변동값이므로 Tag로 쓰지 않는다(Cardinality·이력 왜곡 방지). `recorder_vendor_metric`은 카탈로그에 등록된 `metric_key`만 허용한다.

시간 필드는 두 개를 둔다.

```
observed_at : 기록계를 관측한 시각 (Point timestamp)
received_at : 중앙이 수신한 시각 (Field)
```

Edge가 하루 뒤 복구돼도 Grafana에는 원래 관측 시각으로 채워진다. 단 **현재 상태(health_states)는 `observed_at`이 기존보다 최신일 때만 갱신**해, 늦게 도착한 과거 데이터가 현재 상태를 되돌리지 못하게 한다.

보존정책: 원본 180일 · 5분 집계 2년 · 1시간 집계 5년. 장애 이력은 PostgreSQL에 영구 보관.

---

## 7. Edge Collector 설계

### Store-and-Forward

```
Centaur 수집 → 표준 Metric → 로컬 Spool 기록 → Batch 업로드 → 중앙 ACK → Spool 삭제
```

**로컬 기록을 먼저** 한다. 전송 실패 후 복구를 시도하는 순서보다 유실 위험이 낮다.

Spool 상태: `PENDING → UPLOADING → ACKNOWLEDGED → FAILED`

MVP 기본값:

| 항목 | 값 |
|------|-----|
| Spool 한도 | 5 GB (경고 80%, 장애 90%) |
| 최소 보관 | 7일 (권장 30일) |
| Batch 크기 | 최대 1,000 Poll 또는 5 MB, gzip |
| 업로드 Timeout | 30초 |
| Heartbeat | 30초 |
| 삭제 우선순위 | ACK 완료분 → 오래된 정상 Metric → 집계 가능분. 장애 이벤트는 최후까지 보존 |

### 프로토콜

```
POST /api/v1/edge/enroll            일회용 Token → 클라이언트 인증서 발급
POST /api/v1/edge/heartbeat         상태 보고
GET  /api/v1/edge/config?currentVersion=N   설정 동기화
POST /api/v1/edge/ingest/batches    데이터 업로드 (gzip)
POST /api/v1/edge/tasks/{id}/result 연결 시험 등 원격 작업 결과
```

중복 제거 키: `edge_id` + `sequence` + `batch_id` + `poll_id`. 같은 Batch를 여러 번 보내도 한 번만 반영된다.

설정 적용은 원자적으로 한다. 다운로드 → 서명·Schema 검증 → 장비 중복 할당 검사 → 일괄 적용 → 결과 보고, 실패 시 이전 버전 Rollback. 중앙이 끊긴 동안에는 마지막 성공 설정으로 계속 수집하고 Adapter 자동 업데이트는 하지 않는다.

### 네트워크·보안

- 중앙 → Edge Inbound 연결 없음. Edge → 중앙 HTTPS 443 Outbound만
- Edge → 할당된 기록계 IP 대역만 접근, Edge 간 통신 차단
- Edge별 개별 클라이언트 인증서(mTLS), 만료 전 자동 갱신, 폐기 시 즉시 차단
- 연결 시험 API는 SSRF 차단을 위해 사설망/승인 대역만 허용

### 장애 상관관계

| 상황 | 표시 |
|------|------|
| 기록계 1대 무응답 | 해당 기록계 `OFFLINE` |
| Edge 정상 · 여러 기록계 무응답 | 각 기록계 개별 장애 |
| Edge ↔ 중앙 통신 불가 | `EDGE COMMUNICATION LOST` |
| Edge 서버 중단 | `EDGE OFFLINE` + 하위 기록계 `UNKNOWN / EDGE UNREACHABLE` |
| 업로드만 실패 | `UPLOAD DEGRADED` |
| Spool 임계 | `EDGE STORAGE WARNING/CRITICAL` |
| 설정 적용 실패 | `EDGE CONFIG ERROR` |
| Edge 시각 오차 | `EDGE CLOCK ERROR` |

Edge 하나가 죽었을 때 하위 수십 개 기록계 장애 알림이 쏟아지지 않도록 **하위 장애를 억제하고 Edge 단일 알림**으로 올린다.

---

## 8. 상태 판정과 알림

```
표준 Metric → 단위 변환 → 프로파일 임계값 → 지속시간/연속횟수 → Hysteresis
           → 상태 전이 → Incident 생성·복구 → recorder_health 적재 → Grafana Alert
```

Grafana가 장비별 임계값을 직접 계산하지 않는다. 백엔드가 판정해 `recorder_health.severity`를 적재하고 Grafana는 그 값만 감시한다. 임계값 설정이 화면·DB 한 곳에만 존재하게 하려는 것이다.

MVP 기본 규칙:

| 항목 | 주의 | 장애 |
|------|------|------|
| 기록계 통신 | 2회 연속 실패 | 3회 연속 실패 |
| Edge Heartbeat | 2회 누락 | 3회 누락 |
| 내부 저장소 | 80% | 90% |
| Recording 상태 | 1회 비정상 | 2회 연속 |
| Timing / GNSS | 1회 비정상 | 2회 연속 |
| 센서 | 기록계 Warning | 기록계 Error |
| SD카드 | 상태 이상 | Error / Not Present |
| 설정 Commit | — | `uncommitted` 지속 |
| Edge Spool | 80% | 90% |
| 데이터 지연 | 수집주기 × 2 | 수집주기 × 3 |

전압·온도·Mass Position은 공통 기준을 쓰지 않는다. 12V 배터리 / 24V / 태양광 관측소는 서로 다른 프로파일을 적용한다. GNSS Duty Cycle 장비는 위성 수만으로 장애를 만들지 않는다. 유지보수 시간대에는 알림을 억제하고 상태만 `MAINTENANCE`로 기록한다.

---

## 9. API 목록 (MVP)

```
POST   /api/v1/auth/login | logout        GET /api/v1/auth/me

GET    /api/v1/stations                   POST /api/v1/stations
GET    /api/v1/stations/{id}              PUT  /api/v1/stations/{id}
POST   /api/v1/stations/import            GET  /api/v1/stations/{id}/current-health

POST   /api/v1/stations/{id}/devices      PUT  /api/v1/devices/{id}
POST   /api/v1/devices/{id}/probe         POST /api/v1/devices/{id}/test-connection
POST   /api/v1/devices/{id}/poll-now      GET  /api/v1/devices/{id}/capabilities
GET    /api/v1/devices/{id}/soh-preview   # 민감정보 제거 후 원본 미리보기

GET    /api/v1/edges                      POST /api/v1/edges
POST   /api/v1/edges/{id}/enrollment-token
POST   /api/v1/edges/{id}/assignments     DELETE /api/v1/edges/{id}/assignments/{deviceId}
GET    /api/v1/edges/{id}/health

GET/POST/PUT /api/v1/collection-profiles  GET/POST/PUT /api/v1/metric-profiles
GET    /api/v1/metric-catalog             GET  /api/v1/adapters

GET    /api/v1/fleet/summary              GET  /api/v1/incidents
POST   /api/v1/incidents/{id}/acknowledge POST /api/v1/maintenance-windows
GET    /api/v1/poll-runs                  GET  /api/v1/audit-logs
```

권한: `ADMIN`(전체 설정) · `OPERATOR`(장애 확인·유지보수) · `VIEWER`(조회).

---

## 10. 화면 구성 (MVP)

```
/login
/overview            통합 현황 (상태 집계 · 지도 · 현재 장애 · Direct/Edge 구분)
/stations            목록 (통신·전원·시각·센서·저장소·데이터 컬럼, 필터, 일괄 작업)
/stations/new        등록 마법사
/stations/:id        상세 (요약/전원/시각·GNSS/센서/저장소/데이터/외부SOH/수집이력/설정/장애)
/edges               Edge 목록
/edges/:id           Edge 상세 (할당 장비 · Spool · 설정버전 · 인증서)
/profiles            수집·Metric 프로파일
/incidents           장애 목록·확인
/settings            사용자·알림·감사 로그
```

등록 마법사 흐름:

```
기본정보 → 제조사/모델 선택 → 수집방식(DIRECT/EDGE) → 접속정보 → 연결 시험
→ 장비 자동 탐지(모델·펌웨어·채널·Capability) → 센서 설정 → 외부 SOH 변환식
→ 프로파일·알림 → 검토 → 저장 및 첫 수집
```

제조사 선택 UI는 처음부터 노출하되 미구현 Adapter는 `준비 중`으로 비활성화한다. Adapter Manifest의 JSON Schema로 제조사별 접속 입력 폼을 동적으로 생성해, 새 Adapter가 화면 코드를 고치지 않아도 등록 가능하게 한다.

---

## 11. Grafana

```
01-fleet-overview        전체 상태 · Geomap · 카테고리 Matrix · 현재 장애
02-station-detail        관측소 단위 시계열 전체
03-centaur-ctr-detail    CTR 전용 (Vendor Metric 포함)
04-edge-fleet            Edge 상태 · Spool · 업로드 · 버전 · 인증서
05-collector-operations  Poll 처리량 · 성공률 · Timeout · Influx Write 오류
06-data-quality          채널별 Sample Age · Gap · 가용률
```

Datasource와 Dashboard는 손으로 만들지 않고 `deploy/grafana/provisioning`으로 코드 관리한다. 알림: Recorder Offline · Edge Offline · Timing Error · Recording Stopped · Storage Critical · Edge Spool Critical · Influx Write Failure.

---

## 12. Docker 구성

### 중앙 `compose.central.yml`

```
nginx(443) · web · api · collector · migrate · postgres · influxdb · grafana
```

네트워크 3분할: `public-net`(nginx) / `app-net`(web·api·collector·grafana) / `data-net`(api·collector·postgres·influxdb·grafana). PostgreSQL·InfluxDB 포트는 외부에 공개하지 않는다.

### Edge `compose.edge.yml`

```
edge-agent (volume: edge-spool, certs, edge.env)
```

Edge에는 PostgreSQL·InfluxDB·Grafana를 두지 않는다. Health Endpoint는 `127.0.0.1`에만 바인딩한다.

### 개발 `compose.dev.yml`

`centaur-mock` 추가. 시나리오 전환 가능:

```
NORMAL · GPS_UNLOCKED · LOW_VOLTAGE · SENSOR_ERROR · STORE_FULL
NO_SD_CARD · SLOW_RESPONSE · INVALID_JSON · OFFLINE
```

이미지 태그: `soh-api` · `soh-collector` · `soh-edge` · `soh-web`. Edge 이미지에는 API·Web 리소스를 넣지 않는다.

---

## 13. 테스트 전략

| 계층 | 대상 |
|------|------|
| 단위 | CTR 파싱, 펌웨어별 Mapping, 단위 변환, 상태 Mapping, 임계값·Hysteresis, 외부 SOH 변환식, 스케줄 계산, Spool 상태 전이, 중복 Batch 판정 |
| Adapter 계약 | 정상 · 느린 응답 · 연결 실패 · 인증 실패 · 비정상 JSON · 필드 누락 · 3/6채널 · SD 미장착 · GPS Unlock · Instrument ID 불일치 |
| 통합 | Migration, Influx Write/Query, Poll 중복 방지, 재시도·Offline 판정, Incident 생성·복구, 유지보수 억제, Edge Backfill |
| E2E | 로그인 → 등록 → 연결 시험 → 첫 수집 → 장애 발생 → 복구, 권한별 버튼 제한 |
| 부하 | 100대 1분 주기, 느린 장비 20%, 동시 Timeout, Influx 중단, 재시작 후 스케줄 복구 |

모든 Adapter는 동일한 계약 테스트를 통과해야 등록된다. 실장비 응답은 익명화해 `testdata/`에 Fixture로 보관하고, 이것이 회귀 방지의 기준이 된다.

---

## 14. 마일스톤 개요

```
M-1 장비 조사 ──► M0 골격 ──► M1 계약 확정 ──┬─► M2 CTR Adapter ──► M3 Direct Collector ──► M4 상태판정
                                              │                                                │
                                              └─► M5 관리 API ──► M6 Frontend ────────────────┤
                                                                                               ▼
                                                        M7 Edge Agent ──► M8 Edge 통합 ──► M9 Grafana
                                                                                               ▼
                                                                        M10 운영 강화 ──► M11 확장성 검증
```

| ID | 마일스톤 | 성격 | 선행 |
|----|----------|------|------|
| M-1 | 장비·환경 조사 | 필수 선행, 코드 없음 | — |
| M0 | 저장소 골격과 개발환경 | 기반 | — |
| M1 | 계약 확정 (Metric·DB·OpenAPI·Adapter) | 기반, 이후 전 단계 참조 | M0 |
| M2 | Centaur CTR Adapter + Mock 기록계 | 핵심 | M-1, M1 |
| M3 | Direct Collector + InfluxDB 적재 | 핵심 | M2 |
| M4 | 상태 판정 엔진 + 장애 이력 | 핵심 | M3 |
| M5 | 관리 API (인증·CRUD·프로파일) | 핵심 | M1 |
| M6 | 관리 Frontend 1차 | 핵심 | M5 |
| M7 | Edge Agent (Spool·업로드·설정동기화) | 핵심 | M3 |
| M8 | 중앙 Ingest·Edge 관리화면·장애 상관관계 | 핵심 | M4, M6, M7 |
| M9 | Grafana Provisioning + 알림 | 표출 | M4, M8 |
| M10 | 운영 강화 + 파일럿 | 출시 | M9 |
| M11 | 확장성 검증 (Gen5·타 제조사 준비) | 확장 | M10 |

병렬 트랙: M2~M4(수집)와 M5~M6(관리 화면)은 M1 계약이 고정된 뒤 동시에 진행할 수 있다. M7 Edge는 M3 Poll 결과 모델이 확정되면 착수 가능하다.

---

## 15. 세부 작업 마일스톤

각 작업은 `산출물`과 `완료 판정`을 함께 둔다. 완료 판정은 "구현했다"가 아니라 **관측 가능한 결과**로 쓴다.

### 공통 완료 정의 (DoD)

모든 작업에 공통 적용한다.

1. 단위 테스트 추가 및 통과
2. `contracts/` 변경 시 Schema 검증 통과
3. 사람이 읽는 로그와 오류 메시지가 한국어 또는 명확한 코드로 남음
4. Secret이 로그·응답·이미지·Git에 남지 않음
5. `docs/` 해당 문서 갱신
6. Docker 환경에서 재현 가능(로컬 전용 설정 금지)

---

### M-1 장비·환경 조사 (코드 없음, 최우선)

이 단계 없이 M2를 시작하면 Mapping을 두 번 만들게 된다.

| ID | 작업 | 산출물 | 완료 판정 |
|----|------|--------|-----------|
| M-1.1 | 보유 CTR 목록화 (모델·시리얼·펌웨어·IP·지역) | `docs/inventory.md` | 전 장비가 표에 있고 모델·펌웨어 분포가 집계됨 |
| M-1.2 | 3채널·6채널 각 1대 이상 SOH 응답 채집 | `backend/app/adapters/centaur_ctr/testdata/*.json` | 익명화된 실제 응답 4종 이상 확보 |
| M-1.3 | Mass Position의 SOH API 실제 경로 확정 | Mapping 표 갱신 | 축별 값이 어느 키로 오는지 실응답으로 확인 |
| M-1.4 | 인증 필요 여부·HTTPS 지원 확인 | 조사 메모 | 인증 없이 SOH 조회 가능 여부가 모델별로 확정 |
| M-1.5 | 중앙 → 각 관측소 IP 접근성 시험 | 지역별 접근성 표 | DIRECT 가능 지역과 EDGE 필요 지역이 구분됨 |
| M-1.6 | 센서 A/B 모델·축 구성, 외부 SOH 결선 내역 | 관측소별 구성표 | Mass Position 임계값 설정 근거 확보 |
| M-1.7 | 전원 구성 분류 (12V/24V/태양광) | 전원 프로파일 초안 | 전압 임계값 프로파일 후보가 3종 이내로 정리됨 |
| M-1.8 | 기존 InfluxDB·Grafana 유무·버전, 관측소 코드 체계, 알림 채널 | 통합 요건 메모 | 신규 구축/기존 연동 여부 확정 |

**Exit:** M-1.2와 M-1.3이 끝나지 않으면 M2를 착수하지 않는다.

---

### M0 저장소 골격과 개발환경

| ID | 작업 | 산출물 | 완료 판정 |
|----|------|--------|-----------|
| M0.1 | `soh_monitor/` 디렉터리 골격 생성 | 4절 구조 | 빈 패키지까지 포함해 구조가 존재 |
| M0.2 | 백엔드 기본 앱 3개 실행점 | `main_api.py` `main_collector.py` `main_edge.py` | 각 프로세스가 기동되고 `/healthz` 응답 |
| M0.3 | `requirements.txt` 고정 (FastAPI·httpx·SQLAlchemy·Alembic·influxdb-client·pytest) | 의존성 파일 | 버전 Pin, 설치 재현 가능 |
| M0.4 | Frontend Vite + TS + Router + TanStack Query 골격 | `frontend/` | 빈 대시보드가 `/`에서 렌더 |
| M0.5 | `Dockerfile.backend` Multi-stage (api/collector/migrate Target) | 이미지 3종 | 각 Target 빌드 성공, 런타임에 빌드도구 없음 |
| M0.6 | `Dockerfile.web`(Nginx 정적), `Dockerfile.edge`(경량) | 이미지 2종 | Web 이미지에 Node 런타임 없음, Edge에 API 코드 없음 |
| M0.7 | `compose.dev.yml` (postgres·influxdb·grafana·api·collector·web) | 개발 Compose | `make dev` 한 번으로 전체 기동 |
| M0.8 | `Makefile` (dev/migrate/seed/test/e2e/down/plan-html) | Makefile | 각 타깃 동작 |
| M0.9 | `.env.example`, Secret 분리, `.gitignore` 확인 | 예시 설정 | 저장소에 실제 Secret·인증서 없음 |
| M0.10 | 로깅·요청ID·구조화 로그 기반 | `observability/` | 모든 Poll 로그에 `device_id`·`poll_id` 포함 |

**Exit:** 빈 시스템이지만 `make dev`로 전체 스택이 뜨고 Grafana가 InfluxDB를 Datasource로 인식한다.

---

### M1 계약 확정

이 단계의 산출물이 이후 모든 코드의 기준이 된다. 여기서 이름을 잘못 정하면 Gen5 확장에서 되돌리기 어렵다.

| ID | 작업 | 산출물 | 완료 판정 |
|----|------|--------|-----------|
| M1.1 | 표준 Metric 카탈로그 작성 | `contracts/metrics/catalog.yaml` | 5절 항목 전부 등록, 단위·타입·필수여부 명시 |
| M1.2 | 상태 Mapping 규칙 | `contracts/metrics/status-mappings.yaml` | CTR 상태문자열 전부가 표준 6상태로 매핑 |
| M1.3 | 카탈로그 → 백엔드 상수·프론트 타입 생성기 | `scripts/gen_metrics.py` | 카탈로그 수정 시 양쪽 타입이 동시 갱신 |
| M1.4 | PostgreSQL 초기 스키마 Alembic Migration | `migrations/0001_*` | 6절 테이블 전부 생성·롤백 가능 |
| M1.5 | 제조사 중립 명명 검사 | Lint 규칙 | 코드·스키마에 `centaur_` 접두 테이블/Measurement 없음 |
| M1.6 | `RecorderAdapter` 추상 계약 정의 | `adapters/contract.py` | 10개 메서드 시그니처와 반환 모델 확정 |
| M1.7 | Adapter Manifest Schema | `contracts/adapter/manifest.schema.json` | Manifest 검증 테스트 통과 |
| M1.8 | Capability 키 목록과 4상태 정의 | `contracts/metrics/capabilities.yaml` | `SUPPORTED_ENABLED/DISABLED/UNSUPPORTED/UNKNOWN` 규칙 문서화 |
| M1.9 | Edge 설정·Ingest Schema | `contracts/edge/*.json` | 예시 Payload가 Schema 검증 통과 |
| M1.10 | InfluxDB Bucket·보존정책·다운샘플링 Task 초기화 | `deploy/influxdb/init/` | 컨테이너 초기화만으로 Bucket·Task 생성 |
| M1.11 | OpenAPI 초안 커밋 및 클라이언트 생성 스크립트 | `contracts/openapi/openapi.yaml`, `scripts/gen_api_client.sh` | 생성된 TS 클라이언트가 빌드 통과 |

**Exit:** Metric 이름·상태 값·Adapter 계약·DB 스키마가 문서와 코드에서 일치한다. 이후 이름 변경은 Migration을 동반하는 변경으로만 허용한다.

---

### M2 Centaur CTR Adapter + Mock 기록계

| ID | 작업 | 산출물 | 완료 판정 |
|----|------|--------|-----------|
| M2.1 | 가상 Centaur CTR 서버 | `mock/centaur_mock/` | 9개 시나리오 전환 가능, 3/6채널 응답 제공 |
| M2.2 | CTR HTTP Client (Timeout·재시도 없음, 오류 분류) | `centaur_ctr/client.py` | DNS·거부·연결·응답 Timeout·HTTP·본문오류를 서로 다른 코드로 반환 |
| M2.3 | SOH JSON Parser | `parser.py` | 필드 누락·미지의 상태문자열에도 예외 없이 부분 결과 반환 |
| M2.4 | 표준 Metric Mapper (단위 변환 포함) | `mapper.py` | µV→V, ns, bytes, −1(SD 미장착) 처리 검증 |
| M2.5 | 펌웨어별 Mapping 버전 처리 | `adapter_metric_mappings` Seed | 조건분기 없이 Mapping 테이블로 차이 흡수 |
| M2.6 | Capability 자동 탐지 (채널수·SD·GNSS·외부SOH) | `capabilities.py` | 3채널 장비에서 Sensor B가 `UNSUPPORTED`로 판정 |
| M2.7 | `Probe` 구현 (모델·시리얼·펌웨어·InstrumentID) | `adapter.py` | 등록값과 실제값 불일치를 목록으로 반환 |
| M2.8 | 민감정보 제거 (`RedactSensitiveData`) | `adapter.py` | `soh-preview` 응답에 인증정보·내부 경로 없음 |
| M2.9 | Adapter Manifest 작성·등록 | `manifest.json`, `registry.py` | `GET /api/v1/adapters`에 CTR이 노출 |
| M2.10 | Fixture 기반 계약 테스트 | `tests/unit/adapters/` | M-1.2 실응답 4종 + Mock 9종 전부 통과 |
| M2.11 | 데이터 연속성 Adapter (SeedLink/FDSN) 분리 구현 | `adapters/data_availability/` | 채널별 Sample Age·Gap을 SOH와 독립적으로 산출 |

**Exit:** 서로 다른 CTR 모델·펌웨어의 응답이 **동일한 표준 Metric 집합**으로 변환되고, 미지원 항목은 `UNSUPPORTED`로 표시된다.

---

### M3 Direct Collector + InfluxDB 적재

| ID | 작업 | 산출물 | 완료 판정 |
|----|------|--------|-----------|
| M3.1 | 스케줄러 (10초 Tick, `next_poll_at` 조회) | `collector/scheduler.py` | 분 단위 설정대로 Poll 시각이 잡힘 |
| M3.2 | 중복 실행 방지 (Advisory Lock / Lease) | `collector/lease.py` | 인스턴스 2개 동시 기동에도 장비별 1회만 수집 |
| M3.3 | Jitter 분산 (10~20%) | scheduler | 동일 시각 동시 요청이 분산됨 |
| M3.4 | 동시성 제한 및 장비별 진행 중 Poll 차단 | `collector/worker.py` | 느린 장비가 전체 수집을 지연시키지 않음 |
| M3.5 | 재시도·Backoff, 실패 유형별 분류 | `collector/retry.py` | 10종 실패 유형이 `poll_runs.error_code`로 구분 |
| M3.6 | 연속 실패 카운터와 Offline 판정 | `device_runtime_states` | 2회 WARNING, 3회 CRITICAL 전이 확인 |
| M3.7 | InfluxDB Batch Write | `repository/influx/` | 한 Poll이 분류별 Point로 묶여 기록 |
| M3.8 | Influx 장애 시 재시도·백프레셔 | writer | Influx 30분 중단 후 재개 시 유실 없음 |
| M3.9 | `poll_runs` 이력 적재 | Postgres | 성공률·응답시간 조회 가능 |
| M3.10 | Stale 판정 (수집 성공했으나 값이 낡음) | health 입력 | 마지막 수집 시각이 화면·Grafana에 항상 함께 표시 |
| M3.11 | `poll-now` 수동 수집 | API·Collector 연동 | 화면 요청 후 5초 내 결과 반영 |

**Exit:** Mock 50대 + 실장비 1대를 1분 주기로 안정 수집하고, 한 장비 장애가 다른 장비 수집에 영향을 주지 않는다.

---

### M4 상태 판정 엔진 + 장애 이력

| ID | 작업 | 산출물 | 완료 판정 |
|----|------|--------|-----------|
| M4.1 | 임계값 평가기 (프로파일 + 장비 Override) | `health/evaluator.py` | 관측소별 전압 기준이 서로 다르게 적용 |
| M4.2 | 지속시간·연속횟수·Hysteresis | `health/rules.py` | 순간 스파이크로 장애가 생기지 않음 |
| M4.3 | 카테고리별 상태 집계 (통신·전원·시각·센서·저장소·데이터) | `health/state_machine.py` | 장비 종합 상태와 별개로 카테고리 상태가 계산 |
| M4.4 | `UNSUPPORTED`·`UNKNOWN` 제외 규칙 | evaluator | 미지원 기능이 장애로 집계되지 않음 |
| M4.5 | Incident 생성·확인·복구 상태기계 | `incident/` | `PENDING→OPEN→ACK→RESOLVED` 전이 이력 저장 |
| M4.6 | 유지보수 시간 억제 | `maintenance/` | 유지보수 중 알림 없음, 상태는 `MAINTENANCE` 기록 |
| M4.7 | `recorder_health` Influx 적재 | writer | Grafana가 `severity`만으로 알림 가능 |
| M4.8 | 늦게 도착한 데이터의 현재상태 보호 | health_states 갱신 조건 | 과거 `observed_at` 데이터가 현재 상태를 되돌리지 못함 |
| M4.9 | 알림 중복 억제·복구 알림 | notifier | 동일 장애가 반복 알림되지 않고 복구 시 1회 알림 |

**Exit:** 동일한 장애가 중복 생성되지 않고, 복구가 자동 인식되며, 미지원·확인불가·정상이 서로 구분된다.

---

### M5 관리 API

| ID | 작업 | 산출물 | 완료 판정 |
|----|------|--------|-----------|
| M5.1 | 인증·세션·역할 3종 | `auth/` | 역할별 접근 제한이 API 레벨에서 강제 |
| M5.2 | 관측소 CRUD + `retired` 처리 | `api/routers/stations.py` | 물리 삭제 없이 비활성 가능 |
| M5.3 | 기록계 CRUD + Endpoint·Credential 분리 저장 | devices, device_endpoints | 응답·로그에 비밀번호 없음 |
| M5.4 | 센서·축·외부 SOH 설정 API | routers | 변환식 `value = raw × scale + offset` 적용 |
| M5.5 | `test-connection`·`probe`·`soh-preview` | routers | 화면에서 등록 전 연결·모델 확인 가능 |
| M5.6 | SSRF 방지 (대역 화이트리스트) | validation | 외부 URL·메타데이터 주소 차단 |
| M5.7 | 수집·Metric 프로파일 CRUD + 영향 관측소 수 | profiles | 프로파일 변경 전 영향 범위 표시 |
| M5.8 | 장비별 Override | device_metric_overrides | 프로파일 상속과 개별 재정의 동시 동작 |
| M5.9 | CSV 일괄 등록 (검증·부분실패 보고) | `stations/import` | 오류 행만 실패하고 나머지는 등록, Formula Injection 방지 |
| M5.10 | `fleet/summary`·`current-health` 조회 | routers | 화면 1회 호출로 통합 현황 렌더 가능 |
| M5.11 | 감사 로그 | `audit/` | 설정 변경 주체·전후 값이 기록 |
| M5.12 | OpenAPI 갱신 및 클라이언트 재생성 | contracts, generated | 프론트 타입이 API와 불일치하면 CI 실패 |

**Exit:** 프로그램 수정 없이 API만으로 관측소·기록계·프로파일을 등록·변경할 수 있다.

---

### M6 관리 Frontend 1차

| ID | 작업 | 산출물 | 완료 판정 |
|----|------|--------|-----------|
| M6.1 | 레이아웃·라우팅·권한별 메뉴 | `app/`, `routes/` | VIEWER에게 편집 버튼이 보이지 않음 |
| M6.2 | 로그인·세션 만료 처리 | `features/auth` | 만료 시 재로그인 유도, 작업 내용 손실 안내 |
| M6.3 | 통합 현황 화면 | `features/overview` | 상태 집계·현재 장애·마지막 수집 시각 표시 |
| M6.4 | 관측소 지도 | overview | 상태색 + 아이콘 병행(색약 대응) |
| M6.5 | 관측소 목록 (필터·정렬·일괄 작업) | `features/stations` | 카테고리별 상태 컬럼과 미지원 표시 구분 |
| M6.6 | 등록 마법사 전 단계 | stations/new | 10절 흐름대로 저장까지 완료 |
| M6.7 | 연결 시험 진행 표시 | 공통 컴포넌트 | 장시간 요청에서 진행 상태·취소 제공 |
| M6.8 | 자동 탐지 결과와 입력값 불일치 표시 | 마법사 | 모델·시리얼·펌웨어 차이를 사용자에게 확인받음 |
| M6.9 | Adapter Manifest Schema 기반 동적 폼 | `schemas/` | 새 Adapter 추가 시 화면 코드 수정 없이 입력폼 생성 |
| M6.10 | 관측소 상세 탭 | `stations/:id` | 카테고리별 현재값·상태·Grafana Deep Link |
| M6.11 | 프로파일 화면 (복제·영향 미리보기·이력 비교) | `features/profiles` | 변경 전후 차이 확인 가능 |
| M6.12 | 장애 목록·확인 화면 | `features/incidents` | 장애 확인 시 담당자·시각 기록 |
| M6.13 | 상태 자동 갱신 (Polling, 추후 SSE) | api layer | 갱신 중 화면 깜빡임·스크롤 이동 없음 |

**Exit:** 운영자가 화면만으로 관측소 등록 → 연결 시험 → 첫 수집 → 상태 확인까지 수행한다.

---

### M7 Edge Agent

| ID | 작업 | 산출물 | 완료 판정 |
|----|------|--------|-----------|
| M7.1 | Edge 실행 모드 분리 (`main_edge.py`) | edgeagent | 중앙 Collector와 Adapter 코드 공유 확인 |
| M7.2 | Enrollment (일회용 Token → 인증서 발급) | `edgeagent/enroll` | 등록 후 Token 폐기, 이후 mTLS로만 통신 |
| M7.3 | 설정 동기화 + 원자적 적용 + Rollback | `configsync/` | 잘못된 설정 배포 시 이전 버전으로 자동 복귀 |
| M7.4 | 로컬 Spool (SQLite WAL + gzip Segment) | `spool/` | 전원 강제 차단 후 재기동에도 손상·유실 없음 |
| M7.5 | Sequence·Batch·ACK 관리 | spool | ACK 전 삭제 없음, 재전송 가능 |
| M7.6 | Uploader (Batch·gzip·Backoff) | `uploader/` | 중앙 30분 단절 후 오래된 순서로 전송 완료 |
| M7.7 | 디스크 한도·우선순위 정리 | spool | 한도 초과 시 장애 이벤트가 마지막까지 보존 |
| M7.8 | Heartbeat + 자체 진단(CPU·메모리·디스크·시각오차) | `heartbeat/` | 중앙에서 Edge 자원 상태 조회 가능 |
| M7.9 | 중앙 단절 중 지속 수집 | runtime | 단절 상태에서도 Poll 로그가 계속 증가 |
| M7.10 | 원격 작업 처리 (연결 시험 대행) | `tasks` | 중앙 화면의 연결 시험이 Edge를 통해 수행 |
| M7.11 | Edge 배포 문서 | `docs/edge-deployment/` | 신규 지역 설치 절차가 문서만으로 수행 가능 |

**Exit:** 중앙을 완전히 내린 상태에서도 Edge가 수집을 지속하고, 중앙 복구 후 누락 구간이 원래 시각으로 채워진다.

---

### M8 중앙 Ingest·Edge 관리·장애 상관관계

| ID | 작업 | 산출물 | 완료 판정 |
|----|------|--------|-----------|
| M8.1 | Ingest API (gzip·Schema 검증·크기 제한) | `api/routers/edge_ingest.py` | 과대 Payload·비정상 Batch 거부 |
| M8.2 | 멱등 처리 (`edge_id`+`sequence`+`batch_id`) | repository | 같은 Batch 3회 전송 시 Point 수 불변 |
| M8.3 | 지연 데이터 적재 (`observed_at` 기준) | writer | 하루 늦은 데이터가 과거 시각에 채워짐 |
| M8.4 | mTLS 검증·인증서 폐기 | nginx·api | 폐기된 Edge 즉시 차단 |
| M8.5 | Edge 등록·장비 할당 API·화면 | `features/edges` | 동일 장비를 두 Edge에 할당 시 거부 |
| M8.6 | Edge 상세 화면 (Spool·버전·인증서·성공률) | edges/:id | 미전송량과 최고령 데이터 표시 |
| M8.7 | Edge 장애 시 하위 장애 억제 | health | Edge Offline 시 하위 알림 1건으로 수렴 |
| M8.8 | `UNKNOWN / EDGE UNREACHABLE` 상태 표시 | overview·stations | 기록계 장애와 Edge 장애가 화면에서 구분 |
| M8.9 | Adapter·Core 버전 호환성 검사 | edge config | 미지원 Adapter 필요 장비는 할당 차단 |
| M8.10 | 지역 토폴로지 화면 | overview | 지역 → Edge → 관측소 계층과 영향 범위 표시 |

**Exit:** Edge 하나가 죽어도 알림은 1건이며, 하위 관측소는 장애가 아니라 확인 불가로 표시된다.

---

### M9 Grafana Provisioning + 알림

| ID | 작업 | 산출물 | 완료 판정 |
|----|------|--------|-----------|
| M9.1 | Datasource·Folder Provisioning | `deploy/grafana/provisioning` | 컨테이너 재생성만으로 동일 구성 복원 |
| M9.2 | `01-fleet-overview` | dashboards | 상태 집계·Geomap·Matrix·현재 장애 |
| M9.3 | `02-station-detail` | dashboards | 관측소 변수로 전 카테고리 시계열 표시 |
| M9.4 | `03-centaur-ctr-detail` | dashboards | Vendor Metric 포함, 공통 대시보드와 분리 |
| M9.5 | `04-edge-fleet` | dashboards | Spool·업로드·버전·인증서 만료 표시 |
| M9.6 | `05-collector-operations` | dashboards | Poll 처리량·성공률·Influx Write 오류 |
| M9.7 | `06-data-quality` | dashboards | 채널별 Sample Age·Gap·가용률 |
| M9.8 | 알림 규칙 7종 | provisioning | 중복 알림 없음, 복구 알림 정상 |
| M9.9 | 관제 Kiosk 화면·자동 갱신 | dashboards | 대형 화면에서 장애 우선 정렬 |
| M9.10 | 관리 Web ↔ Grafana Deep Link | frontend | 관측소 상세에서 해당 패널로 직접 이동 |

**Exit:** 표준 Metric만으로 구성된 공통 대시보드에서 CTR 장비 전체가 보이고, 제조사 전용 정보는 별도 대시보드에만 존재한다.

---

### M10 운영 강화와 파일럿

| ID | 작업 | 산출물 | 완료 판정 |
|----|------|--------|-----------|
| M10.1 | 백업·복구 절차 (Postgres·Influx·Grafana·키) | `docs/operations/` | 빈 서버에서 복구 리허설 성공 |
| M10.2 | 보존정책·다운샘플링 검증 | Influx Task | 원본 만료 후에도 장기 추세 조회 가능 |
| M10.3 | 부하 시험 (100대·느린 장비 20%·Influx 중단) | `tests/load/` | 목표 주기 유지, 재시작 후 스케줄 자동 복구 |
| M10.4 | 보안 점검 (Secret·권한·SSRF·CSV·TLS) | 점검표 | 발견 항목 전부 조치 또는 위험 수용 기록 |
| M10.5 | E2E 자동화 (Playwright) | `tests/e2e/` | 등록→수집→장애→복구 시나리오 통과 |
| M10.6 | 장애 시나리오 리허설 12종 | 시험 결과서 | 중앙 단절·Edge 재시작·디스크 Full·중복 Batch·인증서 만료 등 확인 |
| M10.7 | 파일럿 3~5개 관측소 적용 | 운영 기록 | 실장비에서 오탐·누락 목록 확보 |
| M10.8 | 임계값 튜닝 (전압·온도·Mass Position·GNSS) | 프로파일 | 오탐이 운영 수용 수준으로 감소 |
| M10.9 | 운영 문서 (설치·등록·장애대응·FAQ) | `docs/` | 담당자 교체 시 문서만으로 인수 가능 |
| M10.10 | 전체 관측소 확대 적용 | 운영 기록 | 등록 누락 없이 전 장비 수집 |

**Exit:** MVP 완료 기준([16절](#16-mvp-완료-기준)) 전 항목 충족.

---

### M11 확장성 검증 (Gen5·타 제조사 준비)

실제 Gen5 장비가 없어도 확장 가능성은 **지금 검증**해야 한다. 나중에 확인하면 구조를 되돌리기 어렵다.

| ID | 작업 | 산출물 | 완료 판정 |
|----|------|--------|-----------|
| M11.1 | 가상 제조사 Adapter 구현 | `adapters/mock_recorder/` | 다른 필드명·다른 상태문자열·다른 단위 |
| M11.2 | Collector·Scheduler 무변경 확인 | 회귀 테스트 | Adapter 추가로 수집 코드 변경 0줄 |
| M11.3 | DB 스키마 무변경 확인 | Migration 이력 | 제조사 추가에 신규 테이블 불필요 |
| M11.4 | 공통 대시보드 재사용 확인 | Grafana | 가상 제조사 장비가 공통 화면에 그대로 표출 |
| M11.5 | Capability 기반 화면 자동 변화 | Frontend | 미지원 기능 탭·패널이 자동 숨김/미지원 표시 |
| M11.6 | SNMP 등 비HTTP Transport 시험 구현 | `adapters/transport/` | Transport 교체가 Adapter 내부로 한정 |
| M11.7 | gRPC 외부 Adapter Runner 설계 검증 | `docs/adapter-development/` | 제조사 SDK 오류가 Collector를 죽이지 않는 구조 확인 |
| M11.8 | Gen5 착수 체크리스트 | 문서 | 필요한 조사 항목·인증 방식·예상 신규 Metric 정리 |
| M11.9 | Adapter 개발 가이드 | `docs/adapter-development/` | 외부 개발자가 문서만으로 새 Adapter 추가 가능 |

**Exit:** 새 제조사 추가 범위가 `Adapter + Manifest + Mapping + (선택) 전용 대시보드`로 한정됨이 실측으로 증명된다.

---

## 16. MVP 완료 기준

1. `make up` 수준의 단일 명령으로 중앙 스택이 기동된다.
2. 별도 Compose로 지역 Edge가 기동되고, 중앙에 자동 등록된다.
3. 화면에서 관측소와 CTR 기록계를 등록하고 DIRECT/EDGE를 선택할 수 있다.
4. 설정한 분 주기로 SOH가 수집되고, 한 장비 장애가 전체 수집을 막지 않는다.
5. 중앙이 끊겨도 Edge 수집이 지속되고, 복구 후 누락분이 원래 시각으로 채워진다.
6. InfluxDB에 제조사 중립 표준 Metric으로 적재된다.
7. Grafana에서 전체·관측소·Edge·데이터품질을 확인할 수 있다.
8. 기록계 장애와 Edge 장애가 구분되고, Edge 장애 시 알림이 폭주하지 않는다.
9. `UNSUPPORTED`·`UNKNOWN`·`OK`가 화면에서 구분된다.
10. 센서 상태와 별개로 실제 데이터 공백이 검출된다.
11. 새 Adapter 추가에 DB·공통 화면·공통 대시보드 재설계가 필요 없다.
12. Secret이 화면·로그·이미지·Git에 남지 않는다.

---

## 17. 릴리스와 추적

이미지 태그: `soh-{api,collector,edge,web}:<git-sha>`, 정식 릴리스는 `:1.0.0`. 중앙은 Edge의 Core·Adapter 버전 호환성을 검사하고, 비호환 Edge에는 장비 할당을 막는다.

CI 게이트:

```
Format → Lint → Unit → contracts Schema 검증 → OpenAPI/Type 동기 검사
→ Docker Build → Integration(compose.test) → Frontend Build → E2E → 취약점 Scan
```

작업 추적은 마일스톤 ID를 그대로 이슈 라벨로 사용한다(`M2.4` 형식). 마일스톤은 Exit 조건이 충족되기 전에는 닫지 않는다.

---

## 18. 위험과 완화

| 위험 | 영향 | 완화 |
|------|------|------|
| Mass Position의 SOH API 경로가 모델별로 다름 | 센서 감시 누락 | M-1.3에서 실응답으로 확정, Mapping 테이블로 흡수 |
| 펌웨어별 필드·상태문자열 차이 | 파싱 실패·오탐 | Mapping 버전 + 미지의 값은 `UNKNOWN` 처리, Fixture 회귀 |
| 센서 상태가 미연결·파형정지를 못 잡음 | 장애 미검출 | SeedLink/FDSN 기반 `acquisition.*` 병행 |
| Edge 자동 절체 시 이중 수집 | 데이터 중복·경합 | MVP는 수동 절체, 활성 할당 Unique 제약 |
| 중앙 장기 단절 후 대량 Backfill | Ingest·Influx 부하 | Batch 크기 제한·Backoff·우선순위 정리, 부하 시험(M10.3) |
| 늦게 도착한 과거 데이터 | 현재 상태 오표시 | `observed_at` 최신성 검사(M4.8) |
| 임계값 오탐으로 알림 신뢰도 하락 | 운영자가 알림 무시 | 지속시간·Hysteresis, 파일럿 튜닝(M10.8) |
| 기록계 인증정보 유출 | 장비 침해 | Credential 참조 저장·암호화, 로그·응답 Redact, VPN 내부 접근 |
| CTR 원본 필드가 Grafana로 새어나감 | Gen5 확장 시 대시보드 전면 수정 | 명명 Lint(M1.5), 확장성 회귀 검증(M11.4) |

---

## 19. 근거 (Centaur 사용자 가이드)

- SOH API: `GET /api/v1/instruments/soh`, JSON 반환, `instrumentId` 미지정 시 자기 자신의 SOH 보고, `pretty` 파라미터 지원.
- SOH 채널 목록(7.4절): `instrumentStatus`, `config/commitState`, `controller/store/storePercentageUsed`, `controller/store/storeRecordingStatus`, `dataArchive/status`, `dataArchive/status/events`, `digitizer/sensor/status#_0`·`#_1`, `externalSoh/voltage#_1`~`#_3`(µV), `gps/numberOfSatellites`, `instrument/earthLocation`, `instrument/systemInfo/firmwareStatus`, `media/status/removableSD`, `media/freeSpace/removableSD`(미장착 시 −1), `powerSupply/voltage`(V), `sensor/controlLines/state#_0`·`#_1`, `system/current`(A), `systemSoftwareVersion`, `temperature`(°C), `timeStatus`, `timing/lastLockTime`, `timing/phaseLock`, `timing/timeError`(ns), `timing/timeQuality`(%), `timing/timeUncertainty`(ns).
- SOH 그룹: Environment SOH(전압·전류·온도·센서·외부 SOH·시각), Timing SOH(위치·GNSS 상태·위성 수·시각 상태·PLL·불확도), System SOH(내부 저장소·수집 통계).
- Steim 압축 SOH 코드(8.2절): `VEI`(입력전압 mV), `VEC`(시스템 전류 mA), `VDT`(온도 m°C), `VM1`~`VM6`(센서 SOH, 통상 Mass Position, µV), `EX1`~`EX3`(외부 SOH µV), `GST`/`GAN`/`GNS`/`GPL`(GNSS 상태·안테나·위성수·PLL), `LCQ`/`LCE`(시각 품질·위상오차), `VPB`(버퍼 사용률).
- 센서 상태 제약: Sensor LED와 Health 상태는 Mass Position 범위 초과만 검출하며, 센서 미연결 등 다른 고장은 검출하지 않는다(펌웨어 릴리스 노트 알려진 제약).
- 외부 SOH 입력: 3채널 단일단 입력 ±5V, 샘플 간격 1~3600초, CTR2 이상 모델.
- 인증 API: `GET /key` → `POST /login` → 인증 필요 엔드포인트 → `POST /logout` (Calibration 등 인증 필요 API 사용 시).

출처: Centaur User Guide 17935R10(7.0 APIs, 7.4 State of Health API, 8.2 SOH channels in Steim compressed formats), Centaur 데이터시트, Centaur Firmware Release Notes 3.2.8.
