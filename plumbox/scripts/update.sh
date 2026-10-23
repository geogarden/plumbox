#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Uruchom jako root: sudo ./scripts/update.sh"
  exit 1
fi

SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_DIR="/opt/plumbox"

"${SOURCE_DIR}/scripts/preflight.sh"

if [[ ! -d "${INSTALL_DIR}" ]]; then
  echo "Nie znaleziono istniejącej instalacji w ${INSTALL_DIR}."
  echo "Użyj: sudo ./scripts/install.sh"
  exit 1
fi

was_running=false
if systemctl is-active --quiet plumbox; then was_running=true; fi
recover_service() {
  status=$?
  if [[ $status -ne 0 ]] && "$was_running"; then
    echo "Aktualizacja nieudana. Próbuję przywrócić działanie PlumBox." >&2
    if ! systemctl start plumbox; then
      echo "Nie udało się uruchomić usługi. Przywróć kopię zapasową." >&2
    fi
  fi
  return "$status"
}
trap recover_service EXIT
# Complete backup before changing installed code or dependencies.
"${SOURCE_DIR}/scripts/backup.sh" "/root/plumbox-before-update-$(date +%Y%m%d-%H%M%S).tar.gz"
systemctl stop plumbox

rsync -a --delete \
  --exclude '.venv' \
  --exclude '__pycache__' \
  --exclude 'config/config.yaml' \
  "${SOURCE_DIR}/" "${INSTALL_DIR}/"

"${INSTALL_DIR}/.venv/bin/python" -m pip install --upgrade pip wheel setuptools
"${INSTALL_DIR}/.venv/bin/pip" install -r "${INSTALL_DIR}/requirements.txt"

chown -R plumbox:plumbox "${INSTALL_DIR}"
chmod +x "${INSTALL_DIR}/scripts/"*.sh "${INSTALL_DIR}/scripts/"*.py

systemctl daemon-reload
systemctl start plumbox
sleep 2

curl --fail --silent http://127.0.0.1:8080/api/health >/dev/null

echo "Zaktualizowano PlumBox. Konfiguracja i baza danych pozostały bez zmian."
echo "Panel: http://$(hostname -I | awk '{print $1}'):8080"
