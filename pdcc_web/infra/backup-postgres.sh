#!/usr/bin/env bash
set -euo pipefail

# PostgreSQL custom-format dump를 만들고 읽기 검증이 끝난 뒤에만 성공 표식을 갱신한다.
# 사용: DATABASE_URL=postgresql://... DATA_DIR=/data ./backup-postgres.sh [backup-dir]

BACKUP_DIR="${1:-${BACKUP_DIR:-./backups}}"
STATUS_FILE="${BACKUP_STATUS_FILE:-${DATA_DIR:-/data}/backup-last-success}"
DATABASE_URL="${DATABASE_URL:?DATABASE_URL is required}"
PG_URL="${DATABASE_URL/postgresql+psycopg:\/\//postgresql:\/\/}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
FINAL="${BACKUP_DIR}/pdcc-${STAMP}.dump"

mkdir -p "$BACKUP_DIR" "$(dirname "$STATUS_FILE")"
TMP_DUMP="$(mktemp "${BACKUP_DIR}/.pdcc-${STAMP}.XXXXXX")"
TMP_STATUS="$(mktemp "$(dirname "$STATUS_FILE")/.backup-last-success.XXXXXX")"
trap 'rm -f "$TMP_DUMP" "$TMP_STATUS"' EXIT

pg_dump --dbname="$PG_URL" --format=custom --file="$TMP_DUMP"
pg_restore --list "$TMP_DUMP" >/dev/null
mv "$TMP_DUMP" "$FINAL"

date -u +%Y-%m-%dT%H:%M:%SZ >"$TMP_STATUS"
mv "$TMP_STATUS" "$STATUS_FILE"

echo "verified backup: $FINAL"
echo "success marker: $STATUS_FILE"
