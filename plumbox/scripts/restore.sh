#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 || ! -f "$1" ]]; then
  echo "Użycie: sudo ./scripts/restore.sh plumbox-backup.tar.gz"
  exit 1
fi
if [[ "${EUID}" -ne 0 ]]; then
  echo "Uruchom jako root."
  exit 1
fi

# Reject absolute paths, parent traversal and entries outside PlumBox locations.
while IFS= read -r entry; do
  clean="${entry#./}"
  if [[ "$entry" == /* || "$clean" == *"../"* || ! "$clean" =~ ^(etc/plumbox|var/lib/plumbox|opt/plumbox)(/|$) ]]; then
    echo "Niebezpieczna lub obca ścieżka w archiwum: $entry"
    exit 1
  fi
done < <(tar -tzf "$1")

systemctl stop plumbox 2>/dev/null || true
tar -xzf "$1" -C /
chown -R plumbox:plumbox /opt/plumbox /var/lib/plumbox
chown -R root:plumbox /etc/plumbox
find /etc/plumbox -type d -exec chmod 2770 {} +
find /etc/plumbox -type f -exec chmod 660 {} +
[[ ! -e /etc/plumbox/users.yaml ]] || chmod 660 /etc/plumbox/users.yaml
[[ ! -e /etc/plumbox/initial_admin_password.txt ]] || chmod 640 /etc/plumbox/initial_admin_password.txt
systemctl daemon-reload
systemctl enable --now plumbox

echo "Przywrócono PlumBox wraz z użytkownikami."
