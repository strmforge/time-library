#!/usr/bin/env bash
# Memcore Cloud one-command installer for macOS, Linux, and WSL.
set -euo pipefail

REPO="strmforge/memcore-cloud"
VERSION="${VERSION:-2026.6.3}"
ARCHIVE_URL="https://github.com/${REPO}/archive/refs/heads/main.zip"

info() { printf '[memcore-cloud] %s\n' "$*"; }
die() { printf '[memcore-cloud] %s\n' "$*" >&2; exit 1; }

run_from_tree() {
  local root="$1"
  shift

  case "$(uname -s)" in
    Darwin)
      [[ -f "${root}/tools/macos_full_install.sh" ]] || return 1
      exec bash "${root}/tools/macos_full_install.sh" "$@"
      ;;
    Linux)
      [[ -f "${root}/tools/linux_full_install.sh" ]] || return 1
      exec bash "${root}/tools/linux_full_install.sh" "$@"
      ;;
    *)
      die "Unsupported OS: $(uname -s)"
      ;;
  esac
}

download() {
  local url="$1"
  local out="$2"

  if command -v curl >/dev/null 2>&1; then
    curl -fsSL "$url" -o "$out"
  elif command -v python3 >/dev/null 2>&1; then
    python3 - "$url" "$out" <<'PY'
import sys
from urllib.request import urlopen

with urlopen(sys.argv[1], timeout=60) as response:
    data = response.read()
with open(sys.argv[2], "wb") as fh:
    fh.write(data)
PY
  else
    die "curl or python3 is required"
  fi
}

extract_zip() {
  local zip_path="$1"
  local out_dir="$2"

  if command -v unzip >/dev/null 2>&1; then
    unzip -qo "$zip_path" -d "$out_dir"
  elif command -v python3 >/dev/null 2>&1; then
    python3 -m zipfile -e "$zip_path" "$out_dir"
  else
    die "unzip or python3 is required"
  fi
}

script_path="${BASH_SOURCE[0]:-$0}"
if [[ -f "$script_path" ]]; then
  script_dir="$(cd "$(dirname "$script_path")" && pwd)"
  run_from_tree "$script_dir" "$@" || true
fi

tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT

zip_path="${tmp_dir}/memcore-cloud-main.zip"
extract_dir="${tmp_dir}/extracted"

info "Downloading Memcore Cloud ${VERSION}..."
download "$ARCHIVE_URL" "$zip_path"
extract_zip "$zip_path" "$extract_dir"

inner="$(find "$extract_dir" -mindepth 1 -maxdepth 1 -type d | head -1)"
[[ -n "$inner" ]] || die "Downloaded archive is empty"

run_from_tree "$inner" "$@" || die "Installer files were not found"
