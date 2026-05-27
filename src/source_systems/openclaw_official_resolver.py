from __future__ import annotations

import json
import os
import platform
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any, Dict, List, Optional


RESOLVER_VERSION = "v1"
SOURCE_SYSTEM = "openclaw"
SOURCE_VARIANT = "official"


@dataclass
class ServiceInfo:
    type: str = "none"
    name: str = ""
    action: str = ""
    working_directory: str = ""


@dataclass
class ProcessInfo:
    pid: Optional[int] = None
    cmdline: str = ""
    cwd: str = ""


@dataclass
class ActiveInstance:
    instance_id: str = ""
    active: bool = True
    confidence: str = "medium"
    evidence_refs: List[str] = field(default_factory=list)
    config_path: str = ""
    state_dir: str = ""
    agent_id: str = "main"
    workspace_paths: List[str] = field(default_factory=list)
    sessions_paths: List[str] = field(default_factory=list)
    agent_dir: str = ""
    memory_paths: List[str] = field(default_factory=list)
    logs_paths: List[str] = field(default_factory=list)
    process: ProcessInfo = field(default_factory=ProcessInfo)
    service: ServiceInfo = field(default_factory=ServiceInfo)


def _os_name() -> str:
    sys = platform.system().lower()
    if sys.startswith("win"):
        return "windows"
    if sys == "darwin":
        return "macos"
    if sys == "linux":
        return "linux"
    return "unknown"


def _home() -> Path:
    return Path(os.path.expanduser("~"))


def resolve_state_dir() -> Path:
    env = os.environ.get("OPENCLAW_STATE_DIR")
    if env:
        return Path(env)
    env = os.environ.get("OPENCLAW_HOME")
    if env:
        return Path(env)
    return _home() / ".openclaw"


def load_openclaw_config(config_path: Optional[Path] = None) -> Dict[str, Any]:
    if config_path is None:
        config_path = resolve_state_dir() / "openclaw.json"
    else:
        config_path = Path(config_path)
    if not config_path.exists():
        return {"_path": str(config_path), "agents": {}, "missing": True}
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        return {"_path": str(config_path), "agents": cfg.get("agents", {}), "missing": False, **cfg}
    except Exception as e:
        return {"_path": str(config_path), "agents": {}, "missing": True, "error": str(e)}


def resolve_agents_from_filesystem(state_dir: Path) -> List[str]:
    agents: List[str] = []
    seen: set = set()
    agents_dir = state_dir / "agents"
    if agents_dir.is_dir():
        for child in sorted(agents_dir.iterdir()):
            if child.is_dir() and not child.name.startswith("."):
                if child.name not in seen:
                    seen.add(child.name)
                    agents.append(child.name)
    if state_dir.is_dir():
        for child in sorted(state_dir.iterdir()):
            name = child.name
            if name.startswith("workspace-") and child.is_dir():
                agent_id = name[len("workspace-"):]
                if agent_id not in seen:
                    seen.add(agent_id)
                    agents.append(agent_id)
    return agents


def resolve_config_agents(cfg: Dict[str, Any]) -> List[str]:
    agents = cfg.get("agents")
    if isinstance(agents, dict):
        return [str(k) for k in agents.keys()]
    return []


def resolve_agents(cfg: Dict[str, Any], state_dir: Optional[Path] = None) -> List[str]:
    if state_dir is None:
        state_dir = resolve_state_dir()
    config_ids = resolve_config_agents(cfg)
    fs_ids = resolve_agents_from_filesystem(state_dir)
    seen: set = set()
    merged: List[str] = []
    for aid in fs_ids + config_ids:
        if aid not in seen:
            seen.add(aid)
            merged.append(aid)
    if not merged:
        merged = ["main"]
    return merged


def _is_agent_materialized(state_dir: Path, agent_id: str) -> bool:
    agent_dir = state_dir / "agents" / agent_id
    if agent_dir.is_dir():
        return True
    sessions_dir = state_dir / "agents" / agent_id / "sessions"
    if sessions_dir.is_dir():
        return True
    ws = state_dir / f"workspace-{agent_id}"
    if ws.is_dir():
        return True
    return False


def resolve_workspace_paths(state_dir: Path, cfg: Dict[str, Any], agent_id: str) -> List[Path]:
    paths: List[Path] = []
    agents_cfg = cfg.get("agents")
    if isinstance(agents_cfg, dict):
        agent_cfg = agents_cfg.get(agent_id)
        if isinstance(agent_cfg, dict) and agent_cfg.get("workspace"):
            raw = str(agent_cfg["workspace"])
            paths.append(Path(os.path.expanduser(raw)))
    paths.append(state_dir / "workspace")
    paths.append(state_dir / f"workspace-{agent_id}")
    return _unique(paths)


def resolve_sessions_paths(state_dir: Path, agent_id: str) -> List[Path]:
    return [state_dir / "agents" / agent_id / "sessions"]


def resolve_agent_dirs(state_dir: Path, agent_id: str) -> List[str]:
    d = state_dir / "agents" / agent_id / "agent"
    return [str(d)]


def resolve_memory_paths(state_dir: Path, agent_id: str) -> List[Path]:
    return [
        state_dir / "memory" / "main.sqlite",
        state_dir / f"workspace-{agent_id}" / "memory",
    ]


def resolve_logs_paths(state_dir: Path) -> List[Path]:
    return [state_dir / "logs"]


def _exists(p: str) -> bool:
    return Path(p).exists()


def detect_dangling_bindings(instances: List[ActiveInstance]) -> List[Dict[str, Any]]:
    dangling: List[Dict[str, Any]] = []
    for inst in instances:
        for p in (inst.workspace_paths + inst.sessions_paths + inst.memory_paths + inst.logs_paths):
            if not _exists(str(p)):
                dangling.append({
                    "instance_id": inst.instance_id,
                    "path": str(p),
                    "kind": "missing_binding",
                })
    return dangling


def detect_stale_candidates(instances: List[ActiveInstance]) -> List[Dict[str, Any]]:
    stale: List[Dict[str, Any]] = []
    seen: set = set()
    for inst in instances:
        for p in (inst.workspace_paths + inst.sessions_paths):
            ps = str(p)
            if ps in seen:
                stale.append({"instance_id": inst.instance_id, "path": ps, "kind": "duplicate_path"})
            seen.add(ps)
    return stale


def detect_duplicate_candidates(instances: List[ActiveInstance]) -> List[Dict[str, Any]]:
    by_agent: Dict[str, List[ActiveInstance]] = {}
    for inst in instances:
        by_agent.setdefault(inst.agent_id, []).append(inst)
    dup: List[Dict[str, Any]] = []
    for aid, items in by_agent.items():
        if len(items) > 1:
            dup.append({
                "agent_id": aid,
                "instance_ids": [i.instance_id for i in items],
            })
    return dup


def build_resolver_report() -> Dict[str, Any]:
    state_dir = resolve_state_dir()
    cfg = load_openclaw_config()
    config_ids = resolve_config_agents(cfg)
    all_ids = resolve_agents(cfg, state_dir)
    active_instances: List[ActiveInstance] = []
    dangling_config_instances: List[ActiveInstance] = []
    for agent_id in all_ids:
        materialized = _is_agent_materialized(state_dir, agent_id)
        inst = ActiveInstance(
            instance_id=f"openclaw-{agent_id}",
            active=materialized,
            confidence="high" if materialized else "low",
            evidence_refs=[],
            config_path=str(cfg.get("_path", "")),
            state_dir=str(state_dir),
            agent_id=agent_id,
            workspace_paths=[str(p) for p in resolve_workspace_paths(state_dir, cfg, agent_id)],
            sessions_paths=[str(p) for p in resolve_sessions_paths(state_dir, agent_id)],
            agent_dir=resolve_agent_dirs(state_dir, agent_id)[0],
            memory_paths=[str(p) for p in resolve_memory_paths(state_dir, agent_id)],
            logs_paths=[str(p) for p in resolve_logs_paths(state_dir)],
            service=ServiceInfo(type="none"),
        )
        if materialized:
            active_instances.append(inst)
        else:
            dangling_config_instances.append(inst)

    report: Dict[str, Any] = {
        "source_system": SOURCE_SYSTEM,
        "source_variant": SOURCE_VARIANT,
        "resolver_version": RESOLVER_VERSION,
        "os": _os_name(),
        "detected": bool(active_instances),
        "confidence": "high" if active_instances else "medium",
        "active_instances": [asdict(i) for i in active_instances],
        "stale_candidates": detect_stale_candidates(active_instances),
        "duplicate_instances": detect_duplicate_candidates(active_instances),
        "dangling_bindings": detect_dangling_bindings(active_instances + dangling_config_instances),
        "warnings": [
            "Windows native Hermes may live in WSL; do not infer absence from native non-discovery.",
        ],
    }
    return report


def resolve_openclaw_official_instances() -> Dict[str, Any]:
    return build_resolver_report()


def resolve_openclaw_official_for_current_user() -> Dict[str, Any]:
    return build_resolver_report()


def _unique(items: List[Any]) -> List[Any]:
    out: List[Any] = []
    seen: set = set()
    for item in items:
        key = str(item)
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out


# ══════════════════════════════════════════════════════════════════════════════
# G6 FIX: SourceSystemProfile Contract Wrapper
# ══════════════════════════════════════════════════════════════════════════════
# G6 Issue: openclaw_official_resolver bypassed SourceSystemProfile contract.
# Fix: Wrap resolver output in SourceSystemProfile-compatible adapter contract.
# ══════════════════════════════════════════════════════════════════════════════

# ── Adapter Verdict for OpenClaw ────────────────────────────────────────────

OPENCLAW_ADAPTER_VERDICT = {
    "adapter": "OpenClawOfficialResolver",
    "version": RESOLVER_VERSION,
    "source_system": SOURCE_SYSTEM,
    "source_variant": SOURCE_VARIANT,
    "production_ready": False,  # G6 fix does not imply production ready
    "memory_write_enabled": False,  # resolver is read-only discovery
    "skill_write_enabled": False,
    "context_delivery_executed": False,
    "gateway_reachable": None,  # not applicable for OpenClaw resolver
    "bypass_resolved": True,  # G6 resolved — now SourceSystemProfile-compliant
    "legacy_resolver_wrapped": True,  # wrapper provides contract compatibility
    "route_status": "CANDIDATE",  # staged only, not consumed
    "notes": [
        "G6 fix: openclaw_official_resolver wrapped with SourceSystemProfile contract",
        "OpenClaw resolver is read-only discovery — no memory/skill write",
        "Public contract fields: source_system_id, capture_classification, permission_boundary",
        "Production ready requires 甲方 explicit authorization",
    ],
}


# ── Capture classification for OpenClaw artifacts ────────────────────────

OPENCLAW_CAPTURE_CLASSIFICATION = "SHADOW"
# SHADOW = session files readable via resolver, not written by resolver
# OpenClaw workspace sessions are discovered but not modified by this resolver


# ── Permission boundary (public contract) ────────────────────────────────

OPENCLAW_PERMISSION_BOUNDARY = {
    "memory_write_enabled": False,
    "skill_write_enabled": False,
    "context_delivery_executed": False,
    "production_ready": False,
    "apply_to_platform_blocked": True,
    "note": (
        "OpenClaw resolver is read-only discovery. "
        "No writes to memory, skill, or context delivery. "
        "Platform-specific paths retained inside adapter boundary."
    ),
}


# ── SourceSystemProfile-compatible wrapper ────────────────────────────────

def resolve_openclaw_source_system_profile() -> dict:
    """
    G6 Fix: Wrap openclaw_official_resolver output in SourceSystemProfile contract.

    Returns a SourceSystemProfile-compatible dict with:
    - source_system_id: "openclaw"
    - capture_classification: SHADOW
    - permission_boundary
    - adapter_verdict
    - resolver_output (raw OpenClaw data, platform-specific details retained)

    This function resolves the G6 bypass: OpenClaw resolver no longer bypasses
    SourceSystemProfile contract. Instead it wraps the output in the contract.

    Platform-specific details (WS RPC / 18789 / workspace-main paths) are
    retained inside the resolver_output and are NOT part of the public contract.
    """
    raw_report = build_resolver_report()

    # Build SourceSystemProfile-compatible output
    profile_compatible = {
        # ── Public contract fields ─────────────────────────────
        "source_system_id": SOURCE_SYSTEM,
        "capture_classification": OPENCLAW_CAPTURE_CLASSIFICATION,
        "permission_boundary": OPENCLAW_PERMISSION_BOUNDARY.copy(),
        "adapter_verdict": OPENCLAW_ADAPTER_VERDICT.copy(),
        # ── Contract metadata ────────────────────────────────
        "resolver_version": RESOLVER_VERSION,
        "source_variant": SOURCE_VARIANT,
        "os": _os_name(),
        "profile_type": "lan_trusted",
        "bypass_resolved": True,
        "legacy_resolver_wrapped": True,
        # ── Public artifact summary (no platform detail) ───
        "active_instances_count": len(raw_report.get("active_instances", [])),
        "detected": raw_report.get("detected", False),
        "confidence": raw_report.get("confidence", "unknown"),
        "instance_ids": [
            inst["instance_id"]
            for inst in raw_report.get("active_instances", [])
        ],
        # ── Raw resolver output (platform-specific, private) ─
        # Retained inside adapter — not part of public contract
        "_resolver_output": raw_report,
    }

    return profile_compatible


def get_openclaw_adapter_verdict() -> dict:
    """
    Convenience: return the OpenClaw adapter verdict.
    """
    return OPENCLAW_ADAPTER_VERDICT.copy()


def get_openclaw_capability_profile() -> dict:
    """
    Convenience: return the OpenClaw capability profile compatible with
    the TiandaoAdapter consumption route format.
    """
    return {
        "adapter": "OpenClawOfficialResolver",
        "version": RESOLVER_VERSION,
        "source_system": SOURCE_SYSTEM,
        "direction": "openclaw → tiandao",
        "can_write_memory": False,
        "can_write_skill": False,
        "is_production_ready": False,
        "artifact_types_supported": [
            "openclaw_session",
            "openclaw_workspace",
            "openclaw_config",
            "openclaw_agent",
        ],
        "capture_classification_map": {
            "openclaw_session": "SHADOW",
            "openclaw_workspace": "SHADOW",
            "openclaw_config": "RAW",
            "openclaw_agent": "SHADOW",
        },
        "forbidden_fields_stripped": [],
        "bypass_resolved": True,
        "gateway_endpoint": None,
    }
