# ADR 0009. NRL 검색·별칭·제외 장비

상태: 채택  
코드: `apps/api/app/nrl/search.py`, `apps/api/app/seed.py`, `apps/api/app/routers/admin.py`, `apps/web/src/nrl/NrlPanel.tsx`, `apps/web/src/editor/AdminPage.tsx`

## 결정

1. `GET /api/nrl/search?q=&element=` 가 제조사·모델 카탈로그와 DB 별칭을 같이 본다. 별칭은 코드에 하드코딩하지 않는다.
2. 기본 별칭(metrozet→EQMet, cme→RSensors 등)과 Certimus/Minimus/Fortimus 안내는 seed로 넣는다.
3. 제외 장비 검색은 NRL 목록 대신 교정 시트/RESP 안내만 돌려준다.
4. `GET /api/nrl/status`는 모드·캐시, `POST /api/nrl/test`는 관리자만 업스트림을 친다.
5. 관리자는 `/api/admin/nrl/aliases`와 `/api/admin/nrl/excluded`에서 규칙을 추가·수정·삭제한다. 검색은 매 요청에 DB 규칙을 읽으므로 저장 직후 적용하며 변경은 감사 로그에 남긴다.

통과 시나리오: **S3** `3t` 검색, **S11** Certimus 안내, **M4-03** 관리자 별칭·제외 장비 관리와 즉시 검색 반영.
