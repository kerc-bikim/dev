# 프롬프트: PDCC Web 제품 불변식

당신은 IRIS PDCC 3.8.1을 대체하는 **PDCC Web**을 구현·수정합니다. 코드는 `pdcc_web/`만 다룹니다.

## 목표

StationXML 1.2 인벤토리를 웹에서 만들고, NRL v2 응답을 붙이고, 검증한 뒤 StationXML / dataless SEED / RESP로 내보냅니다.

## 하지 말 것

- 브라우저에서 EarthScope NRL(`irisws/nrl`)을 직접 호출하지 않습니다.
- 저장 시 ObsPy `Inventory.write()`로 StationXML 전체를 재생성하지 않습니다. 진실은 XML 원문입니다.
- API 기동 시 NRL을 호출하지 않습니다.
- `stationxml_manager/`, PPSD, Earthworm, ringserver 트리와 의존성·커밋을 섞지 않습니다.
- 레포 루트 Python venv(ObsPy 1.4 / SQLAlchemy 1.4)로 API를 실행하지 않습니다. `pdcc_web/apps/api/.venv`만 씁니다.
- 파형 MiniSEED, full SEED, 인벤토리 zip 가져오기를 구현하지 않습니다. 거절 메시지만 유지합니다.
- 영어 UI 문구를 새로 넣지 않습니다. 사용자에게 보이는 문자열은 한국어입니다.

## 아키텍처

- `apps/web` — React + Vite. `/api`는 개발 서버가 8080으로 프록시합니다.
- `apps/api` — FastAPI. HTTP 계약의 유일한 입구입니다.
- `apps/worker` — Redis 작업 큐. compose 기본 세트에 없습니다. 검증·SEED·RESP는 워커가 필요합니다.
- Redis: 세션, 관측소 잠금, NRL 캐시, 작업 큐, 편집자 알림.
- PostgreSQL: 프로젝트 XML, 원본 파일, 사용자, 버전, 작업, 감사 로그.

## 권한

- 조회자: 열람, 즉시 검사, StationXML 다운로드.
- 편집자: 초안, 위저드, NRL, 검증 요청, SEED/RESP(확인 후).
- 관리자: `/admin` (사용자, NRL 모드·zip, 잠금 강제 해제, 작업, 시스템).
- 프로젝트 멤버가 아니면 목록 404입니다.

## 잠금

단위는 `sta:{project_id}:NET.STA#start`입니다. TTL 기본 300초. 관리자 강제 해제는 사유 필수, 초안 유지, 편집자에게 `관리자가 잠금을 해제했습니다`. 대시보드의 10분 이상 목록은 모니터링용입니다. 강제 해제는 `GET /api/admin/locks`(현재 잠금)를 씁니다.

## 검증·내보내기

- 즉시 검사 코드(`E_LAT` 등)와 공식 번호(410, 412, …)를 섞어 표시하지 않습니다.
- JAR가 없으면 Python 대체 경로 + 경고가 정상입니다.
- StationXML은 오류가 있어도 `_unvalidated.xml`로 받습니다. dataless는 오류면 409입니다.
- SEED 내보내기 전 손실 확인(`loss_ack`)이 필요합니다.

## 문서

동작이 바뀌면 해당 `docs/adr/*.md`를 갱신하고 `pdcc_web/README.md`의 관련 절을 맞춥니다.
