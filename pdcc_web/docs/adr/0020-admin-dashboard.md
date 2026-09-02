# ADR 0020. 관리자 대시보드

상태: 채택  
코드: `apps/api/app/dashboard.py`, `apps/api/app/routers/admin.py`, `apps/web/src/editor/AdminPage.tsx`

## 결정

1. **한 화면.** `/admin` 맨 위에 운영 상태만 둔다. 사용자 수, 프로젝트 수, 오늘 내보내기 수(SEED/RESP 작업), NRL 모드·소스·마지막 동기화·캐시된 응답 수, 실패 작업 최근 10개, 원본/export/NRL zip 바이트, 잠금이 10분 이상 남은 관측소.
2. **빨간 배지.** `API 5xx`, `NRL 장애`/`NRL 연속 실패`, `실패 작업`, `디스크 90% 이상`. 다른 경고는 배지로 쓰지 않는다.
3. **권한.** `GET /api/admin/dashboard` 는 관리자만. 편집자·조회자는 403.
4. **NRL.** 대시보드는 Redis에 기록된 소스(`online`/`cache`/`offline`)를 읽는다. 업스트림을 다시 때리지 않는다. 연결 시험은 기존 `POST /api/nrl/test`(M1-11)다.
5. **NRL zip.** `NRL_OFFLINE_ZIP` 파일이 있으면 그 크기를 쓰고, 없으면 NRL 캐시 바이트를 같은 칸에 보여 준다. 전체 zip 오프라인(M4-02)이 오면 이 경로를 채운다.
6. **M4-10 모니터링.** ASGI 미들웨어가 최근 API 5xx의 메서드·경로·상태·시각을 Redis에 최대 200건 기록한다. 작업 실패는 기존 `jobs` 테이블의 `failed` 상태를 단일 근거로 쓴다. NRL 실시간 요청 실패는 Redis 연속 횟수를 올리고 성공 시 0으로 초기화한다. 기본 15분 내 API 5xx가 있거나 NRL이 3회 연속 실패하면 활성 알림이다.
7. **단일 표면.** 새 운영 메뉴나 백업·복구 API를 만들지 않는다. 관리자는 기존 `GET /api/admin/dashboard`의 `monitoring`, `alerts`, `badges`와 `/admin`의 운영 알림 표에서 확인한다.

통과: **M4-01** 관리자 대시보드에 NRL·실패 작업·디스크가 보인다. **M4-10** API 5xx·worker 작업 실패·NRL 연속 실패 알림이 같은 화면에 보인다.
