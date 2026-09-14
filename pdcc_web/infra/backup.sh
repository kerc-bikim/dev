#!/usr/bin/env bash
set -euo pipefail
# StationXML 프로젝트 ZIP 스냅샷. 로그인 쿠키 또는 계정 필요.
# 사용: backup.sh [api_base] [out.zip]
API_BASE="${1:-http://127.0.0.1:8080}"
OUT="${2:-pdcc-stationxml-$(date -u +%Y%m%dT%H%M%SZ).zip}"
COOKIE="${PDCC_COOKIE_JAR:-/tmp/pdcc.jar}"

if [[ ! -s "$COOKIE" ]]; then
  USER="${PDCC_USER:-stub}"
  PASS="${PDCC_PASSWORD:-stub}"
  curl -sS -c "$COOKIE" -X POST "$API_BASE/api/login" \
    -H "Content-Type: application/json" \
    -d "{\"username\":\"$USER\",\"password\":\"$PASS\"}" >/dev/null
fi

curl -sS -f -b "$COOKIE" -o "$OUT" "$API_BASE/api/ops/backup"
echo "wrote $OUT"
