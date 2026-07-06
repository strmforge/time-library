#!/usr/bin/env python3
"""
source_refs - 统一溯源对象合同
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
2026.6.1 起，新装和新增 raw 写入全面使用 computer_name/source_system/native_artifact_format；
历史 source_system/computer_name 路径只作为兼容读取，不再作为新增写入形状。
"""

import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

try:
    from src.source_system_runtime_declarations import source_system_source_ref_kind
except ImportError:
    from source_system_runtime_declarations import source_system_source_ref_kind

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


def _make_source_refs_generic(source_system: str, **kwargs) -> dict:
    refs = {
        "source_system": source_system,
        "source_path": os.path.expanduser(str(kwargs.get("source_path") or "")),
        "artifact_type": str(kwargs.get("artifact_type") or "unknown"),
        "captured_at": ts(),
    }
    computer_name = str(kwargs.get("computer_name") or "").strip()
    canonical_window_id = str(kwargs.get("canonical_window_id") or "").strip()
    session_id = str(kwargs.get("session_id") or "").strip()
    msg_ids = kwargs.get("msg_ids")
    if computer_name:
        refs["computer_name"] = computer_name
    if canonical_window_id:
        refs["canonical_window_id"] = canonical_window_id
    if session_id:
        refs["session_id"] = session_id
    if isinstance(msg_ids, list):
        refs["msg_ids"] = msg_ids
    for key in ("project_root", "thread_name", "native_thread_id", "agent_id", "source_checksum", "memory_id"):
        value = kwargs.get(key)
        if value:
            refs[key] = value
    return _preserve_refs(refs)


def _make_source_refs_with_agent_session(
    source_system: str,
    source_path: str,
    session_id: str,
    canonical_window_id: str,
    agent_id: str = "",
    computer_name: str = "local",
    msg_ids: Optional[List[str]] = None,
    artifact_type: str = "session_jsonl",
) -> dict:
    refs = {
        "source_system": source_system,
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


def _make_source_refs_with_file_checksum(
    source_system: str,
    source_path: str,
    source_checksum: str,
    memory_id: str = "",
    artifact_type: str = "local_file",
) -> dict:
    refs = {
        "source_system": source_system,
        "source_path": source_path,
        "source_checksum": source_checksum,
        "artifact_type": artifact_type,
        "captured_at": ts(),
    }
    if memory_id:
        refs["memory_id"] = memory_id
    return _preserve_refs(refs)


def _make_source_refs_with_session_window(
    source_system: str,
    source_path: str,
    session_id: str,
    canonical_window_id: str = "",
    computer_name: str = "local",
    msg_ids: Optional[List[str]] = None,
    artifact_type: str = "session_jsonl",
) -> dict:
    refs = {
        "source_system": source_system,
        "computer_name": computer_name,
        "canonical_window_id": canonical_window_id or session_id,
        "session_id": session_id,
        "source_path": source_path,
        "msg_ids": msg_ids or [],
        "artifact_type": artifact_type,
        "captured_at": ts(),
    }
    return _preserve_refs(refs)


def _make_source_refs_with_project_session_window(
    source_system: str,
    source_path: str,
    session_id: str,
    canonical_window_id: str = "",
    computer_name: str = "local",
    msg_ids: Optional[List[str]] = None,
    artifact_type: str = "session_jsonl",
    project_root: str = "",
    thread_name: str = "",
) -> dict:
    refs = {
        "source_system": source_system,
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
    return _make_source_refs_with_agent_session(
        "openclaw",
        source_path=source_path,
        session_id=session_id,
        canonical_window_id=canonical_window_id,
        agent_id=agent_id,
        computer_name=computer_name,
        msg_ids=msg_ids,
        artifact_type=artifact_type,
    )


def make_source_refs_local_files(
    source_path: str,
    source_checksum: str,
    memory_id: str = "",
    artifact_type: str = "local_file",
) -> dict:
    """
    为 local_files 生成 source_refs。
    """
    return _make_source_refs_with_file_checksum(
        "local_files",
        source_path=source_path,
        source_checksum=source_checksum,
        memory_id=memory_id,
        artifact_type=artifact_type,
    )


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
    return _make_source_refs_with_session_window(
        "hermes",
        source_path=source_path,
        session_id=session_id,
        canonical_window_id=canonical_window_id,
        computer_name=computer_name,
        msg_ids=msg_ids,
        artifact_type=artifact_type,
    )


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
    return _make_source_refs_with_project_session_window(
        "codex",
        source_path=source_path,
        session_id=session_id,
        canonical_window_id=canonical_window_id,
        computer_name=computer_name,
        msg_ids=msg_ids,
        artifact_type=artifact_type,
        project_root=project_root,
        thread_name=thread_name,
    )


SOURCE_REF_BUILDERS = {
    "agent_session_window_refs": _make_source_refs_with_agent_session,
    "file_checksum_refs": _make_source_refs_with_file_checksum,
    "session_window_refs": _make_source_refs_with_session_window,
    "project_session_window_refs": _make_source_refs_with_project_session_window,
}


def make_source_refs(
    source_system: str,
    **kwargs
) -> dict:
    """
    统一 factory：根据 source_system 调用对应生成函数。
    """
    source_ref_kind = source_system_source_ref_kind(source_system)
    builder = SOURCE_REF_BUILDERS.get(source_ref_kind)
    if builder is not None:
        return builder(source_system, **kwargs)
    return _make_source_refs_generic(source_system, **kwargs)


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

    artifact_expanders = {
        "agent_session_window_refs": lambda data: {
            "computer_name": data.get("computer_name", "local"),
            "canonical_window_id": data.get("canonical_window_id", data.get("agent_id", "")),
            "session_id": data.get("session_id", ""),
            "agent_id": data.get("agent_id", ""),
            "msg_ids": data.get("msg_ids", []),
        },
        "file_checksum_refs": lambda data: {
            "source_checksum": data.get("checksum", data.get("source_checksum", "")),
            "memory_id": data.get("memory_id", ""),
        },
        "project_session_window_refs": lambda data: {
            "computer_name": data.get("computer_name", "local"),
            "canonical_window_id": data.get("canonical_window_id", data.get("project_id", "")),
            "session_id": data.get("session_id", ""),
            "msg_ids": data.get("msg_ids", []),
            "project_root": data.get("project_root", ""),
            "thread_name": data.get("thread_name", ""),
            "native_thread_id": data.get("native_thread_id", data.get("session_id", "")),
        },
        "session_window_refs": lambda data: {
            "computer_name": data.get("computer_name", "local"),
            "canonical_window_id": data.get("canonical_window_id", data.get("session_id", "")),
            "session_id": data.get("session_id", ""),
            "msg_ids": data.get("msg_ids", []),
        },
    }
    expander = artifact_expanders.get(source_system_source_ref_kind(source_system))
    if expander is not None:
        base.update(expander(artifact))

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

    sample_kwargs = {
        "openclaw": {
            "source_path": args.source_path or "~/.openclaw/agents/sg/sessions/test.jsonl",
            "session_id": args.session_id or "test-session",
            "canonical_window_id": args.window,
            "agent_id": "sg",
        },
        "local_files": {
            "source_path": args.source_path or "/tmp/test.txt",
            "source_checksum": args.checksum or "abc123",
        },
        "hermes": {
            "source_path": args.source_path or "/tmp/hermes.jsonl",
            "session_id": args.session_id or "test",
        },
        "codex": {
            "source_path": args.source_path or "~/.codex/sessions/test.jsonl",
            "session_id": args.session_id or "test",
            "canonical_window_id": args.window,
        },
    }
    refs = make_source_refs(args.source, **sample_kwargs.get(args.source, {}))

    valid, err = validate_source_refs(refs)
    print(f"valid: {valid}")
    if err:
        print(f"error: {err}")
    print(json.dumps(refs, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
