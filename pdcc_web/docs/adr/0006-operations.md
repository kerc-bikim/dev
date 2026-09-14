# ADR 0006. 운영: 비밀, 감사, 백업, 헬스

상태: 채택  
코드: `apps/api/app/runtime.py`, `apps/api/app/routers/ops.py`, `apps/api/app/backup.py`, `infra/`

## 맥락

M0–M2로 편집기와 NRL 프록시가 동작한다. 운영자가 비밀을 고정하고, 프로젝트 StationXML을 스냅샷하며, 감사 로그를 읽고, 프로세스 생존/준비 상태를 구분할 수 있어야 한다. SEED/RESP 변환과 작업 큐는 M3 범위이며 여기에 넣지 않는다.

## 결정

1. **환경.** `APP_ENV=development|production`. 프로덕션은 실패 폐쇄다.
   - `APP_SECRET` 가 비어 있거나 `dev-insecure-change-me` 이면 기동하지 않는다.
   - `DEV_BOOTSTRAP_ADMIN=true` 와 `ALLOW_STUB_LOGIN=true` 는 기동하지 않는다.
   - 개발에서는 같은 조건을 경고만 한다.
2. **인증.** 개발 스텁(`stub`/`stub2`)은 개발 기본값이다. 프로덕션은 스텁을 시드하지 않고 로그인도 거절한다. 사용자 테이블이 비어 있으면 `POST /api/ops/bootstrap` 으로 최초 관리자를 한 번만 만든다.
3. **세션 쿠키.** HttpOnly, SameSite=Lax(기본). Secure는 프로덕션 기본 켜짐. `SESSION_COOKIE_SECURE`, `SESSION_COOKIE_SAMESITE` 로 덮어쓴다. SameSite=None 은 Secure 없이 거절한다.
4. **헬스.** `GET /health/live` 는 프로세스만 본다. `GET /health/ready` 와 기존 `GET /health` 는 DB·Redis가 살아 있어야 200이다.
5. **요청 ID.** 요청마다 `X-Request-ID` 를 받거나 만들고, 응답 헤더와 액세스 로그에 남긴다. 처리되지 않은 예외는 `request_id` 를 본문에 담아 500을 돌려준다.
6. **감사.** `audit_logs` 를 `GET /api/ops/audit` 로 읽는다. 기본 보관 365일(`AUDIT_RETENTION_DAYS`). 기동 시 만료 행을 지우고, 관리자는 `POST /api/ops/audit/purge` 로 같은 작업을 한다.
7. **백업.** 진실은 StationXML 원문이다. `GET /api/ops/backup` 은 모든 프로젝트 XML + `manifest.json` ZIP이다. `POST /api/ops/restore` 는 기본으로 새 프로젝트를 만든다. `replace=true` 는 관리자만. PostgreSQL 덤프는 런북의 `pg_dump` 절차다.

## 결과

운영자는 NRL/위저드 내부 없이 설정·헬스·원문 백업·감사 조회를 할 수 있다. 프로덕션 compose overlay (`infra/docker-compose.prod.yml`)는 `APP_SECRET` 없이 올라가지 않는다.
