# 프롬프트: 슬라이스 구현

아래 티켓 하나만 구현합니다. 범위를 넓히지 않습니다.

## 입력

- 티켓 ID와 통과 조건:
- 관련 ADR (없으면 새로 작성):
- 건드릴 화면/API:

## 절차

1. `pdcc_web/docs/prompts/product.md`와 `completed-m0-m4.md`를 읽고 이미 있는 기능을 다시 만들지 않습니다.
2. 기존 라우터·화면·테스트를 찾아 같은 패턴으로 확장합니다.
3. API 변경이 있으면 pytest를 `pdcc_web/apps/api`에서 추가하거나 기존 테스트에 단언을 보탭니다.
4. UI가 있으면 `apps/web` 한국어 문구, 관리자/조회자 권한, 도움말 링크를 맞춥니다.
5. ADR에 결정·코드 경로·통과 조건을 기록합니다.
6. `python -m pytest --ignore=tests/test_ops.py`가 통과하는지 확인합니다.
7. 가능하면 라이브 API(`stub`/`admin` 쿠키)로 권한·오류 코드를 한 번 더 칩니다. UI면 브라우저에서 해당 흐름을 끝까지 실행합니다.
8. `pdcc_web/`만 커밋합니다. 무관한 `package-lock.json`은 넣지 않습니다.

## 완료 정의

통과 조건이 테스트 또는 라이브 호출로 증명되고, README/ADR이 동작과 모순되지 않으면 끝입니다. “컴파일됨”이나 “페이지가 열림”만으로는 부족합니다.

## Cursor Cloud

- API `:8080`, 웹 `:3000`. 코드 반영 후 uvicorn PID를 재시작합니다.
- Redis가 내려가 있으면 헬스 `redis: false`입니다. 잠금·세션 테스트 전에 Redis 또는 fakeredis TCP를 올립니다.
- 라이브 API를 재시작할 때 `pkill -f`를 쓰지 말고 PID만 종료합니다.
- computer use가 없으면 GUI 미확인을 명시하고 curl/Vite 소스로 대체합니다.
