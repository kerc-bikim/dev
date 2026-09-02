# ADR 0021. NRL 전체 zip 오프라인

상태: 채택  
코드: `apps/api/app/nrl/offline.py`, `apps/api/app/routers/nrl.py`, `apps/web/src/editor/AdminPage.tsx`

## 결정

1. 관리자는 `/admin`에서 EarthScope의 `full_NRL_v2_zip` StationXML archive를 서버의
   `NRL_OFFLINE_ZIP` 경로에 원자적으로 내려받고 NRL 모드를 전환한다. 편집자는 다운로드,
   archive 상태 조회, 모드 변경을 할 수 없다.
2. 오프라인 모드는 archive의 `NRL/index.txt`부터 이어지는 결정 트리를 읽어 장비 유형,
   제조사, 모델, 설정을 만든다. JSON catalog나 Redis의 이전 온라인 index에 의존하지 않는다.
3. 단일 미리보기는 archive 안의 response XML을 그대로 반환한다. 센서와 기록계처럼
   콜론으로 연결한 설정은 stage를 순서대로 이어 붙이고 번호와 전체 감도·출력 단위를
   갱신해 StationXML-Response를 만든다.
4. 오프라인 모드의 catalog, 검색, 위저드, combine, curve, 상태 조회는 EarthScope를
   호출하지 않는다. archive가 없거나 손상됐으면 503을 반환한다.
5. 정상 archive를 쓰는 상태 소스는 `zip`, 배지는 `오프라인 zip`이다. 이 상태는 운영
   대시보드에서 NRL 장애 빨간 배지로 세지 않는다.
6. compose 배포는 `/data` named volume에 archive를 보존한다. 다운로드 제한은
   `NRL_LIBRARY_TIMEOUT_SEC`으로 조정한다.

통과: **M4-02** 오프라인 모드에서 전체 zip으로 탐색·검색·미리보기가 동작한다.
