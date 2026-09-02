#!/usr/bin/env bash
# M0-01 기동 확인. API_BASE 기본 http://127.0.0.1:8080, WEB_BASE 기본 http://127.0.0.1:3000
set -euo pipefail

API_BASE="${API_BASE:-http://127.0.0.1:8080}"
WEB_BASE="${WEB_BASE:-http://127.0.0.1:3000}"

echo "== GET ${API_BASE}/health"
health="$(curl -sfS "${API_BASE}/health")"
echo "$health"
python3 -c 'import json,sys; d=json.loads(sys.argv[1]); assert d=={"ok":True,"db":True,"redis":True}, d' "$health"

echo "== POST stub login"
login="$(curl -sfS -c /tmp/pdcc-cookies.txt -H 'Content-Type: application/json' \
  -d '{"username":"stub","password":"stub"}' "${API_BASE}/api/login")"
echo "$login"
python3 -c 'import json,sys; d=json.loads(sys.argv[1]); assert d["username"]=="stub" and d["role"]=="editor"' "$login"

echo "== GET /api/me"
me="$(curl -sfS -b /tmp/pdcc-cookies.txt "${API_BASE}/api/me")"
echo "$me"

echo "== admin login should be 403"
code="$(curl -sS -o /tmp/pdcc-admin.json -w '%{http_code}' -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"admin"}' "${API_BASE}/api/login")"
echo "status=$code $(cat /tmp/pdcc-admin.json)"
test "$code" = "403"

echo "== GET ${WEB_BASE}/"
curl -sfS -o /tmp/pdcc-index.html -w 'web_status=%{http_code}\n' "${WEB_BASE}/"
grep -q 'id="root"' /tmp/pdcc-index.html

echo "== GET ${WEB_BASE}/api/health (proxy)"
proxy="$(curl -sfS "${WEB_BASE}/api/health")"
echo "$proxy"
python3 -c 'import json,sys; d=json.loads(sys.argv[1]); assert d["ok"] is True' "$proxy"

echo "M0-01 verify OK"
