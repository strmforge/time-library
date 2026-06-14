#!/usr/bin/env bash
# ============================================================
# memcore-cloud Uninstaller (macOS / Linux)
# Usage:
#   ~/.memcore-cloud/uninstall.sh
#   curl -fsSL ... | sudo bash (Linux)
# ============================================================
# This removes ONLY the software and registered services.
# User data (memory/, zhiyi/, experience_lancedb/, config/) is preserved.
set -e

info() { echo "[memcore-cloud] $*"; }
warn() { echo "[memcore-cloud WARNING] $*"; }
error() { echo "[memcore-cloud ERROR] $*" >&2; exit 1; }

OS=""
case "$(uname -s)" in
    Linux*)  OS="linux" ;;
    Darwin*) OS="darwin" ;;
    *)       error "Unsupported OS: $(uname -s)" ;;
esac

# Determine install directory
INSTALL_DIR=""
if [[ "$OS" == "linux" ]]; then
    INSTALL_DIR="${INSTALL_DIR:-/opt/memcore-cloud}"
else
    NEW_MAC_INSTALL_DIR="${HOME}/Library/Application Support/memcore-cloud"
    OLD_MAC_INSTALL_DIR="${HOME}/Library/Application Support/MemcoreCloud"
    if [[ -z "${INSTALL_DIR:-}" ]]; then
        if [[ -d "$NEW_MAC_INSTALL_DIR" || ! -d "$OLD_MAC_INSTALL_DIR" ]]; then
            INSTALL_DIR="$NEW_MAC_INSTALL_DIR"
        else
            INSTALL_DIR="$OLD_MAC_INSTALL_DIR"
        fi
    fi
fi

# Parse args
while [[ $# -gt 0 ]]; do
    case "$1" in
        --dir) INSTALL_DIR="$2"; shift 2 ;;
        --help|-h)
            echo "Usage: ~/.memcore-cloud/uninstall.sh"
            echo "       curl -fsSL ... | sudo bash"
            echo "Options: --dir PATH    Installation directory"
            exit 0 ;;
        *) error "Unknown option: $1" ;;
    esac
done

echo ""
echo "=============================================="
echo " memcore-cloud Uninstaller"
echo "=============================================="
echo ""
info "Installation directory: ${INSTALL_DIR}"
echo ""
echo "This will:"
echo "  1. Stop memcore-cloud services"
if [[ "$OS" == "linux" ]]; then
    echo "  2. Remove systemd service: memcore-cloud-console.service"
elif [[ "$OS" == "darwin" ]]; then
    echo "  2. Remove memcore-cloud LaunchAgents, including the menu bar icon"
fi
echo "  3. Remove software files from ${INSTALL_DIR}"
echo ""
echo "The following user data will be PRESERVED (not deleted):"
echo "  - memory/"
echo "  - zhiyi/"
echo "  - experience_lancedb/"
echo "  - config/"
echo "  - logs/"
echo "  - backups/"
echo ""
echo "Remove software only? [Y/n]"
read -r confirm
case "$confirm" in
    [nN]*) echo "Aborted."; exit 0 ;;
esac

# ─── Stop services ────────────────────────────────────────
info "Stopping memcore-cloud services..."
pkill -f "p6_console" 2>/dev/null || true

# ─── Stop & unregister service ────────────────────────────
if [[ "$OS" == "linux" ]]; then
    if systemctl status memcore-cloud-console.service &>/dev/null 2>&1; then
        info "Stopping and disabling systemd service..."
        systemctl stop memcore-cloud-console.service 2>/dev/null || true
        systemctl disable memcore-cloud-console.service 2>/dev/null || true
    fi
    if [[ -f /etc/systemd/system/memcore-cloud-console.service ]]; then
        info "Removing systemd service file..."
        rm -f /etc/systemd/system/memcore-cloud-console.service
        systemctl daemon-reload 2>/dev/null || true
    fi
elif [[ "$OS" == "darwin" ]]; then
    labels=(
        com.memcorecloud.p0-watcher
        com.memcorecloud.p3-recall
        com.memcorecloud.p4-provider
        com.memcorecloud.p6-console
        com.memcorecloud.raw-gateway
        com.memcorecloud.dialog-entry
        com.memcorecloud.menu-bar
        com.memcorecloud.console
        ai.memcore.memcore-cloud
    )
    for label in "${labels[@]}"; do
        PLIST_PATH="${HOME}/Library/LaunchAgents/${label}.plist"
        if launchctl print "gui/$(id -u)/${label}" &>/dev/null 2>&1; then
            info "Unloading LaunchAgent: ${label}"
            launchctl bootout "gui/$(id -u)/${label}" 2>/dev/null || \
            launchctl unload "$PLIST_PATH" 2>/dev/null || true
        fi
        if [[ -f "$PLIST_PATH" ]]; then
            info "Removing LaunchAgent plist: ${label}"
            rm -f "$PLIST_PATH"
        fi
    done
fi

# ─── Remove software (preserve user data) ─────────────────
if [[ -d "$INSTALL_DIR" ]]; then
    info "Removing software from ${INSTALL_DIR} (preserving user data)..."
    # Remove files and dirs that are part of the software, not user data
    for item in src web tools scripts docs packaging system tests runtime config/default_*.json \
                .venv VERSION README.md README.zh-CN.md LICENSE CHANGELOG.md \
                install.sh uninstall.sh requirements.txt requirements-core.txt \
                requirements-vector.txt requirements-dev.txt *.py \
                PACKAGING.md CURRENT_BASELINE.md CURRENT_STATE.md "AGENTS"".md" \
                update_staging; do
        rm -rf "${INSTALL_DIR:?}/${item}" 2>/dev/null || true
    done
    # Remove configs that can be regenerated (keep memcore.json -- user config)
    for f in alias_map.json model_config.json feature_flags.json \
             window_binding_registry.json init_state.json; do
        rm -f "${INSTALL_DIR}/config/${f}" 2>/dev/null || true
    done
    info "Software has been removed."
else
    warn "Installation directory does not exist: ${INSTALL_DIR}"
fi

echo ""
echo "=============================================="
echo " Uninstallation complete!"
echo "=============================================="
echo ""
echo "Software removed. Your data has been preserved at:"
echo "  ${INSTALL_DIR}/memory/"
echo "  ${INSTALL_DIR}/zhiyi/"
echo "  ${INSTALL_DIR}/experience_lancedb/"
echo "  ${INSTALL_DIR}/config/"
echo "  ${INSTALL_DIR}/logs/"
echo ""
echo "To fully remove all data including user data, run:"
echo "  rm -rf '${INSTALL_DIR}'"
echo ""
