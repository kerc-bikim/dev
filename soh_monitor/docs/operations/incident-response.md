# 장애 대응

## 한 줄 원칙

- 확인(ACK)은 복구가 아니다. 보고 있다는 표시다.
- Edge 가 죽으면 하위 기록계 알림은 접힌다. Edge 한 건을 본다.
- `UNKNOWN` 은 `OK` 가 아니다. 값을 모르면 모른다.

## 우선 보기

1. 관리 Web **통합 현황** — 열린 장애 수, 지도, 지역 토폴로지
2. **장애** — `Edge 억제` 표시가 있으면 원인은 Edge
3. Grafana 함대 / 관제 화면 (`07-kiosk-overview`)

## 유형별

| 증상 | 먼저 할 일 |
|------|------------|
| Recorder Offline | 기록계 전원·회선. DIRECT 면 관측소 상세 **연결 시험**. EDGE 면 Edge 가 살아 있는지 |
| Edge Offline | 지역 서버·회선. Heartbeat 가 돌아오면 하위 UNKNOWN 이 풀린다 |
| Timing Error | GNSS 안테나·하늘. Duty Cycle 장비는 위성 수만으로 장애를 만들지 않게 프로파일을 확인 |
| Recording Stopped / Storage Critical | SD·내부 저장소. 가득 찼으면 교체. 기록 중단은 즉시 |
| Edge Spool Critical | 중앙 업로드가 막혔는지. ACK 전 삭제는 하지 않는다 |
| Influx Write Failure | Influx 컨테이너·디스크. 수집은 계속된다. 그래프만 멈춘다 |

유지보수 창은 관측소 상세 **설정** 에서 OPERATOR 가 연다. 그 시간대 알림은
억제되고 상태는 `MAINTENANCE` 다. 작업이 끝나면 **지금 닫기** 로 일찍 끝낼 수 있다.

복구 알림이 오면 장애 목록에서 RESOLVED 를 확인한다. 안 오면 Grafana 연락처 SMTP 를 본다.
