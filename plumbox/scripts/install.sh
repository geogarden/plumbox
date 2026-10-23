#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Uruchom jako root: sudo ./scripts/install.sh"
  exit 1
fi

SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_DIR="/opt/plumbox"
CONFIG_DIR="/etc/plumbox"
DATA_DIR="/var/lib/plumbox"
USERS_FILE="${CONFIG_DIR}/users.yaml"
INITIAL_ADMIN_PASSWORD_FILE="${CONFIG_DIR}/initial_admin_password.txt"
SERVICE_FILE="/etc/systemd/system/plumbox.service"
USER_NAME="plumbox"

echo
echo "============================================================"
echo " PlumBox 2.8.0 GPTSOL10 V3 Native 6 — Orange Pi / Debian / Ubuntu / Armbian"
echo "============================================================"
echo
echo "WAŻNE: ecoMAX powinien mieć tylko jednego aktywnego klienta/mastera."
echo "Na czas testu wyłącz połączenie Home Assistanta z tym samym RS485/TCP."
echo

"${SOURCE_DIR}/scripts/preflight.sh"

apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y \
  python3 python3-venv python3-pip sqlite3 avahi-daemon \
  curl ca-certificates rsync iproute2

if ! python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)'; then
  echo
  echo "BŁĄD: system ma Python starszy niż 3.10."
  echo "Użyj Debiana 12, Ubuntu 22.04+ albo aktualnego Armbiana."
  exit 1
fi

read -r -p "Ustawić nazwę urządzenia na plumbox (adres plumbox.local)? [T/n]: " SET_HOSTNAME
SET_HOSTNAME="${SET_HOSTNAME:-T}"
if [[ "${SET_HOSTNAME,,}" != "n" ]]; then
  hostnamectl set-hostname plumbox
fi

if ! id "${USER_NAME}" >/dev/null 2>&1; then
  useradd --system --home "${INSTALL_DIR}" --shell /usr/sbin/nologin "${USER_NAME}"
fi
usermod -a -G dialout "${USER_NAME}" || true

systemctl stop plumbox.service 2>/dev/null || true

mkdir -p "${INSTALL_DIR}" "${CONFIG_DIR}" "${DATA_DIR}"
rsync -a --delete \
  --exclude '.venv' \
  --exclude '__pycache__' \
  --exclude 'config/config.yaml' \
  "${SOURCE_DIR}/" "${INSTALL_DIR}/"

python3 -m venv "${INSTALL_DIR}/.venv"
"${INSTALL_DIR}/.venv/bin/python" -m pip install --upgrade pip wheel setuptools

if compgen -G "${SOURCE_DIR}/wheelhouse/*" > /dev/null; then
  echo "Instalacja zależności z lokalnego katalogu wheelhouse."
  "${INSTALL_DIR}/.venv/bin/pip" install \
    --no-index \
    --find-links "${SOURCE_DIR}/wheelhouse" \
    -r "${INSTALL_DIR}/requirements.txt"
else
  echo "Instalacja zależności z PyPI."
  "${INSTALL_DIR}/.venv/bin/pip" install -r "${INSTALL_DIR}/requirements.txt"
fi

if [[ ! -f "${CONFIG_DIR}/config.yaml" ]]; then
  cp "${INSTALL_DIR}/config/config.example.yaml" "${CONFIG_DIR}/config.yaml"

  echo
  echo "Dostępne połączenia:"
  echo "  tcp        — konwerter RS485–Ethernet/Wi-Fi"
  echo "  serial     — adapter USB–RS485"
  echo "  simulation — panel demonstracyjny bez kotła"
  read -r -p "Typ połączenia [tcp/serial/simulation] (simulation): " CONNECTION_TYPE
  CONNECTION_TYPE="${CONNECTION_TYPE:-simulation}"

  case "${CONNECTION_TYPE}" in
    tcp|serial|simulation) ;;
    *)
      echo "Nieprawidłowy typ połączenia."
      exit 1
      ;;
  esac

  HOST="192.168.1.50"
  PORT="8899"
  SERIAL_DEVICE="/dev/ttyUSB0"
  BAUDRATE="115200"

  if [[ "${CONNECTION_TYPE}" == "tcp" ]]; then
    read -r -p "Adres IP konwertera RS485–TCP: " HOST
    read -r -p "Port TCP (8899): " PORT
    PORT="${PORT:-8899}"
  elif [[ "${CONNECTION_TYPE}" == "serial" ]]; then
    read -r -p "Urządzenie USB (/dev/ttyUSB0): " SERIAL_DEVICE
    SERIAL_DEVICE="${SERIAL_DEVICE:-/dev/ttyUSB0}"
    read -r -p "Prędkość (115200): " BAUDRATE
    BAUDRATE="${BAUDRATE:-115200}"
  fi

  while true; do
    read -r -s -p "Ustaw PIN sterowania (minimum 4 znaki): " PIN
    echo
    [[ ${#PIN} -ge 4 ]] && break
    echo "PIN jest za krótki."
  done


  while true; do
    if [[ -n "${PLUMBOX_ADMIN_PASSWORD:-}" ]]; then
      ADMIN_PASSWORD="${PLUMBOX_ADMIN_PASSWORD}"
      break
    fi
    echo
    echo "Konto administratora PlumBox"
    echo "Login startowy: admin"
    read -r -s -p "Ustaw hasło admina min. 8 znaków; Enter = losowe: " ADMIN_PASSWORD
    echo
    if [[ -z "${ADMIN_PASSWORD}" || ${#ADMIN_PASSWORD} -ge 8 ]]; then
      break
    fi
    echo "Hasło jest za krótkie."
  done

  PIN_HASH="$("${INSTALL_DIR}/.venv/bin/python" "${INSTALL_DIR}/scripts/hash_pin.py" "${PIN}")"

  CONFIG_TYPE="${CONNECTION_TYPE}" \
  CONFIG_HOST="${HOST}" \
  CONFIG_PORT="${PORT}" \
  CONFIG_SERIAL="${SERIAL_DEVICE}" \
  CONFIG_BAUD="${BAUDRATE}" \
  CONFIG_PIN_HASH="${PIN_HASH}" \
  "${INSTALL_DIR}/.venv/bin/python" - <<'PY'
import os
from pathlib import Path
import yaml

path = Path("/etc/plumbox/config.yaml")
data = yaml.safe_load(path.read_text(encoding="utf-8"))
data["connection"]["type"] = os.environ["CONFIG_TYPE"]
data["connection"]["host"] = os.environ["CONFIG_HOST"]
data["connection"]["port"] = int(os.environ["CONFIG_PORT"])
data["connection"]["serial_device"] = os.environ["CONFIG_SERIAL"]
data["connection"]["baudrate"] = int(os.environ["CONFIG_BAUD"])
data["security"]["pin"] = None
data["security"]["pin_hash"] = os.environ["CONFIG_PIN_HASH"]
path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
PY
else
  echo "Zachowuję istniejący plik ${CONFIG_DIR}/config.yaml."
fi

cp "${INSTALL_DIR}/systemd/plumbox.service" "${SERVICE_FILE}"

if [[ ! -f "${USERS_FILE}" ]]; then
  "${INSTALL_DIR}/.venv/bin/python" "${INSTALL_DIR}/scripts/create_admin.py" --users "${USERS_FILE}" --password "${ADMIN_PASSWORD:-}" --password-file "${INITIAL_ADMIN_PASSWORD_FILE}"
fi
chown -R "${USER_NAME}:${USER_NAME}" "${INSTALL_DIR}" "${DATA_DIR}"
chown root:"${USER_NAME}" "${CONFIG_DIR}"
chmod 2770 "${CONFIG_DIR}"
chown root:"${USER_NAME}" "${CONFIG_DIR}/config.yaml"
chmod 660 "${CONFIG_DIR}/config.yaml"
if [[ -f "${USERS_FILE}" ]]; then chown root:"${USER_NAME}" "${USERS_FILE}"; chmod 660 "${USERS_FILE}"; fi
if [[ -f "${INITIAL_ADMIN_PASSWORD_FILE}" ]]; then chown root:"${USER_NAME}" "${INITIAL_ADMIN_PASSWORD_FILE}"; chmod 640 "${INITIAL_ADMIN_PASSWORD_FILE}"; fi
chmod +x "${INSTALL_DIR}/scripts/"*.sh "${INSTALL_DIR}/scripts/"*.py

systemctl daemon-reload
systemctl enable --now plumbox.service
systemctl enable --now avahi-daemon

sleep 2
IP_ADDRESS="$(hostname -I | awk '{print $1}')"

echo
echo "============================================================"
echo " PlumBox został zainstalowany"
echo "============================================================"
echo
echo "Panel:       http://${IP_ADDRESS}:8080"
echo "Adres mDNS:  http://$(hostname).local:8080"
echo "Konfiguracja: ${CONFIG_DIR}/config.yaml"
echo "Dane:         ${DATA_DIR}"
echo
echo "Stan usługi:"
systemctl --no-pager --full status plumbox.service || true
echo
echo "Logi: sudo journalctl -u plumbox -f"
