import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def test_tiandao_total_rules_v1_is_locally_registered_without_runtime_claims():
    from tiandao import tiandao_total_rules_v1_contract

    contract = tiandao_total_rules_v1_contract()

    assert contract["canon_ref"] == "tiandao-total-rules-v1@2026-06-22"
    assert contract["canon_status"] == "canon_accepted"
    assert contract["proof_status"] == "not_applicable"
    assert contract["runtime_status"] == "not_connected"
    assert contract["source_layer_only"] is True
    assert contract["runtime_connected"] is False
    assert contract["source_code_connected"] is False
    assert contract["gate_proven"] is False
    assert contract["packaged_proven"] is False
    assert contract["runtime_behavior_changed"] is False
    assert contract["nas_runtime_dependency"] is False
    assert contract["build_run_dependency"] is False
    assert contract["nas_paths_are_audit_refs_only"] is True
    assert "<private-time-rule-canon>/time-rule-total-rules-v1-2026-06-22.md" in contract["source_refs"]
    assert "<private-time-rule-receipts>/time-rule-total-rules-v1-merge-2026-06-22.md" in contract["receipt_refs"]
    assert (
        "<private-time-rule-receipts>/time-rule-total-rules-v1-rule-03-source-proven-2026-06-22.md"
        in contract["receipt_refs"]
    )
    assert (
        "<private-time-rule-receipts>/time-rule-total-rules-v1-rule-04-source-proven-2026-06-22.md"
        in contract["receipt_refs"]
    )
    assert (
        "<private-time-rule-receipts>/time-rule-total-rules-v1-rule-05-source-proven-2026-06-22.md"
        in contract["receipt_refs"]
    )
    assert (
        "<private-time-rule-receipts>/time-rule-total-rules-v1-rule-06-source-proven-2026-06-22.md"
        in contract["receipt_refs"]
    )
    assert (
        "<private-time-rule-receipts>/time-rule-total-rules-v1-rule-07-source-proven-2026-06-22.md"
        in contract["receipt_refs"]
    )
    assert (
        "<private-time-rule-receipts>/time-rule-total-rules-v1-rule-08-source-proven-2026-06-22.md"
        in contract["receipt_refs"]
    )
    assert (
        "<private-time-rule-receipts>/time-rule-total-rules-v1-rule-09-source-proven-2026-06-22.md"
        in contract["receipt_refs"]
    )
    assert (
        "<private-time-rule-receipts>/time-rule-total-rules-v1-rule-10-source-proven-2026-06-22.md"
        in contract["receipt_refs"]
    )
    assert (
        "<private-time-rule-receipts>/time-rule-total-rules-v1-rule-11-source-proven-2026-06-22.md"
        in contract["receipt_refs"]
    )
    assert "does_not_claim_time_twin_star_runtime_integrated" in contract["non_claims"]
    assert "does_not_claim_installed_runtime_time_rule_source_proven" in contract["non_claims"]
    assert "does_not_read_nas_at_import_or_runtime" in contract["non_claims"]


def test_tiandao_source_canon_registry_keeps_nas_as_audit_refs_only():
    from tiandao import tiandao_source_canon_registry

    registry = tiandao_source_canon_registry()

    assert registry["contract"] == "tiandao_source_canon_registry.v1"
    assert registry["registry_scope"] == "time_library_local_source_canon_mirror"
    assert registry["read_only"] is True
    assert registry["write_performed"] is False
    assert registry["raw_write_performed"] is False
    assert registry["memory_write_performed"] is False
    assert registry["platform_write_performed"] is False
    assert registry["nas_runtime_dependency"] is False
    assert registry["build_run_dependency"] is False
    assert registry["runtime_connected"] is False
    assert registry["source_ref_policy"] == "nas_paths_are_audit_refs_only_not_import_or_runtime_dependencies"
    canon_refs = {entry["canon_ref"] for entry in registry["entries"]}
    assert "tiandao-core-yizhong-tongyuan-source-canon-discipline@2026-06-22" in canon_refs
    assert "tiandao-total-rules-v1@2026-06-22" in canon_refs


def test_time_twin_star_status_is_read_only_projection_not_runtime_yet():
    from tiandao import tiandao_total_rules_v1_contract

    time_status = tiandao_total_rules_v1_contract()["time_twin_star"]

    assert time_status["surface_contract"] == "time_tiandao_surface.v1"
    assert time_status["rules_contract"] == "time_rules.v1"
    assert time_status["current_repo_source"] == "src/tiandao/memory_routing.py"
    assert time_status["current_status"] == "read_only_projection_present"
    assert time_status["runtime_status"] == "not_connected"
    assert time_status["implementation_status"] == "first_cut_read_only_projection"
    assert time_status["projection_source"] == "src/tiandao/time_twin_star.py"
    assert time_status["first_cut_policy"] == "read_only_projection_no_runtime_behavior_change"
    assert time_status["rule_status_counts_from_tiandao_v1"] == {
        "candidate_source_proven": 0,
        "contract_only": 1,
        "planned": 1,
        "source_proven": 11,
    }
    assert time_status["source_proven_rules"] == [
        "derived_sediment_must_reference_origin",
        "each_runtime_first_witnessed_raw",
        "events_remain_orderable",
        "platforms_are_inlets_not_origin",
        "raw_is_highest_authority",
        "read_only_descriptor_no_write",
        "river_begins_at_origin_event",
        "source_refs_required_not_replacement",
        "summaries_are_navigation_not_source",
        "time_origin_is_witnessed_raw",
        "unknown_when_no_origin_link",
    ]
    assert time_status["source_proven_scope"] == "repository_behavior_only"


def test_source_canon_import_does_not_touch_nas_paths(monkeypatch):
    import importlib
    import pathlib

    original_exists = pathlib.Path.exists
    checked_paths: list[str] = []

    def recording_exists(self):
        checked_paths.append(str(self))
        return original_exists(self)

    monkeypatch.setattr(pathlib.Path, "exists", recording_exists)

    for module_name in list(sys.modules):
        if module_name == "tiandao" or module_name.startswith("tiandao."):
            del sys.modules[module_name]

    tiandao = importlib.import_module("tiandao")

    registry = tiandao.tiandao_source_canon_registry()

    assert registry["runtime_connected"] is False
    assert not any(path.startswith("/" + "Volumes" + "/private-time-rule-canon") for path in checked_paths)
