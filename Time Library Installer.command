#!/usr/bin/env bash
# Double-click macOS installer for Time Library.
set -euo pipefail

cd "$(dirname "$0")"

echo "[time-library] Starting macOS installer..."
echo "[time-library] This unsigned helper runs the same local installer as install.sh."
echo

bash ./install.sh "$@"

echo
echo "[time-library] Install finished."
if command -v open >/dev/null 2>&1; then
  root="$HOME/Library/Application Support/time-library"
  if [[ -r "$root/runtime/front_door_port" ]]; then
    port="$(tr -d '\r\n' < "$root/runtime/front_door_port")"
    open "http://127.0.0.1:${port}" >/dev/null 2>&1 || true
  fi
fi
echo "You can close this window."
read -r -p "Press Return to close..." _unused || true
