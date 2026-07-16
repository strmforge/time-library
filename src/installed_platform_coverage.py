"""Read-only installed-platform coverage matrix.

This matrix is a release-candidate guardrail: it makes every detected or
explicitly requested local AI surface visible before we claim platform coverage.
It does not read chat bodies, write platform configs, call models, or turn a
single OpenClaw proof into an all-platform proof.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

try:
    from src.platform_autodiscovery import build_autodiscovery
    from src.platform_delivery_matrix import build_platform_delivery_matrix
    from src.platform_thin_adapter_registry import build_authorized_auto_connect_dry_run
except Exception:  # pragma: no cover - direct script import fallback
    from platform_autodiscovery import build_autodiscovery
    from platform_delivery_matrix import build_platform_delivery_matrix
    from platform_thin_adapter_registry import build_authorized_auto_connect_dry_run


INSTALLED_PLATFORM_COVERAGE_CONTRACT = "installed_platform_coverage_matrix.v2026.6.23"
DEFAULT_REQUIRED_TARGETS = (
    "openclaw",
    "hermes",
    "codex",
    "claude_desktop",
    "claude_code_cli",
    "cursor",
    "pi",
)
RELEASE_TARGET_DECLARATIONS: dict[str, dict[str, Any]] = {
    "hermes": {
        "collector_states": {
            "raw_pointer_consumption_only_no_platform_write": "raw_pointer_only_no_platform_write",
        },
    },
    "pi": {
        "collector_state": "verified_collector_required_for_pi_coding_agent",
        "consumer_missing_state": "pi_coding_agent_metadata_only_no_memcore_connection",
        "undetected_gap": "pi_requested_target_not_installed_on_checked_hosts",
    },
}
FULL_RUNTIME_PROVEN_STATES = {"turn_loop_behavior_proven"}
SCOPED_RUNTIME_PROVEN_STATES = {"controlled_smoke_path_proven"}
ANY_RUNTIME_PROVEN_STATES = FULL_RUNTIME_PROVEN_STATES | SCOPED_RUNTIME_PROVEN_STATES


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _items(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _as_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _system_key(value: str) -> str:
    value = str(value or "").strip().lower()
    aliases = {
        "claude": "claude_desktop",
        "claude_code": "claude_code_cli",
        "inflection": "pi",
        "pi.dev": "pi",
        "pi.ai": "pi",
    }
    return aliases.get(value, value)


def _release_target_declaration(system: str) -> dict[str, Any]:
    declaration = RELEASE_TARGET_DECLARATIONS.get(str(system or ""))
    return declaration if isinstance(declaration, dict) else {}


def _autodiscovery_systems(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        _system_key(str(item.get("system") or "")): item
        for item in _items(payload.get("systems"))
        if str(item.get("system") or "").strip()
    }


def _delivery_rows(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    matrix_payload = _dict(payload)
    if matrix_payload.get("contract") != "platform_delivery_liveness_matrix.v2026.6.21":
        matrix_payload = build_platform_delivery_matrix(matrix_payload)
    return {
        _system_key(str(item.get("platform") or "")): item
        for item in _items(matrix_payload.get("matrix"))
        if str(item.get("platform") or "").strip()
    }


def _remote_probe_system(probe: dict[str, Any]) -> str:
    system = str(probe.get("system") or probe.get("platform") or "").strip()
    if system:
        return _system_key(system)
    if "pi_probe" in probe or any(key in probe for key in ("processes", "app_paths", "uninstall_entries")):
        return "pi"
    return ""


def _remote_probe_detected(probe: dict[str, Any]) -> bool:
    if isinstance(probe.get("detected"), bool):
        return bool(probe.get("detected"))
    for key in (
        "processes",
        "app_paths",
        "config_dirs",
        "shortcuts",
        "uninstall_entries",
        "agent_site_metadata_hits",
        "agent_metadata_hits",
        "site_metadata_hits",
        "pwa_metadata_hits",
        "web_login_metadata_hits",
    ):
        if _items(probe.get(key)):
            return True
    return False


def _remote_signal_count(probe: dict[str, Any]) -> int:
    return sum(
        len(_items(probe.get(key)))
        for key in (
            "processes",
            "app_paths",
            "config_dirs",
            "shortcuts",
            "uninstall_entries",
            "agent_site_metadata_hits",
            "agent_metadata_hits",
            "site_metadata_hits",
            "pwa_metadata_hits",
            "web_login_metadata_hits",
        )
    )


def _remote_probe_summary(probe: dict[str, Any]) -> dict[str, Any]:
    return {
        "host": str(probe.get("host") or probe.get("machine") or ""),
        "platform": _remote_probe_system(probe),
        "detected": _remote_probe_detected(probe),
        "signal_count": _remote_signal_count(probe),
        "read_only": bool(probe.get("read_only", True)),
        "body_read": bool(probe.get("body_read", False)),
        "secret_read": bool(probe.get("secret_read", False)),
        "agent_site_metadata_read": bool(probe.get("agent_site_metadata_read", False)),
        "browser_profile_content_read": bool(probe.get("browser_profile_content_read", False)),
    }


def _installed_state(system: str, autodiscovery: dict[str, dict[str, Any]], remotes: list[dict[str, Any]]) -> tuple[str, list[str]]:
    auto = _dict(autodiscovery.get(system))
    remote_hits = [probe for probe in remotes if _remote_probe_system(probe) == system]
    evidence: list[str] = []
    status = str(auto.get("status") or "not_found")
    if status != "not_found" or bool(auto.get("connectable_now")) or bool(auto.get("intent_signal_detected")):
        evidence.append("local_autodiscovery")
    for probe in remote_hits:
        label = str(probe.get("host") or "remote")
        if _remote_probe_detected(probe):
            evidence.append(f"remote_probe:{label}")
    if evidence:
        return "detected", evidence
    if remote_hits:
        return "not_detected_explicit_probe", [f"remote_probe:{probe.get('host') or 'remote'}" for probe in remote_hits]
    return "not_detected", []


def _collector_state(system: str, autodiscovery: dict[str, dict[str, Any]]) -> str:
    auto = _dict(autodiscovery.get(system))
    content_gate = str(auto.get("content_gate") or "")
    declaration = _release_target_declaration(system)
    declared_by_gate = _dict(declaration.get("collector_states")).get(content_gate)
    if declared_by_gate:
        return str(declared_by_gate)
    if declaration.get("collector_state"):
        return str(declaration["collector_state"])
    if content_gate == "verified_format_collector_required":
        return "verified_collector_required"
    if auto.get("status") == "not_found" or not auto:
        return "not_applicable_until_detected"
    return content_gate or "unknown"


def _consumer_state(system: str, autodiscovery: dict[str, dict[str, Any]]) -> str:
    auto = _dict(autodiscovery.get(system))
    if bool(auto.get("connectable_now")):
        return "capability_check_ready"
    if bool(auto.get("intent_signal_detected")):
        return "partial_connection_signal"
    if auto.get("status") and auto.get("status") != "not_found":
        return "detected_without_memcore_connection"
    declared_missing_state = _release_target_declaration(system).get("consumer_missing_state")
    if declared_missing_state:
        return str(declared_missing_state)
    return "not_connected_or_not_detected"


def _runtime_state(system: str, runtime_status: dict[str, Any]) -> str:
    if system in runtime_status:
        return str(runtime_status.get(system) or "not_proven")
    return "not_proven"


def _auto_connect_state(system: str, plan_by_system: dict[str, dict[str, Any]]) -> tuple[str, dict[str, Any]]:
    plan = _dict(plan_by_system.get(system))
    if not plan:
        return "not_planned", {}
    status = str(plan.get("status") or "")
    if status == "ready_for_capability_check":
        return "already_connected_or_capability_check_ready", plan
    if status == "auto_connect_ready":
        would_write = _as_list(plan.get("would_write"))
        apply_status = str(plan.get("apply_endpoint_status") or "")
        if would_write and apply_status.startswith("implemented"):
            return "auto_connect_ready_with_apply_endpoint", plan
        if would_write:
            return "auto_connect_ready_manual_apply_only", plan
        return "auto_connect_ready_no_config_target", plan
    if status == "not_detected":
        return "not_detected", plan
    return status or "unknown", plan


def _coverage_state(
    *,
    system: str,
    installed_state: str,
    delivery_row: dict[str, Any],
    runtime_state: str,
) -> str:
    if installed_state.startswith("not_detected"):
        return "coverage_gap_not_detected"
    if runtime_state in SCOPED_RUNTIME_PROVEN_STATES:
        return "covered_by_controlled_runtime_scope_only"
    if delivery_row.get("platform_delivery_proven") is True and runtime_state in FULL_RUNTIME_PROVEN_STATES:
        return "covered_with_runtime_delivery_proof"
    if runtime_state in FULL_RUNTIME_PROVEN_STATES:
        return "covered_by_runtime_behavior_only"
    if delivery_row:
        return "covered_by_discovery_delivery_matrix_only"
    return "covered_by_detection_only"


def _row(
    system: str,
    *,
    autodiscovery: dict[str, dict[str, Any]],
    delivery_rows: dict[str, dict[str, Any]],
    remote_probes: list[dict[str, Any]],
    runtime_status: dict[str, Any],
    auto_connect_plans: dict[str, dict[str, Any]],
    required: bool,
) -> dict[str, Any]:
    installed, evidence = _installed_state(system, autodiscovery, remote_probes)
    delivery = _dict(delivery_rows.get(system))
    runtime = _runtime_state(system, runtime_status)
    auto_connect_state, auto_connect_plan = _auto_connect_state(system, auto_connect_plans)
    coverage_state = _coverage_state(
        system=system,
        installed_state=installed,
        delivery_row=delivery,
        runtime_state=runtime,
    )
    gaps: list[str] = []
    if installed.startswith("not_detected"):
        gaps.append("install_or_detection_missing")
    if not delivery:
        gaps.append("delivery_matrix_missing")
    elif not delivery.get("platform_delivery_proven"):
        gaps.append("platform_delivery_not_proven")
    if runtime not in ANY_RUNTIME_PROVEN_STATES:
        gaps.append("runtime_turn_loop_not_proven")
    if runtime in SCOPED_RUNTIME_PROVEN_STATES:
        gaps.append("runtime_proof_scoped_not_platform_wide")
    undetected_gap = _release_target_declaration(system).get("undetected_gap")
    if undetected_gap and installed.startswith("not_detected"):
        gaps.append(str(undetected_gap))
    if required and auto_connect_state in {"not_planned", "not_detected", "unknown"}:
        gaps.append("auto_connect_plan_missing")
    return {
        "system": system,
        "required_target": required,
        "installed_state": installed,
        "installed_evidence": evidence,
        "source_capture_state": _collector_state(system, autodiscovery),
        "consumer_connection_state": _consumer_state(system, autodiscovery),
        "auto_connect_state": auto_connect_state,
        "auto_connect_apply_endpoint_status": str(auto_connect_plan.get("apply_endpoint_status") or ""),
        "auto_connect_plan_source": str(auto_connect_plan.get("plan_source") or ""),
        "auto_connect_would_write": _as_list(auto_connect_plan.get("would_write")),
        "install_trust_boundary": "local_installation_implies_trusted_auto_connect_environment",
        "delivery_proof_state": str(delivery.get("platform_proof_state") or "delivery_matrix_missing"),
        "runtime_turn_loop_state": runtime,
        "coverage_state": coverage_state,
        "pre_tiandao_restored": installed == "detected" and (bool(delivery) or runtime in ANY_RUNTIME_PROVEN_STATES),
        "gap": gaps,
        "non_claims": [
            "detected_or_connected_does_not_prove_model_received_memory",
            "source_capture_candidate_does_not_read_chat_bodies",
            "controlled_openclaw_scope_does_not_cover_all_platforms",
            "auto_connect_receipt_does_not_prove_platform_model_delivery",
        ],
    }


def _auto_connect_plan_by_system(
    payload: dict[str, Any],
    autodiscovery_payload: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    explicit = _dict(payload.get("auto_connect_dry_run"))
    if "plans" in explicit:
        plans = _items(explicit.get("plans"))
    else:
        try:
            explicit = build_authorized_auto_connect_dry_run(autodiscovery_payload, include_generic=False)
            plans = _items(explicit.get("plans"))
        except Exception:
            plans = []
    return {
        _system_key(str(plan.get("system") or "")): plan
        for plan in plans
        if str(plan.get("system") or "").strip()
    }


def _derived_structure_analysis(auto_connect_by_system: dict[str, dict[str, Any]]) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    for system, plan in sorted(auto_connect_by_system.items()):
        draft = _dict(plan.get("adapter_draft"))
        if not draft:
            continue
        candidates.append({
            "system": system,
            "source": "auto_connect_adapter_draft",
            "adapter_draft": draft,
        })
    return {
        "contract": "installed_platform_structure_analysis_derived.v2026.6.23",
        "input_kind": "local_metadata_only",
        "chat_body_read": False,
        "secret_read": False,
        "summary": {
            "adapter_draft_count": len(candidates),
            "executed_model_surface_count": sum(
                1
                for candidate in candidates
                if _dict(candidate.get("adapter_draft")).get("recognition", {}).get("recognized_by") == "model"
            ),
            "local_rule_surface_count": sum(
                1
                for candidate in candidates
                if _dict(candidate.get("adapter_draft")).get("recognition", {}).get("recognized_by") in {"local_rules", "known_thin_adapter"}
            ),
        },
        "candidates": candidates,
    }


def _structure_analysis_gate(
    payload: dict[str, Any],
    auto_connect_by_system: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    analysis = _dict(payload.get("model_structure_analysis") or payload.get("provisional_adapter_candidates"))
    if not analysis:
        analysis = _derived_structure_analysis(auto_connect_by_system or {})
    summary = _dict(analysis.get("summary"))
    candidates = _items(analysis.get("candidates"))
    adapter_drafts = int(summary.get("adapter_draft_count") or sum(1 for candidate in candidates if isinstance(candidate.get("adapter_draft"), dict)))
    model_calls = int(summary.get("executed_model_surface_count") or 0)
    if not model_calls:
        model_calls = sum(1 for candidate in candidates if _dict(candidate.get("adapter_draft")).get("recognition", {}).get("recognized_by") == "model")
    chat_body = bool(analysis.get("chat_body_read") or analysis.get("chat_body_included"))
    secret_read = bool(analysis.get("secret_read") or analysis.get("api_key_included"))
    return {
        "contract": "installed_platform_structure_analysis_gate.v2026.6.23",
        "ok": bool(adapter_drafts),
        "model_structure_analysis_present": bool(analysis),
        "adapter_draft_count": adapter_drafts,
        "model_identification_executed_count": model_calls,
        "local_rule_structure_analysis_count": int(summary.get("local_rule_surface_count") or 0),
        "chat_body_read": chat_body,
        "secret_read": secret_read,
        "input_kind": analysis.get("input_kind", "local_metadata_only") or "local_metadata_only",
        "non_claims": [
            "model_structure_analysis_does_not_read_chat_bodies",
            "adapter_draft_does_not_prove_platform_delivery",
            "apply_receipt_still_required_for_config_write",
        ],
    }


def build_installed_platform_coverage(
    payload: dict[str, Any] | None = None,
    *,
    autodiscovery_payload: dict[str, Any] | None = None,
    delivery_matrix_payload: dict[str, Any] | None = None,
    remote_probes: list[dict[str, Any]] | None = None,
    runtime_status: dict[str, Any] | None = None,
    required_targets: list[str] | tuple[str, ...] | str | None = None,
    include_generic: bool = True,
) -> dict[str, Any]:
    source = _dict(payload)
    autodiscovery_payload = autodiscovery_payload or _dict(source.get("autodiscovery"))
    if not autodiscovery_payload:
        autodiscovery_payload = build_autodiscovery(include_generic=include_generic)
    delivery_matrix_payload = delivery_matrix_payload or _dict(source.get("delivery_matrix"))
    if not delivery_matrix_payload:
        delivery_matrix_payload = build_platform_delivery_matrix(
            _dict(source.get("platform_delivery_liveness") or source.get("platform_delivery_probe"))
        )
    remote_probes = remote_probes if remote_probes is not None else _items(source.get("remote_probes"))
    runtime_status = runtime_status if runtime_status is not None else _dict(source.get("runtime_status"))
    required = tuple(dict.fromkeys(_system_key(item) for item in (_as_list(required_targets) or list(DEFAULT_REQUIRED_TARGETS))))
    auto_by_system = _autodiscovery_systems(autodiscovery_payload)
    delivery_by_system = _delivery_rows(delivery_matrix_payload)
    auto_connect_by_system = _auto_connect_plan_by_system(source, autodiscovery_payload)
    remote_systems = {
        _remote_probe_system(probe)
        for probe in remote_probes
        if _remote_probe_system(probe)
    }
    systems = sorted(set(required) | set(auto_by_system) | set(delivery_by_system) | remote_systems)
    rows = [
        _row(
            system,
            autodiscovery=auto_by_system,
            delivery_rows=delivery_by_system,
            remote_probes=remote_probes,
            runtime_status=runtime_status,
            auto_connect_plans=auto_connect_by_system,
            required=system in required,
        )
        for system in systems
        if system and system != "memcore_cloud"
    ]
    required_gaps = [
        row["system"]
        for row in rows
        if row["required_target"] and row["coverage_state"].startswith("coverage_gap")
    ]
    runtime_unproven = [
        row["system"]
        for row in rows
        if row["required_target"] and row["runtime_turn_loop_state"] not in ANY_RUNTIME_PROVEN_STATES
    ]
    auto_connect_gaps = [
        row["system"]
        for row in rows
        if row["required_target"] and "auto_connect_plan_missing" in row["gap"]
    ]
    structure_gate = _structure_analysis_gate(source, auto_connect_by_system)
    return {
        "ok": not required_gaps and not auto_connect_gaps and structure_gate["ok"],
        "contract": INSTALLED_PLATFORM_COVERAGE_CONTRACT,
        "created_at": _now(),
        "read_only": True,
        "findings_only": True,
        "write_performed": False,
        "raw_write_performed": False,
        "memory_write_performed": False,
        "platform_write_performed": False,
        "model_call_performed": False,
        "chat_body_read": False,
        "secret_read": False,
        "release_candidate_gate": {
            "all_required_targets_detected": not required_gaps,
            "required_detection_gaps": required_gaps,
            "required_auto_connect_gaps": auto_connect_gaps,
            "required_runtime_unproven": runtime_unproven,
            "structure_analysis_gate": structure_gate,
            "not_publish_proof": True,
        },
        "counts": {
            "platforms_total": len(rows),
            "required_targets": sum(1 for row in rows if row["required_target"]),
            "detected": sum(1 for row in rows if row["installed_state"] == "detected"),
            "required_detection_gaps": len(required_gaps),
            "runtime_proven": sum(1 for row in rows if row["runtime_turn_loop_state"] in ANY_RUNTIME_PROVEN_STATES),
            "full_runtime_proven": sum(1 for row in rows if row["runtime_turn_loop_state"] in FULL_RUNTIME_PROVEN_STATES),
            "scoped_runtime_proven": sum(1 for row in rows if row["runtime_turn_loop_state"] in SCOPED_RUNTIME_PROVEN_STATES),
            "auto_connect_ready_or_connected": sum(
                1
                for row in rows
                if row["auto_connect_state"] in {
                    "already_connected_or_capability_check_ready",
                    "auto_connect_ready_with_apply_endpoint",
                    "auto_connect_ready_manual_apply_only",
                    "auto_connect_ready_no_config_target",
                }
            ),
        },
        "matrix": rows,
        "remote_probe_summaries": [_remote_probe_summary(probe) for probe in remote_probes],
        "non_claims": [
            "not_a_platform_action",
            "not_a_model_call",
            "not_release_publication",
            "not_all_platform_delivery_proof",
            "nas_model_config_is_not_installation_proof",
            "install_trust_boundary_does_not_allow_chat_body_read_or_external_account_actions",
        ],
    }


__all__ = [
    "DEFAULT_REQUIRED_TARGETS",
    "INSTALLED_PLATFORM_COVERAGE_CONTRACT",
    "build_installed_platform_coverage",
]
