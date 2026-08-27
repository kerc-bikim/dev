#!/usr/bin/env bash
set -euo pipefail
# ZIP 또는 StationXML을 새 프로젝트로 가져온다.
# 사용: restore.sh snapshot.zip [api_base]
FILE="${1:?usage: restore.sh snapshot.zip [api_base]}"
API_BASE="${2:-http://127.0.0.1:8080}"
COOKIE="${PDCC_COOKIE_JAR:-/tmp/pdcc.jar}"

if [[ ! -s "$COOKIE" ]]; then
  USER="${PDCC_USER:-stub}"
  PASS="${PDCC_PASSWORD:-stub}"
  curl -sS -c "$COOKIE" -X POST "$API_BASE/api/login" \
    -H "Content-Type: application/json" \
    -d "{\"username\":\"$USER\",\"password\":\"$PASS\"}" >/dev/null
fi

CTYPE="application/zip"
case "$FILE" in
  *.xml) CTYPE="application/xml" ;;
esac

curl -sS -f -b "$COOKIE" -X POST "$API_BASE/api/ops/restore" \
  -H "Content-Type: $CTYPE" --data-binary @"$FILE"
echo
