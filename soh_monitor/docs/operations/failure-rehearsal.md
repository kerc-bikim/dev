# 장애 시나리오 리허설 12종

각 항목은 구현된 시험이 실제로 돈다. 이름만 있는 점검표가 아니다.

| ID | 상황 | 기대 | 시험 |
|----|------|------|------|
| `central_disconnect` | 중앙이 끊김 | Edge 는 로컬 수집을 계속하고 Spool 이 는다 | `tests/unit/test_edge_agent.py` |
| `edge_restart` | Edge 재시작 | 마지막 설정으로 수집을 이어 간다 | `tests/unit/test_edge_agent.py` |
| `spool_full` | 디스크/Spool 한도 | ACK 분부터 지우고 장애 Poll 은 최후 | `tests/unit/test_edge_agent.py` |
| `duplicate_batch` | 같은 Batch 재전송 | Point 수가 늘지 않는다 | `tests/unit/test_edge_ingest.py` |
| `certificate_revoke` | 인증서 폐기·불일치 | Agent 요청 403 | `tests/unit/test_edge_ingest.py` |
| `influx_outage` | Influx 쓰기 실패 | 수집은 계속, 버퍼에 보관, 복구 후 전송 | `tests/integration/test_collector.py` |
| `slow_device` | 느린 장비 20% | 다른 장비 주기를 막지 않는다 | `tests/integration/test_collector.py`, `tests/load/test_soak.py` |
| `recorder_offline` | 기록계 무응답 3회 | 해당 장비만 CRITICAL | `tests/integration/test_health_service.py` |
| `timing_unlock` | GPS Unlock | 시각 분류 장애. UNKNOWN 과 구분 | `tests/integration/test_health_service.py` |
| `recording_stopped` | 저장소 가득/기록 중단 | storage CRITICAL, 복구 시 닫힘 | `tests/integration/test_health_service.py` |
| `edge_heartbeat_miss` | Heartbeat 2·3회 누락 | Edge 장애 1건, 하위 UNKNOWN 억제 | `tests/unit/test_edge_watch.py` |
| `delayed_backfill` | 하루 늦은 Poll | 시계열은 관측 시각, 현재 상태는 되돌리지 않음 | `tests/unit/test_edge_ingest.py` |

## 운영 리허설 순서

1. `make test` — 위 12종이 포함된 백엔드 시험
2. `make soak devices=100 ticks=3` — 100대, 느린 장비 20%, Influx 중단 구간
3. Compose 가 있는 곳에서 중앙을 끄고 Edge 가 Spool 을 쌓는지, 다시 켜면 업로드되는지 확인
4. Grafana `Influx Write Failure` 가 noData 로 우는지 확인 (Influx 를 잠시 정지)

결과 기록은 [`pilot-log.md`](pilot-log.md) 에 남긴다.
