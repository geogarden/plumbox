#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'kill ${SERVER_PID:-0} 2>/dev/null || true; rm -rf "$TMP"' EXIT

cp "${ROOT}/config/config.example.yaml" "${TMP}/config.yaml"
sed -i "s#/var/lib/plumbox/plumbox.db#${TMP}/plumbox.db#" "${TMP}/config.yaml"
export PLUMBOX_CONFIG="${TMP}/config.yaml"
export PLUMBOX_USERS="${TMP}/users.yaml"
export PLUMBOX_INITIAL_ADMIN_PASSWORD_FILE="${TMP}/initial_admin_password.txt"
export SMOKE_PASSWORD="plumbox-smoke-password"
cd "${ROOT}"
python3 -c 'import os; from pathlib import Path; from app.users import ensure_initial_admin; ensure_initial_admin(Path(os.environ["PLUMBOX_USERS"]), os.environ["SMOKE_PASSWORD"])'
python3 -m uvicorn app.main:app --host 127.0.0.1 --port 18080 >"${TMP}/server.log" 2>&1 &
SERVER_PID=$!

for _ in {1..30}; do
  curl --fail --silent http://127.0.0.1:18080/api/health >/dev/null && break
  sleep 0.2
done
curl --fail --silent -c "${TMP}/cookies" -X POST \
  --data-urlencode 'username=admin' --data-urlencode "password=${SMOKE_PASSWORD}" \
  http://127.0.0.1:18080/login >/dev/null
curl --fail --silent -b "${TMP}/cookies" http://127.0.0.1:18080/api/snapshot | python3 -m json.tool >/dev/null
echo "Smoke test OK."
