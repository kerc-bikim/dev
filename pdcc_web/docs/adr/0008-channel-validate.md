# ADR 0008. 채널 폼, 하위 반영, 즉시 검증

상태: 채택  
코드: `apps/api/app/inventory/xmlbuild.py`, `apps/web/src/editor/`

## 결정

1. 채널 코드·location·깊이·방위각·경사·샘플링은 관측소와 같은 **초안 PUT**으로만 바뀐다.
2. 관측소 좌표·종료일을 바꾸면 확인 창 뒤에만 채널에 반영한다. `propagate=false`면 관측소만. 반영과 미반영 모두 초안 1건이다.
3. `GET /api/projects/{id}/issues`가 초안(있으면) 또는 서버 XML을 검사한다. 오류 클릭은 해당 칸으로 이동한다. 겹침은 `E_EPOCH_OVERLAP`, 위도는 `E_LAT`.
