# packages/stationxml

Inventory의 진실은 StationXML 원문입니다. ObsPy `Inventory`는 뷰이며, 저장 경로에서 `Inventory.write()`로 전체 문서를 재생성하지 않습니다.

패치·가져오기·검증 구현은 `apps/api/app/inventory/`와 ADR [0001](../../docs/adr/0001-monorepo.md), [0011](../../docs/adr/0011-stationxml-import.md)입니다. 이 패키지 디렉터리는 공유 자리입니다.
