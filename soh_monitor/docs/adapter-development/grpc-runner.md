# 외부 Adapter Runner (gRPC) 설계

제조사 SDK 가 프로세스를 죽이면 수집 루프 전체가 멈춘다. 그 위험을 Adapter 프로세스
밖으로 밀어 내는 것이 이 구조의 목적이다. MVP 는 구현하지 않고 **계약만** 확정한다.

## 왜 같은 프로세스에 두면 안 되나

- 네이티브 SDK 는 SIGSEGV 를 낼 수 있다. Python `except` 가 잡지 못한다.
- 스레드를 잡아먹는 블로킹 호출이 한 장비를 넘어 스케줄러 Tick 을 막는다.
- 라이선스·의존성 충돌이 중앙 이미지 전체를 잠근다.

그래서 제조사 SDK 는 **별도 프로세스**에서만 로드한다. 수집기는 그 프로세스에
gRPC 로 `Collect` 를 보내고, 응답을 `PollResult` 로 옮긴다.

## 프로세스 경계

```
collector / edge-agent
    │  gRPC Collect(DeviceContext)
    ▼
adapter-runner (제조사 SDK 격리)
    │  Transport (HTTP / SNMP / 전용)
    ▼
기록계
```

Runner 가 죽거나 시간 초과하면 수집기는 예외를 삼키고

```
PollResult(success=False, error_code=ADAPTER_ERROR)
```

만 남긴다. 한 장비의 SDK 오류가 다른 장비 수집을 멈추지 않는다.

## 서비스 계약 (초안)

```
service RecorderAdapterRunner {
  rpc Collect (CollectRequest) returns (CollectReply);
  rpc Probe (CollectRequest) returns (IdentityReply);
  rpc TestConnection (CollectRequest) returns (ConnectionReply);
}
```

- 요청에는 장비 id, 접속 설정, 자격증명 참조(값 아님)만 실는다.
- 응답 본문은 표준 Metric 샘플과 Capability 다. 제조사 원본 필드명은 넘어오지 않는다.
- Deadline 은 장비 `request_timeout_ms` 와 같다. 초과는 `REQUEST_TIMEOUT` 이다.
- Runner 프로세스가 내려가면 수집기는 재기동을 기다리지 않고 이번 Tick 을 실패로 기록한다.

## Adapter 쪽 구현 위치

`backend/app/adapters/transport/stub.py` 의 `GrpcStubTransport` 가 자리만 차지한다.
실제 Runner 를 붙일 때는 이 Transport 만 갈아끼운다. `collector/scheduler.py` 와
`collector/runner.py` 는 그대로 둔다.

## 검증

M11 시험이 이미 확인하는 것:

1. 수집 계층은 `app.adapters.transport` 를 import 하지 않는다.
2. Transport 가 `RuntimeError` 를 던져도 Adapter `collect()` 는 `PollResult` 를 반환한다.
3. 새 제조사 등록은 Registry 한 줄이다.

SDK 가 있는 실장비를 붙일 때 Runner 바이너리와 proto 를 이 문서의 서비스 이름에 맞춘다.
