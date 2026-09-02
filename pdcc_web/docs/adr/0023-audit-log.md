# ADR 0023. 관리자 감사 로그

상태: 채택  
코드: `apps/api/app/routers/admin.py`, `apps/api/app/inventory/service.py`,
`apps/web/src/editor/AdminPage.tsx`

## 결정

1. 관리자만 `/admin`에서 최근 감사 로그를 보고 프로젝트별로 필터링한다. API는
   `GET /api/admin/audit-logs`이며 최신순 최대 500건, 기본 100건을 반환한다.
2. 프로젝트에 속하지 않는 기관·사용자·NRL 규칙·강제 잠금 기록은 프로젝트를 `시스템`으로
   표시한다. 프로젝트 필터를 선택하면 해당 프로젝트 기록만 반환한다.
3. 감사 기록은 시각, 프로젝트, 사용자, 작업, 대상, 요약과 구조화된 세부 내용을 제공한다.
4. 위저드에서 응답을 적용하거나 기존 관측소에 NRL 응답을 적용하면 사용한 전체
   `instconfig` cascade를 `details`에 보관하고 화면에 표시한다. 기존 감사 로그 테이블은 API
   기동 시 `details` 열을 무중단 추가한다.
5. 감사 화면 조회 자체는 새 감사 기록을 만들지 않는다.

통과: **M4-05** 관리자가 전체 감사 이력을 최신순으로 확인하고 프로젝트별로 좁혀 보며,
NRL 적용에 사용된 `instconfig`를 추적할 수 있다.
