#!/usr/bin/env bash
# Double-click macOS installer for Memcore Cloud.
set -euo pipefail

cd "$(dirname "$0")"

echo "[memcore-cloud] Starting macOS installer..."
echo "[memcore-cloud] This unsigned helper runs the same local installer as install.sh."
echo

bash ./install.sh "$@"

echo
echo "[memcore-cloud] Install finished."
if command -v open >/dev/null 2>&1; then
  open "http://127.0.0.1:9850" >/dev/null 2>&1 || true
fi
echo "You can close this window."
read -r -p "Press Return to close..." _unused || true
