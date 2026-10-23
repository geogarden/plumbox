#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mkdir -p "${ROOT}/wheelhouse"

python3 -m pip download \
  --dest "${ROOT}/wheelhouse" \
  -r "${ROOT}/requirements.txt"

echo "Gotowe. Katalog offline: ${ROOT}/wheelhouse"
