# PDCC Web

IRIS PDCC를 대체하는 StationXML 웹 편집기의 모노레포입니다. 브라우저가 NRL에 직접 붙지 않고, 서버가 StationXML 원문을 보관합니다.

## M0-01 완료 조건

1. 디렉터리 골격 (`apps/`, `packages/`, `infra/`, `docs/adr/`, `tests/fixtures/`)
2. `docker compose` 로 **web, api, postgres, redis** 기동
3. `GET /health` → `{ "ok": true, "db": true, "redis": true }`
4. `POST /api/login` 스텁 사용자(`stub`/`stub`) 200. `admin`/`admin` 은 `DEV_BOOTSTRAP_ADMIN=true` 일 때만
5. 웹이 `/api/health` 를 프록시해 화면 하단에 `API OK`
6. [`docs/adr/0001-monorepo.md`](docs/adr/0001-monorepo.md)

포트: web **3000**, api **8080**, postgres **5432**, redis **6379**.

## 기동

```bash
cd pdcc_web
docker compose -f infra/docker-compose.yml up --build
```

브라우저: http://localhost:3000  
API: http://localhost:8080/health  
스텁 로그인: `stub` / `stub` (두 번째 사용자 `stub2` / `stub2`)

호스트에서만 띄울 때 (compose 없이):

```bash
# postgres·redis 가 DATABASE_URL / REDIS_URL 에 있어야 한다
cd pdcc_web/apps/api && uvicorn app.main:app --host 0.0.0.0 --port 8080
cd pdcc_web/apps/web && npm install && npm run dev -- --host 0.0.0.0 --port 3000
```

## 환경 변수

| 이름 | 기본 | 설명 |
|------|------|------|
| `APP_SECRET` | `dev-insecure-change-me` | 세션 서명. 배포 시 반드시 교체 |
| `DATABASE_URL` | `postgresql+psycopg://pdcc:pdcc@postgres:5432/pdcc` | SQLAlchemy URL |
| `REDIS_URL` | `redis://redis:6379/0` | 세션·헬스 |
| `DEV_BOOTSTRAP_ADMIN` | `false` | `admin`/`admin` 허용 |

## M1 NRL

로그인 후 센서·기록계를 고르면 서버가 NRL catalog를 프록시하고, 고유값이 2개 이상인 설정만 질문합니다. `GET /api/nrl/combine` 으로 StationXML-Response를 미리 봅니다. 브라우저는 EarthScope에 직접 붙지 않습니다. 검색·별칭·Certimus 안내는 [`docs/adr/0009-nrl-search.md`](docs/adr/0009-nrl-search.md).

| 이름 | 기본 | 설명 |
|------|------|------|
| `NRL_BASE_URL` | `https://service.earthscope.org/irisws/nrl/1` | NRL 서비스 |
| `NRL_TIMEOUT_SEC` | `30` | 업스트림 제한 |
| `NRL_CACHE_TTL_SEC` | `3600` | catalog·prefix Redis TTL |
| `NRL_MODE` | `online` | `online` / `cache-first` / `offline`. 장애 시 stale 캐시로 Guralp 미리보기 |

NRL은 API 기동 시 호출하지 않습니다. 업스트림이 죽거나 URL이 잘못되어도 캐시된 combine/catalog 는 그대로 쓰고, 상태 배지는 `캐시 사용`이 됩니다 (`docs/adr/0012-nrl-cache-fallback.md`).

## M2 위저드·잠금

로그인 후 프로젝트를 만들고 **관측소 위저드**로 TEST1 같은 3성분 채널을 만듭니다. NRL 응답은 원문 StationXML에 붙입니다. 같은 프로젝트의 관측소 epoch는 한 사람만 고칩니다 (5분 잠금). 장비 세트, 버전 되돌리기, 실행 취소, 초안 복구는 [`docs/adr/0007-collab.md`](docs/adr/0007-collab.md). 채널 폼·좌표 하위 반영·검사 패널은 [`docs/adr/0008-channel-validate.md`](docs/adr/0008-channel-validate.md).

| 이름 | 기본 | 설명 |
|------|------|------|
| `LOCK_TTL_SEC` | `300` | 관측소 epoch 잠금 TTL |

## M3 가져오기·복제

홈 **파일 열기**는 StationXML 1.2, dataless SEED, RESP를 받습니다. SEED·RESP는 converter(JAR가 있으면) 또는 ObsPy로 StationXML로 바꾼 뒤 프로젝트를 만들고, 원문 바이트는 덮어쓰지 않습니다. 변환 경고는 검사 패널에 남습니다 (`docs/adr/0015-seed-import.md`, `docs/adr/0019-resp.md`).

편집기 **관측소 복제** 표에 엑셀 행을 붙여넣으면 원본 채널·응답을 복사해 관측소를 만듭니다. 코드가 비어 있는 행은 무시합니다. API는 `POST /api/projects/{id}/clone-stations` (`docs/adr/0013-station-clone.md`, S7).

**검증**은 공식 검사를 작업 큐에 넣고 바로 돌아옵니다. 진행률은 상단과 작업 벨에 보이고, 이전 검사 결과는 유지됩니다. 편집은 그동안 계속할 수 있습니다. 끝나면 패널이 스냅샷 결과로 갱신됩니다 (`docs/adr/0016-bulk-validate.md`, S14). 실패한 작업은 같은 version id로 다시 돌립니다.

`dataless SEED` 를 누르면 변환 손실 확인 창이 열립니다. 70자 코멘트·25자 FIR·확장 필드 제거 목록을 본 뒤에만 내보내기가 진행됩니다 (`docs/adr/0017-seed-loss.md`, S6).

**RESP** 는 선택한 채널 파일, **RESP zip** 은 관측소의 채널별 zip입니다. NRL combine이 아니라 현재 편집 StationXML에서 만들므로 고친 감도가 들어갑니다. 검증 오류가 있으면 막습니다 (`docs/adr/0019-resp.md`).

| 이름 | 기본 | 설명 |
|------|------|------|
| `SEED_CONVERTER_JAR` | (없음) | 공식 stationxml-seed-converter. 없으면 ObsPy |

## M0 사용자·역할

관리자(`/admin`)가 기관과 조회자·편집자를 만듭니다. 프로젝트에 속하지 않으면 목록에 없고, 조회자는 StationXML만 받습니다 (`docs/adr/0014-users-roles.md`). `/admin` 대시보드는 NRL 상태, 실패 작업 최근 10개, 원본·export·NRL zip 디스크, 10분 이상 남은 잠금을 보여 줍니다. 빨간 배지는 NRL 장애·실패 작업·디스크 90% 이상만 씁니다 (`docs/adr/0020-admin-dashboard.md`).

| 이름 | 기본 | 설명 |
|------|------|------|
| `NRL_OFFLINE_ZIP` | (없음) | 오프라인 NRL zip 경로. 대시보드 디스크 칸 |
| `DATA_DIR` | `.` | 디스크 사용률을 재는 볼륨 |

## 테스트

```bash
cd pdcc_web/apps/api
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/pytest -q
```

API는 SQLAlchemy 2를 쓰므로 레포 루트 `.venv`(ObsPy 1.4 / SQLAlchemy 1.4)와 섞지 않습니다.
