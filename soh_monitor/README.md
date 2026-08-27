# soh_monitor — 관측소 SOH 통합 모니터링

Nanometrics **Centaur CTR** 계열 기록계의 SOH를 설정한 분 주기로 수집해 InfluxDB에 적재하고, Grafana로 관측소를 통합 감시하는 시스템이다. Centaur Gen5와 타 제조사 기록계는 Adapter 추가만으로 편입한다.

진행 상태: **M0(저장소 골격) · M1(계약 확정) 완료.** 수집기·관리 화면은 아직 골격만 있다. 작업별 상태는 [`docs/progress.md`](docs/progress.md) 에 있다.

## 문서

| 파일 | 내용 |
|------|------|
| [`plan.md`](plan.md) | 확정 계획서. 아키텍처 · 표준 Metric · 데이터 모델 · Edge 설계 · 화면 · 세부 작업 마일스톤 |
| `plan.html` | `plan.md` 를 브라우저용으로 변환한 문서 |
| [`docs/progress.md`](docs/progress.md) | 마일스톤별 실제 진행 상태와 계약에서 못 박은 규칙 |
| [`docs/inventory.md`](docs/inventory.md) | M-1 장비·환경 조사표 양식 (M2 착수 조건) |

## 구조

```
soh_monitor/
├─ contracts/            모든 계약의 단일 원본
│  ├─ metrics/           표준 Metric 카탈로그 · 상태 Mapping · Capability
│  ├─ adapter/           Adapter Manifest Schema
│  └─ edge/              Edge 설정 · Ingest Schema
├─ backend/app/
│  ├─ main_api.py        관리 API
│  ├─ main_collector.py  중앙 직접 수집 (DIRECT)
│  ├─ main_edge.py       지역 Edge Collector (EDGE)
│  ├─ main_migrate.py    마이그레이션과 초기 데이터
│  ├─ adapters/          기록계 Adapter 계약과 구현체
│  ├─ domain/            표준 상태 · 수집 결과 모델
│  ├─ metrics/           카탈로그 로더 · 상태 변환
│  └─ db/                스키마 · Seed
├─ frontend/             관리 Web (React + Vite + TS)
├─ deploy/               Dockerfile · Compose · Grafana · InfluxDB · nginx
├─ scripts/              계약 생성기 · 명명 검사 · 문서 변환
└─ docs/
```

## 설계의 핵심 경계

```
제조사 원본 SOH → Recorder Adapter → 표준 Metric → 상태 판정 → InfluxDB / Grafana
```

수집 스케줄러, 상태 판정 엔진, DB 스키마, Grafana 대시보드는 제조사 원본 필드명을 알지 못한다.
`scripts/check_naming.py` 가 이 경계를 기계적으로 강제한다. 그래서 Gen5·타 제조사 추가 범위가
Adapter 와 일부 상세 패널로 한정된다.

수집 경로는 두 가지이며 같은 Adapter와 같은 표준 Metric을 쓴다.

```
DIRECT : collector  ─────────────► 기록계
EDGE   : edge-agent ─► 기록계 ─► 로컬 Spool ─► 중앙 Ingest
```

## 로컬 개발

Docker 없이 백엔드·프론트를 직접 띄울 수 있다. 이때 설정 DB 는 SQLite 로 대체된다.
운영 DB 는 PostgreSQL 이다.

```bash
cd soh_monitor
make install        # 백엔드 venv + 프론트 의존성
make migrate        # 스키마 생성 + 카탈로그·기본 프로파일·초기 관리자
make api            # http://127.0.0.1:8000
make web            # http://127.0.0.1:5173
```

`make migrate` 는 초기 관리자 비밀번호를 한 번 출력한다. `SOH_BOOTSTRAP_ADMIN_PASSWORD` 를
주면 그 값을 쓴다.

## Docker 실행

```bash
make dev            # 개발 스택 (postgres · influxdb · grafana · api · collector · web)
make dev-mock       # + 가상 기록계
make images         # 배포 이미지 5종 빌드

cp deploy/examples/central.env.example central.env && make central-up   # 중앙
cp deploy/examples/edge.env.example edge.env && make edge-up            # 지역 Edge
```

중앙은 443 하나만 외부에 열고 PostgreSQL·InfluxDB 포트는 공개하지 않는다. Edge 는 중앙으로
Outbound 연결만 사용하며 들어오는 포트를 열지 않는다.

## 검증

```bash
make verify
```

- `contracts-check` : 카탈로그와 생성된 백엔드 상수·프론트 타입이 일치하는지
- `naming-check` : 공통 계층에 제조사 이름이 새어 들어왔는지
- `test` : 백엔드 테스트
- `typecheck` / `build-web` : 프론트 타입 검사와 빌드

## 계약을 고치는 순서

Metric 을 추가하거나 이름을 바꿀 때는 반드시 이 순서를 따른다.

1. `contracts/metrics/catalog.yaml` 수정
2. `make contracts` — 백엔드 상수와 프론트 타입 재생성
3. `make migrate` — `metric_definitions` 재동기화
4. `make verify` — 전체 검증
5. 생성물까지 함께 커밋

## 계획 문서 갱신

```bash
make plan-html
```
