# FAQ

**비밀번호를 화면에 넣어도 되나?**  
안 된다. `env:` / `file:` 참조만 저장한다. 접속정보 테이블에 평문 컬럼이 없다.

**값이 없으면 0 으로 보이는데?**  
버그다. 없는 값은 `UNSUPPORTED` / `UNKNOWN` / `ERROR` 다. 이슈로 남긴다.

**Centaur 가 아닌 장비를 붙이려면?**  
[`adapter-development.md`](../adapter-development.md). Adapter + Manifest + Mapping. DB·공통 화면·공통 Grafana 는 손대지 않는다.

**Grafana 에서 대시보드를 고쳤는데 사라졌다.**  
Git 이 원본이다. `scripts/gen_grafana.py` 로 고치고 배포한다.

**첫 로그인 비밀번호를 모른다.**  
`make migrate` 로그. 이미 바꿨으면 관리자가 재설정한다. 초기 비밀번호는 저장소에 없다.

**VIEWER 가 설정을 못 본다.**  
의도다. 조회만 한다.

**센서 교체 때 장애가 열린다.**  
관측소 상세 설정에서 유지보수 창을 연다. 알림은 억제되고 상태는 `MAINTENANCE` 다.

**실장비 SOH JSON 이 가상 서버와 다르다.**  
`inventory.md` 를 채우고 Fixture 를 `testdata/real-*.json` 에 넣는다. 파서가 실응답을 따른다.
