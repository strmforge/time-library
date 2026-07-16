#!/usr/bin/env python3
"""Internal direction-closure audit for Time Library.

This script is for maintainer release notes and NAS construction notes. It does
not call local services, does not write product UI, and does not claim that a
dry-run contract is a finished user-facing feature.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
INTERNAL_AUDIENCE = "maintainer_only_not_product_ui"
CORE_KEEP = "core_keep"
SUBCAPABILITY_CONSTRAIN = "subcapability_constrain"
PAUSE_EXPANSION = "pause_expansion"
STRATEGIC_BUCKETS = (CORE_KEEP, SUBCAPABILITY_CONSTRAIN, PAUSE_EXPANSION)


@dataclass(frozen=True)
class DirectionSpec:
    direction_id: str
    zh_name: str
    en_name: str
    strategic_bucket: str
    strategic_rule: str
    maturity: str
    user_surface_policy: str
    code_paths: tuple[str, ...]
    test_paths: tuple[str, ...]
    anchors: tuple[str, ...] = ()
    next_step: str = ""


DIRECTIONS: tuple[DirectionSpec, ...] = (
    DirectionSpec(
        direction_id="record_origin_guard",
        zh_name="记录底座与时间起源",
        en_name="Record Origin Guard",
        strategic_bucket=CORE_KEEP,
        strategic_rule="keep_as_first_mission_raw_records_and_recovery",
        maturity="verified_foundation",
        user_surface_policy="show_record_health_only_not_internal_completion",
        code_paths=("src/raw_record_guardian.py", "src/raw_origin_event.py"),
        test_paths=("tests/test_raw_record_guardian.py", "tests/test_raw_origin_event.py"),
        anchors=("遗失源", "遗失 raw", "/api/v1/records/guardian/status", "/api/v1/records/canonical-index"),
        next_step="Keep long-running multi-machine samples under record health monitoring.",
    ),
    DirectionSpec(
        direction_id="codex_large_session_canonical_index",
        zh_name="Codex 大会话 canonical index",
        en_name="Codex Large Session Canonical Index",
        strategic_bucket=CORE_KEEP,
        strategic_rule="keep_as_record_reliability_for_primary_platform",
        maturity="verified_foundation",
        user_surface_policy="show_all_session_record_status_not_internal_architecture",
        code_paths=("src/codex_local_connector.py", "src/raw_record_guardian.py", "src/raw_record_canonical_index.py"),
        test_paths=("tests/test_codex_connector.py", "tests/test_raw_record_guardian.py"),
        anchors=("canonical_index", "codex_session_jsonl", "message_index_in_record"),
        next_step="Run against real growing Codex JSONL files during long tasks.",
    ),
    DirectionSpec(
        direction_id="claude_desktop_body_capture",
        zh_name="Claude Desktop 正文采集",
        en_name="Claude Desktop Body Capture",
        strategic_bucket=CORE_KEEP,
        strategic_rule="keep_as_primary_platform_record_capture",
        maturity="implemented_needs_long_run_validation",
        user_surface_policy="show_claude_record_health_not_reference_tool_names",
        code_paths=("src/claude_desktop_connector.py", "src/raw_record_guardian.py"),
        test_paths=("tests/test_claude_desktop_connector.py", "tests/test_claude_desktop_p0_ingest.py"),
        anchors=("claude_projects_jsonl_desktop_entrypoint", "claude_desktop_authorized_local_store_jsonl"),
        next_step="Keep independent Windows samples running to prove stable capture beyond fixtures.",
    ),
    DirectionSpec(
        direction_id="openclaw_hermes_record_coverage",
        zh_name="OpenClaw / Hermes 记录覆盖",
        en_name="OpenClaw / Hermes Record Coverage",
        strategic_bucket=CORE_KEEP,
        strategic_rule="keep_as_primary_platform_record_capture",
        maturity="implemented_needs_long_run_validation",
        user_surface_policy="show_platform_record_health_and_connection_state",
        code_paths=(
            "src/raw_record_guardian.py",
            "system/openclaw/plugins/time-library-native/index.js",
            "system/hermes/plugins/time_library/__init__.py",
        ),
        test_paths=("tests/test_raw_record_guardian.py", "tests/test_shared_memory_consumption.py"),
        anchors=("messagesSnapshot", "hermes_state_db_messages_jsonl", "openclaw_session_jsonl"),
        next_step="Validate with real active OpenClaw and Hermes sessions, not only synthetic fixtures.",
    ),
    DirectionSpec(
        direction_id="time_river_and_sediment",
        zh_name="时间长河与沉积链",
        en_name="Time River and Sediment",
        strategic_bucket=SUBCAPABILITY_CONSTRAIN,
        strategic_rule="constrain_as_internal_rule_layer_not_user_feature",
        maturity="contract_and_dry_run_verified",
        user_surface_policy="do_not_show_internal_completion_panel",
        code_paths=("src/time_river_sediment.py", "src/tiandao/memory_routing.py", "src/raw_origin_event.py"),
        test_paths=("tests/test_tiandao_merge.py", "tests/test_time_river_sediment.py", "tests/test_raw_origin_event.py"),
        anchors=("tiandao_time_river.v1", "tiandao_time_river_sediment.v1", "time_river_has_no_endpoint"),
        next_step="Use it as the neutral rule layer behind record health and recall, not as a user dashboard.",
    ),
    DirectionSpec(
        direction_id="code_change_tiandao_source_inlet",
        zh_name="代码变更time-rule源流接入口",
        en_name="Code Change Tiandao Source Inlet",
        strategic_bucket=SUBCAPABILITY_CONSTRAIN,
        strategic_rule="constrain_to_read_only_source_refs_for_maintainer_code_changes",
        maturity="source_refs_only_audit_verified",
        user_surface_policy="maintainer_only_do_not_show_as_memory_or_release_claim",
        code_paths=("src/code_change_tiandao_source.py",),
        test_paths=("tests/test_code_change_tiandao_source.py",),
        anchors=(
            "tiandao_code_change_source_inlet.v1",
            "source_refs_only_until_raw_origin",
            "code_changes_are_source_evidence_not_memory_sediment",
        ),
        next_step="Persist a raw source artifact only through an explicit maintainer workflow; do not auto-adopt into Zhiyi/Xingce.",
    ),
    DirectionSpec(
        direction_id="second_brain",
        zh_name="第二大脑",
        en_name="Second Brain",
        strategic_bucket=SUBCAPABILITY_CONSTRAIN,
        strategic_rule="constrain_to_source_backed_material_processing",
        maturity="dry_run_orchestration_verified",
        user_surface_policy="internal_workbench_until_productized",
        code_paths=("src/second_brain.py", "src/material_processing_pipeline.py", "src/time_river_sediment.py"),
        test_paths=("tests/test_second_brain.py", "tests/test_material_processing_pipeline.py"),
        anchors=("tiandao_second_brain.v1", "second_brain_receipt.v1", "/api/v1/tiandao/second-brain/dry-run"),
        next_step="Productize only when the user-facing workflow is about processing material, not internal status.",
    ),
    DirectionSpec(
        direction_id="material_processing_pipeline",
        zh_name="资料处理流水线",
        en_name="Material Processing Pipeline",
        strategic_bucket=SUBCAPABILITY_CONSTRAIN,
        strategic_rule="constrain_to_batch_review_for_traceable_evidence",
        maturity="dry_run_orchestration_verified",
        user_surface_policy="user_value_is_reviewable_material_batches_not_internal_method_names",
        code_paths=("src/material_processing_pipeline.py",),
        test_paths=("tests/test_material_processing_pipeline.py",),
        anchors=("zhixing_material_processing_pipeline.v1", "wip_limit", "small_batch_review"),
        next_step="Connect real document/source batches after the dry-run rules stay stable.",
    ),
    DirectionSpec(
        direction_id="external_docs_evidence",
        zh_name="外部文档证据层",
        en_name="External Docs Evidence",
        strategic_bucket=SUBCAPABILITY_CONSTRAIN,
        strategic_rule="constrain_to_source_capture_before_answer",
        maturity="dry_run_contract_verified",
        user_surface_policy="do_not_brand_named_doc_providers_as_dependencies",
        code_paths=("src/external_docs_evidence.py",),
        test_paths=("tests/test_external_docs_evidence.py",),
        anchors=("zhixing_external_docs_evidence.v1", "brand_named_provider_dependency", "user_configured_docs_provider"),
        next_step="Keep provider names as user-configured sources, not required project dependencies.",
    ),
    DirectionSpec(
        direction_id="context_delivery_compaction",
        zh_name="上下文投递压缩",
        en_name="Context Delivery Compaction",
        strategic_bucket=SUBCAPABILITY_CONSTRAIN,
        strategic_rule="constrain_to_delivery_optimization_without_raw_loss",
        maturity="dry_run_contract_verified",
        user_surface_policy="show_benefit_as_less_context_noise_not_named_external_tooling",
        code_paths=("src/context_delivery_compaction.py",),
        test_paths=("tests/test_context_delivery_compaction.py",),
        anchors=("zhixing_context_delivery_compaction.v1", "source_refs", "retrieve_contract"),
        next_step="Attach to real recall/context packaging only after source-ref retrieval remains lossless.",
    ),
    DirectionSpec(
        direction_id="ai_platform_discovery_and_model_facts",
        zh_name="AI 平台发现与模型事实",
        en_name="AI Platform Discovery and Model Facts",
        strategic_bucket=PAUSE_EXPANSION,
        strategic_rule="pause_beyond_record_and_zhiyi_model_use_no_generic_asset_management",
        maturity="read_only_and_host_owned_self_install_verified",
        user_surface_policy="show_recognized_tools_and_zhiyi_model_only",
        code_paths=("src/platform_autodiscovery.py", "src/platform_thin_adapter_registry.py", "src/model_facts.py"),
        test_paths=("tests/test_platform_autodiscovery.py", "tests/test_model_facts.py"),
        anchors=(
            "host_self_install_then_verified_self_report",
            "model_facts_are_read_back_for_time_library_use",
            "detected_is_not_runnable",
        ),
        next_step="Keep default scans metadata-only; live model smoke remains explicit authorization.",
    ),
    DirectionSpec(
        direction_id="dialog_entry_lan_security",
        zh_name="Dialog Entry LAN 安全分档",
        en_name="Dialog Entry LAN Security",
        strategic_bucket=CORE_KEEP,
        strategic_rule="keep_as_record_entry_safety_and_lan_reachability",
        maturity="verified_runtime_boundary",
        user_surface_policy="show_service_health_not_security_internals",
        code_paths=("src/dialog_entry_proxy.py", "tools/windows_guardian.ps1", "tools/windows_full_install.ps1"),
        test_paths=("tests/test_security_boundaries.py",),
        anchors=("MEMCORE_DIALOG_ENTRY_TOKEN", "dialog_entry_host", "Authorization"),
        next_step="Preserve LAN reachability for OpenClaw/Hermes while keeping action routes token-gated.",
    ),
    DirectionSpec(
        direction_id="release_artifact_gate",
        zh_name="发布包与 release gate",
        en_name="Release Artifact Gate",
        strategic_bucket=PAUSE_EXPANSION,
        strategic_rule="pause_as_public_product_feature_keep_as_maintainer_gate",
        maturity="working_tree_pre_release_verified",
        user_surface_policy="public_release_notes_only_after_head_build_and_tag",
        code_paths=("tools/build_release_artifact.py", "tools/release_gate.py"),
        test_paths=("tests/test_release_artifact.py", "tests/test_release_gate.py"),
        anchors=("working-tree", "git\", \"archive", "PUBLIC_FORBIDDEN_TERMS"),
        next_step="Before public release, commit, build from HEAD, tag, and upload zip plus checksum.",
    ),
)


def _read_text(rel_path: str) -> str:
    path = ROOT / rel_path
    if not path.exists() or not path.is_file():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def _exists(rel_path: str) -> bool:
    return (ROOT / rel_path).is_file()


def _anchor_hits(spec: DirectionSpec) -> list[dict[str, Any]]:
    files = [*spec.code_paths, *spec.test_paths, "src/p6_console.py", "web/console_product.html"]
    hits: list[dict[str, Any]] = []
    for anchor in spec.anchors:
        found_in = [rel for rel in files if anchor in _read_text(rel)]
        hits.append({"anchor": anchor, "found": bool(found_in), "files": found_in[:6]})
    return hits


def _status_for(missing_code: list[str], missing_tests: list[str], anchors: list[dict[str, Any]]) -> str:
    if missing_code:
        return "missing_code"
    if missing_tests:
        return "missing_tests"
    if any(not item["found"] for item in anchors):
        return "missing_anchor"
    return "present"


def audit_directions() -> dict[str, Any]:
    version = _read_text("VERSION").strip()
    directions: list[dict[str, Any]] = []
    for spec in DIRECTIONS:
        missing_code = [rel for rel in spec.code_paths if not _exists(rel)]
        missing_tests = [rel for rel in spec.test_paths if not _exists(rel)]
        anchors = _anchor_hits(spec)
        status = _status_for(missing_code, missing_tests, anchors)
        directions.append({
            "direction_id": spec.direction_id,
            "zh_name": spec.zh_name,
            "en_name": spec.en_name,
            "strategic_bucket": spec.strategic_bucket,
            "strategic_rule": spec.strategic_rule,
            "status": status,
            "maturity": spec.maturity,
            "audience": INTERNAL_AUDIENCE,
            "user_surface_policy": spec.user_surface_policy,
            "code_paths": list(spec.code_paths),
            "test_paths": list(spec.test_paths),
            "missing_code_paths": missing_code,
            "missing_test_paths": missing_tests,
            "anchors": anchors,
            "next_step": spec.next_step,
        })
    counts: dict[str, int] = {}
    strategic_counts = {bucket: 0 for bucket in STRATEGIC_BUCKETS}
    for item in directions:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
        strategic_counts[item["strategic_bucket"]] = strategic_counts.get(item["strategic_bucket"], 0) + 1
    return {
        "ok": all(item["status"] == "present" for item in directions),
        "contract": "memcore_internal_direction_audit.v1",
        "audience": INTERNAL_AUDIENCE,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "version": version,
        "read_only": True,
        "write_performed": False,
        "service_call_performed": False,
        "product_ui_write_performed": False,
        "public_docs_write_performed": False,
        "counts": {
            "directions_total": len(directions),
            "by_status": counts,
            "by_strategic_bucket": strategic_counts,
        },
        "subtractive_strategy": {
            "contract": "memcore_subtractive_strategy.v1",
            "product_law": "protect_raw_records_and_continue_with_evidence_first",
            "core_keep": "records_sync_index_recovery_recall_evidence",
            "subcapability_constrain": "second_brain_external_docs_compaction_time_river_only_when_they_strengthen_record_evidence",
            "pause_expansion": "do_not_expand_into_generic_asset_management_model_center_or_public_internal_status",
            "ordinary_user_ui_rule": "show_record_health_platform_connection_lost_source_lost_raw_recovery_backup",
        },
        "directions": directions,
        "summary": {
            "completion_claim": "core_directions_have_code_test_anchor_coverage_when_status_present",
            "non_claim": "present_does_not_mean_public_stable_product_or_long_run_proven",
            "public_ui_policy": "ordinary_users_see_record_health_and_recovery_not_internal_direction_completion",
            "subtractive_policy": "new_work_must_fit_core_keep_or_constrained_subcapability_before_release",
        },
    }


def _format_file_list(paths: Iterable[str]) -> str:
    values = list(paths)
    if not values:
        return "-"
    return ", ".join(f"`{path}`" for path in values)


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        f"# Time Library内部方向收口审计 {report.get('version') or ''}".rstrip(),
        "",
        f"- 合同: `{report['contract']}`",
        f"- 受众: `{report['audience']}`",
        f"- 生成时间: `{report['generated_at']}`",
        f"- 只读: `{report['read_only']}`",
        f"- 结论: `{'PASS' if report['ok'] else 'ATTENTION'}`",
        "",
        "## 减法策略",
        "",
        f"- 产品铁律: `{report['subtractive_strategy']['product_law']}`",
        f"- 核心保留: `{report['subtractive_strategy']['core_keep']}`",
        f"- 收束为子能力: `{report['subtractive_strategy']['subcapability_constrain']}`",
        f"- 暂停扩张: `{report['subtractive_strategy']['pause_expansion']}`",
        "",
        "## 边界",
        "",
        "- 这是维护者内部审计，不进入普通用户控制台。",
        "- 普通用户只看记录健康、平台连接、遗失源 / 遗失 raw、恢复与备份。",
        "- `present` 只代表代码 / 测试 / 锚点覆盖，不代表公开稳定产品态或长期运行已证明。",
        "",
        "## 方向",
        "",
    ]
    for item in report["directions"]:
        lines.extend([
            f"### {item['zh_name']} / {item['en_name']}",
            "",
            f"- 状态: `{item['status']}`",
            f"- 战略桶: `{item['strategic_bucket']}`",
            f"- 收束规则: `{item['strategic_rule']}`",
            f"- 成熟度: `{item['maturity']}`",
            f"- 用户界面边界: `{item['user_surface_policy']}`",
            f"- 代码: {_format_file_list(item['code_paths'])}",
            f"- 测试: {_format_file_list(item['test_paths'])}",
            f"- 下一步: {item['next_step']}",
            "",
        ])
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate internal direction-closure audit.")
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    parser.add_argument("--output", help="optional output path; stdout is used when omitted")
    args = parser.parse_args()

    report = audit_directions()
    if args.format == "json":
        content = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    else:
        content = render_markdown(report)
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(content, encoding="utf-8")
    else:
        print(content, end="")
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
