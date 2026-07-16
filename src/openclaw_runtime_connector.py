#!/usr/bin/env python3
"""
memcore-cloud OpenClaw Runtime Connector

Minimal access plan.
OpenClaw runtime write boundary
- observe_only=True (default): blocks all real writes to ~/.openclaw/
- rollback requires: backup + diff + audit log + authorization token
- paired.json / device identity / session JSONL / private key: all hard-blocked
- auto_fix / auto_repair: forbidden

Architecture:
- Gateway HTTP API only exposes /health
- No plugin/hook: cannot rely on OpenClaw internal call chain
- Minimal access: direct filesystem read of openclaw.json + session files
- Read-only by default, write only via explicit authorization chain

Functions:
- E1: Read OpenClaw runtime structure (config/agents/sessions/logs)
- E2: Probe available entry points (filesystem only)
- E3: Minimal access scheme (filesystem access)
- E4: Runtime connector (read+backup+diff)
"""

import json
import os
import shutil
import hashlib
import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from config_loader import get_memcore_root

OPENCLAW_ROOT = Path.home() / ".openclaw"
MEMCORE_ROOT = Path(get_memcore_root())
BACKUP_DIR = MEMCORE_ROOT / "backup" / "openclaw_config"
BACKUP_DIR.mkdir(parents=True, exist_ok=True)

UTC = timezone.utc

# OpenClaw runtime write boundary.
# True = observe-only; no real writes to ~/.openclaw/.
OBSERVE_ONLY = True

# 禁止写入的 OpenClaw 路径（硬阻断）
FORBIDDEN_OPENCLAW_WRITES = [
    "paired.json",          # device identity
    "device_identity",       # device identity files
    "identity/",            # identity directory (device.json, device-auth.json)
    "private_key",           # private keys
    "session",               # session JSONL files (raw memory)
    "memory",                # memory files
    "logs",                 # log files (audit tamper risk)
    "openclaw.json",         # gateway config (tamper risk)
]

# Authorization token placeholder for guarded local operations.
AUTHORIZED_TOKENS = {
    "memcore-cloud-openclaw-runtime-v1",
}

# Credential fields omitted from config reports and config backups. This applies
# only to OpenClaw configuration credentials, not saved platform conversation text.
SENSITIVE_FIELDS = {
    "token", "tokens", "api_key", "apikey", "api_key_b64", "password",
    "secret", "private_key", "privatekey", "client_secret",
    "auth_token", "access_token", "refresh_token", "bearer_token",
    "encryption" + "_key", "encryption" + "_key_b64", "secret" + "_key",
}
REDACTED = "***REDACTED***"


def _sanitize_value(val):
    """Return a config/report-safe copy with credential values omitted."""
    if isinstance(val, (int, float, bool)):
        return val
    elif isinstance(val, dict):
        return {k: REDACTED if _field_is_sensitive(k) else _sanitize_value(v) for k, v in val.items()}
    elif isinstance(val, (list, tuple)):
        return [_sanitize_value(i) for i in val]
    return val  # strings, None, etc. pass through


def _field_is_sensitive(key: str) -> bool:
    return key.lower() in SENSITIVE_FIELDS


def sanitize_config(config: dict) -> dict:
    """Return a config/report-safe copy without changing the original object."""
    import copy
    return _sanitize_value(copy.deepcopy(config))


def is_openclaw_write_path(path: str) -> bool:
    """检查是否写入 OpenClaw runtime 目录，是则拦截.

    拦截规则：
    1. 路径在 OPENCLAW_ROOT 内部 AND
    2. 完整路径字符串包含禁止关键字（防止 logs/, session/, memory/, paired.json 等）
    """
    # SDC-C-FIX: 展开 ~ 为绝对路径
    expanded = os.path.expanduser(path)
    p = Path(expanded)
    # 写入目标是 ~/.openclaw/ 内部
    try:
        p.relative_to(OPENCLAW_ROOT)
    except ValueError:
        # 不在 OPENCLAW_ROOT 下，不拦截
        return False
    # 检查完整路径字符串是否包含禁止关键字
    path_str = str(p)
    for forbidden in FORBIDDEN_OPENCLAW_WRITES:
        if forbidden in path_str:
            return True
    return False


def check_authorization(token: str) -> tuple[bool, str]:
    """验证授权 token."""
    if not token:
        return False, "authorization token required"
    if token not in AUTHORIZED_TOKENS:
        return False, "invalid authorization token"
    return True, ""


def log_runtime_change(action: str, ok: bool, detail: dict):
    """Audit log for all OpenClaw runtime operations."""
    log_path = MEMCORE_ROOT / "logs" / "openclaw_runtime_audit.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    from datetime import datetime
    entry = {
        "ts": datetime.now(UTC).isoformat(),
        "action": action,
        "ok": ok,
        "observe_only": OBSERVE_ONLY,
        **detail,
    }
    try:
        with open(log_path, "a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass  # non-blocking


def ts():
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def file_hash(path: Path) -> Optional[str]:
    """计算文件 SHA256 前16位"""
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()[:16]
    except Exception:
        return None


def read_openclaw_config() -> dict:
    """E1: Read openclaw.json as a config-safe report."""
    cfg_path = OPENCLAW_ROOT / "openclaw.json"
    if not cfg_path.exists():
        return {"error": "openclaw.json not found", "path": str(cfg_path)}

    with open(cfg_path) as f:
        raw = json.load(f)

    safe = sanitize_config(raw)

    # Extract display fields from the credential-safe copy.
    gw = safe.get("gateway", {})
    agents_list = safe.get("agents", {}).get("list", [])
    plugins_allow = safe.get("plugins", {}).get("allow", [])
    plugins_entries = list(safe.get("plugins", {}).get("entries", {}).keys())
    models = safe.get("models", {})

    return {
        "path": str(cfg_path),
        "hash": file_hash(cfg_path),
        "gateway_port": gw.get("port"),
        "gateway_mode": gw.get("mode"),
        "agent_count": len(agents_list),
        "agents": [
            {
                "id": a.get("id"),
                "workspace": a.get("workspace"),
                "model": a.get("model") if isinstance(a.get("model"), str) else a.get("model", {}).get("primary"),
            }
            for a in agents_list
        ],
        "plugins_allow": plugins_allow,
        "plugins_loaded": plugins_entries,
        "models_mode": list(models.keys()) if isinstance(models, dict) else [],
        "_credentials_omitted": True,
    }


def read_openclaw_logs_summary() -> dict:
    """E1: 读取 logs 目录摘要"""
    log_dir = OPENCLAW_ROOT / "logs"
    if not log_dir.exists():
        return {"error": "logs dir not found"}

    entries = {}
    for f in log_dir.iterdir():
        if f.is_file():
            entries[f.name] = {
                "size_bytes": f.stat().st_size,
                "hash": file_hash(f),
                "mtime": f.stat().st_mtime,
            }
    return entries


def read_agents_sessions_summary() -> dict:
    """E1: 读取各 agent 的 session 摘要（不做全量读取）"""
    agents_dir = OPENCLAW_ROOT / "agents"
    if not agents_dir.exists():
        return {}

    summary = {}
    for d in agents_dir.iterdir():
        if not d.is_dir():
            continue
        sessions_dir = d / "sessions"
        if not sessions_dir.exists():
            summary[d.name] = {"sessions_count": 0, "total_size": 0, "sessions": []}
            continue

        sessions = []
        total_size = 0
        for sf in sessions_dir.glob("*.jsonl"):
            stat = sf.stat()
            size = stat.st_size
            total_size += size
            sessions.append({
                "session_id": sf.stem,
                "size_bytes": size,
                "size_mb": round(size / 1024 / 1024, 2),
                "hash": file_hash(sf),
                "mtime": stat.st_mtime,
            })

        sessions.sort(key=lambda x: x["size_bytes"], reverse=True)
        summary[d.name] = {
            "sessions_count": len(sessions),
            "total_size_mb": round(total_size / 1024 / 1024, 2),
            "top_sessions": sessions[:3],
        }
    return summary


def backup_openclaw_config() -> dict:
    """E6: Back up current openclaw.json as a credential-safe copy."""
    cfg_path = OPENCLAW_ROOT / "openclaw.json"
    if not cfg_path.exists():
        return {"error": "not found"}

    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    backup_name = f"openclaw_{timestamp}.json"
    backup_path = BACKUP_DIR / backup_name

    with open(cfg_path) as f:
        raw_config = json.load(f)
    sanitized = sanitize_config(raw_config)
    with open(backup_path, "w") as f:
        json.dump(sanitized, f, indent=2, ensure_ascii=False)

    # Back up the latest bak file with the same credential-safe handling.
    bak_files = sorted(cfg_path.parent.glob("openclaw.json.bak*"))
    recent_bak = bak_files[-1] if bak_files else None
    if recent_bak and recent_bak != cfg_path:
        bak_backup_name = f"openclaw_recent_bak_{timestamp}_{recent_bak.name}"
        bak_backup_path = BACKUP_DIR / bak_backup_name
        try:
            with open(recent_bak) as f:
                raw_bak = json.load(f)
            with open(bak_backup_path, "w") as f:
                json.dump(sanitize_config(raw_bak), f, indent=2, ensure_ascii=False)
        except Exception:
            pass  # bak backup is best-effort

    return {
        "backup_path": str(backup_path),
        "backup_name": backup_name,
        "hash": file_hash(backup_path),
        "credentials_omitted": True,
    }


def diff_configs(path_a: str, path_b: str) -> dict:
    """E6: diff 两个 config 文件"""
    result = {"files_differ": False, "diff_lines": []}
    try:
        with open(path_a) as fa, open(path_b) as fb:
            lines_a = fa.readlines()
            lines_b = fb.readlines()
        if lines_a == lines_b:
            return result
        result["files_differ"] = True
        # 简单行对比
        max_len = max(len(lines_a), len(lines_b))
        for i in range(max_len):
            la = lines_a[i].rstrip() if i < len(lines_a) else None
            lb = lines_b[i].rstrip() if i < len(lines_b) else None
            if la != lb:
                result["diff_lines"].append({
                    "line": i + 1,
                    "old": la,
                    "new": lb,
                })
                if len(result["diff_lines"]) >= 50:
                    result["diff_lines"].append({"note": "... truncated after 50 diff lines"})
                    break
        return result
    except Exception as e:
        return {"error": str(e)}


def get_current_snapshot() -> dict:
    """获取当前 runtime snapshot（用于 diff）"""
    return read_openclaw_config()


def rollback_to_backup(backup_name: str, authorization_token: str = "") -> dict:
    """E6: 从备份回滚 openclaw.json

    Guarded operation chain: observe_only / backup / diff / audit / authorization.
    """
    # Step 0: observe_only 检查
    if OBSERVE_ONLY:
        log_runtime_change("rollback_blocked", False, {
            "reason": "observe_only=True",
            "backup_name": backup_name,
        })
        return {"error": "observe_only=True: rollback writes to OpenClaw runtime are blocked", "observe_only": True}

    # Step 1: authorization
    auth_ok, auth_err = check_authorization(authorization_token)
    if not auth_ok:
        log_runtime_change("rollback_blocked", False, {"reason": "unauthorized", "error": auth_err})
        return {"error": f"unauthorized: {auth_err}"}

    backup_path = BACKUP_DIR / backup_name
    cfg_path = OPENCLAW_ROOT / "openclaw.json"

    if not backup_path.exists():
        return {"error": f"backup not found: {backup_name}"}

    # Step 2: diff（写之前先对比）
    try:
        with open(backup_path) as bf, open(cfg_path) as cf:
            backup_content = bf.read()
            current_content = cf.read()
        diff_lines = []
        if backup_content != current_content:
            from difflib import unified_diff
            diff_lines = list(unified_diff(
                current_content.splitlines(keepends=True),
                backup_content.splitlines(keepends=True),
                fromfile="current", tofile=backup_name
            ))
    except Exception as e:
        diff_lines = [f"diff error: {e}"]

    # Step 3: 写之前先 backup 当前
    current_backup = backup_openclaw_config()

    # Step 4: 回滚
    shutil.copy2(backup_path, cfg_path)

    # Step 5: audit log
    log_runtime_change("rollback", True, {
        "rolled_back_to": str(backup_path),
        "current_preserved_as": current_backup.get("backup_path"),
        "diff_lines_count": len(diff_lines),
        "backup_name": backup_name,
    })

    return {
        "rolled_back_to": str(backup_path),
        "current_preserved_as": current_backup.get("backup_path"),
        "diff_preview": "".join(diff_lines[:10]),  # 前10行
        "audit_logged": True,
    }


# ─── API Server ───────────────────────────────────

from http.server import HTTPServer, BaseHTTPRequestHandler


class ConnectorHandler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass

    def send_json(self, data, code=200):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode())

    def do_GET(self):
        if self.path == "/health":
            self.send_json({"status": "ok", "service": "openclaw-runtime-connector"})
        elif self.path == "/config":
            cfg = read_openclaw_config()
            self.send_json(cfg)
        elif self.path == "/sessions_summary":
            summary = read_agents_sessions_summary()
            self.send_json(summary)
        elif self.path == "/logs":
            logs = read_openclaw_logs_summary()
            self.send_json(logs)
        elif self.path.startswith("/backup"):
            result = backup_openclaw_config()
            self.send_json(result)
        elif self.path == "/snapshot":
            snapshot = {
                "generated_at": ts(),
                "config": read_openclaw_config(),
                "logs_summary": read_openclaw_logs_summary(),
                "sessions_summary": read_agents_sessions_summary(),
            }
            self.send_json(snapshot)
        else:
            self.send_json({"error": "not found"}, 404)

    def do_POST(self):
        if self.path == "/rollback":
            # /rollback requires observe_only=False + authorization token.
            cl = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(cl).decode()) if cl > 0 else {}
            backup_name = body.get("backup_name", "")
            auth_token = body.get("authorization_token", "")
            result = rollback_to_backup(backup_name, authorization_token=auth_token)
            if "error" in result:
                self.send_json(result, 400)
            else:
                self.send_json(result)
        elif self.path == "/diff":
            cl = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(cl).decode()) if cl > 0 else {}
            path_a = body.get("path_a", "")
            path_b = body.get("path_b", "")
            result = diff_configs(path_a, path_b)
            self.send_json(result)
        else:
            self.send_json({"error": "not found"}, 404)


def run(port=9850):
    server = HTTPServer(("127.0.0.1", port), ConnectorHandler)
    print(f"[openclaw_connector] running on http://127.0.0.1:{port}")
    print(f"[openclaw_connector] endpoints: GET /health /config /sessions_summary /logs /backup /snapshot")
    print(f"[openclaw_connector] POST /rollback /diff")
    server.serve_forever()


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="memcore-cloud OpenClaw Runtime Connector")
    p.add_argument("--port", type=int, default=9850)
    args = p.parse_args()
    run(args.port)
