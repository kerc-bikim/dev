# PDCC Web

IRIS **PDCC 3.8.1**을 대체하는 StationXML 1.2 + NRL v2 웹 편집기입니다. 위치는 레포 루트가 아니라 `pdcc_web/`입니다. 기존 `stationxml_manager/`와 DB·의존성을 섞지 않습니다.

- 브라우저는 EarthScope NRL에 직접 호출하지 않습니다. API만 프록시합니다.
- Inventory의 진실은 **StationXML 원문**입니다. ObsPy `Inventory`는 뷰이며, 저장 경로에서 `Inventory.write()`로 전체 문서를 다시 쓰지 않습니다.
- 앱 안 사용자·관리자 매뉴얼: `/help`, `/help/admin`.

M0–M4 번호 티켓(뼈대, NRL, 위저드·잠금, 가져오기·내보내기·검증, 운영)은 구현되어 있습니다. 결정 기록은 [`docs/adr/`](docs/adr/README.md), 에이전트용 고정 프롬프트는 [`docs/prompts/`](docs/prompts/README.md)입니다.

## 구성

| 경로 | 역할 |
|------|------|
| `apps/web` | React + Vite. 포트 **3000** |
| `apps/api` | FastAPI. HTTP의 유일한 입구. 포트 **8080** |
| `apps/worker` | 검증·SEED·RESP 작업 큐 러너 (`python -m app.jobs.runner`) |
| `infra/` | `docker-compose.yml`, `env.example`, `backup-postgres.sh` |
| `docs/adr/` | 채택된 설계 결정 |
| `docs/prompts/` | 이후 구현·수정에 붙이는 프롬프트 |
| `docs/restore.md` | PostgreSQL 백업·복구 |

compose 기본 기동은 **web, api, postgres, redis**입니다. worker는 넣지 않습니다. 공식 검증과 SEED·RESP 작업을 쓰려면 API와 같은 코드·환경 변수로 워커를 따로 띄웁니다.

## 기동

```bash
cd pdcc_web
docker compose -f infra/docker-compose.yml up --build
```

- 웹: http://localhost:3000
- API 헬스: http://localhost:8080/health → `{ "ok": true, "db": true, "redis": true }`
- 스텁 로그인: `stub` / `stub`, `stub2` / `stub2`
- `admin` / `admin`은 `DEV_BOOTSTRAP_ADMIN=true`일 때만. 운영 계정을 만든 뒤 이 플래그를 끕니다.

호스트에서만 띄울 때 (compose 없이 postgres·redis가 `DATABASE_URL` / `REDIS_URL`에 있어야 합니다):

```bash
cd pdcc_web/apps/api
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
export DATABASE_URL=postgresql+psycopg://pdcc:pdcc@127.0.0.1:5432/pdcc
export REDIS_URL=redis://127.0.0.1:6379/0
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8080

# 다른 터미널. 검증·SEED·RESP를 쓸 때
.venv/bin/python -m app.jobs.runner

cd pdcc_web/apps/web && npm install && npm run dev -- --host 0.0.0.0 --port 3000
```

API는 SQLAlchemy 2를 쓰므로 레포 루트 `.venv`(ObsPy 1.4 / SQLAlchemy 1.4)와 섞지 않습니다.

## 기능

### 프로젝트·권한

관리자가 기관과 조회자·편집자·관리자를 만듭니다. 프로젝트 멤버가 아니면 목록에도 없고 `GET`도 404입니다. 조회자는 보기·즉시 검사·StationXML 다운로드만, 편집자는 초안·위저드·NRL·내보내기, 관리자는 `/admin`입니다 ([`docs/adr/0014-users-roles.md`](docs/adr/0014-users-roles.md)).

편집 권한이 있으면 프로젝트를 보관할 수 있습니다. 보관본은 일반 목록에서 숨기고, 복원은 관리자만 합니다 ([`docs/adr/0024-project-archive.md`](docs/adr/0024-project-archive.md)).

### NRL

로그인 후 센서·기록계를 고르면 서버가 catalog를 프록시하고, 고유값이 2개 이상인 설정만 질문합니다. `GET /api/nrl/combine`으로 StationXML-Response를 미리 봅니다. 검색·별칭·Certimus 등 제외 장비 안내는 [`docs/adr/0009-nrl-search.md`](docs/adr/0009-nrl-search.md).

업스트림이 죽어도 유효한 Redis 캐시가 있으면 배지는 **캐시 사용**입니다 ([`docs/adr/0012-nrl-cache-fallback.md`](docs/adr/0012-nrl-cache-fallback.md)). 관리자는 `/admin`에서 연결 테스트, 카탈로그 새로고침, 모드(온라인 / 캐시 우선 / 오프라인), 전체 zip 받기를 합니다. 오프라인은 zip의 `index.txt`만 읽고 EarthScope를 치지 않습니다 ([`docs/adr/0021-nrl-offline-zip.md`](docs/adr/0021-nrl-offline-zip.md), [`docs/adr/0026-admin-ops.md`](docs/adr/0026-admin-ops.md)).

### 위저드·편집·잠금

관측소 위저드는 식별·이름·기간·위치·NRL·채널 패턴·확인 7단계입니다. NRL 응답은 원문 XML에 붙입니다. 잠금 단위는 프로젝트 안의 관측소 epoch이며 TTL 기본 5분, heartbeat로 연장합니다 ([`docs/adr/0004-wizard-lock.md`](docs/adr/0004-wizard-lock.md)).

장비 세트, 버전 되돌리기, 실행 취소, 초안 복구·충돌 시 필드 선택은 [`docs/adr/0007-collab.md`](docs/adr/0007-collab.md). 채널 폼·좌표 하위 반영·즉시 검사는 [`docs/adr/0008-channel-validate.md`](docs/adr/0008-channel-validate.md). 깊이 칸 안내는 `지면 기준 센서 깊이(m). 고도에 더하면 지표면 고도입니다.`

관리자 강제 해제는 사유가 필수이고 초안은 유지합니다. 해당 편집자에게 `관리자가 잠금을 해제했습니다` 알림이 갑니다. 대시보드의 10분 이상 잠금은 모니터링용이며, 기본 TTL 5분 잠금은 **현재 잠금** 목록에서 해제합니다.

### 가져오기·복제·검증·내보내기

홈 **파일 열기**는 StationXML 1.2, dataless SEED, RESP를 받습니다. 원문 바이트는 편집 XML과 덮어쓰지 않습니다. zip·MiniSEED·full SEED는 거절합니다. 허용 확장자·크기·zip 경로는 [`docs/adr/0025-upload-security.md`](docs/adr/0025-upload-security.md).

**관측소 복제** 표에 엑셀 행을 붙여넣으면 원본 채널·응답을 복사합니다 (`POST /api/projects/{id}/clone-stations`, [`docs/adr/0013-station-clone.md`](docs/adr/0013-station-clone.md)).

**검증**은 공식 검사를 작업 큐에 넣고 바로 돌아옵니다. JAR가 없으면 Python이 같은 번호를 붙입니다. StationXML은 오류가 있어도 `{network}_unvalidated.xml`로 받습니다. dataless는 오류면 409입니다 ([`docs/adr/0010-official-validator.md`](docs/adr/0010-official-validator.md), [`docs/adr/0016-bulk-validate.md`](docs/adr/0016-bulk-validate.md)).

**dataless SEED**는 70자 코멘트·25자 FIR·확장 필드 제거 목록을 확인한 뒤에만 진행합니다 ([`docs/adr/0017-seed-loss.md`](docs/adr/0017-seed-loss.md), [`docs/adr/0018-seed-export.md`](docs/adr/0018-seed-export.md)). **RESP** / **RESP zip**은 현재 편집 XML에서 만들므로 고친 감도가 들어갑니다 ([`docs/adr/0019-resp.md`](docs/adr/0019-resp.md)). 실패한 작업은 같은 스냅샷으로 다시 시도할 수 있고, 대기 작업은 취소할 수 있습니다.

### 관리자 `/admin`

운영 대시보드(사용자·프로젝트·오늘 내보내기, NRL, 실패 작업 10개, 디스크, 10분 이상 잠금, 백업 성공 시각, 운영 알림), 감사 로그, NRL zip·모드, 현재 잠금 강제 해제, 작업 목록, 별칭·제외 장비, 기관·사용자·멤버, 시스템 한도·인용입니다.

빨간 배지는 API 5xx, NRL 장애·연속 실패, 실패 작업, 디스크 90% 이상에만 씁니다. 오프라인 zip은 NRL 장애로 세지 않습니다. 백업 시각은 검증된 PostgreSQL 덤프 표식만 읽습니다 ([`docs/restore.md`](docs/restore.md)).

## 환경 변수

`infra/env.example`을 기준으로 배포 값을 넣습니다. `APP_SECRET`과 DB 비밀번호는 운영에서 반드시 바꿉니다.

| 이름 | 기본 | 설명 |
|------|------|------|
| `APP_SECRET` | `dev-insecure-change-me` | 세션 서명 |
| `DATABASE_URL` | `postgresql+psycopg://pdcc:pdcc@postgres:5432/pdcc` | SQLAlchemy URL |
| `REDIS_URL` | `redis://redis:6379/0` | 세션·잠금·NRL 캐시·작업 큐 |
| `DEV_BOOTSTRAP_ADMIN` | `false` | `admin`/`admin` 허용 |
| `DATA_DIR` | `.` (compose `/data`) | 디스크 사용률·기본 데이터 경로 |
| `BACKUP_STATUS_FILE` | `${DATA_DIR}/backup-last-success` | 검증된 마지막 백업 UTC 시각 |
| `NRL_BASE_URL` | `https://service.earthscope.org/irisws/nrl/1` | NRL 서비스 |
| `NRL_TIMEOUT_SEC` | `30` | 업스트림 제한 |
| `NRL_CACHE_TTL_SEC` | `3600` | catalog·prefix Redis TTL |
| `NRL_MODE` | `online` | `online` / `cache-first` / `offline` |
| `NRL_OFFLINE_ZIP` | (없음, compose는 `/data/nrl/full_NRL_v2.stationxml.zip`) | 전체 StationXML zip |
| `NRL_LIBRARY_TIMEOUT_SEC` | `900` | 관리자 zip 다운로드 제한 |
| `LOCK_TTL_SEC` | `300` | 관측소 epoch 잠금 TTL |
| `VALIDATOR_JAR` | (없음) | 공식 StationXML validator |
| `VALIDATOR_TIMEOUT_SEC` | `60` | validator 제한 |
| `SEED_CONVERTER_JAR` | (없음) | stationxml-seed-converter. 없으면 ObsPy |
| `CONVERTER_TIMEOUT_SEC` | `60` | converter 제한 |
| `SEED_ORGANIZATION` / `SEED_LABEL` | (비움) | 비우면 프로젝트 운영기관 / 네트워크 코드 |
| `MAX_UPLOAD_BYTES` | `20971520` | 프로젝트 가져오기 최대 크기 |
| `MAX_ZIP_BYTES` | `536870912` | NRL zip 저장 최대 크기 |
| `MAX_ZIP_UNCOMPRESSED_BYTES` | `2147483648` | zip 압축 해제 상한 |
| `MAX_ZIP_MEMBERS` | `100000` | zip 항목 수 상한 |
| `MONITOR_API_5XX_WINDOW_SEC` | `900` | API 5xx 알림 집계 구간 |
| `MONITOR_NRL_FAILURE_THRESHOLD` | `3` | NRL 연속 실패 알림 기준 |

## 테스트

```bash
cd pdcc_web/apps/api
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest --ignore=tests/test_ops.py -q
```

`tests/test_ops.py`는 이전 운영 스택 잔여이며 이 트리의 기본 경로가 아닙니다. 웹 UI 변경은 브라우저에서 동작까지 확인합니다. Cursor Cloud 환경의 포트·tmux·Redis 주의는 [`AGENTS.md`](AGENTS.md)를 따릅니다.

## 문서

| 문서 | 내용 |
|------|------|
| [`AGENTS.md`](AGENTS.md) | 이 트리에서 코딩할 때 지킬 규칙 |
| [`docs/prompts/`](docs/prompts/README.md) | 제품 불변식·슬라이스 구현 프롬프트 |
| [`docs/adr/`](docs/adr/README.md) | 설계 결정 |
| [`docs/restore.md`](docs/restore.md) | 백업·복구 |
| 앱 `/help`, `/help/admin` | 사용자·관리자 매뉴얼 |
