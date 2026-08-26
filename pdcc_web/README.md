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
스텁 로그인: `stub` / `stub`

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

`.env` 는 커밋하지 않습니다. 예시는 [`infra/env.example`](infra/env.example).

## 테스트

```bash
cd pdcc_web/apps/api
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/pytest -q
```

API는 SQLAlchemy 2를 쓰므로 레포 루트 `.venv`(ObsPy 1.4 / SQLAlchemy 1.4)와 섞지 않습니다.
