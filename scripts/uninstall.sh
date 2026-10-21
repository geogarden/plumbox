#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Uruchom jako root."
  exit 1
fi

systemctl disable --now plumbox 2>/dev/null || true
rm -f /etc/systemd/system/plumbox.service
systemctl daemon-reload

echo "Usunięto usługę PlumBox."
echo "Dane pozostawiono w /var/lib/plumbox i /etc/plumbox."
echo "Aby usunąć wszystko:"
echo "  sudo rm -rf /opt/plumbox /etc/plumbox /var/lib/plumbox"
