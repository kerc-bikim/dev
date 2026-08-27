# ADR 0010. 공식 validator 와 `_unvalidated` XML

상태: 채택  
코드: `apps/api/app/inventory/validator.py`, `apps/web/src/editor/`

## 결정

1. 즉시 검사(`E_LAT`, `W_NO_RESPONSE` 등)와 공식 번호(410, 412, …)를 섞지 않는다. `GET /issues` 기본은 즉시 검사, `POST /validate` 와 `?mode=full` 이 공식 규칙을 돌린다.
2. `infra/jars/` 에 JAR 가 없거나 `VALIDATOR_JAR` 가 비어 있으면 Python 이 같은 번호를 붙인다. JAR 가 있으면 sidecar 결과를 합친다.
3. StationXML 은 오류가 있어도 내려받는다. 파일명은 `{network}_unvalidated.xml`. dataless SEED 는 오류가 있으면 `409 E_UNVALIDATED`.
4. 검사 패널에서 412 를 누르면 채널 **감도** 칸(`data-field="sensitivity"`)으로 이동한다.

통과 시나리오: **S5**.
