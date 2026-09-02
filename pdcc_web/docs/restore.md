# PDCC 백업·복구 절차

PostgreSQL이 프로젝트 StationXML, 업로드 원본, 사용자, 버전, 작업 및 감사 로그의 원본이다.
Redis는 세션과 재생성 가능한 NRL 캐시이므로 복구 대상이 아니다. `/data`의 NRL 전체 zip도
EarthScope에서 다시 받을 수 있지만, 폐쇄망 운영이면 PostgreSQL 덤프와 별도로 보관한다.

## 백업과 성공 확인

API와 같은 `BACKUP_STATUS_FILE` 경로를 볼 수 있는 호스트 또는 백업 컨테이너에서 실행한다.
SQLAlchemy URL의 `postgresql+psycopg://` 형식도 스크립트가 `pg_dump`용으로 변환한다.

```bash
cd pdcc_web
export DATABASE_URL='postgresql+psycopg://pdcc:비밀번호@postgres:5432/pdcc'
export BACKUP_DIR=/backup/pdcc
export BACKUP_STATUS_FILE=/data/backup-last-success
infra/backup-postgres.sh
```

스크립트는 임시 파일에 custom-format 덤프를 만들고 `pg_restore --list`로 읽기 검증한 후
최종 파일로 옮긴다. 모든 단계가 성공한 경우에만 UTC 시각을
`BACKUP_STATUS_FILE`에 원자적으로 기록한다. API의 `DATA_DIR`와 다른 볼륨을 쓴다면
API에도 동일한 파일을 읽기 전용으로 마운트하고 `BACKUP_STATUS_FILE`을 설정한다.

관리자 대시보드의 **마지막 백업 성공**과 다음 명령으로 결과를 확인한다.

```bash
test -s "$BACKUP_STATUS_FILE"
pg_restore --list "$BACKUP_DIR"/pdcc-YYYYMMDDThhmmssZ.dump >/dev/null
```

`확인 기록 없음`은 파일이 없거나 ISO 8601 UTC 시각이 아닌 경우다. 실패한 백업은 기존
성공 시각을 바꾸지 않으므로, 대시보드 시각이 오래되면 백업 작업 로그를 조사한다.

## PostgreSQL 복구

1. 복구할 덤프에 `pg_restore --list`가 성공하는지 확인한다.
2. 웹과 API를 중지해 쓰기를 막는다. PostgreSQL은 계속 실행한다.
3. 현재 데이터베이스를 별도 긴급 덤프로 남긴다.
4. 대상 덤프를 복원한다.
5. API와 웹을 기동하고 헬스, 로그인, 프로젝트 목록과 StationXML 다운로드를 확인한다.

```bash
export DATABASE_URL='postgresql://pdcc:비밀번호@127.0.0.1:5432/pdcc'
pg_restore --list /backup/pdcc/pdcc-YYYYMMDDThhmmssZ.dump >/dev/null

pg_dump --dbname="$DATABASE_URL" --format=custom \
  --file="/backup/pdcc/pre-restore-$(date -u +%Y%m%dT%H%M%SZ).dump"
pg_restore --dbname="$DATABASE_URL" --clean --if-exists --no-owner \
  /backup/pdcc/pdcc-YYYYMMDDThhmmssZ.dump

curl -fsS http://127.0.0.1:8080/health
```

Compose 배포는 API와 웹만 중지한 뒤 같은 절차를 PostgreSQL 컨테이너에서 수행할 수 있다.
덤프 파일은 표준 입력으로 전달해 컨테이너에 영구 복사본을 남기지 않는다.

```bash
docker compose -f infra/docker-compose.yml stop web api
docker compose -f infra/docker-compose.yml exec -T postgres \
  pg_restore -U pdcc -d pdcc --clean --if-exists --no-owner \
  < /backup/pdcc/pdcc-YYYYMMDDThhmmssZ.dump
docker compose -f infra/docker-compose.yml start api web
```

복구 자체는 백업 성공이 아니므로 `backup-last-success`를 갱신하지 않는다. 복구 검증 후 새
백업을 한 번 성공시켜 새로운 복구 기준점과 대시보드 시각을 만든다.

## `/data` 복구

폐쇄망 때문에 NRL zip을 별도 보관했다면 API가 중지된 동안 원래
`NRL_OFFLINE_ZIP` 경로에 복사하고 소유권과 읽기 권한을 확인한다. 이 파일이 없어도
PostgreSQL 복구 데이터는 손상되지 않으며, 관리자가 온라인에서 전체 zip을 다시 받을 수 있다.
