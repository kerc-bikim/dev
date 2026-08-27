# ADR 0012. NRL 장애 시 캐시 폴백

상태: 채택  
코드: `apps/api/app/nrl/client.py`, `apps/api/app/routers/nrl.py`, `apps/web/src/App.tsx`

## 결정

1. catalog·prefix-lookup·combine 은 Redis 신선 캐시(TTL)와 **30일 stale 사본**을 같이 둔다.
2. 신선 캐시가 있으면 업스트림을 치지 않는다. 신선 캐시가 없고 NRL이 실패하면 stale 로 미리보기를 계속한다.
3. 잘못된 URL·연결 거부·5xx 이고 stale 도 없으면 `503` `캐시에 없는 항목입니다. NRL이 복구된 뒤에 다시 시도하세요`. 404/400 은 그대로 둔다.
4. `GET /api/nrl/status` 는 `source`(online/cache/offline) 와 한글 `badge`(`온라인` / `캐시 사용` / `NRL 장애`), `last_ok_at`, `cache_count` 를 준다. 하단 상태바와 NRL 패널이 `캐시 사용` 배지를 보여 준다.

통과 시나리오: **S10** 캐시 읽기. 잘못된 NRL URL 에서도 캐시된 Guralp 미리보기는 되고, 캐시 없는 신규 모델은 적용할 수 없다.
