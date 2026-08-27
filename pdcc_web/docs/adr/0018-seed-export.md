# ADR 0018. dataless SEED 내보내기

상태: 채택  
코드: `apps/api/app/inventory/seed_write.py`, `apps/api/app/inventory/seed_convert.py`, `apps/api/app/jobs/service.py`, `apps/web/src/jobs/JobBell.tsx`

## 맥락

M3-09가 잘림 표를 보여 준 뒤 `POST /export/seed` 는 501이었다. S6는 그 확인 뒤에 실제 dataless 파일이 나와야 한다. 공식 converter JAR가 없는 배포가 기본이다.

## 결정

1. `loss_ack` 가 맞고 검증 오류가 없으면 내보내기 직전 버전 스냅샷을 만들고 `jobs.kind=dataless` 를 Redis 큐에 넣는다. HTTP는 `queued` 를 바로 반환한다.
2. 워커가 StationXML 스냅샷을 dataless로 변환한다. `SEED_CONVERTER_JAR` 가 있으면 공식 converter, 없으면 ObsPy xseed 블록ette. Blockette 10 `--organization` 은 프로젝트 `operator`, `--label` 은 네트워크 코드다.
3. 산출물은 `file_assets(kind=job_export)` 에 두고 `GET /api/jobs/{id}/download` 로 받는다. 파일명 예: `YZ.TEST1.20260410.dataless`. 조회자는 403.
4. 같은 `id`·`version_id`·`xml_snapshot` 재시도(M3-10)가 SEED에도 적용된다.

통과 시나리오: **S6**.
