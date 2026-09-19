# Centaur Gen5 착수 체크리스트

CTR Adapter 를 복사해 필드명만 바꾸면 실패한다. Gen5(StrataOS) 는 인증·경로·채널
집합이 다를 가능성이 크다. 아래를 조사한 뒤에 `adapters/centaur_gen5/` 를 만든다.

## 조사 항목

| ID | 항목 | 확인할 것 | 메모 |
|----|------|-----------|------|
| G5.1 | SOH 엔드포인트 | 경로가 `/api/v1/instruments/soh` 와 같은지, 새 REST/gRPC 인지 | |
| G5.2 | 인증 | 세션 쿠키 + MD5 가 남는지, 토큰/mTLS/OIDC 로 바뀌었는지 | CTR 의 `CentaurClient._authenticate` 를 재사용하지 말 것 |
| G5.3 | 응답 봉투 | 채널 배열 / 맵 / 평평한 객체. 실응답을 `testdata/real-*.json` 에 저장 | |
| G5.4 | 상태 문자열 | `OK/WARNING` 이 유지되는지, 새 코드가 있는지 | 모르면 `UNKNOWN` + 원문 |
| G5.5 | 단위 | 전압·전류·온도 단위가 V/A/°C 인지 mV 등인지 | 응답 `units` 우선 |
| G5.6 | Instrument ID | `centaur-6__0242` 형식이 유지되는지 | 신원 불일치 비교에 필요 |
| G5.7 | 센서 포트 | 3/6채널, Mass Position 축 이름 | 없는 포트는 `UNSUPPORTED` |
| G5.8 | 저장소 | 내부 스토어 + 착탈 매체 채널 | 슬롯 없음 ≠ 카드 없음 |
| G5.9 | 외부 SOH | 아날로그 채널 수 | 없으면 capability 미선언 |
| G5.10 | TLS | 기본 HTTPS 여부, 사설 CA | `tlsVerify` + 관측소망 CA |
| G5.11 | 펌웨어  rev | 지원 최소 버전, 채널 추가 이력 | |
| G5.12 | 라이선스/SDK | HTTP 만으로 충분한지, 전용 SDK 가 필수인지 | SDK 면 [gRPC Runner](adapter-development/grpc-runner.md) |

## 예상 신규 Metric

카탈로그에 없는 값이 필요하면 Adapter 보다 **카탈로그를 먼저** 확장한다.
지금 시점에서 Gen5 전용으로 보이는 후보는 아래다. 실응답이 오기 전에는 키를 만들지 않는다.

| 후보 | 이유 | 처리 |
|------|------|------|
| 신규 GNSS 품질 채널 | StrataOS 가 위성 체계를 분리 보고할 수 있음 | 실응답 확인 후 `gnss.*` 확장 |
| 내부 버스/버퍼 | CTR 전용 `vendor.nanometrics.centaur.*` 와 키가 다를 수 있음 | `vendor.nanometrics.gen5.*` 로 가두고 공통 대시보드에 넣지 않음 |
| 전원 경로 분리 | PoE / 배터리 이중화 | 표준 `power.*` 로 수용 가능하면 새 키를 만들지 않음 |

## 구현 순서

1. 이 표의 G5.1–G5.6 을 실장비 또는 제조사 문서로 채운다.
2. `contracts/metrics/status-mappings.yaml` 에 `nanometrics.centaur.gen5` 섹션을 추가한다.
3. `backend/app/adapters/centaur_gen5/` 를 [Adapter 개발 안내](adapter-development.md) 대로 작성한다.
4. `get_registry()` 에 한 줄 등록한다. 수집기·DB·공통 Grafana 는 손대지 않는다.
5. 전용 상세 패널이 필요하면 `scripts/gen_grafana.py` 에 `08-centaur-gen5-detail` 만 추가한다.

## 하지 말 것

- CTR parser 에 `if generation == "gen5"` 분기를 넣지 않는다.
- `device_capabilities` 외에 Gen5 전용 테이블을 만들지 않는다.
- 공통 대시보드 Flux 에 `vendor.nanometrics` 를 넣지 않는다.
- 조사 전에 카탈로그에 추정 Metric 을 넣지 않는다.
