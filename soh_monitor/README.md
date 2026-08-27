# soh_monitor — 관측소 SOH 통합 모니터링

Nanometrics **Centaur CTR** 계열 기록계의 SOH를 설정한 분 주기로 수집해 InfluxDB에 적재하고, Grafana로 관측소를 통합 감시하는 시스템이다. Centaur Gen5와 타 제조사 기록계는 Adapter 추가만으로 편입한다.

현재 상태: **계획 단계.** 구현 코드는 아직 없다.

## 문서

| 파일 | 내용 |
|------|------|
| [`plan.md`](plan.md) | 확정 계획서. 아키텍처 · 표준 Metric · 데이터 모델 · Edge 설계 · 화면 · 세부 작업 마일스톤 |
| `plan.html` | `plan.md` 를 브라우저용으로 변환한 문서 |

## 요약

```
Centaur CTR ──HTTP SOH API──► Recorder Adapter ──► 표준 Metric ──► InfluxDB ──► Grafana
                                     ▲
                     DIRECT(중앙) 또는 EDGE(지역 Collector)
```

- 수집 경로는 중앙 직접 수집(`DIRECT`)과 지역 Edge Collector(`EDGE`) 두 가지이며, 같은 Adapter와 같은 표준 Metric을 쓴다.
- Edge는 중앙으로 Outbound 연결만 사용하고, 중앙 단절 시 로컬 Spool에 저장한 뒤 복구되면 원래 관측 시각으로 채워 넣는다.
- 설정·이력은 PostgreSQL, 시계열은 InfluxDB에 두고, 임계값 판정은 백엔드가 수행해 Grafana는 표준 `severity`만 감시한다.
- 제조사 원본 필드명은 Adapter 안에만 존재한다. 이것이 Gen5·타 제조사 확장 범위를 Adapter로 한정하는 근거다.

## 스택

백엔드 FastAPI · 프론트엔드 React + Vite + TypeScript · PostgreSQL · InfluxDB · Grafana · Docker Compose (이 저장소 `earthworm_web` · `stationxml_manager` 와 동일한 관례).

## 계획 문서 갱신

```bash
python soh_monitor/scripts/build_plan_html.py
```
