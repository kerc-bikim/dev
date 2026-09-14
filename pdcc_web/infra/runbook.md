# PDCC Web 운영 런북

Docker-in-Docker가 없는 호스트와 compose 배포를 모두 다룬다. StationXML 원문이 인벤토리 진실이다. SEED/RESP는 M3.

## 비밀

| 이름 | 개발 기본 | 프로덕션 |
|------|-----------|----------|
| `APP_SECRET` | `dev-insecure-change-me` (경고) | **필수**. 기본값이면 API가 기동하지 않음 |
| `APP_ENV` | `development` | `production` |
| `DATABASE_URL` | compose 서비스명 | 실제 Postgres URL |
| `REDIS_URL` | compose 서비스명 | 실제 Redis URL |
| `POSTGRES_PASSWORD` | `pdcc` | **반드시 교체** |
| `ALLOW_STUB_LOGIN` | `true` | `false` (프로덕션에서 true면 기동 거부) |
| `DEV_BOOTSTRAP_ADMIN` | `false` | `false` (true면 기동 거부) |
| `SESSION_COOKIE_SECURE` | 꺼짐 | 켜짐 |
| `CORS_ORIGINS` | localhost:3000 | 브라우저 출처. 비우면 same-origin |
| `AUDIT_RETENTION_DAYS` | 365 | 필요 시 조정 |

복사: `cp infra/env.example infra/.env` 후 `APP_SECRET` 을 긴 난수로 바꾼다.

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```

## Compose

개발:

```bash
cd pdcc_web
docker compose -f infra/docker-compose.yml --env-file infra/.env up --build
```

프로덕션 overlay (`APP_SECRET`, `POSTGRES_PASSWORD` 미설정 시 실패):

```bash
export APP_SECRET=... POSTGRES_PASSWORD=...
docker compose -f infra/docker-compose.yml -f infra/docker-compose.prod.yml --env-file infra/.env up -d --build
```

## 호스트 기동 (compose 없이)

Postgres 16과 Redis 7이 `DATABASE_URL` / `REDIS_URL` 에 있어야 한다.

```bash
export APP_ENV=development
export APP_SECRET=test-or-real-secret
export DATABASE_URL=postgresql+psycopg://pdcc:pdcc@127.0.0.1:5432/pdcc
export REDIS_URL=redis://127.0.0.1:6379/0
cd pdcc_web/apps/api && .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8080
cd pdcc_web/apps/web && npm run dev -- --host 0.0.0.0 --port 3000
```

## 헬스

| 경로 | 의미 | 실패 |
|------|------|------|
| `GET /health/live` | 프로세스 생존 | 프로세스 다운 |
| `GET /health/ready` | DB+Redis | 503 |
| `GET /health` | ready와 동일 (M0 계약) | 503 |

```bash
curl -sS http://127.0.0.1:8080/health/live
curl -sS -D- http://127.0.0.1:8080/health/ready | head
# 요청 ID
curl -sS -D- -H 'X-Request-ID: ops-1' http://127.0.0.1:8080/health/live | grep -i request
```

웹 하단 `API OK` 는 `/api/health` 프록시다.

## 인증

- 개발: `stub`/`stub`, `stub2`/`stub2`. `DEV_BOOTSTRAP_ADMIN=true` 이면 `admin`/`admin`.
- 프로덕션: 스텁 없음. 사용자가 없으면 로그인 화면의 **최초 관리자** 또는:

```bash
curl -sS http://127.0.0.1:8080/api/ops/bootstrap
curl -sS -X POST http://127.0.0.1:8080/api/ops/bootstrap \
  -H 'Content-Type: application/json' \
  -d '{"username":"operator1","password":"change-me-now"}'
```

이후 같은 엔드포인트는 409다.

로그인 쿠키는 HttpOnly. 프로덕션은 Secure.

```bash
curl -sS -c /tmp/pdcc.jar -X POST http://127.0.0.1:8080/api/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"stub","password":"stub"}'
```

## StationXML 백업·복원

진실은 프로젝트 `xml_text` 다. ZIP에는 `manifest.json` 과 `projects/*.xml` 이 들어 있다.

```bash
# 로그인 쿠키 필요
curl -sS -b /tmp/pdcc.jar -o pdcc-stationxml.zip http://127.0.0.1:8080/api/ops/backup
curl -sS -b /tmp/pdcc.jar -X POST http://127.0.0.1:8080/api/ops/restore \
  -H 'Content-Type: application/zip' --data-binary @pdcc-stationxml.zip
```

스크립트: `infra/backup.sh`, `infra/restore.sh`.

덮어쓰기 복원(`?replace=true`)은 관리자만. 웹 **운영 → 백업 · 복원** 에서 ZIP을 내려받고 가져온다.

## PostgreSQL 덤프 (메타데이터·사용자·잠금)

원문 ZIP과 별개로 DB 전체를 남길 때:

```bash
pg_dump -h 127.0.0.1 -U pdcc -d pdcc -Fc -f pdcc-$(date -u +%Y%m%dT%H%M%SZ).dump
pg_restore -h 127.0.0.1 -U pdcc -d pdcc --clean --if-exists pdcc-YYYYMMDDThhmmssZ.dump
```

Redis 세션은 덤프하지 않는다. 복구 후 다시 로그인한다.

## 감사 로그

```bash
curl -sS -b /tmp/pdcc.jar 'http://127.0.0.1:8080/api/ops/audit?limit=50'
curl -sS -b /tmp/pdcc.jar 'http://127.0.0.1:8080/api/ops/audit?action=create&actor=stub'
```

웹 **운영 → 감사 로그**. 보관기간이 지난 행은 API 기동 시 삭제된다. 관리자 수동 정리: `POST /api/ops/audit/purge`.

운영 상태(비밀 기본값 여부 포함): `GET /api/ops/status`.

## 로그

API 로그 형식: `시간 LEVEL logger request_id=...: message`. 헬스 폴링은 액세스 로그에서 뺀다. 브라우저·프록시는 `X-Request-ID` 로 한 요청을 묶는다.
