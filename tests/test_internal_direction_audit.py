import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "internal_direction_audit.py"


def _load_audit():
    spec = importlib.util.spec_from_file_location("internal_direction_audit_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_internal_direction_audit_is_maintainer_only_and_read_only():
    audit = _load_audit()

    report = audit.audit_directions()

    assert report["ok"] is True
    assert report["contract"] == "memcore_internal_direction_audit.v1"
    assert report["audience"] == "maintainer_only_not_product_ui"
    assert report["read_only"] is True
    assert report["write_performed"] is False
    assert report["service_call_performed"] is False
    assert report["product_ui_write_performed"] is False
    assert report["public_docs_write_performed"] is False
    assert report["summary"]["public_ui_policy"] == (
        "ordinary_users_see_record_health_and_recovery_not_internal_direction_completion"
    )
    assert report["counts"]["directions_total"] >= 10
    assert report["counts"]["by_status"] == {"present": report["counts"]["directions_total"]}
    assert report["subtractive_strategy"]["contract"] == "memcore_subtractive_strategy.v1"
    assert report["subtractive_strategy"]["product_law"] == "protect_raw_records_and_continue_with_evidence_first"
    assert report["subtractive_strategy"]["ordinary_user_ui_rule"] == (
        "show_record_health_platform_connection_lost_source_lost_raw_recovery_backup"
    )


def test_internal_direction_audit_covers_current_direction_set():
    audit = _load_audit()

    report = audit.audit_directions()
    by_id = {item["direction_id"]: item for item in report["directions"]}

    expected_ids = {
        "record_origin_guard",
        "codex_large_session_canonical_index",
        "claude_desktop_body_capture",
        "openclaw_hermes_record_coverage",
        "time_river_and_sediment",
        "second_brain",
        "material_processing_pipeline",
        "external_docs_evidence",
        "context_delivery_compaction",
        "ai_platform_discovery_and_model_facts",
        "dialog_entry_lan_security",
        "release_artifact_gate",
    }
    assert expected_ids.issubset(by_id)
    assert by_id["second_brain"]["maturity"] == "dry_run_orchestration_verified"
    assert by_id["second_brain"]["strategic_bucket"] == "subcapability_constrain"
    assert by_id["record_origin_guard"]["strategic_bucket"] == "core_keep"
    assert by_id["codex_large_session_canonical_index"]["strategic_bucket"] == "core_keep"
    assert by_id["claude_desktop_body_capture"]["strategic_bucket"] == "core_keep"
    assert by_id["openclaw_hermes_record_coverage"]["strategic_bucket"] == "core_keep"
    assert by_id["external_docs_evidence"]["user_surface_policy"] == (
        "do_not_brand_named_doc_providers_as_dependencies"
    )
    assert by_id["external_docs_evidence"]["strategic_bucket"] == "subcapability_constrain"
    assert by_id["context_delivery_compaction"]["strategic_bucket"] == "subcapability_constrain"
    assert by_id["ai_platform_discovery_and_model_facts"]["strategic_bucket"] == "pause_expansion"
    assert by_id["release_artifact_gate"]["maturity"] == "working_tree_pre_release_verified"
    assert by_id["release_artifact_gate"]["strategic_bucket"] == "pause_expansion"


def test_internal_direction_audit_subtractive_buckets_are_balanced():
    audit = _load_audit()

    report = audit.audit_directions()
    counts = report["counts"]["by_strategic_bucket"]

    assert counts["core_keep"] >= 4
    assert counts["subcapability_constrain"] >= 4
    assert counts["pause_expansion"] >= 1
    assert sum(counts.values()) == report["counts"]["directions_total"]
    assert report["summary"]["subtractive_policy"] == (
        "new_work_must_fit_core_keep_or_constrained_subcapability_before_release"
    )


def test_internal_direction_audit_markdown_states_not_product_ui():
    audit = _load_audit()

    markdown = audit.render_markdown(audit.audit_directions())

    assert "# 忆凡尘内部方向收口审计 2026.6.20" in markdown
    assert "`maintainer_only_not_product_ui`" in markdown
    assert "这是维护者内部审计，不进入普通用户控制台。" in markdown
    assert "## 减法策略" in markdown
    assert "`protect_raw_records_and_continue_with_evidence_first`" in markdown
    assert "战略桶: `subcapability_constrain`" in markdown
    assert "战略桶: `pause_expansion`" in markdown
    assert "present` 只代表代码 / 测试 / 锚点覆盖" in markdown
    assert "第二大脑 / Second Brain" in markdown
