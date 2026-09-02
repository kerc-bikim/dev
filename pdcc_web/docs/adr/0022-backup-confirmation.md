# ADR 0022. 백업 성공 확인

상태: 채택  
코드: `apps/api/app/dashboard.py`, `infra/backup-postgres.sh`, `docs/restore.md`

## 결정

1. 관리자는 `/admin` 대시보드에서 마지막으로 검증된 PostgreSQL 백업 성공 시각을 본다.
2. 백업 작업은 custom-format 덤프 생성과 `pg_restore --list` 검증이 모두 성공한 뒤에만
   ISO 8601 UTC 시각을 표식 파일에 원자적으로 기록한다.
3. API는 `BACKUP_STATUS_FILE`을 읽는다. 설정하지 않으면
   `${DATA_DIR}/backup-last-success`를 사용한다. 파일이 없거나 값이 잘못되면 성공으로
   추정하지 않고 `확인 기록 없음`을 표시한다.
4. 백업 시각은 기존 관리자 대시보드의 세 가지 빨간 배지 조건을 늘리지 않는다.
5. PostgreSQL 전체 복구, Compose 복구, `/data`의 선택적 NRL zip 복구와 복구 후 검증은
   `docs/restore.md`를 따른다.

통과: **M4-04** 관리자에게 마지막 백업 성공 시각이 보이고 운영자가 문서만으로 복구 절차를
수행할 수 있다.
