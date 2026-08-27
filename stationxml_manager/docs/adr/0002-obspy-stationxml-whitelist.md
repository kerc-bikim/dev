# ADR 0002. ObsPy StationXML 직렬화 화이트리스트

상태: 채택  
코드: `app/stationxml/whitelist.py`, `compare.py`, `patch.py`  
테스트: `tests/stationxml/test_roundtrip_whitelist.py`

## 결정

1. 저장 진실은 StationXML 원문이다. ObsPy Inventory는 편집·검증용 뷰다.
2. 저장은 원문 트리를 패치한다. `Inventory.write()`로 문서를 통째로 갈아엎지 않는다.
3. 왕복 성공 기준은 바이트 diff가 아니라 화이트리스트 필드의 의미 동등이다.
4. 이 저장소의 ObsPy는 1.4.1이며 읽기/쓰기 스키마는 1.2를 지원한다.

## 금지

- 프로덕션 저장 경로에서 `inv.write(format="STATIONXML")`로 전체 문서를 재생성하지 않는다.
- Operator Agency가 둘 이상이면 원문을 유지한다. ObsPy write는 첫 Agency만 남긴다.
