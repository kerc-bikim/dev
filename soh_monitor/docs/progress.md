# 구현 진행 상황

마일스톤 정의는 [`plan.md`](../plan.md) 15절에 있다. 이 문서는 각 작업의 실제 상태만 기록한다.

| 마일스톤 | 상태 | 비고 |
|----------|------|------|
| M-1 장비·환경 조사 | 대기 | 양식만 준비됨 ([`inventory.md`](inventory.md)). 실장비 접근이 필요하다 |
| M0 저장소 골격·개발환경 | 완료 | Docker 빌드는 이 환경에 Docker 가 없어 미검증 |
| M1 계약 확정 | 완료 | 카탈로그·상태 Mapping·Capability·Adapter/Edge Schema·DB 스키마 |
| M2 Centaur CTR Adapter | 완료(실장비 미검증) | 가상 서버 + Adapter. 응답 형태는 실응답으로 확정해야 한다 |
| M3 Direct Collector | 완료(InfluxDB 미검증) | 스케줄러·Lease·재시도·적재. 실제 InfluxDB 연결은 Docker 환경에서 확인 필요 |
| M4 상태 판정 엔진 | 완료 | 임계값·Hysteresis·Incident 생명주기·유지보수 억제 |
| M5 관리 API | 완료 | 인증·CRUD·연결 시험·CSV·감사. Edge 등록 API 는 M7 |
| M6 관리 Frontend | 완료 | 로그인·현황·지도·등록 마법사·프로파일·장애. Edge 화면은 M8 에서 연결 |
| M7 Edge Agent | 완료 | Enrollment·Spool·단절 중 수집·원격 연결 시험. 운영 mTLS 는 M8 |
| M8 Edge 통합 | 완료 | Ingest 멱등·지연 도달·mTLS 폐기·Edge 화면·장애 상관 |
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
| M1.11 | OpenAPI·클라이언트 | 완료 | `contracts/openapi.json`, `frontend/src/generated/api-paths.ts`. `--check` 로 경로 불일치 실패 |

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

## M3 Direct Collector

| ID | 작업 | 상태 | 결과 |
|----|------|------|------|
| M3.1 | 스케줄러 | 완료 | `next_poll_at` 기준 대상 선택. 한 번도 수집하지 않은 장비 포함 |
| M3.2 | 중복 실행 방지 | 완료 | DB 행 Lease. 만료 시각이 지나면 자동 해제되고 소유자를 화면에서 볼 수 있다 |
| M3.3 | Jitter 분산 | 완료 | 주기 ±설정% 범위로 흩뜨린다 |
| M3.4 | 동시성 제한·중복 호출 차단 | 완료 | Semaphore + 진행 중 장비 표시. 느린 장비가 전체를 붙잡지 않는다 |
| M3.5 | 재시도·실패 분류 | 완료 | 회선 오류만 재시도. 인증·신원·본문 오류는 즉시 포기 |
| M3.6 | 연속 실패와 Offline 판정 | 완료 | 2회 WARNING, 3회 CRITICAL. 1회 실패로는 상태를 내리지 않는다 |
| M3.7 | InfluxDB 적재 | 완료(미검증) | Point 구성은 순수 함수로 분리해 시험. 실제 InfluxDB 연결은 미검증 |
| M3.8 | 적재 실패 버퍼링 | 완료 | 한도 있는 버퍼. 넘치면 오래된 것부터 버리고 버린 사실을 남긴다 |
| M3.9 | `poll_runs` 이력 | 완료 | 실패도 남긴다. 미지의 상태 문자열과 채널까지 함께 기록 |
| M3.10 | 지연 도달 데이터 보호 | 완료 | `observed_at` 이 기존보다 최신일 때만 상태를 갱신한다 |
| M3.11 | 수동 수집 | 완료 | `POST /devices/{id}/poll-now`. API 가 장비를 직접 부르지 않는다 |

### 설계 판단

- **Lease 를 Advisory Lock 이 아니라 DB 행으로 뒀다.** 어느 인스턴스가 언제까지 잡았는지
  화면에서 볼 수 있고, 프로세스가 급사해도 만료로 자동 해제되며, SQLite 로도 같은 논리를
  시험할 수 있다. 이 규모(수백 대·분 주기)에서 행 Lease 비용은 문제되지 않는다.
- **수동 수집은 `next_poll_at` 을 당기는 방식이다.** API 프로세스가 관측소망으로 직접
  나가지 않고, 같은 장비를 API 와 수집기가 동시에 부르는 상황도 만들지 않는다.
- **값이 없는 샘플은 InfluxDB 에 적재하지 않는다.** 없는 데이터를 0 으로 채우면 그래프가
  거짓말을 한다. 이유는 `device_capabilities` 가 답한다.
- **Bulk UPDATE 는 ORM 평가를 끈다.** SQLite 처럼 시간대를 잃는 DB 에서 naive/aware 비교로
  터진다. 판정은 DB 가 하고, 세션의 낡은 객체는 명시적으로 만료시킨다.

---

## M4 상태 판정 엔진

| ID | 작업 | 상태 | 결과 |
|----|------|------|------|
| M4.1 | 임계값 평가기 | 완료 | 프로파일 + 장비 Override(차원별 포함). 조건은 JSON 구조로 저장·검증 |
| M4.2 | 지속시간·연속횟수·Hysteresis | 완료 | 악화는 지속시간+연속횟수, 회복은 회복 지속시간을 요구 |
| M4.3 | 분류별 상태 집계 | 완료 | Metric 행과 분류 집계 행을 함께 저장. 장비 종합은 분류들의 최악값 |
| M4.4 | 미지원·확인불가 제외 | 완료 | UNSUPPORTED 는 판정 제외, UNKNOWN 은 OK 보다 나쁘게 집계 |
| M4.5 | Incident 상태기계 | 완료 | OPEN → ACKNOWLEDGED → RESOLVED. 열린 장애 유일성은 DB 부분 인덱스로 보장 |
| M4.6 | 유지보수 억제 | 완료 | 장비·관측소·Edge·지역·전체 범위. 상태는 MAINTENANCE 로 기록 |
| M4.7 | `recorder_health` 적재 | 완료 | 분류별 + overall severity·is_stale. Grafana 는 이 값만 감시한다 |
| M4.8 | 지연 도달 데이터 보호 | 완료 | M3 의 `observed_at` 최신성 검사 + 낡은 값 표시 |
| M4.9 | 알림 중복 억제 | 완료 | 알림은 Incident 상태 전이에서만 나온다. 구조적으로 중복이 없다 |

### 설계 판단

- **첫 판정은 정상일 때만 즉시 확정한다.** 회복 지연은 확정된 상태 사이의 진동을 막는
  장치이고 첫 관측에는 되돌아갈 이전 상태가 없다. 이것을 미루면 새로 등록한 관측소가
  첫 회복 구간 동안 계속 '확인 불가' 로 보인다. 반대로 첫 판정이 나쁜 값이면 지속시간을
  그대로 요구한다. 설치 중 흔들리는 값 한 샘플로 장애를 만들지 않기 위한 것이다.
- **통신 판정에는 지연을 두지 않는다.** 악화는 이미 '연속 실패 N회' 로 걸러지고, 회복은
  응답이 왔다는 사실 자체가 근거다. 회복 지연을 더하면 수집기가 보고하는 상태와 판정
  결과가 서로 다른 값을 말하게 된다.
- **통신이 끊긴 동안에는 값 기반 판정을 하지 않는다.** 응답이 없는데 '전압 정상' 이라고
  표시하면 안 되고, 이전 값으로 새 장애를 만들어도 안 된다.
- **알림 중복 억제 로직을 따로 두지 않았다.** 알림을 Incident 전이에서만 내보내면
  중복이 생길 자리가 없다. 억제 로직은 그 자체로 또 다른 버그의 자리가 된다.
- **낡은 값 판정 기준이 두 갈래다.** 수집이 성공했으면 관측 시각의 나이를, 실패했으면
  마지막 성공의 나이를 본다. 수집이 멈춘 동안에는 실패 기록조차 남지 않는다.
- **조건은 표현식 문자열이 아니라 구조로 저장한다.** 문자열을 평가하면 설정 화면이 코드
  실행 경로가 되고, 잘못 입력한 조건이 조용히 '항상 정상' 이 된다.
- **차원 표기는 카탈로그가 선언한 순서를 따른다.** `sensor_port, axis` 로 선언했으면
  `A/U` 다. 순서가 흔들리면 운영자가 쓴 Override 가 조용히 적용되지 않는다.

### 실증 (50대, 6 Tick)

| Tick | 상황 | 새 장애 | 복구 |
|------|------|--------:|-----:|
| 1 | 첫 수집 (저장소·시각·센서 이상 포함) | 21 | 0 |
| 2 | 통신 실패 2회 도달 | 5 | 0 |
| 3 | 적재 중단 구간 | 0 | 0 |
| 4 | 이상 지속 | 0 | 0 |
| 5 | 전 장비 정상화 | 0 | 26 |
| 6 | 정상 유지 | 0 | 0 |

300회 수집 동안 장애는 26건만 생성됐고(대상별 1건), 중복 장애 0건, 알림 57건
(열림 26 + 승격 5 + 복구 26)이다. 같은 원인으로 장애나 알림이 반복되지 않는다.

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
make soak              # 수집기 부하·안정성 시험 (50대, 장애 생성·복구 구간 포함)
make soak devices=100 ticks=3
```

현재 결과: 백엔드 테스트 438개 통과(1개 skip — 실장비 Fixture 대조 시험). Frontend `npm run typecheck` 와 `npm run build` 통과.

부하 시험(50대, 느린 장비 5대 800ms, 실패 장비 5대, 동시 20):

| 항목 | 결과 |
|------|------|
| Tick 소요 | 평균 1.06s (초당 약 47대) |
| 느린 장비 영향 | 없음. 800ms 장비가 있어도 Tick 은 1초 대 |
| 실패 격리 | 45대 성공 / 5대 실패. 실패가 다른 장비에 번지지 않음 |
| 중복 수집 | 0건 |
| 남은 Lease | 0건 |
| 적재 중단 구간 | Tick 3 에서 끊고 Tick 4 에서 버퍼까지 복구. 유실 0 |

100대·동시 30 에서는 Tick 평균 1.31s(초당 약 76대). 실제 병목은 장비 응답 지연이며
동시 실행 수로 조절된다.

---

---

## M5 관리 API

| ID | 작업 | 상태 | 결과 |
|----|------|------|------|
| M5.1 | 인증·세션·역할 3종 | 완료 | 서명 쿠키 세션. ADMIN/OPERATOR/VIEWER. 초기 비밀번호 변경 강제 |
| M5.2 | 관측소 CRUD + retired | 완료 | 물리 삭제 없음. `/retire` 가 하위 장비도 비활성 |
| M5.3 | 기록계 CRUD + Credential 분리 | 완료 | `credentialReference`(env:/file:) 만 저장. 평문 비밀번호 거절 |
| M5.4 | 센서·축·외부 SOH | 완료 | 축 기본 U/V/W. 외부 SOH 는 `value = raw × scale + offset` |
| M5.5 | test-connection·probe·soh-preview | 완료 | 등록 전/후 모두. 미리보기는 Adapter `redact()` |
| M5.6 | SSRF 화이트리스트 | 완료 | RFC1918 기본. 메타데이터·링크 로컬은 허용 목록에 넣어도 거부 |
| M5.7 | 수집·Metric 프로파일 | 완료 | 영향 장비 수(`affectedDeviceCount`)를 응답에 포함 |
| M5.8 | 장비 Override | 완료 | 카탈로그·조건 검증 후 저장. 차원값 포함 |
| M5.9 | CSV 일괄 등록 | 완료 | 오류 행만 실패. 수식 주입(`=`, `+`, `@`) 거부 |
| M5.10 | fleet/summary·current-health | 완료(M4) | 인증을 붙였다 |
| M5.11 | 감사 로그 | 완료 | 설정 변경 주체·전후 값. 비밀값은 `***` |
| M5.12 | OpenAPI·클라이언트 | 완료 | `scripts/export_openapi.py --check` |

### 설계 판단

- **세션 저장소를 두지 않았다.** HMAC 서명 쿠키면 API 프로세스를 여러 대 띄워도
  공유 상태가 필요 없다. 토큰에 비밀번호를 넣지 않는다.
- **연결 시험만 API 가 관측소망으로 나간다.** `poll-now` 는 여전히 collector 가
  담당한다. 나가는 경로를 등록 화면의 읽기 동작으로 한정한다.
- **호스트명 해석 결과가 하나라도 허용 대역 밖이면 거부한다.** 사설 이름 뒤에
  공인 IP 가 붙어 있는 DNS 재바인딩을 막기 위한 것이다. 해석 실패도 거부한다.
- **역할은 API 에서 강제한다.** VIEWER 는 조회, OPERATOR 는 연결 시험·장애 확인·
  유지보수, ADMIN 은 설정 전체. 화면에서 버튼을 숨기는 것만으로는 부족하다.

### 권한

| | VIEWER | OPERATOR | ADMIN |
|--|:------:|:--------:|:-----:|
| 조회 (관측소·상태·프로파일) | ○ | ○ | ○ |
| 연결 시험·Probe·미리보기·수동 수집 | | ○ | ○ |
| 장애 확인·유지보수 시간 | | ○ | ○ |
| 관측소·장비·프로파일·CSV | | | ○ |
| 사용자·감사 로그 | | | ○ |

---

## M6 관리 Frontend

| ID | 작업 | 상태 | 결과 |
|----|------|------|------|
| M6.1 | 레이아웃·권한별 메뉴 | 완료 | VIEWER 에게 설정 메뉴·등록·폐기·편집 버튼이 보이지 않는다 |
| M6.2 | 로그인·세션 만료 | 완료 | 초기 비밀번호 변경 강제. 401 이면 재로그인과 작업 손실 안내 |
| M6.3 | 통합 현황 | 완료 | 장비 수·장애·통신·마지막 수집. 15초 갱신, 갱신 중 목록 유지 |
| M6.4 | 관측소 지도 | 완료 | 색+도형(●정상 ◆주의 ▲장애 ■확인불가). 위경도 없는 점은 올리지 않음 |
| M6.5 | 관측소 목록 | 완료 | 통신·전원·시각·센서·저장소·데이터 컬럼. 미지원/미수집은 `—` |
| M6.6 | 등록 마법사 | 완료 | 기본정보→Adapter→접속→시험·탐지→센서·외부SOH→프로파일→검토/저장 |
| M6.7 | 연결 시험 진행 표시 | 완료 | 경과 초와 취소(`AbortController`) |
| M6.8 | 탐지 불일치 | 완료 | Instrument ID·모델·시리얼·펌웨어를 저장 전에 보여 준다 |
| M6.9 | Schema 기반 폼 | 완료 | Adapter Manifest `configurationSchema`. `secretFields` 는 `credentialReference` |
| M6.10 | 관측소 상세 | 완료 | 분류 탭·현재값·수집 이력·Grafana Deep Link |
| M6.11 | 프로파일 | 완료 | 영향 장비 수, 저장 전 차이, 복제 |
| M6.12 | 장애 확인 | 완료 | 확인 시 담당자·시각. VIEWER 는 확인 버튼이 없다 |
| M6.13 | 상태 자동 갱신 | 완료 | TanStack Query 15초 `refetchInterval` + `keepPreviousData` |

마법사 10절의 10단계는 화면에서 7단계로 묶었다. 제조사 선택과 수집 방식, 연결 시험과
자동 탐지를 한 화면에 둔다. EDGE 수집은 Edge 를 고르면 활성화된다.

브라우저는 기록계에 붙지 않는다. Vite 개발 서버가 `/api` 를 백엔드로 넘기고 세션 쿠키는
같은 출처로 오간다.

시연 계정: `admin` (초기 비밀번호 변경 강제), `operator` / `viewer` (`scripts/seed_demo.py`).

### 설계 판단

- **목록 API 에 분류 상태를 실었다.** 화면이 관측소마다 `current-health` 를 부르면
  N+1 이 된다. `GET /stations` 가 분류 집계·마지막 성공·수집 방식을 같이 준다.
  종합(`worstSeverity`)은 통신 성공 여부(`device_runtime_state.overall_severity`)가 아니라
  분류 상태의 최악값이다. 통신만 되면 시각이 CRITICAL 이어도 정상이라고 보이면 안 된다.
- **비밀번호 칸을 두지 않는다.** Manifest 의 `secretFields` 는 Secret 참조 입력으로
  바뀐다. 평문을 저장할 자리가 화면에도 없다.
- **세션 만료는 로그인 화면으로 되돌린다.** 저장 중이던 마법사 값은 메모리에만 있으므로
  손실 안내를 띄운다. 토큰 갱신은 두지 않았다.

---

## M7 Edge Agent

| ID | 작업 | 상태 | 결과 |
|----|------|------|------|
| M7.1 | Edge 실행 모드 분리 | 완료 | `main_edge.py` + `edgeagent/runtime.py`. 중앙과 같은 `poll_device`·Adapter |
| M7.2 | Enrollment | 완료 | 일회용 Token → 자리 표시 인증서 + HMAC 클라이언트 토큰. Token 파일 폐기 |
| M7.3 | 설정 동기·원자 적용·Rollback | 완료 | Schema·edgeId·중복 장비·미등록 Adapter 검증. 실패 시 previous.json |
| M7.4 | 로컬 Spool | 완료 | SQLite WAL + gzip Segment. 파일 먼저, 행 커밋 |
| M7.5 | Sequence·Batch·ACK | 완료 | ACK 전 삭제 없음. 재전송 시 같은 batchId 는 멱등 |
| M7.6 | Uploader | 완료 | gzip Batch, 실패 시 PENDING 복귀와 Backoff |
| M7.7 | 디스크 한도 | 완료 | ACK 분 → 정상 Poll. 장애 Poll 은 최후 |
| M7.8 | Heartbeat·자체 진단 | 완료 | CPU·메모리·디스크·시각오차. 중앙 `GET /edges/{id}/health` |
| M7.9 | 중앙 단절 중 수집 | 완료 | 중앙이 꺼져도 Spool 이 늘고, 복구 후 sequence 순으로 업로드 |
| M7.10 | 원격 연결 시험 | 완료 | EDGE 장비 `test-connection` 은 작업 대기열. Edge 가 대행 |
| M7.11 | 배포 문서 | 완료 | [`edge-deployment/README.md`](edge-deployment/README.md) |

운영 mTLS 검증·폐기와 InfluxDB 적재·지연 도달 보호의 중앙 강화는 M8.

### 설계 판단

- **중앙 Postgres 를 Edge 에 두지 않는다.** 수집 대상은 내려받은 설정과 로컬 일정만 본다.
- **Placeholder 인증서는 등록이 끝났다는 표시다.** 통신 식별은 HMAC `clientToken` 이다.
- **4xx 등록 실패는 Token 을 버린다.** 네트워크 실패는 다음 Tick 에 같은 Token 으로 재시도한다.

---

## M8 Edge 통합

| ID | 작업 | 상태 | 결과 |
|----|------|------|------|
| M8.1 | Ingest gzip·Schema·크기 제한 | 완료 | 압축·해제 모두 `SOH_EDGE_INGEST_MAX_BYTES`(기본 6MB). 초과는 413 |
| M8.2 | 멱등 (`edge_id`+`sequence`+`batch_id`) | 완료 | `edge_ingest_sequences`. 같은 Batch 재전송은 Point 수 불변 |
| M8.3 | 지연 데이터 `observed_at` 적재 | 완료 | Influx timestamp 는 관측 시각. 현재 상태는 최신 관측만 갱신 |
| M8.4 | mTLS 검증·인증서 폐기 | 완료 | `X-Edge-Certificate-Serial` 불일치·`POST /edges/{id}/revoke` → 403 |
| M8.5 | Edge 등록·할당 화면 | 완료 | `features/edges`. 미지원 Adapter·낮은 Edge 버전은 409 |
| M8.6 | Edge 상세 (Spool·버전·인증서) | 완료 | `/edges/:id` |
| M8.7 | Edge 장애 시 하위 억제 | 완료 | Heartbeat 2회 WARNING / 3회 CRITICAL. 장비 장애는 `suppressed_by_edge` |
| M8.8 | `UNKNOWN / EDGE UNREACHABLE` | 완료 | 관측소 목록·현황. 기록계 장애와 구분 |
| M8.9 | Adapter·Core 버전 호환 | 완료 | `installed_adapters`·`minimumEdgeVersion` |
| M8.10 | 지역 토폴로지 | 완료 | `GET /api/v1/fleet/topology`, 통합 현황 계층 |

### 설계 판단

- **시계열은 늦어도 채우고, 현재 상태는 되돌리지 않는다.** 하루 늦은 Poll 이 그래프의 빈칸을 메우는 것은 맞다. 그 값으로 '지금 정상' 이라고 바꾸면 안 된다.
- **함대 열린 장애 수는 Edge 억제분을 뺀다.** Edge 한 대가 죽으면 하위 수십 건이 아니라 Edge 장애 1건이 집계된다. 목록에는 억제 표시를 남겨 추적이 가능하게 한다.
- **nginx mTLS 는 배포 스위치다.** Compose 개발은 HMAC `clientToken` 만 쓴다. 운영에서 `ssl_verify_client` 를 켜면 일련번호 헤더가 오고, 폐기된 Edge 는 API 가 403 한다.

---

## 다음 착수 지점

1. **M9 Grafana** — Datasource·Dashboard Provisioning 과 알림.
2. **M-1.2 / M-1.3** — 실장비 SOH 응답 확보. 확보되면 `envelope.py`·`parser.py` 를 실제
   형태로 맞추고 기준선 대조 시험을 켠다.
3. **실제 InfluxDB 연결 검증** — Docker 환경에서 `make dev` 로 적재·조회·보존정책을 확인한다.
   현재는 Point 구성만 시험됐다.
4. **M2.11** — SeedLink/FDSN 기반 데이터 연속성 검사. 센서 상태만으로는 파형 정지를 잡지 못한다.

