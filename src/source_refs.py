#!/usr/bin/env python3
"""
P9-System-SDC-B: source_refs — 统一溯源对象合同
==================================================
所有 source_system 必须使用此模块生成 source_refs。
source_refs 是知意对象的 provenance metadata，不可篡改。

source_refs 合同：
{
    "source_system": str,          # required: openclaw / hermes / local_files
    "computer_name": str,         # optional: hostname or computer id
    "canonical_window_id": str,   # optional: window-level isolation id
    "session_id": str,            # optional: session-level id
    "source_path": str,           # required: absolute path to source artifact
    "msg_ids": list[str],         # optional: specific message UUIDs
    "artifact_type": str,          # required: session_jsonl / local_file / etc.
    "captured_at": str,           # required: ISO8601 timestamp
    # openclaw-specific
    "agent_id": str,              # optional: openclaw agent id
    # local_files-specific
    "source_checksum": str,        # optional: SHA256 of source file
    "memory_id": str,             # optional: derived memory id
}

source_refs 只是回源定位信息。平台原始记录不在这里改写，raw 层保持原样。
"""

import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

UTC = timezone.utc

# 旧字段列表保留给 validate_source_refs 提醒调用方；不再静默改写字段值。
FORBIDDEN_REFS_FIELDS = {
    "token", "tokens", "api_key", "apikey", "api_key_b64",
    "password", "secret", "private_key", "privatekey", "client_secret",
    "auth_token", "access_token", "refresh_token", "bearer_token",
    "encryption_key", "secret_key", "message_content", "raw_content",
}


def ts():
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _preserve_refs(refs: dict) -> dict:
    """Compatibility no-op: source refs are not silently rewritten."""
    return dict(refs)


def make_source_refs_openclaw(
    source_path: str,
    session_id: str,
    canonical_window_id: str,
    agent_id: str = "",
    computer_name: str = "local",
    msg_ids: Optional[List[str]] = None,
    artifact_type: str = "session_jsonl",
) -> dict:
    """
    为 OpenClaw session 生成 source_refs。

    溯源链：session JSONL file → source_refs → matched_memory → injectable_prompt
    """
    refs = {
        "source_system": "openclaw",
        "computer_name": computer_name,
        "canonical_window_id": canonical_window_id,
        "session_id": session_id,
        "source_path": os.path.expanduser(source_path),
        "msg_ids": msg_ids or [],
        "artifact_type": artifact_type,
        "captured_at": ts(),
    }
    if agent_id:
        refs["agent_id"] = agent_id
    return _preserve_refs(refs)


def make_source_refs_local_files(
    source_path: str,
    source_checksum: str,
    memory_id: str = "",
    artifact_type: str = "local_file",
) -> dict:
    """
    为 local_files 生成 source_refs。
    """
    refs = {
        "source_system": "local_files",
        "source_path": source_path,
        "source_checksum": source_checksum,
        "artifact_type": artifact_type,
        "captured_at": ts(),
    }
    if memory_id:
        refs["memory_id"] = memory_id
    return _preserve_refs(refs)


def make_source_refs_hermes(
    source_path: str,
    session_id: str,
    canonical_window_id: str = "",
    computer_name: str = "local",
    msg_ids: Optional[List[str]] = None,
    artifact_type: str = "hermes_session",
) -> dict:
    """
    为 Hermes session 生成 source_refs（预留）。
    """
    refs = {
        "source_system": "hermes",
        "computer_name": computer_name,
        "canonical_window_id": canonical_window_id or session_id,
        "session_id": session_id,
        "source_path": source_path,
        "msg_ids": msg_ids or [],
        "artifact_type": artifact_type,
        "captured_at": ts(),
    }
    return _preserve_refs(refs)


def make_source_refs_codex(
    source_path: str,
    session_id: str,
    canonical_window_id: str = "",
    computer_name: str = "local",
    msg_ids: Optional[List[str]] = None,
    artifact_type: str = "codex_session_jsonl",
    project_root: str = "",
    thread_name: str = "",
) -> dict:
    """
    为 Codex rollout session 生成 source_refs。
    """
    refs = {
        "source_system": "codex",
        "computer_name": computer_name,
        "canonical_window_id": canonical_window_id or session_id,
        "session_id": session_id,
        "source_path": source_path,
        "msg_ids": msg_ids or [],
        "artifact_type": artifact_type,
        "captured_at": ts(),
    }
    if project_root:
        refs["project_root"] = project_root
    if thread_name:
        refs["thread_name"] = thread_name
    return _preserve_refs(refs)


def make_source_refs(
    source_system: str,
    **kwargs
) -> dict:
    """
    统一 factory：根据 source_system 调用对应生成函数。
    """
    if source_system == "openclaw":
        return make_source_refs_openclaw(**kwargs)
    elif source_system == "local_files":
        return make_source_refs_local_files(**kwargs)
    elif source_system == "hermes":
        return make_source_refs_hermes(**kwargs)
    elif source_system == "codex":
        return make_source_refs_codex(**kwargs)
    else:
        raise ValueError(f"Unknown source_system: {source_system}")


def validate_source_refs(refs: dict) -> tuple[bool, Optional[str]]:
    """
    验证 source_refs 合规性。

    必填字段：
    - source_system
    - source_path
    - artifact_type
    - captured_at

    提醒字段（检测到直接拒绝）：
    - 调用方不应该把配置凭据塞进 source_refs
    """
    required = ["source_system", "source_path", "artifact_type", "captured_at"]
    for field in required:
        if field not in refs or not refs[field]:
            return False, f"Missing required field: {field}"

    # 检查禁止字段
    refs_lower = {k.lower(): v for k, v in refs.items()}
    for forbidden in FORBIDDEN_REFS_FIELDS:
        if forbidden in refs_lower:
            return False, f"Forbidden field in source_refs: {forbidden}"

    # source_system 必须是已注册的
    valid_systems = {"openclaw", "local_files", "hermes", "codex"}
    if refs["source_system"] not in valid_systems:
        return False, f"Unknown source_system: {refs['source_system']}"

    return True, None


def source_refs_from_artifact(source_system: str, artifact: dict) -> dict:
    """
    从 artifact descriptor 直接生成 source_refs。
    artifact 格式由 source_system_profile.discover() 返回。
    """
    ts_str = artifact.get("_discovered_at", ts())
    base = {
        "source_system": source_system,
        "artifact_type": artifact.get("artifact_type", "unknown"),
        "source_path": artifact.get("source_path", ""),
        "captured_at": ts_str,
    }

    if source_system == "openclaw":
        base.update({
            "computer_name": artifact.get("computer_name", "local"),
            "canonical_window_id": artifact.get("canonical_window_id", artifact.get("agent_id", "")),
            "session_id": artifact.get("session_id", ""),
            "agent_id": artifact.get("agent_id", ""),
            "msg_ids": artifact.get("msg_ids", []),
        })
    elif source_system == "local_files":
        base.update({
            "source_checksum": artifact.get("checksum", artifact.get("source_checksum", "")),
            "memory_id": artifact.get("memory_id", ""),
        })
    elif source_system == "codex":
        base.update({
            "computer_name": artifact.get("computer_name", "local"),
            "canonical_window_id": artifact.get("canonical_window_id", artifact.get("project_id", "")),
            "session_id": artifact.get("session_id", ""),
            "msg_ids": artifact.get("msg_ids", []),
            "project_root": artifact.get("project_root", ""),
            "thread_name": artifact.get("thread_name", ""),
            "native_thread_id": artifact.get("native_thread_id", artifact.get("session_id", "")),
        })

    return _preserve_refs(base)


def compute_memory_id(content: str, source_path: str, checksum: str) -> str:
    """
    计算 local_files memory_id: SHA256(content + source_path + checksum)
    """
    h = hashlib.sha256()
    h.update((content + source_path + checksum).encode("utf-8"))
    return h.hexdigest()


# ── CLI ──────────────────────────────────────────────────────────────────────

def main():
    import argparse
    p = argparse.ArgumentParser(description="source_refs unified溯源对象生成器")
    p.add_argument("--source", default="openclaw", choices=["openclaw", "local_files", "hermes", "codex"], help="source_system")
    p.add_argument("--source-path", default="", help="source_path")
    p.add_argument("--session-id", default="", help="session_id (openclaw/hermes)")
    p.add_argument("--window", default="sg", help="canonical_window_id (openclaw)")
    p.add_argument("--checksum", default="", help="source_checksum (local_files)")
    p.add_argument("--validate", default="", help="验证已有 source_refs (JSON string)")
    args = p.parse_args()

    if args.validate:
        refs = json.loads(args.validate)
        valid, err = validate_source_refs(refs)
        print(f"valid: {valid}")
        if err:
            print(f"error: {err}")
        print(json.dumps(refs, indent=2, ensure_ascii=False))
        return

    if args.source == "openclaw":
        refs = make_source_refs_openclaw(
            source_path=args.source_path or "~/.openclaw/agents/sg/sessions/test.jsonl",
            session_id=args.session_id or "test-session",
            canonical_window_id=args.window,
            agent_id="sg",
        )
    elif args.source == "local_files":
        refs = make_source_refs_local_files(
            source_path=args.source_path or "/tmp/test.txt",
            source_checksum=args.checksum or "abc123",
        )
    else:
        refs = make_source_refs_hermes(
            source_path=args.source_path or "/tmp/hermes.jsonl",
            session_id=args.session_id or "test",
        )

    valid, err = validate_source_refs(refs)
    print(f"valid: {valid}")
    if err:
        print(f"error: {err}")
    print(json.dumps(refs, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
