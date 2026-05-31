#!/usr/bin/env bash
# macOS user-level full installer for Yifanchen / memcore-cloud.
#
# This installs from the current folder into the user's Application Support
# directory, starts local background services, and connects OpenClaw and Hermes
# when they are available.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
INSTALL_ROOT="${INSTALL_ROOT:-${HOME}/Library/Application Support/memcore-cloud}"
LAUNCH_AGENT_DIR="${HOME}/Library/LaunchAgents"
LOG_DIR="${HOME}/Library/Logs/memcore-cloud"
STATE_DIR="${HOME}/Library/Application Support/memcore-cloud-state"
OPENCLAW_CONFIG="${OPENCLAW_CONFIG:-${HOME}/.openclaw/openclaw.json}"
HERMES_HOME="${HERMES_HOME:-${HOME}/.hermes}"
HERMES_AGENT_DIR="${HERMES_AGENT_DIR:-${HERMES_HOME}/hermes-agent}"
REINSTALL=0
RESET_INSTALL=0
PRESERVE_DATA=1
SKIP_OPENCLAW=0
SKIP_HERMES=0
SKIP_CODEX=0
SKIP_START=0
RUN_SMOKE=1
CODEX_SKILL_STATUS="pending"
CODEX_MCP_STATUS="pending"

usage() {
  cat <<'USAGE'
Usage: bash tools/macos_full_install.sh [options]

Options:
  --install-root PATH     Install root. Default: ~/Library/Application Support/memcore-cloud
  --reinstall             Replace app files, preserve local data.
  --reset-install         Remove old install root before installing.
  --no-preserve-data      With --reset-install, do not copy old memory/log/config data back.
  --skip-openclaw         Do not connect OpenClaw during install.
  --skip-hermes           Do not connect Hermes during install.
  --skip-codex            Do not install the Codex skill or register the Codex MCP server.
  --no-start              Install only; do not start background services.
  --no-smoke              Skip start-up checks.
  -h, --help              Show this help.
USAGE
}

log() { printf '[yifanchen-macos-install] %s\n' "$*"; }
warn() { printf '[yifanchen-macos-install WARNING] %s\n' "$*" >&2; }
die() { printf '[yifanchen-macos-install ERROR] %s\n' "$*" >&2; exit 1; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --install-root) INSTALL_ROOT="$2"; shift 2 ;;
    --reinstall) REINSTALL=1; shift ;;
    --reset-install) RESET_INSTALL=1; REINSTALL=1; shift ;;
    --no-preserve-data) PRESERVE_DATA=0; shift ;;
    --skip-openclaw) SKIP_OPENCLAW=1; shift ;;
    --skip-hermes) SKIP_HERMES=1; shift ;;
    --skip-codex) SKIP_CODEX=1; shift ;;
    --no-start) SKIP_START=1; shift ;;
    --no-smoke) RUN_SMOKE=0; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "Unknown option: $1" ;;
  esac
done

if [[ "$(uname -s)" != "Darwin" ]]; then
  die "This installer is macOS-only. Use the platform-specific installer on other systems."
fi

command -v python3 >/dev/null 2>&1 || die "python3 not found"
command -v rsync >/dev/null 2>&1 || die "rsync not found"

copy_runtime_data() {
  local from="$1"
  local to="$2"
  for name in memory zhiyi experience_lancedb logs backups output config .checkpoint .checkpoint_p2.json; do
    if [[ -e "${from}/${name}" ]]; then
      mkdir -p "$to"
      rsync -a "${from}/${name}" "${to}/" 2>/dev/null || true
    fi
  done
}

stop_old_launchagents() {
  local labels=(
    com.memcorecloud.p0-watcher
    com.memcorecloud.p3-recall
    com.memcorecloud.p4-provider
    com.memcorecloud.p6-console
    com.memcorecloud.raw-gateway
    com.memcorecloud.dialog-entry
    ai.memcore.memcore-cloud
  )
  for label in "${labels[@]}"; do
    launchctl bootout "gui/${UID}/${label}" >/dev/null 2>&1 || true
    launchctl remove "$label" >/dev/null 2>&1 || true
  done
}

install_files() {
  mkdir -p "$(dirname "$INSTALL_ROOT")" "$LOG_DIR" "$STATE_DIR"
  local backup=""
  if [[ -d "$INSTALL_ROOT" && "$REINSTALL" == "1" ]]; then
    backup="${INSTALL_ROOT}.backup.$(date +%Y%m%d%H%M%S)"
    log "Backing up existing install to ${backup}"
    rsync -a "$INSTALL_ROOT/" "$backup/"
    if [[ "$RESET_INSTALL" == "1" ]]; then
      rm -rf "$INSTALL_ROOT"
      mkdir -p "$INSTALL_ROOT"
      if [[ "$PRESERVE_DATA" == "1" ]]; then
        copy_runtime_data "$backup" "$INSTALL_ROOT"
      fi
    fi
  fi
  mkdir -p "$INSTALL_ROOT"
  rsync -a --delete \
    --exclude '.git/' \
    --exclude '.venv/' \
    --exclude '__pycache__/' \
    --exclude '.pytest_cache/' \
    --exclude 'logs/' \
    --exclude 'memory/' \
    --exclude 'zhiyi/' \
    --exclude 'experience_lancedb/' \
    --exclude 'backups/' \
    --exclude 'output/' \
    --exclude '.checkpoint' \
    --exclude '.checkpoint_p2.json' \
    "${SOURCE_ROOT}/" "${INSTALL_ROOT}/"
}

write_config() {
  mkdir -p "${INSTALL_ROOT}/config" "${INSTALL_ROOT}/logs" "${INSTALL_ROOT}/memory" \
    "${INSTALL_ROOT}/zhiyi/case_memory" "${INSTALL_ROOT}/zhiyi/error_memory" \
    "${INSTALL_ROOT}/zhiyi/preference_memory" "${INSTALL_ROOT}/experience_lancedb" \
    "${INSTALL_ROOT}/backups" "${INSTALL_ROOT}/output"

  if [[ ! -f "${INSTALL_ROOT}/config/model_config.json" && -f "${INSTALL_ROOT}/config/default_model_config.json" ]]; then
    cp "${INSTALL_ROOT}/config/default_model_config.json" "${INSTALL_ROOT}/config/model_config.json"
  fi
  if [[ ! -f "${INSTALL_ROOT}/config/feature_flags.json" && -f "${INSTALL_ROOT}/config/default_feature_flags.json" ]]; then
    cp "${INSTALL_ROOT}/config/default_feature_flags.json" "${INSTALL_ROOT}/config/feature_flags.json"
  fi
  if [[ ! -f "${INSTALL_ROOT}/config/alias_map.json" && -f "${INSTALL_ROOT}/config/default_alias_map.json" ]]; then
    cp "${INSTALL_ROOT}/config/default_alias_map.json" "${INSTALL_ROOT}/config/alias_map.json"
  fi

  python3 - "$INSTALL_ROOT" <<'PY'
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

root = Path(sys.argv[1])
cfg_path = root / "config" / "memcore.json"
cfg = {}
if cfg_path.exists():
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8-sig"))
    except Exception:
        cfg = {}
cfg.setdefault("_comment", "Yifanchen user-level macOS config")
cfg["_base_dir"] = str(root)
cfg["version"] = str(cfg.get("version") or "1.0.0")
paths = cfg.setdefault("paths", {})
paths.update({
    "memory": "memory",
    "openclaw_agents": "${OPENCLAW_AGENTS_DIR:-~/.openclaw/agents}",
    "openclaw_workspace": "${OPENCLAW_WORKSPACE_DIR:-~/.openclaw/workspace}",
    "zhiyi": "zhiyi",
    "config_dir": "config",
    "experience_lancedb": "experience_lancedb",
    "checkpoint": ".checkpoint",
    "alias_map": "config/alias_map.json",
    "model_config": "config/model_config.json",
    "lancedb_v2_metadata": "config/lancedb_v2_metadata.json",
    "logs": "logs",
})
cfg["nodes"] = {
    "current": os.uname().nodename.split(".")[0] or "local-macos",
    "raw_memory_subpath": f"openclaw/{os.uname().nodename.split('.')[0] or 'local-macos'}",
}
services = cfg.setdefault("services", {})
services.update({
    "p0_watcher_enabled": True,
    "p3_recall_port": 9830,
    "p4_provider_port": 9840,
    "p6_console_port": 9850,
    "raw_consumption_gateway_port": 9851,
    "dialog_entry_port": 9860,
})
model_call = cfg.setdefault("integrations", {}).setdefault("hermes", {}).setdefault("model_call", {})
if not model_call.get("hermes_provider") and not model_call.get("provider"):
    hermes = shutil.which("hermes")
    if hermes:
        try:
            auth_list = subprocess.run(
                [hermes, "auth", "list"],
                capture_output=True,
                text=True,
                timeout=8,
            )
            if "custom:minimax" in (auth_list.stdout or ""):
                model_call["hermes_provider"] = "custom:minimax"
                model_call.setdefault("hermes_model", "minimax-m2.7")
                model_call.setdefault("source", "memcore-yifanchen")
        except Exception:
            pass
cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

model_cfg_path = root / "config" / "model_config.json"
model_cfg = {}
if model_cfg_path.exists():
    try:
        model_cfg = json.loads(model_cfg_path.read_text(encoding="utf-8-sig"))
    except Exception:
        model_cfg = {}
model_cfg.setdefault("version", "1.0")
recall = model_cfg.setdefault("recall", {})
recall["mode"] = "off"
recall.setdefault("substring", {"table": "experiences"})
model_cfg_path.write_text(json.dumps(model_cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

flags_path = root / "config" / "feature_flags.json"
flags = {}
if flags_path.exists():
    try:
        flags = json.loads(flags_path.read_text(encoding="utf-8-sig"))
    except Exception:
        flags = {}
flags.update({
    "zhiyi_direct": True,
    "zhiyi_inject": True,
    "openclaw_rpc": True,
    "passthrough": True,
    "audit_log": True,
})
flags_path.write_text(json.dumps(flags, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

current_node = cfg.get("nodes", {}).get("current") or (os.uname().nodename.split(".")[0] or "local-macos")

def normalize_zhiyi_node_refs():
    zhiyi_root = root / "zhiyi"
    changed_files = []
    for subtype in ("preference_memory", "case_memory", "error_memory"):
        path = zhiyi_root / subtype / f"{subtype}.jsonl"
        if not path.exists():
            continue
        changed = False
        out = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except Exception:
                out.append(line)
                continue
            sr_raw = rec.get("source_refs")
            try:
                sr = json.loads(sr_raw) if isinstance(sr_raw, str) else (sr_raw if isinstance(sr_raw, dict) else {})
            except Exception:
                sr = {}
            source_path = str(sr.get("source_path") or "")
            if f"/memory/openclaw/{current_node}/" in source_path.replace("\\", "/"):
                if rec.get("computer_id") != current_node:
                    rec["computer_id"] = current_node
                    changed = True
                if sr.get("computer_name") != current_node:
                    sr["computer_name"] = current_node
                    rec["source_refs"] = json.dumps(sr, ensure_ascii=False)
                    changed = True
            out.append(json.dumps(rec, ensure_ascii=False) if changed else line)
        if changed:
            path.write_text("\n".join(out) + "\n", encoding="utf-8")
            changed_files.append(str(path))
    if changed_files:
        print("normalized zhiyi node refs:", ", ".join(changed_files))

normalize_zhiyi_node_refs()
PY
}

install_python_env() {
  log "Preparing Python venv"
  python3 -m venv "${INSTALL_ROOT}/.venv"
  "${INSTALL_ROOT}/.venv/bin/python" -m pip install --upgrade pip >/dev/null
  if [[ -f "${INSTALL_ROOT}/requirements-core.txt" ]]; then
    "${INSTALL_ROOT}/.venv/bin/python" -m pip install -r "${INSTALL_ROOT}/requirements-core.txt"
  fi
  "${INSTALL_ROOT}/.venv/bin/python" - <<'PY'
import importlib.util
missing = [name for name in ("cryptography",) if importlib.util.find_spec(name) is None]
if missing:
    raise SystemExit("missing python packages: " + ", ".join(missing))
PY
}

write_launch_agent() {
  local label="$1"
  local log_name="$2"
  shift 2
  local plist="${LAUNCH_AGENT_DIR}/${label}.plist"
  mkdir -p "$LAUNCH_AGENT_DIR" "$LOG_DIR"
  python3 - "$plist" "$label" "$INSTALL_ROOT" "$LOG_DIR" "$log_name" "$@" <<'PY'
import plistlib
import sys
from pathlib import Path

plist_path = Path(sys.argv[1])
label = sys.argv[2]
install_root = sys.argv[3]
log_dir = sys.argv[4]
log_name = sys.argv[5]
args = sys.argv[6:]
env = {
    "MEMCORE_ROOT": install_root,
    "MEMCORE_INSTALL_ROOT": install_root,
    "PYTHONPATH": install_root,
    "PYTHONIOENCODING": "utf-8",
    "MEMCORE_HERMES_CLI": str(Path.home() / ".local" / "bin" / "hermes"),
}
data = {
    "Label": label,
    "ProgramArguments": args,
    "WorkingDirectory": install_root,
    "EnvironmentVariables": env,
    "RunAtLoad": True,
    "KeepAlive": {"SuccessfulExit": False},
    "ProcessType": "Background",
    "LowPriorityIO": True,
    "StandardOutPath": str(Path(log_dir) / f"{log_name}.out.log"),
    "StandardErrorPath": str(Path(log_dir) / f"{log_name}.err.log"),
}
plist_path.write_bytes(plistlib.dumps(data, sort_keys=False))
PY
  plutil -lint "$plist" >/dev/null
}

install_launchagents() {
  local py="${INSTALL_ROOT}/.venv/bin/python"
  write_launch_agent com.memcorecloud.p0-watcher p0-watcher \
    "$py" "${INSTALL_ROOT}/src/memcore-cloud.py" --watch --source all
  write_launch_agent com.memcorecloud.p3-recall p3-recall \
    "$py" "${INSTALL_ROOT}/src/p3_recall.py" serve --port 9830
  write_launch_agent com.memcorecloud.p4-provider p4-provider \
    "$py" "${INSTALL_ROOT}/src/p4_provider.py" --port 9840
  write_launch_agent com.memcorecloud.p6-console p6-console \
    "$py" "${INSTALL_ROOT}/src/p6_console.py" --host 127.0.0.1 --port 9850
  write_launch_agent com.memcorecloud.raw-gateway raw-gateway \
    "$py" "${INSTALL_ROOT}/src/raw_consumption_gateway.py"
  write_launch_agent com.memcorecloud.dialog-entry dialog-entry \
    "$py" "${INSTALL_ROOT}/src/dialog_entry_proxy.py" --port 9860
}

start_launchagents() {
  local labels=(
    com.memcorecloud.p0-watcher
    com.memcorecloud.p3-recall
    com.memcorecloud.p4-provider
    com.memcorecloud.p6-console
    com.memcorecloud.raw-gateway
    com.memcorecloud.dialog-entry
  )
  for label in "${labels[@]}"; do
    local plist="${LAUNCH_AGENT_DIR}/${label}.plist"
    launchctl bootstrap "gui/${UID}" "$plist" >/dev/null 2>&1 || launchctl load -w "$plist" >/dev/null 2>&1 || true
    launchctl kickstart -k "gui/${UID}/${label}" >/dev/null 2>&1 || true
  done
}

install_openclaw_plugin() {
  [[ "$SKIP_OPENCLAW" == "1" ]] && return
  local plugin_src="${INSTALL_ROOT}/system/openclaw/plugins/memcore-zhiyi-native"
  [[ -d "$plugin_src" ]] || { warn "OpenClaw plugin source not found: ${plugin_src}"; return; }
  if command -v openclaw >/dev/null 2>&1; then
    openclaw plugins install --link "$plugin_src" >/dev/null 2>&1 || true
    openclaw plugins enable memcore-zhiyi-native >/dev/null 2>&1 || true
    openclaw plugins registry --refresh >/dev/null 2>&1 || true
  fi
  if [[ -f "$OPENCLAW_CONFIG" ]]; then
    python3 - "$OPENCLAW_CONFIG" "$plugin_src" <<'PY'
import json
import shutil
import sys
import time
from pathlib import Path

cfg_path = Path(sys.argv[1])
plugin_src = sys.argv[2]
cfg = json.loads(cfg_path.read_text(encoding="utf-8-sig"))
backup = cfg_path.with_name(cfg_path.name + f".yifanchen-bak.{time.strftime('%Y%m%d%H%M%S')}")
shutil.copy2(cfg_path, backup)
plugins = cfg.setdefault("plugins", {})
entries = plugins.setdefault("entries", {})
entry = entries.setdefault("memcore-zhiyi-native", {})
entry["enabled"] = True
entry["config"] = {
    **(entry.get("config") if isinstance(entry.get("config"), dict) else {}),
    "enabled": True,
    "endpointUrl": "http://127.0.0.1:9860/entry/openclaw-before-dispatch",
    "allowedChannels": ["webchat"],
    "enableModelCall": True,
    "forceZhiyiDirect": True,
    "timeoutMs": 120000,
}
load = plugins.setdefault("load", {})
paths = load.setdefault("paths", [])
if isinstance(paths, list) and plugin_src not in paths:
    paths.append(plugin_src)
cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(str(backup))
PY
  else
    warn "OpenClaw config not found: ${OPENCLAW_CONFIG}"
  fi
}

install_hermes_plugin() {
  [[ "$SKIP_HERMES" == "1" ]] && return
  local src="${INSTALL_ROOT}/system/hermes/plugins/memcore_yifanchen"
  [[ -d "$src" ]] || { warn "Hermes plugin source not found: ${src}"; return; }
  mkdir -p "${HERMES_HOME}/plugins"
  rm -rf "${HERMES_HOME}/plugins/memcore_yifanchen"
  rsync -a "$src/" "${HERMES_HOME}/plugins/memcore_yifanchen/"

  python3 - "$HERMES_HOME" <<'PY'
import json
import shutil
import sys
import time
from pathlib import Path

home = Path(sys.argv[1]).expanduser()
profile_cfg = home / "profiles" / "default" / "config.yaml"
root_cfg = home / "config.yaml"
if profile_cfg.exists():
    cfg_path = profile_cfg
elif root_cfg.exists():
    cfg_path = root_cfg
elif (home / "profiles").exists():
    cfg_path = profile_cfg
else:
    cfg_path = root_cfg
cfg_path.parent.mkdir(parents=True, exist_ok=True)
backup = None
try:
    import yaml
except Exception:
    yaml = None

if yaml:
    cfg = {}
    if cfg_path.exists():
        backup = cfg_path.with_name(cfg_path.name + f".yifanchen-bak.{time.strftime('%Y%m%d%H%M%S')}")
        shutil.copy2(cfg_path, backup)
        cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8-sig")) or {}
        if not isinstance(cfg, dict):
            cfg = {}
    memory = cfg.setdefault("memory", {})
    memory["provider"] = "memcore_yifanchen"
    plugins = cfg.setdefault("plugins", {})
    enabled = plugins.setdefault("enabled", [])
    if isinstance(enabled, list) and "memcore_yifanchen" not in enabled:
        enabled.append("memcore_yifanchen")
    plugins["memcore_yifanchen"] = {
        **(plugins.get("memcore_yifanchen") if isinstance(plugins.get("memcore_yifanchen"), dict) else {}),
        "provider_url": "http://127.0.0.1:9851/api/v1/raw/query",
        "memory_scope": "raw_pool",
        "computer_name": "",
        "limit": 3,
        "excerpt_chars": 500,
        "context_chars": 2400,
        "timeout_seconds": 5,
        "include_session_id": False,
        "receipt_url": "http://127.0.0.1:9850/api/v1/hermes/consumption-receipts",
        "enable_receipts": True,
        "enable_queue_prefetch": True,
    }
    cfg_path.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")
else:
    # Minimal fallback that preserves the common top-level keys poorly but keeps
    # the provider selectable when PyYAML is not available.
    existing = cfg_path.read_text(encoding="utf-8") if cfg_path.exists() else ""
    if cfg_path.exists():
        backup = cfg_path.with_name(cfg_path.name + f".yifanchen-bak.{time.strftime('%Y%m%d%H%M%S')}")
        shutil.copy2(cfg_path, backup)
    block = """
memory:
  provider: memcore_yifanchen
plugins:
  enabled:
    - memcore_yifanchen
  memcore_yifanchen:
    provider_url: http://127.0.0.1:9851/api/v1/raw/query
    memory_scope: raw_pool
    computer_name: ""
    limit: 3
    excerpt_chars: 500
    context_chars: 2400
    timeout_seconds: 5
    include_session_id: false
    receipt_url: http://127.0.0.1:9850/api/v1/hermes/consumption-receipts
    enable_receipts: true
    enable_queue_prefetch: true
"""
    cfg_path.write_text(existing.rstrip() + "\n" + block, encoding="utf-8")
print(str(backup) if backup else "")
PY

  if [[ -x "${HERMES_HOME}/hermes-agent/venv/bin/python" ]]; then
    "${HERMES_HOME}/hermes-agent/venv/bin/python" - <<'PY' || true
import os
import sys
from pathlib import Path
home = Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes").expanduser()
agent = home / "hermes-agent"
sys.path.insert(0, str(agent))
from plugins.memory import load_memory_provider
p = load_memory_provider("memcore_yifanchen")
raise SystemExit(0 if p and p.is_available() else 1)
PY
  fi
}

install_codex_skill() {
  if [[ "$SKIP_CODEX" == "1" ]]; then
    CODEX_SKILL_STATUS="skipped"
    return
  fi
  local skill_src="${INSTALL_ROOT}/system/skills/yifanchen-zhiyi"
  if [[ ! -d "$skill_src" ]]; then
    warn "Codex skill source not found: ${skill_src}"
    CODEX_SKILL_STATUS="source not found"
    return
  fi
  local codex_home="${CODEX_HOME:-${HOME}/.codex}"
  local skill_dst="${codex_home}/skills/yifanchen-zhiyi"
  mkdir -p "$(dirname "$skill_dst")"
  rm -rf "$skill_dst"
  rsync -a "$skill_src/" "$skill_dst/"
  log "Codex skill installed: ${skill_dst}"
  CODEX_SKILL_STATUS="yifanchen-zhiyi"
}

install_codex_mcp() {
  if [[ "$SKIP_CODEX" == "1" ]]; then
    CODEX_MCP_STATUS="skipped"
    return
  fi
  if ! command -v codex >/dev/null 2>&1; then
    warn "Codex CLI not found; skipping Codex MCP registration"
    CODEX_MCP_STATUS="codex CLI not found"
    return
  fi
  codex mcp remove yifanchen-zhiyi >/dev/null 2>&1 || true
  if codex mcp add yifanchen-zhiyi --url http://127.0.0.1:9851/mcp >/dev/null 2>&1; then
    log "Codex MCP registered: yifanchen-zhiyi -> http://127.0.0.1:9851/mcp"
    CODEX_MCP_STATUS="yifanchen-zhiyi"
  else
    warn "Codex MCP registration failed; Codex users can run: codex mcp add yifanchen-zhiyi --url http://127.0.0.1:9851/mcp"
    CODEX_MCP_STATUS="registration failed"
  fi
}

smoke_check() {
  local name="$1"
  local url="$2"
  python3 - "$name" "$url" <<'PY'
import json
import sys
import urllib.request
name, url = sys.argv[1], sys.argv[2]
try:
    with urllib.request.urlopen(url, timeout=5) as resp:
        body = resp.read(500).decode("utf-8", errors="replace")
    print(f"{name}: ok {body[:160]}")
except Exception as exc:
    print(f"{name}: fail {exc}")
    raise SystemExit(1)
PY
}

run_smoke() {
  sleep 4
  smoke_check p3 "http://127.0.0.1:9830/health"
  smoke_check p4 "http://127.0.0.1:9840/health"
  smoke_check p6 "http://127.0.0.1:9850/api/health"
  smoke_check raw "http://127.0.0.1:9851/health"
  smoke_check dialog "http://127.0.0.1:9860/health"
}

log "Source: ${SOURCE_ROOT}"
log "Install root: ${INSTALL_ROOT}"
stop_old_launchagents
install_files
write_config
install_python_env
install_launchagents
install_openclaw_plugin
install_hermes_plugin
install_codex_skill
install_codex_mcp
if [[ "$SKIP_START" == "0" ]]; then
  start_launchagents
fi
if [[ "$RUN_SMOKE" == "1" && "$SKIP_START" == "0" ]]; then
  run_smoke
fi

cat <<EOF

Yifanchen macOS full install complete.
Install root: ${INSTALL_ROOT}
Console: http://127.0.0.1:9850
Services: p0 watcher, 9830, 9840, 9850, 9851, 9860
Logs: ${LOG_DIR}
OpenClaw plugin: $([[ "$SKIP_OPENCLAW" == "1" ]] && echo skipped || echo memcore-zhiyi-native)
Hermes memory provider: $([[ "$SKIP_HERMES" == "1" ]] && echo skipped || echo memcore_yifanchen)
Codex skill: ${CODEX_SKILL_STATUS}
Codex MCP: ${CODEX_MCP_STATUS}
EOF
