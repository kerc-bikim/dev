# Adapter 개발 안내

새 기록계를 붙이는 작업의 전부는 **Adapter 구현체 하나와 Manifest 하나**를 만드는 일이다.
수집 스케줄러, DB 스키마, 공통 화면, 공통 Grafana 대시보드는 손대지 않는다.

Centaur CTR(`backend/app/adapters/centaur_ctr/`)이 첫 번째 구현체이며 참고 기준이다.
확장성 검증용 두 번째 구현체는 `backend/app/adapters/mock_recorder/` 다. 필드명·상태
문자열·단위가 CTR 과 다르다. 이 Adapter 를 추가할 때 수집기·DB·공통 Grafana 는
한 줄도 바꾸지 않았다.

## 파일 구성

```
backend/app/adapters/<vendor_model>/
├─ manifest.json      자기 선언. 등록 화면이 이것으로 입력 폼을 만든다
├─ client.py          통신과 실패 분류
├─ parser.py          제조사 응답 → {채널 이름: 원값}
├─ mapper.py          채널 → 표준 Metric (단위·상태 변환)
├─ capabilities.py    기능 지원 상태 판정
├─ adapter.py         RecorderAdapter 구현
└─ testdata/          실장비 응답 Fixture (real-*) 와 가상 응답 (synthetic-*)
```

## 반드시 지켜야 하는 것

계약 위반은 문서가 아니라 테스트로 막혀 있다. 아래를 어기면 등록이나 시험이 실패한다.

1. **예외를 밖으로 던지지 않는다.** 실패는 `PollResult(success=False)` 와 `PollErrorCode` 로
   표현한다. 한 장비의 예외가 수집 루프를 멈추면 안 된다.
2. **모르는 상태 문자열은 `OK` 가 아니다.** `UNKNOWN` 으로 떨어뜨리고 원문을
   `unmapped_values` 에 남긴다. 새 펌웨어가 새 문자열을 내보낼 때 정상으로 오인하면
   장애를 놓친다.
3. **값이 없으면 0 으로 채우지 않는다.** `UNSUPPORTED`(장비에 기능이 없음) /
   `UNKNOWN`(값을 알 수 없음) / `ERROR` 중 하나로 표시한다.
4. **미지원과 확인 불가를 구분한다.** SD 슬롯이 없는 모델은 `UNSUPPORTED`,
   슬롯은 있으나 카드가 없으면 값은 `UNKNOWN` 이고 기능은 `SUPPORTED_ENABLED` 다.
5. **포트가 있는데 채널만 없으면 `UNSUPPORTED` 가 아니라 `UNKNOWN`** 이다.
   없는 기능으로 단정하면 실제 이상을 감시에서 빼 버린다.
6. **단위를 무시하지 않는다.** 응답이 알려 준 단위를 우선하고, 없을 때만 매뉴얼 기준
   단위를 쓴다. 상수로 나누면 펌웨어가 단위를 바꿨을 때 1000배 틀린 값이 조용히 쌓인다.
7. **옮기지 못한 채널 이름을 버리지 않는다.** `unknown_channels` 에 남긴다.
   새 펌웨어가 채널을 추가했다는 신호다.
8. **등록값과 실제 장비가 다르면 수집을 거부한다.** 다른 관측소 데이터가 섞이면
   되돌릴 수 없다.
9. **비밀값을 결과·로그·미리보기에 남기지 않는다.** `redact()` 를 구현하고
   `manifest.configurationSchema.secretFields` 를 실제 필드와 일치시킨다.
10. **표준 Metric 키에 제조사 이름을 쓰지 않는다.** 제조사 고유 정보는 `vendor.*` 로 둔다.
    `scripts/check_naming.py` 가 검사한다.

## 추가 절차

1. 제조사 API/프로토콜 문서 확보와 실응답 샘플 채집
2. `contracts/metrics/catalog.yaml` 에 없는 Metric 이 필요하면 카탈로그부터 확장
   (`make contracts` 로 생성물 재생성)
3. `contracts/metrics/status-mappings.yaml` 에 상태 문자열 Mapping 추가
4. `manifest.json` 작성 — `capabilities` 와 `providedMetrics` 는 계약에 있는 키만 쓸 수 있다
5. `parser.py` / `mapper.py` / `capabilities.py` / `adapter.py` 구현
6. `testdata/` 에 Fixture 추가
7. `app/adapters/registry.py` 의 `get_registry()` 에 등록
8. 계약 시험 통과 — 정상, 느린 응답, 연결 실패, 인증 실패, 비정상 JSON, 필드 누락,
   모델 차이, 상태 미등록 값, 신원 불일치
9. 제조사 전용 Grafana 대시보드는 `scripts/gen_grafana.py` 에 패널을 추가한 뒤
   생성한다. 공통 대시보드(`01`·`02`·`04`–`07`)에는 `vendor.*` 를 넣지 않는다.

## 가상 기록계로 시험하기

실장비 없이 Adapter 를 압박할 수 있다. 가상 서버는 `mock/centaur_mock/` 에 있다.

```bash
make mock          # http://127.0.0.1:8090
curl -s "http://127.0.0.1:8090/_mock/devices" | python -m json.tool
curl -s "http://127.0.0.1:8090/_mock/scenarios" | python -m json.tool

# 시나리오를 도중에 바꾼다
curl -X POST http://127.0.0.1:8090/_mock/devices/centaur-6__0242/scenario \
  -H 'Content-Type: application/json' \
  -d '{"payloadScenario":"GPS_UNLOCKED"}'

# 특정 채널 값을 고정한다 (임계값 경계 시험)
curl -X POST http://127.0.0.1:8090/_mock/devices/centaur-6__0242/values \
  -H 'Content-Type: application/json' \
  -d '{"values":{"powerSupply/voltage":11.4}}'
```

단위 시험에서는 HTTP 를 띄우지 않고 ASGI 전송으로 붙는다.

```python
from httpx import ASGITransport
from mock.centaur_mock.server import create_app
adapter = CentaurCtrAdapter(transport=ASGITransport(app=create_app(registry)))
```

주의: httpx 의 ASGI 전송은 **Timeout 을 적용하지 않는다.** 같은 프로세스에서 앱을 직접
await 하기 때문이다. 그래서 Timeout 분류는 예외를 주입해 확인하고, 실제 회선에서의
Timeout 은 실 HTTP 로 확인한다.

## 가상 서버가 계약이 되지 않게 하는 장치

가상 서버를 정교하게 만들면 Adapter 가 우리 상상에 맞춰 완성되고, 실장비를 붙이는 순간
드러난다. 그래서 응답 형식의 권위는 `testdata/real-*.json` 이다. 실장비 Fixture 가 하나라도
들어오면 `test_실응답과_가상서버_기준선이_어긋나지_않는다` 가 켜져 채널 집합을 대조한다.

Centaur CTR 의 경우 매뉴얼에 응답 본문 예시가 없어 형태 추측이 `mock/centaur_mock/envelope.py`
한 파일에 갇혀 있다. 실응답을 확보하면 그 파일과 `parser.py` 만 고친다.

## 데이터 연속성 검사

기록계 SOH 의 센서 상태는 파형 정지를 잡지 못한다. `acquisition.*` 는 SeedLink/FDSN
availability 로 **SOH 와 따로** 산출한다. 구현은 `backend/app/adapters/data_availability/` 다.

- 관측소에 데이터 서버 URI 가 없으면 capability 는 `UNSUPPORTED` 이고 값을 만들지 않는다.
- URI 가 있으면 HTTP/FDSN JSON 을 읽고 채널별 경과·공백·활성을 표준 Metric 으로 옮긴다.
- SeedLink(`seedlink://host:port` 또는 `seedlink://host:port/NET_STA`) 는 HELLO 뒤
  `INFO STREAMS` XML 을 읽어 채널 끝 시각을 만든다. DATA 스트림은 열지 않는다.
- 이 검사가 실패해도 SOH `PollResult.success` 를 뒤집지 않는다.

## Transport

통신 프로토콜 교체는 Adapter 내부에 한정한다. 수집기는 HTTP 인지 SNMP 인지 모른다.

```
backend/app/adapters/transport/
├─ http.py     JSON GET. Bearer 토큰만 다룬다
├─ stub.py     SNMP·gRPC 자리. 실제 OID/SDK 호출은 없다
└─ base.py     TransportResult. 실패도 예외가 아니다
```

제조사 고유 인증(예: Centaur 세션 MD5)은 해당 Adapter `client.py` 에 남긴다.
공통 Transport 에 제조사 절차를 넣지 않는다.

SNMP 나 전용 SDK 가 필요하면 stub 을 실제 호출로 바꾸되, 예외는 반드시
`TransportResult` / `PollResult(success=False)` 로 가둔다. 프로세스 격리 설계는
[외부 Adapter Runner](adapter-development/grpc-runner.md) 를 따른다.

## 가상 제조사로 확장성을 확인하는 방법

```bash
# Registry 에 acme.mock.recorder 가 보인다
curl -s http://127.0.0.1:8000/api/v1/adapters | python -m json.tool
```

관측소 등록 화면에서 ACME Mock Recorder 를 고르면 센서·외부 SOH 탭이
**미지원**으로 표시된다. Manifest 에 없는 capability 는 빈 표로 남지 않는다.

Gen5 착수 전에 조사할 항목은 [Gen5 체크리스트](gen5-checklist.md) 다.
