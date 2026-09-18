# 백업과 복구

빈 서버에서 이 문서만으로 되돌릴 수 있어야 한다. 비밀 값은 묶음에 넣지 않는다.

## 무엇을 백업하는가

| 대상 | 위치 | 방법 |
|------|------|------|
| 설정 DB | PostgreSQL (운영) / SQLite (로컬) | `scripts/ops_backup.py` |
| Grafana 대시보드·알림 | `deploy/grafana/` | Git 이 원본. 묶음에 사본을 넣어 대조한다 |
| Influx 보존·다운샘플 | `deploy/influxdb/init/` | Task 파일. 시계열 원본은 `influx backup` |
| 비밀 | `secrets/` | 이름만 목록. 값은 금고 |
| TLS 키 | `certs/` | 금고. Git 금지 |

장애 이력은 PostgreSQL 에 영구 보관한다. Influx 원본은 180일, 5분 집계 2년, 1시간 집계 5년이다.

## 백업

```bash
# 로컬 SQLite
python scripts/ops_backup.py --out /var/backups/soh \
  --database sqlite:////var/lib/soh/soh.db \
  --secret-dir ./secrets

# 운영 PostgreSQL
python scripts/ops_backup.py --out /var/backups/soh \
  --database postgresql://soh@postgres/soh_monitor
```

시계열 원본은 Influx 컨테이너에서 별도로 뜬다.

```bash
docker compose -f deploy/compose/compose.central.yml exec influxdb \
  influx backup /tmp/influx-backup
```

## 복구 리허설 (빈 서버)

1. 이미지를 받고 `secrets/` 와 `certs/` 를 금고에서 채운다. 값은 백업 묶음에 없다.
2. 설정 DB 를 되돌린다.

```bash
python scripts/ops_restore.py \
  --archive /var/backups/soh/soh-backup-YYYYMMDDThhmmssZ.tar.gz \
  --database sqlite:////var/lib/soh/soh.db
```

3. Git 의 Grafana·Influx Task 를 배포한다. 묶음 사본과 UID 가 같은지 확인한다.
4. Influx 원본을 `influx restore` 한 뒤 `10-buckets.sh` 가 만든 집계 Bucket·Task 가 있는지 본다.
5. `make central-up` 후 로그인 → 관측소 목록 → Grafana 함대가 뜨는지 확인한다.

리허설 자동화: `backend/tests/unit/test_ops_contracts.py` 의 `test_빈_서버_복구_리허설`.
Docker 없는 환경에서는 SQLite 경로만 돈다. PostgreSQL·Influx 는 Compose 있는 곳에서 한 번 더 한다.

## 순환

- 설정 DB: 매일. 최근 14일 보관
- Influx: 매주. 최근 4주 보관
- 비밀: 교체할 때마다 금고 버전을 올린다. `session_secret` 을 바꾸면 모든 세션이 끊긴다
