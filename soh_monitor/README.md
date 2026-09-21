# soh_monitor — 관측소 SOH 통합 모니터링

Nanometrics **Centaur CTR** 계열 기록계의 SOH를 설정한 분 주기로 수집해 InfluxDB에 적재하고, Grafana로 관측소를 통합 감시하는 시스템이다. Centaur Gen5와 타 제조사 기록계는 Adapter 추가만으로 편입한다.

진행 상태: **M0–M11 완료.** 실장비 파일럿(M10.7·M10.10)과 Docker 라이브 검증은 조사표·실행 환경이 필요하다. 작업별 상태는 [`docs/progress.md`](docs/progress.md) 에 있다.

## 문서

| 파일 | 내용 |
|------|------|
| [`plan.md`](plan.md) | 확정 계획서. 아키텍처 · 표준 Metric · 데이터 모델 · Edge 설계 · 화면 · 세부 작업 마일스톤 |
| `plan.html` | `plan.md` 를 브라우저용으로 변환한 문서 |
| [`docs/progress.md`](docs/progress.md) | 마일스톤별 실제 진행 상태와 계약에서 못 박은 규칙 |
| [`docs/inventory.md`](docs/inventory.md) | M-1 장비·환경 조사표 양식 |
| [`docs/adapter-development.md`](docs/adapter-development.md) | 새 기록계 Adapter 를 붙이는 절차와 지켜야 할 규칙 |
| [`docs/gen5-checklist.md`](docs/gen5-checklist.md) | Centaur Gen5 착수 전 조사 항목 |
| [`docs/edge-deployment/README.md`](docs/edge-deployment/README.md) | 지역 Edge Collector 설치·등록·확인 절차 |
| [`docs/grafana.md`](docs/grafana.md) | Grafana 대시보드·알림·Deep Link |
| [`docs/operations/`](docs/operations/) | 설치·등록·백업·장애대응·보안·FAQ |

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
├─ mock/centaur_mock/    시험용 가상 Centaur CTR 서버 (런타임 이미지에 넣지 않는다)
├─ deploy/               Dockerfile · Compose · Grafana · InfluxDB · nginx
├─ scripts/              계약 생성기 · 명명 검사 · Fixture 생성 · 문서 변환
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

## 실장비 없이 시험하기

가상 Centaur CTR 서버가 있다. 본문 이상 15종과 통신 오작동 12종을 스위치로 걸 수 있다.

```bash
make mock                                    # http://127.0.0.1:8090
curl -s http://127.0.0.1:8090/_mock/devices  # 가상 장비 목록과 현재 시나리오
make mock-load                               # 부하 시험용 100대 (20% 느린 장비)
```

수집기 부하·안정성 시험도 실장비 없이 돌린다.

```bash
make soak                      # 50대. 느린 장비·실패 장비·적재 중단·복구 구간 포함
make soak devices=100 ticks=3
```

시나리오 전환과 값 고정 방법은 [`docs/adapter-development.md`](docs/adapter-development.md) 에 있다.
가상 서버는 계약이 아니다. 응답 형식의 권위는 `backend/app/adapters/centaur_ctr/testdata/real-*.json`
이며, 실장비 Fixture 가 들어오면 가상 서버 기준선과 대조하는 시험이 켜진다.

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

## 운영

```bash
make backup OUT=/var/backups/soh
make restore ARCHIVE=/var/backups/soh/soh-backup-....tar.gz
make secrets-check
```

절차는 [`docs/operations/install.md`](docs/operations/install.md) 와
[`docs/operations/backup-restore.md`](docs/operations/backup-restore.md).

## 검증

```bash
make verify
```

- `contracts-check` : 카탈로그와 생성된 백엔드 상수·프론트 타입이 일치하는지
- `naming-check` : 공통 계층에 제조사 이름이 새어 들어왔는지
- `secrets-check` : Git 에 비밀이 남았는지
- `test` : 백엔드 테스트 (단위·통합·부하 축소·E2E API)
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
