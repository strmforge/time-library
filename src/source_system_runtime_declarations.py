#!/usr/bin/env python3
"""Thin source-system runtime declarations for runtime core behavior.

Platform-specific identity, source-ref shape, canonical-index parsing, guardian
validation, and recall fallback rules live here so core runtime paths can stay
declaration-driven.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


@dataclass(frozen=True)
class SourceSystemRuntimeDeclaration:
    source_system: str
    aliases: tuple[str, ...] = ()
    consumer_match_tokens: tuple[str, ...] = ()
    native_delivery_shape: str = "none"
    has_session_window_id: bool = False
    canonical_index_enabled: bool = False
    guardian_connector_module: str = ""
    guardian_implemented: bool = False
    recall_window_aliases: tuple[str, ...] = ()
    recall_alias_consumer_tokens: tuple[str, ...] = ()
    recall_collection_filter: str = ""
    recall_collection_alias_boundary: str = ""
    ingest_kind: str = ""
    default_artifact_type: str = ""
    raw_validation_kind: str = "generic_message_payload"
    source_ref_kind: str = "generic"
    canonical_index_kind: str = "generic_message_payload"
    canonical_message_source_preference: str = "prefer_source_path"
    source_scan_kind: str = "jsonl"
    gap_probe_kind: str = "none"
    delivery_session_hint_kind: str = "default"
    delivery_flag_keys: tuple[str, ...] = ()
    delivery_session_key_fields: tuple[str, ...] = ()
    delivery_session_prefixes: tuple[str, ...] = ()
    delivery_runtime_kind: str = "none"
    project_status_fallback_kind: str = "none"
    raw_backfill_kind: str = "none"
    distillable: bool = False
    distill_priority: int = 99
    distill_checkpoint_adapter_kind: str = "none"
    distill_index_status_prefixes: tuple[str, ...] = ()
    distill_target_shapes: tuple[str, ...] = ()
    distill_required_coverage_source: str = ""
    reading_area_raw_index_kind: str = "none"
    reading_area_raw_index_source_ref_kind: str = ""
    broad_context_workflow_reasons: tuple[str, ...] = ()
    default_recall_scope_source: bool = False
    default_work_preflight_source: bool = False
    native_generation_trigger_kind: str = "none"
    generation_cadence: str = ""
    generation_model_hint: str = ""
    generation_scope: str = ""


SOURCE_SYSTEM_RUNTIME_DECLARATIONS: dict[str, SourceSystemRuntimeDeclaration] = {
    "codex": SourceSystemRuntimeDeclaration(
        source_system="codex",
        consumer_match_tokens=("codex",),
        native_delivery_shape="project_instruction_and_mcp",
        has_session_window_id=True,
        canonical_index_enabled=True,
        guardian_connector_module="codex_local_connector",
        guardian_implemented=True,
        ingest_kind="session_file_jsonl",
        default_artifact_type="codex_session_jsonl",
        raw_validation_kind="response_item_payload_message",
        source_ref_kind="project_session_window_refs",
        canonical_index_kind="response_item_payload_message",
        distillable=True,
        distill_priority=1,
        default_work_preflight_source=True,
    ),
    "claude_code_cli": SourceSystemRuntimeDeclaration(
        source_system="claude_code_cli",
        consumer_match_tokens=("claude_code", "claude_code_cli"),
        native_delivery_shape="user_prompt_submit_hook_and_mcp",
        has_session_window_id=True,
        canonical_index_enabled=True,
        guardian_connector_module="claude_code_local_connector",
        guardian_implemented=True,
        ingest_kind="session_file_jsonl",
        default_artifact_type="claude_code_session_jsonl",
        raw_validation_kind="message_envelope_content_blocks",
        canonical_index_kind="message_envelope_content_blocks",
        distillable=True,
        distill_priority=0,
    ),
    "claude_desktop": SourceSystemRuntimeDeclaration(
        source_system="claude_desktop",
        consumer_match_tokens=("claude", "claude_desktop"),
        native_delivery_shape="desktop_extension_and_mcp",
        canonical_index_enabled=True,
        guardian_implemented=False,
        recall_window_aliases=("claude_code_cli",),
        recall_alias_consumer_tokens=("claude",),
        recall_collection_filter="claude_all",
        recall_collection_alias_boundary="same_window_or_session_anchor_only",
        ingest_kind="local_store_or_metadata",
        default_artifact_type="claude_desktop_authorized_local_store_jsonl",
        canonical_message_source_preference="prefer_raw_path",
        gap_probe_kind="desktop_local_store_status",
        distillable=True,
        distill_priority=5,
    ),
    "openclaw": SourceSystemRuntimeDeclaration(
        source_system="openclaw",
        consumer_match_tokens=("openclaw",),
        native_delivery_shape="plugin_and_local_gateway",
        canonical_index_enabled=True,
        guardian_implemented=True,
        ingest_kind="session_file_jsonl",
        default_artifact_type="openclaw_session_jsonl",
        raw_validation_kind="message_snapshot_batch",
        source_ref_kind="agent_session_window_refs",
        canonical_index_kind="message_snapshot_batch",
        gap_probe_kind="session_source_sample",
        delivery_session_hint_kind="agent_session_delivery",
        delivery_flag_keys=("deliver_to_openclaw",),
        delivery_session_key_fields=("openclaw_session_key",),
        delivery_session_prefixes=("agent:",),
        delivery_runtime_kind="ws_rpc_forward",
        raw_backfill_kind="source_artifact_copy",
        distillable=True,
        distill_priority=4,
        default_recall_scope_source=True,
    ),
    "hermes": SourceSystemRuntimeDeclaration(
        source_system="hermes",
        consumer_match_tokens=("hermes",),
        native_delivery_shape="native_review_observer",
        canonical_index_enabled=True,
        guardian_implemented=True,
        ingest_kind="state_db_messages",
        default_artifact_type="hermes_state_db_messages_jsonl",
        source_ref_kind="session_window_refs",
        canonical_message_source_preference="prefer_raw_path",
        gap_probe_kind="state_db_presence",
        project_status_fallback_kind="default_recall_fallback",
        raw_backfill_kind="state_db_messages",
        distillable=True,
        distill_priority=3,
        native_generation_trigger_kind="hermes_cron",
        generation_cadence="nightly",
        generation_model_hint="large_model",
        generation_scope="read_only_new_raw",
        broad_context_workflow_reasons=(
            "hermes_skill_generation",
            "skill_generation",
            "skill-generation",
            "native_skill_generation",
            "hermes_self_review",
            "self_review",
            "self-review",
        ),
    ),
    "mimocode": SourceSystemRuntimeDeclaration(
        source_system="mimocode",
        aliases=("mimo", "mimo_code"),
        consumer_match_tokens=("mimo", "mimo_code", "mimocode"),
        native_delivery_shape="skill_or_rule_and_mcp",
        ingest_kind="checkpoint_markdown",
        default_artifact_type="mimocode_checkpoint_markdown",
        source_ref_kind="mimocode_checkpoint_source_path_fallback",
        canonical_message_source_preference="prefer_source_path",
        source_scan_kind="checkpoint_markdown",
        distillable=True,
        distill_priority=2,
        distill_checkpoint_adapter_kind="checkpoint_markdown_sections",
        distill_index_status_prefixes=("mimocode_",),
        distill_target_shapes=("mimocode_deep_distill",),
        distill_required_coverage_source="reading_area_declared_mimocode_checkpoint",
        reading_area_raw_index_kind="declared_checkpoint_markdown",
        reading_area_raw_index_source_ref_kind="mimocode_checkpoint_source_path_fallback",
    ),
    "kiro": SourceSystemRuntimeDeclaration(
        source_system="kiro",
        consumer_match_tokens=("kiro",),
        native_delivery_shape="mcp",
        canonical_index_enabled=True,
        guardian_connector_module="kiro_local_connector",
        guardian_implemented=True,
        ingest_kind="workspace_session_json",
        default_artifact_type="kiro_workspace_sessions_json",
        source_scan_kind="workspace_session_json_document",
        canonical_message_source_preference="prefer_raw_path",
        gap_probe_kind="workspace_session_connector_status",
    ),
    "local_files": SourceSystemRuntimeDeclaration(
        source_system="local_files",
        ingest_kind="local_file",
        default_artifact_type="local_file",
        source_ref_kind="file_checksum_refs",
        canonical_index_enabled=False,
        raw_validation_kind="generic_message_payload",
        canonical_index_kind="",
    ),
    "cursor": SourceSystemRuntimeDeclaration(
        source_system="cursor",
        consumer_match_tokens=("cursor",),
        native_delivery_shape="project_rule_and_mcp",
    ),
    "minimax": SourceSystemRuntimeDeclaration(
        source_system="minimax",
        consumer_match_tokens=("minimax",),
        native_delivery_shape="skill_or_rule_and_mcp",
    ),
    "gemini_cli": SourceSystemRuntimeDeclaration(
        source_system="gemini_cli",
        consumer_match_tokens=("gemini", "gemini_cli"),
        native_delivery_shape="extension_and_mcp",
    ),
}


def _source_token(value: Any) -> str:
    return "_".join(_clean_text(value).lower().replace("-", "_").split())


def runtime_source_system_declaration(source_system: str) -> SourceSystemRuntimeDeclaration:
    source = _source_token(source_system)
    declaration = SOURCE_SYSTEM_RUNTIME_DECLARATIONS.get(source)
    if declaration is not None:
        return declaration
    for item in SOURCE_SYSTEM_RUNTIME_DECLARATIONS.values():
        if source in item.aliases:
            return item
    return SourceSystemRuntimeDeclaration(source_system=source)


def source_system_declared_tokens(source_system: str) -> tuple[str, ...]:
    declaration = runtime_source_system_declaration(source_system)
    tokens: list[str] = []
    for token in (declaration.source_system, *declaration.aliases):
        cleaned = _source_token(token)
        if cleaned and cleaned not in tokens:
            tokens.append(cleaned)
    return tuple(tokens)


def source_system_consumer_match_tokens(source_system: str) -> tuple[str, ...]:
    declaration = runtime_source_system_declaration(source_system)
    tokens: list[str] = []
    for token in (
        declaration.source_system,
        *declaration.aliases,
        *declaration.consumer_match_tokens,
    ):
        cleaned = _source_token(token)
        if cleaned and cleaned not in tokens:
            tokens.append(cleaned)
    return tuple(tokens)


def source_system_from_consumer_name(consumer: Any) -> str:
    text = _source_token(consumer)
    if not text:
        return ""
    candidates: list[tuple[str, str]] = []
    for name, declaration in SOURCE_SYSTEM_RUNTIME_DECLARATIONS.items():
        for token in source_system_consumer_match_tokens(name):
            if token:
                candidates.append((token, declaration.source_system))
    for token, source_system in sorted(candidates, key=lambda item: len(item[0]), reverse=True):
        if token in text:
            return source_system
    return ""


def default_recall_scope_source_system() -> str:
    for name, declaration in SOURCE_SYSTEM_RUNTIME_DECLARATIONS.items():
        if declaration.default_recall_scope_source:
            return name
    return ""


def default_work_preflight_source_system() -> str:
    for name, declaration in SOURCE_SYSTEM_RUNTIME_DECLARATIONS.items():
        if declaration.default_work_preflight_source:
            return name
    return ""


def source_system_broad_context_workflow_reasons(source_system: str) -> tuple[str, ...]:
    return runtime_source_system_declaration(source_system).broad_context_workflow_reasons


def declared_broad_context_workflow_reasons() -> tuple[str, ...]:
    reasons: list[str] = []
    for declaration in SOURCE_SYSTEM_RUNTIME_DECLARATIONS.values():
        for reason in declaration.broad_context_workflow_reasons:
            cleaned = _clean_text(reason).lower().replace(" ", "_")
            if cleaned and cleaned not in reasons:
                reasons.append(cleaned)
    return tuple(reasons)


def source_system_has_broad_context_workflow(source_system: str, reason: Any) -> bool:
    cleaned = _clean_text(reason).lower().replace(" ", "_")
    return bool(cleaned and cleaned in source_system_broad_context_workflow_reasons(source_system))


def source_system_broad_context_workflow_from_consumer(consumer: Any, reason: Any) -> bool:
    source_system = source_system_from_consumer_name(consumer)
    return bool(source_system and source_system_has_broad_context_workflow(source_system, reason))


def source_system_filter_matches(source_system: str, filters: list[str] | tuple[str, ...] | set[str] | None) -> bool:
    wanted = {_source_token(item) for item in (filters or []) if _source_token(item)}
    if not wanted or wanted.intersection({"all", "*"}):
        return True
    return bool(set(source_system_declared_tokens(source_system)) & wanted)


def source_system_filter_query_tokens(filters: list[str] | tuple[str, ...] | set[str] | None) -> tuple[str, ...]:
    tokens: list[str] = []
    for item in filters or []:
        source = _source_token(item)
        if not source:
            continue
        declared = source_system_declared_tokens(source)
        for token in declared or (source,):
            if token and token not in tokens:
                tokens.append(token)
    return tuple(tokens)


def source_system_has_session_window_id(source_system: str) -> bool:
    return runtime_source_system_declaration(source_system).has_session_window_id


def source_system_native_delivery_shape(source_system: str) -> str:
    return runtime_source_system_declaration(source_system).native_delivery_shape


def source_system_default_artifact_type(source_system: str, fallback: str = "") -> str:
    artifact_type = runtime_source_system_declaration(source_system).default_artifact_type
    return artifact_type or _clean_text(fallback)


def source_system_raw_validation_kind(source_system: str) -> str:
    return runtime_source_system_declaration(source_system).raw_validation_kind


def source_system_source_ref_kind(source_system: str) -> str:
    return runtime_source_system_declaration(source_system).source_ref_kind


def source_system_canonical_index_kind(source_system: str) -> str:
    return runtime_source_system_declaration(source_system).canonical_index_kind


def source_system_uses_raw_path_as_canonical_source(source_system: str) -> bool:
    return runtime_source_system_declaration(source_system).canonical_message_source_preference == "prefer_raw_path"


def source_system_source_scan_kind(source_system: str) -> str:
    return runtime_source_system_declaration(source_system).source_scan_kind


def source_system_gap_probe_kind(source_system: str) -> str:
    return runtime_source_system_declaration(source_system).gap_probe_kind


def source_system_delivery_session_hint_kind(source_system: str) -> str:
    return runtime_source_system_declaration(source_system).delivery_session_hint_kind


def source_system_project_status_fallback_kind(source_system: str) -> str:
    return runtime_source_system_declaration(source_system).project_status_fallback_kind


def source_system_raw_backfill_kind(source_system: str) -> str:
    return runtime_source_system_declaration(source_system).raw_backfill_kind


def declared_raw_backfill_source_systems() -> tuple[tuple[str, str], ...]:
    return tuple(
        (name, declaration.raw_backfill_kind)
        for name, declaration in SOURCE_SYSTEM_RUNTIME_DECLARATIONS.items()
        if declaration.raw_backfill_kind and declaration.raw_backfill_kind != "none"
    )


def source_system_for_raw_backfill_kind(kind: str) -> str:
    expected = _clean_text(kind)
    if not expected:
        return ""
    for name, declaration in SOURCE_SYSTEM_RUNTIME_DECLARATIONS.items():
        if declaration.raw_backfill_kind == expected:
            return name
    return ""


def source_system_distillable(source_system: str) -> bool:
    return runtime_source_system_declaration(source_system).distillable


def source_system_distill_priority(source_system: str) -> int:
    return runtime_source_system_declaration(source_system).distill_priority


def declared_distillable_source_systems() -> tuple[str, ...]:
    return tuple(
        name
        for name, declaration in SOURCE_SYSTEM_RUNTIME_DECLARATIONS.items()
        if declaration.distillable
    )


def declared_distill_checkpoint_source_systems(kind: str = "") -> tuple[str, ...]:
    expected = _clean_text(kind)
    return tuple(
        name
        for name, declaration in SOURCE_SYSTEM_RUNTIME_DECLARATIONS.items()
        if declaration.distill_checkpoint_adapter_kind
        and declaration.distill_checkpoint_adapter_kind != "none"
        and (not expected or declaration.distill_checkpoint_adapter_kind == expected)
    )


def source_system_uses_distill_checkpoint_adapter(
    source_system: str,
    *,
    index_status: str = "",
    kind: str = "",
) -> bool:
    expected = _clean_text(kind)
    declaration = runtime_source_system_declaration(source_system)
    if declaration.distill_checkpoint_adapter_kind and declaration.distill_checkpoint_adapter_kind != "none":
        if not expected or declaration.distill_checkpoint_adapter_kind == expected:
            return True
    status = _clean_text(index_status)
    if status:
        for item in SOURCE_SYSTEM_RUNTIME_DECLARATIONS.values():
            if expected and item.distill_checkpoint_adapter_kind != expected:
                continue
            if any(status.startswith(prefix) for prefix in item.distill_index_status_prefixes):
                return True
    return False


def source_system_for_distill_checkpoint_adapter(kind: str = "") -> str:
    sources = declared_distill_checkpoint_source_systems(kind)
    return sources[0] if sources else ""


def source_system_supports_distill_target_shape(source_system: str, target_shape: str) -> bool:
    target = _clean_text(target_shape)
    if not target:
        return False
    return target in runtime_source_system_declaration(source_system).distill_target_shapes


def source_system_required_coverage_source_for_distill_target_shape(source_system: str, target_shape: str) -> str:
    if source_system_supports_distill_target_shape(source_system, target_shape):
        return runtime_source_system_declaration(source_system).distill_required_coverage_source
    return ""


def source_system_uses_reading_area_raw_index(
    source_system: str,
    *,
    consumer: str = "",
    kind: str = "",
) -> bool:
    expected = _clean_text(kind)
    for value in (source_system, consumer):
        declaration = runtime_source_system_declaration(value)
        if declaration.reading_area_raw_index_kind and declaration.reading_area_raw_index_kind != "none":
            if not expected or declaration.reading_area_raw_index_kind == expected:
                return True
    return False


def source_system_for_reading_area_raw_index(kind: str = "") -> str:
    expected = _clean_text(kind)
    for name, declaration in SOURCE_SYSTEM_RUNTIME_DECLARATIONS.items():
        if declaration.reading_area_raw_index_kind and declaration.reading_area_raw_index_kind != "none":
            if not expected or declaration.reading_area_raw_index_kind == expected:
                return name
    return ""


def source_system_reading_area_raw_index_source_ref_kind(source_system: str, fallback: str = "") -> str:
    declared = runtime_source_system_declaration(source_system).reading_area_raw_index_source_ref_kind
    return declared or _clean_text(fallback)


def source_system_index_status_matches_reading_area_raw_index(source_system: str, index_status: str) -> bool:
    status = _clean_text(index_status)
    if not status:
        return False
    declaration = runtime_source_system_declaration(source_system)
    prefixes = declaration.distill_index_status_prefixes
    return any(status.startswith(prefix) for prefix in prefixes)


def source_system_delivery_runtime_kind(source_system: str) -> str:
    return runtime_source_system_declaration(source_system).delivery_runtime_kind


def source_system_native_generation_trigger_kind(source_system: str) -> str:
    return runtime_source_system_declaration(source_system).native_generation_trigger_kind


def source_system_generation_cadence(source_system: str) -> str:
    return runtime_source_system_declaration(source_system).generation_cadence


def source_system_generation_model_hint(source_system: str) -> str:
    return runtime_source_system_declaration(source_system).generation_model_hint


def source_system_generation_scope(source_system: str) -> str:
    return runtime_source_system_declaration(source_system).generation_scope


def declared_delivery_runtime_kinds() -> tuple[str, ...]:
    return tuple(
        declaration.delivery_runtime_kind
        for declaration in SOURCE_SYSTEM_RUNTIME_DECLARATIONS.values()
        if declaration.delivery_runtime_kind and declaration.delivery_runtime_kind != "none"
    )


def source_system_should_try_project_status_fallback(source_system: str) -> bool:
    return source_system_project_status_fallback_kind(source_system) == "default_recall_fallback"


def source_system_project_status_fallback_source(effective_source_system: str) -> str:
    source = _clean_text(effective_source_system)
    if source:
        return source if source_system_should_try_project_status_fallback(source) else ""
    for name, declaration in SOURCE_SYSTEM_RUNTIME_DECLARATIONS.items():
        if declaration.project_status_fallback_kind == "default_recall_fallback":
            return name
    return ""


def source_system_delivery_session_key(body: dict[str, Any] | None = None) -> str:
    payload = body if isinstance(body, dict) else {}
    for declaration in SOURCE_SYSTEM_RUNTIME_DECLARATIONS.values():
        for key in declaration.delivery_session_key_fields:
            value = _clean_text(payload.get(key))
            if value:
                return value
    return ""


def source_system_delivery_enabled(body: dict[str, Any] | None = None, cfg: dict[str, Any] | None = None) -> bool:
    payload = body if isinstance(body, dict) else {}
    if any(bool(payload.get(key)) for key in ("deliver_to_platform",)):
        return True
    for declaration in SOURCE_SYSTEM_RUNTIME_DECLARATIONS.values():
        if any(bool(payload.get(key)) for key in declaration.delivery_flag_keys):
            return True
    return False


def source_system_delivery_session_key_from_identity(
    session_id: str = "",
    source_system: str = "",
) -> str:
    session = _clean_text(session_id)
    if not session:
        return ""
    source = runtime_source_system_declaration(source_system)
    candidate_prefix_sets: list[tuple[str, ...]] = []
    if source.delivery_session_prefixes:
        candidate_prefix_sets.append(source.delivery_session_prefixes)
    else:
        candidate_prefix_sets.extend(
            declaration.delivery_session_prefixes
            for declaration in SOURCE_SYSTEM_RUNTIME_DECLARATIONS.values()
            if declaration.delivery_session_prefixes
        )
    for prefixes in candidate_prefix_sets:
        if any(session.startswith(prefix) for prefix in prefixes):
            return session
    return ""


def infer_delivery_source_system(
    *,
    platform: str = "",
    session_key: str = "",
    body: dict[str, Any] | None = None,
) -> str:
    source = _clean_text(platform).lower()
    if source and source != "same_chat":
        return source
    payload = body if isinstance(body, dict) else {}
    session = _clean_text(session_key)
    for name, declaration in SOURCE_SYSTEM_RUNTIME_DECLARATIONS.items():
        if any(bool(payload.get(key)) for key in declaration.delivery_flag_keys):
            return name
        if session and any(session.startswith(prefix) for prefix in declaration.delivery_session_prefixes):
            return name
    return source


def declared_source_systems_with_canonical_index() -> tuple[str, ...]:
    return tuple(
        name
        for name, declaration in SOURCE_SYSTEM_RUNTIME_DECLARATIONS.items()
        if declaration.canonical_index_enabled and declaration.canonical_index_kind
    )


def declared_source_systems_with_gap_probe() -> tuple[str, ...]:
    return tuple(
        name
        for name, declaration in SOURCE_SYSTEM_RUNTIME_DECLARATIONS.items()
        if declaration.gap_probe_kind != "none"
    )


def declared_guardian_connectors() -> tuple[tuple[str, str], ...]:
    return tuple(
        (name, declaration.guardian_connector_module)
        for name, declaration in SOURCE_SYSTEM_RUNTIME_DECLARATIONS.items()
        if declaration.guardian_connector_module
    )


def declared_guarded_source_systems() -> tuple[str, ...]:
    return tuple(
        name
        for name, declaration in SOURCE_SYSTEM_RUNTIME_DECLARATIONS.items()
        if declaration.guardian_implemented
    )


def normalize_source_system_window_identity(
    *,
    source_system: str,
    session_id: str,
    canonical_window_id: str,
    project_id: str = "",
    legacy_window_id: str = "",
) -> dict[str, str]:
    sid = _clean_text(session_id)
    window_id = _clean_text(canonical_window_id)
    project = _clean_text(project_id)
    legacy = _clean_text(legacy_window_id)
    if source_system_has_session_window_id(source_system) and sid:
        if window_id and window_id != sid:
            legacy = legacy or window_id
            if not project:
                project = window_id
        window_id = sid
    return {
        "session_id": sid,
        "canonical_window_id": window_id,
        "project_id": project,
        "source_refs_canonical_window_id": legacy,
    }


def recall_source_system_filters(
    *,
    effective_source_system: str,
    consumer: str = "",
    session_id: str = "",
    canonical_window_id: str = "",
) -> tuple[list[str], dict[str, Any]]:
    source = _clean_text(effective_source_system)
    if not source:
        return [""], {}
    declaration = runtime_source_system_declaration(source)
    consumer_text = _clean_text(consumer).lower().replace("-", "_")
    anchored = bool(_clean_text(session_id) or _clean_text(canonical_window_id))
    alias_tokens = declaration.recall_alias_consumer_tokens
    consumer_matches = not alias_tokens or any(token in consumer_text for token in alias_tokens)
    filters = [source]
    if anchored and consumer_matches:
        for alias in declaration.recall_window_aliases:
            alias_text = _clean_text(alias)
            if alias_text and alias_text not in filters:
                filters.append(alias_text)
    extra: dict[str, Any] = {}
    if len(filters) > 1:
        extra["source_system_filter_aliases"] = [item for item in filters if item]
        if declaration.recall_collection_filter:
            extra["source_collection_filter"] = declaration.recall_collection_filter
            extra["claude_collection_alias_applied"] = True
        if declaration.recall_collection_alias_boundary:
            extra["claude_collection_alias_boundary"] = declaration.recall_collection_alias_boundary
    return filters, extra
