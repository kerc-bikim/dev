# ADR 0016. 대량 검증 작업 큐

상태: 채택  
코드: `apps/api/app/jobs/`, `apps/api/app/routers/jobs.py`, `apps/web/src/jobs/JobBell.tsx`

## 맥락

`POST /validate` 가 공식 검증을 요청 스레드에서 돌리면 큰 프로젝트에서 편집기가 멈춘다. S14는 검증이 돌아가는 동안에도 좌표·채널을 고치고, 끝나면 검사 패널만 갱신한다.

## 결정

1. **스냅샷.** `POST /api/projects/{id}/validate` 는 초안(있으면) 또는 서버 XML을 복사해 `jobs` 행을 만들고 Redis `pdcc:jobs:queue` 에 넣는다. HTTP는 `queued` 를 바로 반환한다.
2. **워커.** `python -m app.jobs.runner` 가 스냅샷을 `mode=full` 로 검사한다. 상태: `queued | running | succeeded | failed`. 진행률은 상단 배너와 작업 벨에 보인다. 이전 검사 결과는 덮어쓰지 않는다.
3. **편집 병행.** 초안 PUT 은 작업과 잠금만 공유한다. 워커는 enqueue 당시 스냅샷만 본다. 끝난 뒤 `GET /jobs/{id}` 의 `result` 로 패널을 갱신한다. 지금 XML의 즉시/공식 검사는 `GET /issues` 가 그대로 한다.
4. **재시도 (M3-10).** 실패한 작업은 같은 `id`·`version_id`·`xml_snapshot` 으로 다시 큐에 넣는다. 다른 사용자에게는 작업이 404다.

통과 시나리오: **S14**.
