# ADR 0001. PDCC Web 모노레포와 StationXML 원문 저장

상태: 채택  
코드: `pdcc_web/`

## 맥락

IRIS PDCC 3.8.1(Java/JavaFX dataless SEED 편집기)을 웹으로 옮긴다. PDCC/NRL v1은 2024년 공식 폐기되었고, 후속은 StationXML 1.2와 NRL v2다. 이 저장소는 이미 PPSD, StationXML 관리기, Earthworm 웹 등 여러 앱을 한 레포에 둔다.

## 결정

1. **위치.** PDCC 웹은 레포 루트가 아니라 `pdcc_web/` 아래에 둔다. 기존 `stationxml_manager/` 등과 디렉터리·의존성을 섞지 않는다.
2. **앱 분할.**
   - `apps/web` — React + Vite + TypeScript. 브라우저는 NRL에 직접 호출하지 않는다.
   - `apps/api` — FastAPI. HTTP 계약의 유일한 입구.
   - `apps/worker` — SEED/RESP 변환 작업 큐 (M3).
3. **패키지.** `packages/shared`, `packages/stationxml`, `packages/nrl` 은 공유 코드 자리. M0에서는 문서만.
4. **언어.** API·워커는 Python 3.12. 웹은 TypeScript. XML 파싱·패치는 서버에서만 한다.
5. **저장 진실.** Inventory의 진실은 **StationXML 원문**이다. ObsPy Inventory는 편집·검증용 뷰다. 프로덕션 저장 경로에서 `Inventory.write()`로 전체 문서를 재생성하지 않는다.
6. **인프라.** 로컬 기동은 `infra/docker-compose.yml` 로 web, api, postgres, redis 를 올린다. NRL은 기동 시 호출하지 않는다.
7. **비밀.** `APP_SECRET`, `DATABASE_URL`, `REDIS_URL` 은 환경 변수. `DEV_BOOTSTRAP_ADMIN` 기본값은 꺼짐. `admin/admin` 로그인은 이 플래그가 켜진 개발 환경에서만 허용한다.

## 결과

- 기존 StationXML 관리기와 배포·DB가 분리된다.
- 이후 마일스톤(NRL 프록시, 위저드, SEED/RESP)이 같은 트리에서 앱만 채우면 된다.
