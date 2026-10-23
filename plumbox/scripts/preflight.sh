#!/usr/bin/env bash
set -euo pipefail

echo
echo "============================================================"
echo " PlumBox — kontrola urządzenia i systemu"
echo "============================================================"
echo

ARCH="$(uname -m)"
OS_ID="unknown"
OS_NAME="unknown"
OS_VERSION="unknown"

if [[ -r /etc/os-release ]]; then
  # shellcheck disable=SC1091
  source /etc/os-release
  OS_ID="${ID:-unknown}"
  OS_NAME="${PRETTY_NAME:-${NAME:-unknown}}"
  OS_VERSION="${VERSION_ID:-unknown}"
fi

echo "System:       ${OS_NAME}"
echo "Architektura: ${ARCH}"
echo "Kernel:       $(uname -r)"

case "${ARCH}" in
  aarch64|arm64|x86_64|amd64)
    echo "Architektura: OK"
    ;;
  armv7l|armhf)
    echo "UWAGA: system 32-bit ARM może działać, ale zalecany jest ARM64."
    ;;
  *)
    echo "BŁĄD: nieobsługiwana lub niesprawdzona architektura ${ARCH}."
    exit 1
    ;;
esac

if ! command -v systemctl >/dev/null 2>&1; then
  echo "BŁĄD: brak systemd/systemctl."
  exit 1
fi

if ! command -v apt-get >/dev/null 2>&1; then
  echo "BŁĄD: instalator natywny wymaga Debiana/Ubuntu/Armbiana z apt."
  echo "Na innym systemie użyj Dockera."
  exit 1
fi

MEM_KB="$(awk '/MemTotal/ {print $2}' /proc/meminfo)"
MEM_MB="$((MEM_KB / 1024))"
ROOT_FREE_MB="$(df -Pm / | awk 'NR==2 {print $4}')"

echo "RAM:          ${MEM_MB} MB"
echo "Wolne na /:   ${ROOT_FREE_MB} MB"

if (( MEM_MB < 700 )); then
  echo "UWAGA: mniej niż 700 MB RAM. Taka konfiguracja nie jest zalecana."
elif (( MEM_MB < 1000 )); then
  echo "UWAGA: poniżej 1 GB RAM. Panel powinien działać, ale zapas jest niewielki."
else
  echo "Pamięć RAM:   OK"
fi

if (( ROOT_FREE_MB < 1500 )); then
  echo "BŁĄD: wymagane jest co najmniej około 1,5 GB wolnego miejsca."
  exit 1
elif (( ROOT_FREE_MB < 3000 )); then
  echo "UWAGA: mało wolnego miejsca. Zalecane minimum to 3 GB."
else
  echo "Miejsce:      OK"
fi

if command -v python3 >/dev/null 2>&1; then
  PY_VERSION="$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:3])))')"
  echo "Python:       ${PY_VERSION}"
  if ! python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)'; then
    echo "UWAGA: Python jest starszy niż 3.10."
    echo "Instalator spróbuje zainstalować nowszy pakiet systemowy, ale"
    echo "najbezpieczniej użyć Debiana 12 lub Ubuntu 22.04+."
  else
    echo "Python:       OK"
  fi
else
  echo "Python:       nie jest jeszcze zainstalowany — zrobi to instalator."
fi

if [[ -e /dev/ttyUSB0 ]]; then
  echo "USB–RS485:    wykryto /dev/ttyUSB0"
else
  echo "USB–RS485:    nie wykryto /dev/ttyUSB0 (to normalne przy RS485–TCP)"
fi

echo
echo "Wynik: urządzenie nadaje się do instalacji PlumBox."
echo
