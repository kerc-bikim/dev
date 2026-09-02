# PDCC Web 프롬프트

이후 에이전트·사람에게 붙이는 고정 지시입니다. 제품 설명은 [`README.md`](../../README.md), 설계 결정은 [`adr/`](../adr/README.md)입니다.

| 파일 | 용도 |
|------|------|
| [`product.md`](product.md) | 모든 PDCC 작업에 먼저 넣는 제품 불변식 |
| [`implement-slice.md`](implement-slice.md) | 한 장의 티켓·버그를 구현할 때 |
| [`completed-m0-m4.md`](completed-m0-m4.md) | 이미 끝난 M0–M4. 다시 뼈대를 만들지 말 것 |

새 슬라이스를 맡길 때 권장 순서:

1. `product.md` 전문
2. `completed-m0-m4.md`에서 중복 여부 확인
3. 관련 ADR
4. `implement-slice.md` + 이번 티켓 본문
