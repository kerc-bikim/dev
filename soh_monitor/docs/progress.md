# 구현 진행 상황

마일스톤 정의는 [`plan.md`](../plan.md) 15절에 있다. 이 문서는 각 작업의 실제 상태만 기록한다.

| 마일스톤 | 상태 | 비고 |
|----------|------|------|
| M-1 장비·환경 조사 | 대기 | 양식만 준비됨 ([`inventory.md`](inventory.md)). 실장비 접근이 필요하다 |
| M0 저장소 골격·개발환경 | 완료 | Docker 빌드는 이 환경에 Docker 가 없어 미검증 |
| M1 계약 확정 | 완료 | 카탈로그·상태 Mapping·Capability·Adapter/Edge Schema·DB 스키마 |
| M2 Centaur CTR Adapter | 완료(실장비 미검증) | 가상 서버 + Adapter. 응답 형태는 실응답으로 확정해야 한다 |
| M3 Direct Collector | 착수 전 | Adapter 가 준비됐으므로 실장비 없이 진행 가능 |
| M4 상태 판정 엔진 | 착수 전 | |
| M5 관리 API | 착수 전 | 계약 조회 API 만 존재 |
| M6 관리 Frontend | 착수 전 | 화면 골격과 표준 Metric 화면만 존재 |
| M7 Edge Agent | 착수 전 | 실행점과 Schema 만 존재 |
| M8 Edge 통합 | 착수 전 | |
| M9 Grafana | 부분 | Datasource·Dashboard Provisioning 골격만 |
| M10 운영 강화 | 착수 전 | |
| M11 확장성 검증 | 착수 전 | 명명 Lint 는 이미 동작 |

---

## M0 저장소 골격과 개발환경

| ID | 작업 | 상태 | 결과 |
|----|------|------|------|
| M0.1 | 디렉터리 골격 | 완료 | `backend/` `frontend/` `contracts/` `deploy/` `scripts/` `docs/` |
| M0.2 | 실행점 3개 | 완료 | `app.main_api` `app.main_collector` `app.main_edge` + `app.main_migrate` |
| M0.3 | 의존성 고정 | 완료 | `backend/requirements.txt` 전 항목 버전 Pin |
| M0.4 | Frontend 골격 | 완료 | Vite + React 18 + TS + Router + TanStack Query |
| M0.5 | Backend 이미지 | 완료(미검증) | `Dockerfile.backend` 3 Target |
| M0.6 | Web·Edge 이미지 | 완료(미검증) | Web 은 Nginx 정적, Edge 는 API 코드 제외 |
| M0.7 | 개발 Compose | 완료(미검증) | `compose.dev.yml` |
| M0.8 | Makefile | 완료 | `make verify` 로 전체 검증 |
| M0.9 | 설정·Secret 분리 | 완료 | `deploy/examples/*.env.example`, Compose Secret 파일 참조 |
| M0.10 | 구조화 로깅 | 완료 | JSON 로거, 문맥 필드 주입 |

Docker 관련 항목은 이 개발 환경에 Docker 가 없어 빌드를 실행하지 못했다. 구성 파일만 작성된 상태이며,
Docker 가 있는 환경에서 `make images` 와 `make dev` 로 확인해야 한다.

---

## M1 계약 확정

| ID | 작업 | 상태 | 결과 |
|----|------|------|------|
| M1.1 | 표준 Metric 카탈로그 | 완료 | `contracts/metrics/catalog.yaml`, 44개 Metric / 13개 분류 |
| M1.2 | 상태 Mapping | 완료 | `status-mappings.yaml`, CTR 텍스트 12종 + 수치코드 3종 |
| M1.3 | 상수·타입 생성기 | 완료 | `scripts/gen_metrics.py`, `--check` 로 CI 게이트 |
| M1.4 | DB 초기 스키마 | 완료 | Alembic `0001_initial_schema`, 30개 테이블 |
| M1.5 | 명명 검사 | 완료 | `scripts/check_naming.py` |
| M1.6 | Adapter 계약 | 완료 | `adapters/contract.py`, 6개 추상 메서드 |
| M1.7 | Manifest Schema | 완료 | `contracts/adapter/manifest.schema.json` |
| M1.8 | Capability 정의 | 완료 | `capabilities.yaml`, 20개 기능 / 5개 지원 상태 |
| M1.9 | Edge Schema | 완료 | `contracts/edge/config.schema.json`, `ingest.schema.json` |
| M1.10 | InfluxDB 초기화 | 완료(미검증) | `deploy/influxdb/init/10-buckets.sh` |
| M1.11 | OpenAPI·클라이언트 | 부분 | FastAPI 자동 생성 스키마 사용. 파일 추출과 TS 클라이언트 생성은 M5 에서 |

### 계약에서 못 박은 규칙

이후 구현이 이 규칙을 어기면 테스트가 실패한다.

1. 모르는 상태 문자열은 `OK` 가 아니라 `UNKNOWN` 으로 떨어지고 원문이 남는다.
2. 값이 없는 Metric 은 `UNSUPPORTED` / `UNKNOWN` / `ERROR` 중 하나로 표시된다. 0 으로 채우지 않는다.
3. `UNSUPPORTED` 와 `MAINTENANCE` 는 상태 집계에서 제외되고, `UNKNOWN` 은 `OK` 보다 나쁘게 집계된다.
4. 표준 Metric 키에 제조사 이름을 넣을 수 없다. `vendor.*` 만 예외다.
5. 공통 계층의 테이블·Measurement·API 경로에 제조사 이름을 넣을 수 없다.
6. 카탈로그에 없는 Metric 이나 정의되지 않은 capability 를 선언한 Adapter 는 등록에 실패한다.
7. `secretFields` 가 실제 설정 필드와 어긋난 Adapter 는 등록에 실패한다.
8. `EDGE` 수집 장비는 Edge 지정이 없으면 DB 가 거부한다.
9. 활성 Edge 할당은 장비당 하나만 존재할 수 있다.
10. 접속정보 테이블에는 평문 비밀번호 컬럼이 아예 없다.

---

## M2 Centaur CTR Adapter

| ID | 작업 | 상태 | 결과 |
|----|------|------|------|
| M2.1 | 가상 Centaur CTR 서버 | 완료 | `mock/centaur_mock/`. 본문 시나리오 15종 + 통신 시나리오 12종, 제어 API |
| M2.2 | HTTP Client 와 실패 분류 | 완료 | DNS·연결거부·연결/응답 Timeout·HTTP·인증·본문 오류를 서로 다른 코드로 |
| M2.3 | SOH Parser | 완료 | 응답 형태 3종(channels 배열 / soh 객체 / 평평한 객체) 관용 처리 |
| M2.4 | 표준 Metric Mapper | 완료 | 단위 인식 변환(µV·mV·m°C), SD 미장착 −1 → 값 없음, 축 W/V/U 매핑 |
| M2.5 | 펌웨어별 Mapping | 부분 | 수치 코드(예전 형태) 처리. `adapter_metric_mappings` 표 활용은 실응답 확보 후 |
| M2.6 | Capability 자동 탐지 | 완료 | 3채널 Sensor B → UNSUPPORTED, 슬롯 없음/카드 없음 구분 |
| M2.7 | Probe | 완료 | Instrument ID 로 채널 수·시리얼 추정. 모델명은 SOH API 에 없어 비워 둔다 |
| M2.8 | 민감정보 제거 | 완료 | `redact()` 재귀 처리. 수집 결과에 비밀값 없음을 시험으로 확인 |
| M2.9 | Manifest 등록 | 완료 | 파일 원본으로 검증해 Registry 에 등록. 화면 선택 목록에 노출 |
| M2.10 | Fixture 회귀 시험 | 완료 | synthetic 10종. `real-` 파일이 들어오면 기준선 대조 시험이 켜진다 |
| M2.11 | 데이터 연속성 Adapter | 착수 전 | 가상 서버에 availability 응답만 준비 |

### 응답 형식이 아직 추측인 부분

매뉴얼 17935R10 7.4절은 URI·파라미터·SOH 채널 이름까지만 명시하고 **응답 본문 예시가 없다.**
그래서 다음 두 가지가 추측이며, 각각 한 곳에 갇혀 있다.

| 항목 | 갇혀 있는 위치 | 확정 방법 |
|------|----------------|-----------|
| JSON 응답 봉투 형태 | `mock/centaur_mock/envelope.py` | M-1.2 실응답 |
| Mass Position 채널 이름 | 같은 파일의 `UNITS` 주석 + `mapper.py` | M-1.3 실응답 |

파서가 세 형태를 모두 읽으므로 실제 형태가 그 중 하나면 수정이 필요 없고, 변형이면
`envelope.py` 와 `parser.py` 만 고친다.

---

## 검증 방법

```bash
make contracts-check   # 카탈로그와 생성물 일치
make naming-check      # 제조사 중립 명명
make test              # 백엔드 테스트
make typecheck         # 프론트 타입
make build-web         # 프론트 빌드
make verify            # 위 전부

make mock              # 가상 Centaur CTR 서버 (http://127.0.0.1:8090)
make fixtures          # 가상 응답 Fixture 재생성
```

현재 결과: 백엔드 테스트 267개 통과(1개 skip — 실장비 Fixture 대조 시험), 프론트 타입 검사·빌드 통과.

---

## 다음 착수 지점

1. **M3 Direct Collector** — 스케줄러·재시도·Lease·InfluxDB 적재. Adapter 와 가상 서버가
   준비됐으므로 실장비 없이 진행할 수 있다.
2. **M-1.2 / M-1.3** — 실장비 SOH 응답 확보. 확보되면 `envelope.py`·`parser.py` 를 실제
   형태로 맞추고 기준선 대조 시험을 켠다.
3. **M2.11** — SeedLink/FDSN 기반 데이터 연속성 검사. 센서 상태만으로는 파형 정지를 잡지 못한다.
