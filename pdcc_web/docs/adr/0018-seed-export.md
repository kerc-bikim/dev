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
5. ObsPy 경로는 FDSN SEED Manual V2.4 dataless를 쓴다. Volume(B010 2.4 + B011), Abbreviation(B030/B033/B034, 코멘트면 B031), Station(B050/B052와 응답 B053·B054·B057·B058·B061). Time Span·데이터 레코드는 쓰지 않는다. 네트워크 코드는 2자, 디지털 단계는 B057, 채널마다 B058 stage 0이 없으면 거절한다. ASCII 코멘트는 B051/B059로 넣는다.

통과 시나리오: **S6**. 검증: `tests/test_seed_v24.py`.
