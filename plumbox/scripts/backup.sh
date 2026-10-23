#!/usr/bin/env bash
set -euo pipefail
if [[ "${EUID}" -ne 0 ]]; then
  exec sudo bash "$0" "${1:-$HOME/plumbox-backup-$(date +%Y%m%d-%H%M%S).tar.gz}"
fi
TARGET="${1:-$HOME/plumbox-backup-$(date +%Y%m%d-%H%M%S).tar.gz}"
TARGET="$(realpath -m -- "$TARGET")"
case "$TARGET" in /etc/plumbox/*|/var/lib/plumbox/*|/opt/plumbox/*)
  echo "Kopia musi być zapisana poza katalogami archiwizowanymi."; exit 1;;
esac
was_running=false
if systemctl is-active --quiet plumbox; then was_running=true; fi
restart_service() { if "$was_running"; then systemctl start plumbox; fi; }
trap restart_service EXIT
if "$was_running"; then systemctl stop plumbox; fi
# Zatrzymana usługa zapewnia spójny zestaw SQLite, WAL, kont i konfiguracji.
umask 077
tar -C / -czf "$TARGET" etc/plumbox var/lib/plumbox opt/plumbox
echo "Utworzono kompletną kopię: $TARGET"
