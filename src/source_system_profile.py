#!/usr/bin/env python3
"""
SourceSystemProfile - 统一 Source System Profile 合同
=======================================================================
所有 source_system（openclaw / hermes / codex / local_files）必须实现此合同。

合同接口：
1. profile() -> dict: 返回 source_system 画像
2. discover() -> list[dict]: 发现可用 artifact
3. capture(source, dry_run=True) -> dict: 采集 artifact（不写 production raw）
4. source_refs(artifact) -> dict: 生成 source_refs 溯源对象

Profile 类型：
- lan_trusted: OpenClaw 同网段可信
- localhost_only: 仅本机访问
- remote_vpn: VPN 远程接入
- public_exposed: 公网暴露（严格身份验证）

Capture 分类：
- RAW: 原始 session 文件（只读，不写 raw）
- SHADOW: 影子采集（写到 memcore-cloud memory/）
- DERIVED: 派生对象（知意提取结果，写到 zhiyi/）
- EXTERNAL: 外部平台（不采集）
"""

import json
import os
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

UTC = timezone.utc

CAPTURE_RAW = "RAW"           # 原始 artifact，只读
CAPTURE_SHADOW = "SHADOW"     # 影子采集，写到 memcore-cloud memory/
CAPTURE_DERIVED = "DERIVED"   # 派生对象，写到 memcore-cloud zhiyi/
CAPTURE_EXTERNAL = "EXTERNAL"  # 外部平台，不采集


class SourceSystemProfile(ABC):
    """
    Source System Profile 抽象基类。
    所有 source_system 必须实现此合同。
    """

    @property
    @abstractmethod
    def source_system(self) -> str:
        """source_system 标识符，如 'openclaw' / 'hermes' / 'local_files'"""
        raise NotImplementedError

    @property
    def profile(self) -> str:
        """接入画像: lan_trusted / localhost_only / remote_vpn / public_exposed"""
        return "lan_trusted"

    @property
    def capture_classification(self) -> str:
        """主采集类型: RAW / SHADOW / DERIVED / EXTERNAL"""
        return "DERIVED"

    @property
    def scope_level(self) -> str:
        """隔离级别: window / file / project / global"""
        return "window"

    @abstractmethod
    def profile_info(self) -> dict:
        """返回 source_system 画像信息"""
        raise NotImplementedError

    @abstractmethod
    def discover(self) -> List[dict]:
        """
        发现可用 artifact。
        返回 list of artifact descriptors（不读取内容）。
        """
        raise NotImplementedError

    @abstractmethod
    def source_refs_from_artifact(self, artifact: dict) -> dict:
        """
        从 artifact descriptor 生成 source_refs 溯源对象。
        source_refs 格式：
        {
            "source_system": str,
            "computer_name": str,
            "canonical_window_id": str,
            "session_id": str,
            "source_path": str,
            "msg_ids": list[str],
            "artifact_type": str,
            "captured_at": str (ISO8601),
        }
        """
        raise NotImplementedError

    def capture(self, source: dict, dry_run: bool = True) -> dict:
        """
        采集 artifact。
        - dry_run=True: 仅报告，不写任何文件
        - dry_run=False: 写入 memcore-cloud memory/（SHADOW）或 zhiyi/（DERIVED）
        默认 dry_run=True（shadow capture）
        """
        return {
            "source_system": self.source_system,
            "artifact": source,
            "dry_run": dry_run,
            "capture_classification": self.capture_classification,
            "source_refs": self.source_refs_from_artifact(source),
            "skipped": dry_run,
            "note": "override capture() to implement real ingestion"
        }

    def validate_profile(self) -> tuple[bool, Optional[str]]:
        """
        验证 profile 合规性。
        返回 (is_valid, error_message)
        """
        required_fields = ["source_system", "profile", "capture_classification", "scope_level"]
        for field in required_fields:
            if not hasattr(self, field) or getattr(self, field) is None:
                return False, f"Missing required field: {field}"
        return True, None


class OpenClawProfile(SourceSystemProfile):
    """
    OpenClaw source_system profile 实现。
    实现 lan_trusted 接入，SHADOW + DERIVED 双通道采集。
    """

    @property
    def source_system(self) -> str:
        return "openclaw"

    @property
    def profile(self) -> str:
        return "lan_trusted"

    @property
    def capture_classification(self) -> str:
        return "SHADOW"  # 主通道：session 文件影子采集到 memcore-cloud memory/

    @property
    def scope_level(self) -> str:
        return "window"

    def profile_info(self) -> dict:
        # runtime_context detection (lazy import to avoid circular)
        try:
            from runtime_context import detect_runtime_context, wsl_windows_path_pair
            runtime_ctx = detect_runtime_context()
            wsl_info = wsl_windows_path_pair() if runtime_ctx == "wsl_guest" else {"is_wsl": False}
        except Exception:
            runtime_ctx = "unknown"
            wsl_info = {"is_wsl": False}

        return {
            "source_system": self.source_system,
            "profile": self.profile,
            "runtime_context": runtime_ctx,
            "cross_environment": wsl_info,
            "capture_classification": self.capture_classification,
            "scope_level": self.scope_level,
            "channels": {
                "shadow": {
                    "classification": "SHADOW",
                    "target": "memcore-cloud/memory/<window>/",
                    "source_artifacts": ["session JSONL files"],
                    "source_refs_type": "openclaw_session",
                },
                "derived": {
                    "classification": "DERIVED",
                    "target": "memcore-cloud/zhiyi/<type>/",
                    "source_artifacts": ["preference_memory", "case_memory", "error_memory"],
                    "source_refs_type": "openclaw_derived",
                }
            },
            "discovery_tool": "tools/openclaw_runtime_discovery.py",
            "access_profile": "config/openclaw_access_profile.json",
            "connector": "src/openclaw_runtime_connector.py",
            "catalog": "src/openclaw_session_catalog.py",
            "extract": "src/p2_extract.py",
            "capture_flow": "session JSONL → memory/ (shadow) → zhiyi/ (derived) → recall → inject",
            "new_core_guarantee": "All OpenClaw interactions route through p1→p2→p3→p4→zhiyi_gateway→dialog_entry_proxy. No raw/ direct write.",
        }

    def discover(self) -> List[dict]:
        """发现 OpenClaw runtime 中的 session artifacts"""
        from openclaw_runtime_connector import read_agents_sessions_summary
        summary = read_agents_sessions_summary()
        artifacts = []
        for agent_id, info in summary.items():
            for session in info.get("top_sessions", []):
                artifacts.append({
                    "source_system": "openclaw",
                    "agent_id": agent_id,
                    "session_id": session["session_id"],
                    "canonical_window_id": agent_id,  # agent_id as window proxy
                    "source_path": f"~/.openclaw/agents/{agent_id}/sessions/{session['session_id']}.jsonl",
                    "size_bytes": session["size_bytes"],
                    "size_mb": session["size_mb"],
                    "mtime": session["mtime"],
                    "hash": session["hash"],
                    "artifact_type": "session_jsonl",
                    "capture_classification": "SHADOW",
                })
            # also note agents with no sessions
            if info.get("sessions_count", 0) == 0:
                artifacts.append({
                    "source_system": "openclaw",
                    "agent_id": agent_id,
                    "sessions_count": 0,
                    "artifact_type": "agent_empty",
                    "capture_classification": "EXTERNAL",
                    "note": "no sessions to capture",
                })
        return artifacts

    def source_refs_from_artifact(self, artifact: dict) -> dict:
        """为 OpenClaw session artifact 生成 source_refs"""
        ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        return {
            "source_system": "openclaw",
            "computer_name": "local",
            "canonical_window_id": artifact.get("canonical_window_id", artifact.get("agent_id", "")),
            "session_id": artifact.get("session_id", ""),
            "source_path": artifact.get("source_path", ""),
            "msg_ids": [],  # session-level, no specific msg_ids until extract
            "artifact_type": artifact.get("artifact_type", "session_jsonl"),
            "captured_at": ts,
        }


class LocalFilesProfile(SourceSystemProfile):
    """
    Local Files source_system profile 实现。
    实现 local 接入，DERIVED 采集。
    """

    @property
    def source_system(self) -> str:
        return "local_files"

    @property
    def profile(self) -> str:
        return "local"

    @property
    def capture_classification(self) -> str:
        return "DERIVED"

    @property
    def scope_level(self) -> str:
        return "file"

    def profile_info(self) -> dict:
        return {
            "source_system": self.source_system,
            "profile": self.profile,
            "capture_classification": self.capture_classification,
            "scope_level": self.scope_level,
            "connector": "src/connectors/local_files_connector.py",
            "input_dir": "input/local_files/",
            "raw_dir": "memory/local_files/",
            "capture_flow": "input/local_files/ → memory/local_files/ (shadow) → source_refs",
            "idempotent": True,
        }

    def discover(self) -> List[dict]:
        """发现 input/local_files/ 下的文件"""
        from src.connectors.local_files_connector import discover
        items = discover()
        artifacts = []
        for item in items:
            artifacts.append({
                "source_system": "local_files",
                "source_path": item["source_path"],
                "filename": item["filename"],
                "size": item["size"],
                "checksum": item["checksum"],
                "modified_at": item["modified_at"],
                "artifact_type": "local_file",
                "capture_classification": "DERIVED",
            })
        return artifacts

    def source_refs_from_artifact(self, artifact: dict) -> dict:
        ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        return {
            "source_system": "local_files",
            "source_path": artifact.get("source_path", ""),
            "source_checksum": artifact.get("checksum", ""),
            "memory_id": "",  # filled by connector after ingest
            "artifact_type": artifact.get("artifact_type", "local_file"),
            "captured_at": ts,
        }


# ── Hermes Profile (Draft) ───────────────────────────────────────────────────

class HermesProfile(SourceSystemProfile):
    """
    Hermes source_system profile 实现。

    Hermes v0.11: 基于 Codestral / DeepSeek-V3-0324 的记忆管理 CLI。
    https://github.com/sophia- secrete/hermes

    Draft — 本机未安装，待真实环境验证。
    """

    @property
    def source_system(self) -> str:
        return "hermes"

    @property
    def profile(self) -> str:
        return "cli_trusted"

    @property
    def capture_classification(self) -> str:
        return "EXTERNAL"

    @property
    def scope_level(self) -> str:
        return "session"

    def profile_info(self) -> dict:
        return {
            "source_system": self.source_system,
            "profile": self.profile,
            "capture_classification": self.capture_classification,
            "scope_level": self.scope_level,
            "status": "PROBED",
            "description": "Hermes v0.11 CLI memory management — shadow pilot (PROBED)",
            "artifact_types": ["memory_db", "preferences", "session_log"],
            "expected_locations": [
                "$HOME/.hermes/memory.db",
                "$HOME/.hermes/preferences.json",
                "$HOME/.hermes/sessions/",
            ],
            "credential_requirements": ["hermes_api_key"],
            "discovery_status": "PROBED",
            "real_locations": {
                "state_db": "$HOME/.hermes/state.db",
                "sessions": "$HOME/.hermes/sessions/*.json",
                "auth_json": "$HOME/.hermes/auth.json (EXISTS, token content NOT READ)",
            },
        }

    def discover(self) -> List[dict]:
        """Discover real Hermes artifacts (shadow, read-only probe)."""
        from pathlib import Path
        import os
        hermes_root = Path(os.path.expanduser("~/.hermes"))
        if not hermes_root.exists():
            return []

        artifacts = []
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        # Session files
        sessions_dir = hermes_root / "sessions"
        if sessions_dir.is_dir():
            for f in sorted(sessions_dir.glob("session_*.json")):
                size = f.stat().st_size
                mtime = datetime.fromtimestamp(f.stat().st_mtime, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                artifacts.append({
                    "source_system": "hermes",
                    "artifact_type": "session_json",
                    "source_path": str(f),
                    "filename": f.name,
                    "size_bytes": size,
                    "size_mb": round(size / 1024 / 1024, 3),
                    "mtime": mtime,
                    "capture_classification": "SHADOW",
                    "read_only_probe": True,
                    "discovered_at": ts,
                })

        # Request dump files
        if sessions_dir.is_dir():
            for f in sorted(sessions_dir.glob("request_dump_*.json")):
                size = f.stat().st_size
                mtime = datetime.fromtimestamp(f.stat().st_mtime, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                artifacts.append({
                    "source_system": "hermes",
                    "artifact_type": "request_dump_json",
                    "source_path": str(f),
                    "filename": f.name,
                    "size_bytes": size,
                    "size_mb": round(size / 1024 / 1024, 3),
                    "mtime": mtime,
                    "capture_classification": "SHADOW",
                    "read_only_probe": True,
                    "discovered_at": ts,
                })

        # State database (memory store)
        state_db = hermes_root / "state.db"
        if state_db.exists():
            size = state_db.stat().st_size
            mtime = datetime.fromtimestamp(state_db.stat().st_mtime, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            artifacts.append({
                "source_system": "hermes",
                "artifact_type": "state_db",
                "source_path": str(state_db),
                "filename": "state.db",
                "size_bytes": size,
                "size_mb": round(size / 1024 / 1024, 3),
                "mtime": mtime,
                "capture_classification": "EXTERNAL",
                "read_only_probe": True,
                "discovered_at": ts,
            })

        # Auth.json — exists but DO NOT read token/credential content
        auth_json = hermes_root / "auth.json"
        if auth_json.exists():
            size = auth_json.stat().st_size
            mtime = datetime.fromtimestamp(auth_json.stat().st_mtime, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            artifacts.append({
                "source_system": "hermes",
                "artifact_type": "auth_json",
                "source_path": str(auth_json),
                "filename": "auth.json",
                "size_bytes": size,
                "size_mb": round(size / 1024 / 1024, 3),
                "mtime": mtime,
                "capture_classification": "EXTERNAL",
                "read_only_probe": True,
                "credential_risk": "HIGH — token content NOT read per constraints",
                "discovered_at": ts,
            })

        return artifacts

    def source_refs_from_artifact(self, artifact: dict) -> dict:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        return {
            "source_system": self.source_system,
            "source_path": artifact.get("source_path", ""),
            "source_checksum": "",
            "memory_id": "",
            "artifact_type": artifact.get("artifact_type", "unknown"),
            "capture_classification": artifact.get("capture_classification", "SHADOW"),
            "filename": artifact.get("filename", ""),
            "size_bytes": artifact.get("size_bytes", 0),
            "mtime": artifact.get("mtime", ""),
            "discovered_at": artifact.get("discovered_at", ts),
        }

    def validate_profile(self) -> tuple[bool, str]:
        return False, "HermesProfile is DRAFT — not tested on real environment"


# ── Codex Profile (Draft) ─────────────────────────────────────────────────────

class CodexProfile(SourceSystemProfile):
    """
    Codex profile 实现。

    Codex local app/CLI session history.
    State observed in: ~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl
    Thread index observed in: ~/.codex/session_index.jsonl
    """

    @property
    def source_system(self) -> str:
        return "codex"

    @property
    def profile(self) -> str:
        return "cli_trusted"

    @property
    def capture_classification(self) -> str:
        return "SHADOW"

    @property
    def scope_level(self) -> str:
        return "project"

    def profile_info(self) -> dict:
        return {
            "source_system": self.source_system,
            "profile": self.profile,
            "capture_classification": self.capture_classification,
            "scope_level": self.scope_level,
            "status": "ACTIVE",
            "description": "Codex local rollout JSONL profile",
            "artifact_types": ["codex_session_jsonl", "session_index_jsonl"],
            "expected_locations": [
                "$HOME/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl",
                "$HOME/.codex/session_index.jsonl",
            ],
            "credential_requirements": [],
            "discovery_status": "LOCAL_TESTED",
            "connector": "src/codex_local_connector.py",
            "capture_flow": "Codex rollout JSONL -> memory/codex/<node>/<project>/ -> zhiyi/ (derived)",
            "write_boundary": "read local Codex session records and archive an independent raw copy; never write Codex runtime",
        }

    def discover(self) -> List[dict]:
        from codex_local_connector import discover_sessions
        return discover_sessions()

    def source_refs_from_artifact(self, artifact: dict) -> dict:
        from codex_local_connector import source_refs_from_artifact
        return source_refs_from_artifact(artifact)

    def validate_profile(self) -> tuple[bool, str]:
        return True, ""


# ── Profile Registry ──────────────────────────────────────────────────────────

_PROFILE_REGISTRY = {
    "openclaw": OpenClawProfile,
    "local_files": LocalFilesProfile,
    "hermes": HermesProfile,
    "codex": CodexProfile,
}


def get_profile(source_system: str) -> SourceSystemProfile:
    """获取指定 source_system 的 profile 实例"""
    cls = _PROFILE_REGISTRY.get(source_system)
    if cls is None:
        raise ValueError(f"Unknown source_system: {source_system}. Available: {list(_PROFILE_REGISTRY.keys())}")
    return cls()


def list_registered_profiles() -> List[str]:
    """列出所有已注册的 source_system"""
    return list(_PROFILE_REGISTRY.keys())


def validate_all_profiles() -> dict:
    """验证所有已注册 profile 的合规性"""
    results = {}
    for name in _PROFILE_REGISTRY:
        profile = get_profile(name)
        valid, err = profile.validate_profile()
        results[name] = {"valid": valid, "error": err, "profile_info": profile.profile_info() if valid else None}
    return results


# ── CLI ──────────────────────────────────────────────────────────────────────

def main():
    import argparse
    p = argparse.ArgumentParser(description="SourceSystemProfile registry")
    p.add_argument("--list", action="store_true", help="列出所有 profile")
    p.add_argument("--profile", default="", help="查看指定 profile 详情")
    p.add_argument("--discover", default="", help="discover 指定 source_system")
    p.add_argument("--validate", action="store_true", help="验证所有 profile 合规性")
    args = p.parse_args()

    if args.list:
        print("Registered profiles:", list_registered_profiles())

    elif args.profile:
        prof = get_profile(args.profile)
        print(json.dumps(prof.profile_info(), indent=2, ensure_ascii=False))

    elif args.discover:
        prof = get_profile(args.discover)
        artifacts = prof.discover()
        print(json.dumps(artifacts, indent=2, ensure_ascii=False))

    elif args.validate:
        results = validate_all_profiles()
        for name, result in results.items():
            status = "✅" if result["valid"] else f"❌ {result['error']}"
            print(f"  {name}: {status}")

    else:
        p.print_help()


if __name__ == "__main__":
    main()
