# ADR 0013. 관측소 복제 표

상태: 채택  
코드: `apps/api/app/inventory/xmlbuild.py`, `apps/api/app/routers/projects.py`, `apps/web/src/editor/CloneTable.tsx`

## 결정

1. `POST /api/projects/{id}/clone-stations` 는 원본 관측소 StationXML 서브트리를 복사한다. 채널 `Response` 도 같이 복제한다. ObsPy `Inventory.write()` 로 문서를 다시 쓰지 않는다.
2. 표 열은 관측소 코드, 사이트명, 위도, 경도, 고도, 시작, 종료, 채널 코멘트, 시리얼이다. 엑셀 TSV(또는 CSV) 붙여넣기를 받는다. 헤더 행이 있으면 한글/영문 열 이름으로 맞춘다.
3. **코드가 비어 있는 행은 만들지 않는다.** 그 외 빈 칸은 원본 값을 쓴다. 종료를 비우면 `endDate` 를 넣지 않아 현재 운영으로 둔다.
4. 시리얼은 30자를 넘으면 거부하고, 채널 `Comment` 에 짧은 문자열로 넣는다.
5. 한 요청에서 유효 행을 모두 만든 뒤 버전 스냅샷 `clone` 과 감사 로그를 남긴다. 빈 코드만 있는 요청은 400 이다.

통과 시나리오: **S7**. TEST1 을 원본으로 5행을 붙여넣고 한 행의 코드가 비어 있으면 코드 있는 4개만 생성되고, 트리에 응답이 복사된 관측소가 생긴다.
