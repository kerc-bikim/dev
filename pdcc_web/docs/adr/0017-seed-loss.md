# ADR 0017. SEED 변환 손실 표

상태: 채택  
코드: `apps/api/app/inventory/seed_loss.py`, `apps/web/src/editor/SeedLossDialog.tsx`

## 맥락

dataless SEED는 코멘트 70자, FIR 이름 25자로 잘리고 Identifier·확장 필드는 빠진다. S6는 이 목록을 본 뒤에만 변환을 시작한다.

## 결정

1. `GET /api/projects/{id}/export/seed-loss` 가 초안(있으면) 또는 서버 XML을 훑어 잘림·제거 행을 돌려준다. 안내는 네 문장을 항상 붙인다.
2. `POST /export/seed?loss_ack=` 는 같은 XML의 ack 토큰이 있을 때만 진행한다. 없으면 `409 E_LOSS_ACK` 와 표를 돌려준다. 검증 오류는 기존처럼 `409 E_UNVALIDATED` 가 먼저다.
3. 편집기 `dataless SEED` 는 확인 창을 연다. `손실 목록 보기` 뒤에만 `확인 후 내보내기` 가 켜진다.

통과 시나리오: **S6** (잘림 목록). 실제 SEED 파일은 M3-04.
