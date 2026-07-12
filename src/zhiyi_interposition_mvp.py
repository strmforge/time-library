#!/usr/bin/env python3
"""
Zhiyi interposition MVP
最小 staged context-file / sidecar-style interposition package。

本模块只生成可审计、可回滚、可投递的 staged context package，
不修改平台配置，不写生产 raw / zhiyi / LanceDB。

Interposition Tiandao adapter link
新增：adapter contract 集成
- InterpositionRequest 支持 adapter_contract 可选输入
- context_package.json 携带 adapter_verdict / consumption_route / capability_profile
- interposition_plan.json 携带 route_id / route_type / route_status
- audit_event.jsonl 记录 adapter_verdict
- apply_to_platform=true 仍返回 APPLY_BLOCKED
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import uuid
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.runtime_context_package import ContextPackage


UTC = timezone.utc

STATUS_OBSERVE_ONLY = "OBSERVE_ONLY"
STATUS_STAGED_CONTEXT_FILE = "STAGED_CONTEXT_FILE"
STATUS_APPLY_BLOCKED = "APPLY_BLOCKED"
STATUS_LOW_CONFIDENCE_BLOCKED = "LOW_CONFIDENCE_BLOCKED"
STATUS_SCOPE_BLOCKED = "SCOPE_BLOCKED"
STATUS_ERROR = "ERROR"

MODE_CONTEXT_FILE = "context_file"
MODE_OBSERVE_ONLY = "observe_only"

# ── TiandaoAdapter contract route status ──────────────────────────────────────
ROUTE_STATUS_CANDIDATE = "CANDIDATE"  # staged, not consumed
ROUTE_STATUS_APPLIED = "APPLIED"       # consumed by platform
ROUTE_STATUS_BLOCKED = "BLOCKED"       # rejected by gate


def ts() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def hash_query(query: str) -> str:
    return hashlib.sha256(query.encode("utf-8")).hexdigest()


def query_summary(query: str, limit: int = 48) -> str:
    text = (query or "").strip().replace("\n", " ")
    return text[:limit] + ("..." if len(text) > limit else "")


# ── ConsumptionRoute helpers ──────────────────────────────────────────────────

def build_consumption_route(
    adapter_contract: Optional[Dict[str, Any]],
    source_system: str,
) -> Dict[str, Any]:
    """
    Build a ConsumptionRoute dict from an adapter_contract dict.

    The adapter_contract is provided by the caller (e.g., HermesToTiandaoAdapter
    via get_hermes_adapter_verdict() + get_hermes_adapter_capability_profile()).

    Returns a ConsumptionRoute-compatible dict with route metadata.
    """
    if adapter_contract is None:
        return {
            "route_id": f"route-{source_system}-none",
            "route_type": "source_system_adapter",
            "route_status": ROUTE_STATUS_CANDIDATE,
            "source_system": source_system,
            "adapter": "none",
            "production_ready": False,
            "memory_write_enabled": False,
            "skill_write_enabled": False,
            "context_delivery_executed": False,
            "notes": ["No adapter_contract provided — route is a placeholder"],
        }

    # Extract from adapter verdict if available
    verdict = adapter_contract.get("adapter_verdict", {})
    capability = adapter_contract.get("capability_profile", {})
    routes = adapter_contract.get("consumption_routes", {})

    # Build route_id from adapter name + source_system
    adapter_name = verdict.get("adapter", capability.get("adapter", "unknown"))
    route_id = f"route-{source_system}-{adapter_name.lower().replace(' ', '_')}"

    # Determine route_status — always CANDIDATE unless explicitly applied
    route_status = ROUTE_STATUS_CANDIDATE
    if verdict.get("context_delivery_executed", False):
        route_status = ROUTE_STATUS_APPLIED
    if not verdict.get("gateway_reachable", True):
        route_status = ROUTE_STATUS_BLOCKED

    return {
        "route_id": route_id,
        "route_type": "source_system_adapter",
        "route_status": route_status,
        "source_system": source_system,
        "adapter": adapter_name,
        "adapter_version": verdict.get("version", capability.get("version", "unknown")),
        "production_ready": verdict.get("production_ready", False),
        "memory_write_enabled": verdict.get("memory_write_enabled", False),
        "skill_write_enabled": verdict.get("skill_write_enabled", False),
        "context_delivery_executed": verdict.get("context_delivery_executed", False),
        "gateway_reachable": verdict.get("gateway_reachable", False),
        "artifact_types": capability.get("artifact_types_supported", []),
        "consumption_routes": routes,
        "notes": verdict.get("notes", []),
    }


def build_adapter_verdict_for_audit(adapter_contract: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Extract adapter_verdict from adapter_contract for audit logging.
    Returns a minimal dict safe for audit_event.jsonl.
    """
    if adapter_contract is None:
        return {
            "adapter": "none",
            "production_ready": False,
            "memory_write_enabled": False,
            "skill_write_enabled": False,
            "context_delivery_executed": False,
            "route_status": ROUTE_STATUS_CANDIDATE,
        }

    verdict = adapter_contract.get("adapter_verdict", {})
    return {
        "adapter": verdict.get("adapter", "unknown"),
        "version": verdict.get("version", "unknown"),
        "production_ready": verdict.get("production_ready", False),
        "memory_write_enabled": verdict.get("memory_write_enabled", False),
        "skill_write_enabled": verdict.get("skill_write_enabled", False),
        "context_delivery_executed": verdict.get("context_delivery_executed", False),
        "route_status": ROUTE_STATUS_CANDIDATE,
        "gateway_reachable": verdict.get("gateway_reachable", False),
    }


# ── Request / Plan dataclasses ────────────────────────────────────────────────

@dataclass
class InterpositionRequest:
    request_id: str
    source_system: str
    caller_scope: str
    target_session_id: str
    target_window_id: str
    query: str
    top_k: int = 3
    mode: str = MODE_CONTEXT_FILE
    observe_only: bool = True
    apply_to_platform: bool = False
    # ── TiandaoAdapter contract (optional) ──────────────────────────────────
    # Provided by caller when a concrete TiandaoAdapter is available.
    # Contains: {adapter_verdict, capability_profile, consumption_routes}
    adapter_contract: Optional[Dict[str, Any]] = None


@dataclass
class InterpositionPlan:
    request_id: str
    source_system: str
    caller_scope: str
    target_session_id: str
    target_window_id: str
    mode: str
    observe_only: bool
    apply_to_platform: bool
    source_refs: List[Dict[str, Any]] = field(default_factory=list)
    context_package: Dict[str, Any] = field(default_factory=dict)
    staging_dir: str = ""
    context_file: str = ""
    manifest_file: str = ""
    rollback_manifest_file: str = ""
    audit_file: str = ""
    status: str = STATUS_OBSERVE_ONLY
    reason: str = ""
    # ── TiandaoAdapter contract fields ──────────────────────────────────────
    adapter_contract: Dict[str, Any] = field(default_factory=dict)
    consumption_route: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RollbackManifest:
    platform_mutation: bool = False
    files_written: List[str] = field(default_factory=list)
    staged_files: List[str] = field(default_factory=list)
    rollback_required: bool = False
    rollback_steps: List[str] = field(default_factory=list)


@dataclass
class InterpositionResult:
    request_id: str
    status: str
    reason: str
    source_system: str
    caller_scope: str
    target_session_id: str
    target_window_id: str
    observe_only: bool
    apply_to_platform: bool
    staging_dir: str = ""
    context_file: str = ""
    manifest_file: str = ""
    rollback_manifest_file: str = ""
    audit_file: str = ""
    source_refs_count: int = 0
    runtime_recall: str = "real_p3_recall"
    recall_provider: str = "real_p3_recall"
    # ── TiandaoAdapter contract fields ──────────────────────────────────────
    consumption_route: Dict[str, Any] = field(default_factory=dict)


def _is_transformers_missing() -> bool:
    """Check if transformers module is available."""
    try:
        import transformers
        return False
    except ImportError:
        return True


def real_p3_recall_provider(query: str, top_k: int) -> Dict[str, Any]:
    """
    Real recall provider using p3_recall.handle_recall().

    Handles missing transformers gracefully with degraded fallback.
    Preserves source_refs from p3_recall results.
    """
    try:
        from src.p3_recall import handle_recall

        # Build recall request body compatible with p3_recall.handle_recall()
        recall_body = {
            "query": query or "",
            "scope_filter": "",  # No scope filter in default provider
            "type_filter": [],
            "top_k": max(1, top_k),
            "recall_mode": "substring",  # Use substring to avoid transformers dependency
        }

        result = handle_recall(recall_body)
        matched_memories = result.get("matched_memories", []) or []

        if not matched_memories:
            return {
                "confidence": 0.0,
                "matched_memories": [],
                "source_refs": [],
                "summary": "No memories matched.",
                "provider": "real_p3_recall_empty",
                "engine_status": "degraded" if _is_transformers_missing() else "available",
            }

        # Extract source_refs from matched memories
        source_refs = []
        for m in matched_memories:
            sr = m.get("source_refs", {})
            if sr:
                source_refs.append(sr)

        # Build summary
        summary_text = f"召回到 {len(matched_memories)} 条相关经验。"

        return {
            "confidence": max([m.get("confidence", 0.0) for m in matched_memories], default=0.0),
            "matched_memories": matched_memories,
            "source_refs": source_refs,
            "summary": summary_text,
            "provider": "real_p3_recall",
            "engine_status": "degraded" if _is_transformers_missing() else "available",
        }

    except Exception as e:
        # Fallback with explicit error marking
        error_summary = str(e)[:200] if str(e) else "unknown error"
        return {
            "confidence": 0.0,
            "matched_memories": [],
            "source_refs": [],
            "summary": f"Real recall failed: {error_summary}",
            "provider": "real_p3_recall_failed_fallback",
            "recall_error": error_summary,
            "engine_status": "error",
        }


def build_interposition_plan(
    request: InterpositionRequest,
    output_dir: Path,
    recall_result: Optional[Dict[str, Any]] = None,
) -> InterpositionPlan:
    recall_result = recall_result or real_p3_recall_provider(request.query, request.top_k)
    staging_dir = output_dir / request.request_id
    context_file = staging_dir / "context.md"
    package_file = staging_dir / "context_package.json"
    manifest_file = staging_dir / "interposition_plan.json"
    rollback_file = staging_dir / "rollback_manifest.json"
    audit_file = staging_dir / "audit_event.jsonl"

    # ── APPLY_BLOCKED: apply_to_platform=true always blocked in MVP ──────────
    if request.apply_to_platform:
        consumption_route = build_consumption_route(request.adapter_contract, request.source_system)
        return InterpositionPlan(
            request_id=request.request_id,
            source_system=request.source_system,
            caller_scope=request.caller_scope,
            target_session_id=request.target_session_id,
            target_window_id=request.target_window_id,
            mode=request.mode,
            observe_only=request.observe_only,
            apply_to_platform=request.apply_to_platform,
            staging_dir=str(staging_dir),
            context_file=str(context_file),
            manifest_file=str(manifest_file),
            rollback_manifest_file=str(rollback_file),
            audit_file=str(audit_file),
            status=STATUS_APPLY_BLOCKED,
            reason="platform mutation is not allowed in MVP-A",
            adapter_contract=request.adapter_contract or {},
            consumption_route=consumption_route,
        )

    if not request.caller_scope:
        consumption_route = build_consumption_route(request.adapter_contract, request.source_system)
        return InterpositionPlan(
            request_id=request.request_id,
            source_system=request.source_system,
            caller_scope=request.caller_scope,
            target_session_id=request.target_session_id,
            target_window_id=request.target_window_id,
            mode=request.mode,
            observe_only=request.observe_only,
            apply_to_platform=request.apply_to_platform,
            staging_dir=str(staging_dir),
            context_file=str(context_file),
            manifest_file=str(manifest_file),
            rollback_manifest_file=str(rollback_file),
            audit_file=str(audit_file),
            status=STATUS_SCOPE_BLOCKED,
            reason="caller_scope is required",
            adapter_contract=request.adapter_contract or {},
            consumption_route=consumption_route,
        )

    # Observe-only mode: return OBSERVE_ONLY status regardless of recall confidence
    if request.mode == MODE_OBSERVE_ONLY:
        consumption_route = build_consumption_route(request.adapter_contract, request.source_system)
        return InterpositionPlan(
            request_id=request.request_id,
            source_system=request.source_system,
            caller_scope=request.caller_scope,
            target_session_id=request.target_session_id,
            target_window_id=request.target_window_id,
            mode=request.mode,
            observe_only=request.observe_only,
            apply_to_platform=request.apply_to_platform,
            staging_dir=str(staging_dir),
            context_file=str(context_file),
            manifest_file=str(manifest_file),
            rollback_manifest_file=str(rollback_file),
            audit_file=str(audit_file),
            status=STATUS_OBSERVE_ONLY,
            reason="observe only mode: no context file generated",
            adapter_contract=request.adapter_contract or {},
            consumption_route=consumption_route,
        )

    confidence = float(recall_result.get("confidence", 0.0) or 0.0)
    matched_memories = recall_result.get("matched_memories", []) or []
    source_refs = recall_result.get("source_refs", []) or []
    if confidence < 0.2 or not matched_memories:
        consumption_route = build_consumption_route(request.adapter_contract, request.source_system)
        return InterpositionPlan(
            request_id=request.request_id,
            source_system=request.source_system,
            caller_scope=request.caller_scope,
            target_session_id=request.target_session_id,
            target_window_id=request.target_window_id,
            mode=request.mode,
            observe_only=request.observe_only,
            apply_to_platform=request.apply_to_platform,
            source_refs=source_refs,
            staging_dir=str(staging_dir),
            context_file=str(context_file),
            manifest_file=str(manifest_file),
            rollback_manifest_file=str(rollback_file),
            audit_file=str(audit_file),
            status=STATUS_LOW_CONFIDENCE_BLOCKED,
            reason="recall empty or low confidence",
            adapter_contract=request.adapter_contract or {},
            consumption_route=consumption_route,
        )

    # ── Build ContextPackage ──────────────────────────────────────────────────
    context_package = ContextPackage(
        query=request.query,
        canonical_window_id=request.target_window_id,
        session_id=request.target_session_id,
        intent_mode="summary",
        matched_memories=matched_memories,
        source_refs=source_refs,
        scope_enforced=True,
        injection_blocked=False,
    ).to_dict()

    # ── Embed TiandaoAdapter contract into context_package ───────────────────
    if request.adapter_contract is not None:
        verdict = request.adapter_contract.get("adapter_verdict", {})
        capability = request.adapter_contract.get("capability_profile", {})
        routes = request.adapter_contract.get("consumption_routes", {})

        context_package["adapter_verdict"] = {
            "adapter": verdict.get("adapter", "unknown"),
            "version": verdict.get("version", "unknown"),
            "production_ready": verdict.get("production_ready", False),
            "memory_write_enabled": verdict.get("memory_write_enabled", False),
            "skill_write_enabled": verdict.get("skill_write_enabled", False),
            "context_delivery_executed": verdict.get("context_delivery_executed", False),
            "gateway_reachable": verdict.get("gateway_reachable", False),
            "route_status": ROUTE_STATUS_CANDIDATE,
        }
        context_package["capability_profile"] = {
            "adapter": capability.get("adapter", "unknown"),
            "version": capability.get("version", "unknown"),
            "source_system": capability.get("source_system", request.source_system),
            "can_write_memory": capability.get("can_write_memory", False),
            "can_write_skill": capability.get("can_write_skill", False),
            "is_production_ready": capability.get("is_production_ready", False),
            "artifact_types_supported": capability.get("artifact_types_supported", []),
            "forbidden_fields_stripped": capability.get("forbidden_fields_stripped", []),
        }
        context_package["consumption_routes"] = routes
        context_package["permission_boundary"] = {
            "memory_write_enabled": verdict.get("memory_write_enabled", False),
            "skill_write_enabled": verdict.get("skill_write_enabled", False),
            "context_delivery_executed": verdict.get("context_delivery_executed", False),
            "production_ready": verdict.get("production_ready", False),
            "apply_to_platform_blocked": True,
            "note": "permission_boundary enforces read-only adapter contract — no writes without 甲方 authorization",
        }
        context_package["source_system_adapter"] = request.source_system

    status = STATUS_OBSERVE_ONLY if request.mode == MODE_OBSERVE_ONLY else STATUS_STAGED_CONTEXT_FILE
    reason = "observe only mode" if status == STATUS_OBSERVE_ONLY else "staged context file generated"
    consumption_route = build_consumption_route(request.adapter_contract, request.source_system)

    return InterpositionPlan(
        request_id=request.request_id,
        source_system=request.source_system,
        caller_scope=request.caller_scope,
        target_session_id=request.target_session_id,
        target_window_id=request.target_window_id,
        mode=request.mode,
        observe_only=request.observe_only,
        apply_to_platform=request.apply_to_platform,
        source_refs=source_refs,
        context_package=context_package,
        staging_dir=str(staging_dir),
        context_file=str(context_file),
        manifest_file=str(manifest_file),
        rollback_manifest_file=str(rollback_file),
        audit_file=str(audit_file),
        status=status,
        reason=reason,
        adapter_contract=request.adapter_contract or {},
        consumption_route=consumption_route,
    )


def build_context_markdown(request: InterpositionRequest, plan: InterpositionPlan, recall_result: Dict[str, Any]) -> str:
    summary = recall_result.get("summary", "") or "No summary available."
    refs = plan.source_refs or []
    ref_lines = []
    for idx, ref in enumerate(refs, start=1):
        ref_lines.append(
            f"{idx}. {ref.get('source_type', 'unknown')} | {ref.get('source_path', '')} | msg_ids={ref.get('msg_ids', [])}"
        )
    ref_block = "\n".join(ref_lines) if ref_lines else "(none)"

    # ── TiandaoAdapter contract section ───────────────────────────────────
    adapter_section = ""
    if plan.consumption_route:
        route = plan.consumption_route
        adapter_section = (
            f"\n## TiandaoAdapter Contract\n"
            f"- adapter: {route.get('adapter', 'none')}\n"
            f"- route_id: {route.get('route_id', 'none')}\n"
            f"- route_type: {route.get('route_type', 'unknown')}\n"
            f"- route_status: {route.get('route_status', 'CANDIDATE')}\n"
            f"- production_ready: {route.get('production_ready', False)}\n"
            f"- memory_write_enabled: {route.get('memory_write_enabled', False)}\n"
            f"- skill_write_enabled: {route.get('skill_write_enabled', False)}\n"
            f"- context_delivery_executed: {route.get('context_delivery_executed', False)}\n"
            f"- gateway_reachable: {route.get('gateway_reachable', False)}\n"
        )

    return (
        "# MEMCORE ZHIYI CONTEXT PACKAGE\n\n"
        f"- source_system: {request.source_system}\n"
        f"- caller_scope: {request.caller_scope}\n"
        f"- target_session_id: {request.target_session_id}\n"
        f"- target_window_id: {request.target_window_id}\n"
        f"- query_hash: {hash_query(request.query)}\n"
        f"- query_summary: {query_summary(request.query)}\n"
        f"- status: {plan.status}\n"
        f"- observe_only: {request.observe_only}\n"
        f"- apply_to_platform: {request.apply_to_platform}\n"
        + adapter_section + "\n"
        "## Recall Summary\n"
        f"{summary}\n\n"
        "## Source Refs\n"
        f"{ref_block}\n\n"
        "## Notice\n"
        "This package is staged context only. It is not a final answer and is not proof of platform consumption.\n"
    )


def write_json(path: Path, data: Dict[str, Any]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def write_rollback_manifest(path: Path, staged_files: List[str]) -> RollbackManifest:
    manifest = RollbackManifest(
        platform_mutation=False,
        files_written=[],
        staged_files=staged_files,
        rollback_required=False,
        rollback_steps=[],
    )
    write_json(path, asdict(manifest))
    return manifest


def write_audit_event(path: Path, request: InterpositionRequest, plan: InterpositionPlan) -> None:
    """
    Write audit event to audit_event.jsonl.

    Includes adapter_verdict from the TiandaoAdapter contract when available.
    """
    adapter_verdict_for_audit = build_adapter_verdict_for_audit(request.adapter_contract)

    event = {
        "timestamp": ts(),
        "request_id": request.request_id,
        "source_system": request.source_system,
        "caller_scope": request.caller_scope,
        "mode": request.mode,
        "observe_only": request.observe_only,
        "apply_to_platform": request.apply_to_platform,
        "status": plan.status,
        "reason": plan.reason,
        "staged_files": [plan.context_file, plan.manifest_file, plan.rollback_manifest_file],
        "source_refs_count": len(plan.source_refs or []),
        # TiandaoAdapter contract in audit
        "adapter_verdict": adapter_verdict_for_audit,
        "consumption_route": {
            "route_id": plan.consumption_route.get("route_id", ""),
            "route_type": plan.consumption_route.get("route_type", ""),
            "route_status": plan.consumption_route.get("route_status", ROUTE_STATUS_CANDIDATE),
            "source_system": plan.consumption_route.get("source_system", request.source_system),
            "adapter": plan.consumption_route.get("adapter", "none"),
        },
    }
    path.write_text(json.dumps(event, ensure_ascii=False) + "\n", encoding="utf-8")


def stage_context_file(
    request: InterpositionRequest,
    output_dir: Path,
    recall_result: Optional[Dict[str, Any]] = None,
) -> InterpositionResult:
    recall_result = recall_result or real_p3_recall_provider(request.query, request.top_k)
    plan = build_interposition_plan(request, output_dir, recall_result)
    ensure_dir(Path(plan.staging_dir))

    staged_files: List[str] = []
    if plan.status == STATUS_STAGED_CONTEXT_FILE:
        context_md = build_context_markdown(request, plan, recall_result)
        Path(plan.context_file).write_text(context_md, encoding="utf-8")
        staged_files.append(plan.context_file)

        write_json(Path(plan.manifest_file), asdict(plan))
        staged_files.append(plan.manifest_file)

        write_json(Path(plan.context_file).with_name("context_package.json"), plan.context_package)
        staged_files.append(str(Path(plan.context_file).with_name("context_package.json")))

        write_rollback_manifest(Path(plan.rollback_manifest_file), staged_files)
        staged_files.append(plan.rollback_manifest_file)

        write_audit_event(Path(plan.audit_file), request, plan)
        staged_files.append(plan.audit_file)
    else:
        write_json(Path(plan.manifest_file), asdict(plan))
        staged_files.append(plan.manifest_file)
        write_rollback_manifest(Path(plan.rollback_manifest_file), staged_files)
        staged_files.append(plan.rollback_manifest_file)
        write_audit_event(Path(plan.audit_file), request, plan)
        staged_files.append(plan.audit_file)

    return InterpositionResult(
        request_id=request.request_id,
        status=plan.status,
        reason=plan.reason,
        source_system=request.source_system,
        caller_scope=request.caller_scope,
        target_session_id=request.target_session_id,
        target_window_id=request.target_window_id,
        observe_only=request.observe_only,
        apply_to_platform=request.apply_to_platform,
        staging_dir=plan.staging_dir,
        context_file=plan.context_file if plan.status == STATUS_STAGED_CONTEXT_FILE else "",
        manifest_file=plan.manifest_file,
        rollback_manifest_file=plan.rollback_manifest_file,
        audit_file=plan.audit_file,
        source_refs_count=len(plan.source_refs or []),
        runtime_recall="not_executed",
        recall_provider=recall_result.get("provider", "unknown"),
        consumption_route=plan.consumption_route,
    )


def run_interposition_mvp(
    source_system: str,
    caller_scope: str,
    target_session_id: str,
    query: str,
    top_k: int,
    mode: str,
    output_dir: Path,
    dry_run: bool = True,
    target_window_id: str = "",
    apply_to_platform: bool = False,
    recall_result: Optional[Dict[str, Any]] = None,
    adapter_contract: Optional[Dict[str, Any]] = None,
) -> InterpositionResult:
    request = InterpositionRequest(
        request_id=str(uuid.uuid4()),
        source_system=source_system,
        caller_scope=caller_scope,
        target_session_id=target_session_id,
        target_window_id=target_window_id or target_session_id,
        query=query,
        top_k=top_k,
        mode=mode,
        observe_only=dry_run,
        apply_to_platform=apply_to_platform,
        adapter_contract=adapter_contract,
    )
    return stage_context_file(request, output_dir, recall_result=recall_result)


def main() -> int:
    parser = argparse.ArgumentParser(description="Zhiyi Interposition MVP A + TiandaoAdapter Link")
    parser.add_argument("--source-system", required=True)
    parser.add_argument("--caller-scope", required=True)
    parser.add_argument("--target-session-id", required=True)
    parser.add_argument("--target-window-id", default="")
    parser.add_argument("--query", required=True)
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--mode", default=MODE_CONTEXT_FILE)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply-to-platform", action="store_true")
    args = parser.parse_args()

    result = run_interposition_mvp(
        source_system=args.source_system,
        caller_scope=args.caller_scope,
        target_session_id=args.target_session_id,
        target_window_id=args.target_window_id,
        query=args.query,
        top_k=args.top_k,
        mode=args.mode,
        output_dir=Path(args.output_dir),
        dry_run=args.dry_run or True,
        apply_to_platform=args.apply_to_platform,
    )
    print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
