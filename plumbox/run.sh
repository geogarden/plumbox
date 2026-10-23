#!/usr/bin/with-contenv bash
set -Eeuo pipefail
export PYTHONPATH=/opt/plumbox
export PLUMBOX_CONFIG=${PLUMBOX_CONFIG:-/data/config.yaml}
export PLUMBOX_USERS=${PLUMBOX_USERS:-/data/users.yaml}
export PLUMBOX_INITIAL_ADMIN_PASSWORD_FILE=${PLUMBOX_INITIAL_ADMIN_PASSWORD_FILE:-/data/initial_admin_password.txt}
export PLUMBOX_INITIAL_PIN_FILE=${PLUMBOX_INITIAL_PIN_FILE:-/data/initial_pin.txt}
export PATH=/opt/plumbox/.venv/bin:$PATH
mkdir -p /data
python3 /opt/plumbox/addon_init.py
exec python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8080 --proxy-headers
