import sys
import urllib.error
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def test_time_twin_star_projection_matches_tiandao_v1_shape():
    from tiandao import time_twin_star_projection

    projection = time_twin_star_projection()

    assert projection["lawId"] == "time"
    assert projection["owner"] == "yifanchen"
    assert projection["twinStar"] == {
        "surfaceContract": "time_tiandao_surface.v1",
        "rulesContract": "time_rules.v1",
    }
    assert projection["status"] == "READ_ONLY_PROJECTION"
    assert projection["implementation_status"] == "read_only_projection_present"
    assert projection["runtime_status"] == "not_connected"
    assert projection["sourceFile"] == "src/tiandao/memory_routing.py"
    assert projection["surfaces"] == ["time_origin", "time_river", "time_sediment"]
    assert len(projection["principles"]) == 5
    assert len(projection["timePolicyFields"]) == 13
    assert len(projection["ruleDefinitions"]) == 13
    assert len(projection["ruleBindings"]) == 13
    assert projection["read_only"] is True
    assert projection["runtime_behavior_changed"] is False
    assert projection["memory_write_performed"] is False
    assert projection["platform_write_performed"] is False
    assert projection["nas_runtime_dependency"] is False
    assert "does_not_claim_any_installed_runtime_time_rule_source_proven" in projection["non_claims"]


def test_time_twin_star_runtime_status_exposes_behavior_proof_when_manifest_gate_passes():
    from tiandao import time_twin_star_runtime_status

    status = time_twin_star_runtime_status()

    assert status["ok"] is True
    assert status["contract"] == "time_twin_star_runtime_status.v1"
    assert status["projection_contract"] == "time_twin_star_read_only_projection.v1"
    assert status["source_runtime_route_status"] == "source_runtime_route_present"
    assert status["runtime_status"] == "source_runtime_route_present"
    assert status["installed_runtime_status"] == "proven"
    assert status["platform_delivery_status"] == "proven"
    assert status["platform_delivery_scope"] == "controlled_openclaw_smoke_path_only"
    assert status["agent_turn_loop_status"] == "agent_turn_loop_behavior_observed"
    assert status["turn_loop_behavior_status"] == "turn_loop_behavior_proven"
    assert status["source_proven_scope"] == "repository_behavior_plus_controlled_openclaw_smoke"
    assert status["runtimeTarget"] == "p6-console-source-route"
    assert status["endpoint"] == "/api/v1/tiandao/time-twin-star/status"
    assert status["read_only"] is True
    assert status["write_performed"] is False
    assert status["raw_write_performed"] is False
    assert status["memory_write_performed"] is False
    assert status["platform_write_performed"] is False
    assert status["model_call_performed"] is False
    assert status["network_call_performed"] is False
    assert status["runtime_behavior_changed"] is True
    assert status["nas_runtime_dependency"] is False
    assert status["behavior_proof"]["trace_sufficient_for_behavior_proven"] is True
    assert status["behavior_proof"]["trace_kind"] == "observed_real_agent_turn"
    assert not status["behavior_proof"]["gate"]["missing_observations"]
    assert not status["behavior_proof"]["gate"]["forbidden_substitutes_present"]
    assert status["rule_status_counts"] == {
        "candidate_source_proven": 0,
        "contract_only": 1,
        "planned": 1,
        "source_proven": 11,
    }
    assert "time_river_has_no_endpoint" in status["contract_only_rules"]
    assert "source_streams_merge_not_overwrite" in status["planned_rules"]
    assert "each_runtime_first_witnessed_raw" in status["source_proven_rules"]
    assert status["consistency"]["ok"] is True
    assert status["consistency"]["errors"] == []
    assert "does_not_claim_platform_wide_delivery" in status["non_claims"]


def test_time_twin_star_runtime_status_without_manifest_remains_honest_not_proven(tmp_path):
    from tiandao import time_twin_star_runtime_status

    status = time_twin_star_runtime_status(proof_manifest_path=tmp_path / "missing-proof.json")

    assert status["installed_runtime_status"] == "not_proven"
    assert status["platform_delivery_status"] == "not_proven"
    assert status["runtime_behavior_changed"] is False
    assert status["behavior_proof"]["manifest_status"] == "missing"
    assert "does_not_claim_platform_delivery_proven" in status["non_claims"]


class _FakeResponse:
    def __init__(self, status: int, body: str):
        self.status = status
        self._body = body.encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self._body


def test_time_twin_star_installed_runtime_probe_detects_present_route():
    from tiandao import probe_time_twin_star_installed_runtime

    def opener(request, timeout=0):
        url = request.full_url
        if url.endswith("/api/health"):
            return _FakeResponse(200, '{"ok": true}')
        if url.endswith("/api/v1/tiandao/time-twin-star/status"):
            return _FakeResponse(
                200,
                (
                    '{"contract":"time_twin_star_runtime_status.v1",'
                    '"runtime_status":"source_runtime_route_present",'
                    '"installed_runtime_status":"proven",'
                    '"platform_delivery_status":"proven",'
                    '"agent_turn_loop_status":"agent_turn_loop_behavior_observed",'
                    '"runtime_behavior_changed":true,'
                    '"rule_status_counts":{"source_proven":11}}'
                ),
            )
        raise AssertionError(url)

    result = probe_time_twin_star_installed_runtime(opener=opener)

    assert result["contract"] == "time_twin_star_installed_runtime_probe.v1"
    assert result["installed_runtime_status"] == "installed_runtime_route_present"
    assert result["platform_delivery_status"] == "proven"
    assert result["agent_turn_loop_status"] == "agent_turn_loop_behavior_observed"
    assert result["runtime_behavior_changed"] is True
    assert result["observed_contract_payload"]["contract"] == "time_twin_star_runtime_status.v1"
    assert result["read_only"] is True
    assert result["http_methods_used"] == ["GET"]
    assert result["write_performed"] is False
    assert result["restart_performed"] is False
    assert result["sync_performed"] is False


def test_time_twin_star_installed_runtime_probe_marks_healthy_console_404_as_not_updated():
    from tiandao import probe_time_twin_star_installed_runtime

    def opener(request, timeout=0):
        url = request.full_url
        if url.endswith("/api/health"):
            return _FakeResponse(200, '{"ok": true}')
        if url.endswith("/api/v1/tiandao/time-twin-star/status"):
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
        raise AssertionError(url)

    result = probe_time_twin_star_installed_runtime(opener=opener)

    assert result["ok"] is True
    assert result["installed_runtime_status"] == "installed_runtime_not_updated"
    assert result["health_check"]["status_code"] == 200
    assert result["endpoint_check"]["status_code"] == 404
    assert result["interpretation"]["route_missing_while_console_healthy"] is True
    assert result["observed_contract_payload"] == {}
    assert "does_not_sync_installed_runtime" in result["non_claims"]
    assert "does_not_restart_p6_console" in result["non_claims"]


def test_time_twin_star_installed_runtime_probe_marks_unreachable_console():
    from tiandao import probe_time_twin_star_installed_runtime

    def opener(request, timeout=0):
        raise OSError("connection refused")

    result = probe_time_twin_star_installed_runtime(opener=opener)

    assert result["ok"] is False
    assert result["installed_runtime_status"] == "installed_runtime_not_reachable"
    assert result["health_check"]["reachable"] is False
    assert result["endpoint_check"]["reachable"] is False
    assert result["write_performed"] is False
    assert result["runtime_behavior_changed"] is False


def test_time_twin_star_consistency_preserves_proof_discipline():
    from tiandao import time_twin_star_consistency_report, time_twin_star_status_counts

    report = time_twin_star_consistency_report()

    assert report["ok"] is True
    assert report["contract"] == "time_twin_star_read_only_projection.v1"
    assert report["source_file"] == "src/tiandao/memory_routing.py"
    assert report["declared_time_policy_count"] == 13
    assert report["rule_definition_count"] == 13
    assert report["rule_binding_count"] == 13
    assert report["missing_declared_policy_fields"] == []
    assert report["unreferenced_declared_policy_fields"] == []
    assert report["errors"] == []
    assert report["status_counts"] == {
        "candidate_source_proven": 0,
        "contract_only": 1,
        "planned": 1,
        "source_proven": 11,
    }
    assert time_twin_star_status_counts() == report["status_counts"]
    assert report["source_proven_requires_complete_evidence_refs"] is True
    assert report["source_policy_classification_status"] == "all_source_policies_classified_or_covered"
    assert report["source_policies_without_classification"] == []
    assert report["stale_source_policy_classifications"] == []
    assert report["read_only"] is True
    assert report["runtime_behavior_changed"] is False
    assert report["memory_write_performed"] is False
    assert report["platform_write_performed"] is False
    assert report["nas_runtime_dependency"] is False


def test_time_twin_star_fields_are_sourced_from_memory_routing_descriptors():
    from tiandao import time_twin_star_consistency_report

    policy_values = time_twin_star_consistency_report()["source_policy_values"]

    assert policy_values["raw_authority_policy"] == ["raw_source_text_is_highest_authority"]
    assert policy_values["origin_event_policy"] == ["time_origin_begins_when_raw_is_witnessed"]
    assert policy_values["derived_sediment_policy"] == ["derived_sediment_must_reference_origin"]
    assert policy_values["local_runtime_policy"] == ["each_runtime_has_first_witnessed_raw_event"]
    assert policy_values["multi_machine_policy"] == ["source_streams_merge_not_overwrite"]
    assert set(policy_values["platform_policy"]) == {
        "platforms_are_inlets_not_origin",
        "platforms_are_inlets_not_river_laws",
    }
    assert policy_values["river_endpoint_policy"] == ["time_river_has_no_endpoint"]
    assert policy_values["origin_policy"] == ["time_river_begins_at_raw_origin_event"]
    assert policy_values["source_ref_policy"] == [
        "every_derived_sediment_must_return_to_source_refs_or_state_unavailable",
        "source_refs_are_required_but_not_a_source_replacement",
    ]
    assert policy_values["origin_link_policy"] == ["derived_sediment_must_reference_origin"]
    assert policy_values["summary_policy"] == ["summaries_are_navigation_not_source_replacement"]
    assert policy_values["time_order_policy"] == ["events_remain_orderable_by_event_time_and_audit_time"]
    assert policy_values["write_policy"] == ["read_only_descriptor_no_memory_write"]


def test_non_time_source_policies_have_explicit_classification_without_new_rules():
    from tiandao import (
        time_twin_star_consistency_report,
        time_twin_star_policy_classifications,
        time_twin_star_projection,
    )

    report = time_twin_star_consistency_report()
    classifications = {item["policyField"]: item for item in time_twin_star_policy_classifications()}

    assert report["source_policies_not_declared_as_time_rules"] == report["source_policies_outside_time_rules"]
    assert report["source_policies_not_declared_as_time_rules"] == report["unclassified_source_policies"]
    assert report["unclassified_source_policies_legacy_alias"] is True
    assert report["unclassified_source_policies_replaced_by"] == "source_policies_not_declared_as_time_rules"
    assert report["unclassified_source_policies"] == [
        "adapter_boundary_policy",
        "audit_policy",
        "context_delivery_policy",
        "endpoint_policy",
        "global_recall_policy",
        "library_identity_policy",
        "lifecycle_policy",
        "platform_capability_policy",
    ]
    assert sorted(classifications) == report["unclassified_source_policies"]
    assert all(item["ruling"] in {"not_time_rule", "covered_by_existing_time_rule"} for item in classifications.values())
    assert classifications["endpoint_policy"]["ruling"] == "covered_by_existing_time_rule"
    assert classifications["endpoint_policy"]["coveredByRule"] == "time_river_has_no_endpoint"
    assert classifications["endpoint_policy"]["coveredBySourcePolicyField"] == "river_endpoint_policy"
    assert classifications["lifecycle_policy"]["ruling"] == "not_time_rule"
    assert "不是时间律不变量" in classifications["lifecycle_policy"]["boundaryConfirmation"]
    assert report["source_policy_values"]["endpoint_policy"] == report["source_policy_values"]["river_endpoint_policy"]
    assert len(time_twin_star_projection()["sourcePolicyClassifications"]) == 8
    assert len(time_twin_star_projection()["ruleDefinitions"]) == 13
    assert len(time_twin_star_projection()["ruleBindings"]) == 13


def test_time_twin_star_rule_bindings_preserve_source_proven_discipline():
    from tiandao import time_twin_star_rule_bindings

    bindings = time_twin_star_rule_bindings()
    bindings_by_id = {binding["ruleId"]: binding for binding in bindings}
    source_proven = [binding for binding in bindings if binding["currentStatus"] == "source_proven"]

    assert [binding["ruleId"] for binding in source_proven] == [
        "raw_is_highest_authority",
        "derived_sediment_must_reference_origin",
        "source_refs_required_not_replacement",
        "summaries_are_navigation_not_source",
        "unknown_when_no_origin_link",
        "time_origin_is_witnessed_raw",
        "river_begins_at_origin_event",
        "each_runtime_first_witnessed_raw",
        "platforms_are_inlets_not_origin",
        "read_only_descriptor_no_write",
        "events_remain_orderable",
    ]
    raw_rule = bindings_by_id["raw_is_highest_authority"]
    assert raw_rule["proofScope"] == "repository_behavior"
    assert raw_rule["runtimeTarget"] == "repository-tests"
    assert raw_rule["workingDirectory"] == str(ROOT)
    assert "tests/test_raw_archive_verbatim.py" in raw_rule["evidenceRefs"]
    assert "tests/test_saved_content_verbatim_pipeline.py" in raw_rule["evidenceRefs"]
    assert "tests/test_zhixing_library.py" in raw_rule["evidenceRefs"]
    assert "tests/test_context_delivery_compaction.py" in raw_rule["evidenceRefs"]
    assert "tests/test_memory_authority_policy.py" in raw_rule["evidenceRefs"]
    assert "pending" not in " ".join(raw_rule["evidenceRefs"]).lower()
    assert "test_openclaw_raw_archive_preserves_platform_record_verbatim" in raw_rule["evidenceCommand"]
    assert "test_memory_authority_policy_documents_installed_scoped_recall_boundary" in raw_rule[
        "evidenceCommand"
    ]
    assert "不宣称所有 raw 入口或所有保存路径已穷尽" in raw_rule["nonClaims"]

    derived_rule = bindings_by_id["derived_sediment_must_reference_origin"]
    assert derived_rule["proofScope"] == "repository_behavior"
    assert derived_rule["runtimeTarget"] == "repository-tests"
    assert derived_rule["workingDirectory"] == str(ROOT)
    assert "tests/test_time_river_sediment.py" in derived_rule["evidenceRefs"]
    assert "tests/test_code_change_tiandao_source.py" in derived_rule["evidenceRefs"]
    assert "pending" not in " ".join(derived_rule["evidenceRefs"]).lower()
    assert "tests/test_time_river_sediment.py" in derived_rule["evidenceCommand"]
    assert "test_code_change_tiandao_source_reports_dirty_worktree_without_writing" in derived_rule[
        "evidenceCommand"
    ]
    assert "不宣称所有派生沉积路径已穷尽" in derived_rule["nonClaims"]

    read_only_rule = bindings_by_id["read_only_descriptor_no_write"]
    assert read_only_rule["proofScope"] == "repository_behavior"
    assert read_only_rule["runtimeTarget"] == "repository-tests"
    assert read_only_rule["workingDirectory"] == str(ROOT)
    assert "tests/test_time_twin_star.py" in read_only_rule["evidenceRefs"]
    assert "tests/test_time_river_sediment.py" in read_only_rule["evidenceRefs"]
    assert "tests/test_tiandao_source_canon.py" in read_only_rule["evidenceRefs"]
    assert "pending" not in " ".join(read_only_rule["evidenceRefs"]).lower()
    assert "test_time_twin_star_projection_matches_tiandao_v1_shape" in read_only_rule["evidenceCommand"]
    assert "test_time_river_sediment_dry_run_is_read_only" in read_only_rule["evidenceCommand"]
    assert "不宣称所有只读路径或所有导入路径已穷尽" in read_only_rule["nonClaims"]

    source_refs_rule = bindings_by_id["source_refs_required_not_replacement"]
    assert source_refs_rule["proofScope"] == "repository_behavior"
    assert source_refs_rule["runtimeTarget"] == "repository-tests"
    assert source_refs_rule["workingDirectory"] == str(ROOT)
    assert "tests/test_delivery_receipt.py" in source_refs_rule["evidenceRefs"]
    assert "tests/test_search_think_dry_run.py" in source_refs_rule["evidenceRefs"]
    assert "tests/test_evidence_atom_vocabulary.py" in source_refs_rule["evidenceRefs"]
    assert "tests/test_time_river_sediment.py" in source_refs_rule["evidenceRefs"]
    assert "pending" not in " ".join(source_refs_rule["evidenceRefs"]).lower()
    assert source_refs_rule["evidenceCommand"].startswith("python3 -m pytest -q")
    assert "不宣称忆凡尘运行态已接入时间双子星" in source_refs_rule["nonClaims"]

    summary_rule = bindings_by_id["summaries_are_navigation_not_source"]
    assert summary_rule["proofScope"] == "repository_behavior"
    assert summary_rule["runtimeTarget"] == "repository-tests"
    assert summary_rule["workingDirectory"] == str(ROOT)
    assert "tests/test_source_ref_compact_evidence.py" in summary_rule["evidenceRefs"]
    assert "tests/test_context_delivery_compaction.py" in summary_rule["evidenceRefs"]
    assert "tests/test_zhixing_context_unit.py" in summary_rule["evidenceRefs"]
    assert "tests/test_zhixing_library.py" in summary_rule["evidenceRefs"]
    assert "pending" not in " ".join(summary_rule["evidenceRefs"]).lower()
    assert "test_source_ref_compact_evidence_reads_bounded_raw_for_model_only" in summary_rule["evidenceCommand"]
    assert "test_context_delivery_compaction_recommends_log_compaction_with_source_refs" in summary_rule[
        "evidenceCommand"
    ]
    assert "不宣称所有摘要/压缩路径已穷尽" in summary_rule["nonClaims"]

    unknown_rule = bindings_by_id["unknown_when_no_origin_link"]
    assert unknown_rule["proofScope"] == "repository_behavior"
    assert unknown_rule["runtimeTarget"] == "repository-tests"
    assert unknown_rule["workingDirectory"] == str(ROOT)
    assert "tests/test_evidence_bound_model.py" in unknown_rule["evidenceRefs"]
    assert "tests/test_search_think_dry_run.py" in unknown_rule["evidenceRefs"]
    assert "tests/test_time_river_sediment.py" in unknown_rule["evidenceRefs"]
    assert "pending" not in " ".join(unknown_rule["evidenceRefs"]).lower()
    assert "test_no_evidence_returns_unknown_without_model_call" in unknown_rule["evidenceCommand"]
    assert "test_time_river_sediment_without_origin_or_source_refs_is_untrusted_candidate" in unknown_rule["evidenceCommand"]
    assert "不宣称所有 UNKNOWN 场景已穷尽" in unknown_rule["nonClaims"]

    origin_rule = bindings_by_id["time_origin_is_witnessed_raw"]
    assert origin_rule["proofScope"] == "repository_behavior"
    assert origin_rule["runtimeTarget"] == "repository-tests"
    assert origin_rule["workingDirectory"] == str(ROOT)
    assert "tests/test_raw_origin_event.py" in origin_rule["evidenceRefs"]
    assert "tests/test_raw_record_guardian.py" in origin_rule["evidenceRefs"]
    assert "tests/test_tiandao_merge.py" in origin_rule["evidenceRefs"]
    assert "pending" not in " ".join(origin_rule["evidenceRefs"]).lower()
    assert "test_raw_origin_event_is_stable_and_raw_is_time_origin" in origin_rule["evidenceCommand"]
    assert "test_raw_record_guardian_reports_record_guarded_after_raw_mirror" in origin_rule["evidenceCommand"]
    assert "test_canonical_record_index_stores_codex_offsets_and_chunks" in origin_rule["evidenceCommand"]
    assert "不宣称所有 raw 入口或所有 guardian/index 路径已穷尽" in origin_rule["nonClaims"]

    runtime_rule = bindings_by_id["each_runtime_first_witnessed_raw"]
    assert runtime_rule["proofScope"] == "repository_behavior"
    assert runtime_rule["runtimeTarget"] == "repository-tests"
    assert runtime_rule["workingDirectory"] == str(ROOT)
    assert "src/raw_origin_event.py" in runtime_rule["evidenceRefs"]
    assert "tests/test_raw_origin_event.py" in runtime_rule["evidenceRefs"]
    assert "tests/test_tiandao_merge.py" in runtime_rule["evidenceRefs"]
    assert "pending" not in " ".join(runtime_rule["evidenceRefs"]).lower()
    assert "test_origin_summary_reports_first_witnessed_raw_per_local_runtime" in runtime_rule[
        "evidenceCommand"
    ]
    assert "test_raw_origin_event_is_stable_and_raw_is_time_origin" in runtime_rule["evidenceCommand"]
    assert "test_tiandao_python_exports_nantianmen_promoted_contracts" in runtime_rule["evidenceCommand"]
    assert "不宣称所有 runtime/source_system 分组或所有机器已穷尽" in runtime_rule["nonClaims"]
    assert "不宣称多机源流合并已由本条证明" in runtime_rule["nonClaims"]
    assert "不宣称 source_streams_merge_not_overwrite 已由本条证明" in runtime_rule["nonClaims"]

    river_rule = bindings_by_id["river_begins_at_origin_event"]
    assert river_rule["proofScope"] == "repository_behavior"
    assert river_rule["runtimeTarget"] == "repository-tests"
    assert river_rule["workingDirectory"] == str(ROOT)
    assert "tests/test_raw_origin_event.py" in river_rule["evidenceRefs"]
    assert "tests/test_tiandao_merge.py" in river_rule["evidenceRefs"]
    assert "tests/test_time_river_sediment.py" in river_rule["evidenceRefs"]
    assert "pending" not in " ".join(river_rule["evidenceRefs"]).lower()
    assert "test_raw_origin_event_is_stable_and_raw_is_time_origin" in river_rule["evidenceCommand"]
    assert "test_tiandao_python_exports_nantianmen_promoted_contracts" in river_rule["evidenceCommand"]
    assert "test_tiandao_schema_and_ts_sources_preserve_neutral_contract_names" in river_rule["evidenceCommand"]
    assert "test_time_river_sediment_links_derived_memory_to_raw_origin" in river_rule["evidenceCommand"]
    assert "不宣称 time_river_has_no_endpoint 公理已由本条测试证明" in river_rule["nonClaims"]

    platform_rule = bindings_by_id["platforms_are_inlets_not_origin"]
    assert platform_rule["proofScope"] == "repository_behavior"
    assert platform_rule["runtimeTarget"] == "repository-tests"
    assert platform_rule["workingDirectory"] == str(ROOT)
    assert "tests/test_raw_origin_event.py" in platform_rule["evidenceRefs"]
    assert "tests/test_tiandao_merge.py" in platform_rule["evidenceRefs"]
    assert "pending" not in " ".join(platform_rule["evidenceRefs"]).lower()
    assert "test_platform_source_system_is_inlet_not_time_origin" in platform_rule["evidenceCommand"]
    assert "test_tiandao_python_exports_nantianmen_promoted_contracts" in platform_rule["evidenceCommand"]
    assert "test_tiandao_schema_and_ts_sources_preserve_neutral_contract_names" in platform_rule[
        "evidenceCommand"
    ]
    assert "不宣称所有平台、入口或适配器路径已穷尽" in platform_rule["nonClaims"]
    assert "不宣称平台动作权限或平台送达由本条证明" in platform_rule["nonClaims"]

    order_rule = bindings_by_id["events_remain_orderable"]
    assert order_rule["proofScope"] == "repository_behavior"
    assert order_rule["runtimeTarget"] == "repository-tests"
    assert order_rule["workingDirectory"] == str(ROOT)
    assert "src/raw_record_canonical_index.py" in order_rule["evidenceRefs"]
    assert "tests/test_raw_record_guardian.py" in order_rule["evidenceRefs"]
    assert "tests/test_raw_origin_event.py" in order_rule["evidenceRefs"]
    assert "tests/test_tiandao_merge.py" in order_rule["evidenceRefs"]
    assert "pending" not in " ".join(order_rule["evidenceRefs"]).lower()
    assert "test_origin_events_remain_orderable_by_event_time_and_audit_time" in order_rule[
        "evidenceCommand"
    ]
    assert "test_raw_origin_event_is_stable_and_raw_is_time_origin" in order_rule["evidenceCommand"]
    assert "test_tiandao_python_exports_nantianmen_promoted_contracts" in order_rule["evidenceCommand"]
    assert "不宣称所有 origin_events 查询路径或排序场景已穷尽" in order_rule["nonClaims"]
    assert "不宣称事件时间本身的真实性已由本条证明" in order_rule["nonClaims"]

    candidates = [binding for binding in bindings if binding["currentStatus"] == "candidate_source_proven"]
    assert candidates == []


def test_source_canon_reports_time_twin_star_first_cut_without_runtime_claim():
    from tiandao import tiandao_total_rules_v1_contract

    status = tiandao_total_rules_v1_contract()["time_twin_star"]

    assert status["current_status"] == "read_only_projection_present"
    assert status["implementation_status"] == "first_cut_read_only_projection"
    assert status["projection_source"] == "src/tiandao/time_twin_star.py"
    assert status["runtime_status"] == "not_connected"
    assert status["rule_status_counts_from_tiandao_v1"] == {
        "candidate_source_proven": 0,
        "contract_only": 1,
        "planned": 1,
        "source_proven": 11,
    }
    assert status["source_proven_rules"] == [
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
    assert status["source_proven_scope"] == "repository_behavior_only"


def test_time_order_policy_is_classified_as_time_river_rule():
    from tiandao import time_twin_star_consistency_report, time_twin_star_rule_definitions, time_twin_star_rule_bindings

    report = time_twin_star_consistency_report()
    definitions = {definition["id"]: definition for definition in time_twin_star_rule_definitions()}
    bindings = {binding["ruleId"]: binding for binding in time_twin_star_rule_bindings()}

    assert "time_order_policy" not in report["unclassified_source_policies"]
    assert definitions["events_remain_orderable"]["surface"] == "time_river"
    assert definitions["events_remain_orderable"]["sourcePolicyFields"] == ["time_order_policy"]
    assert "time_order_policy belongs to the time river surface" in definitions["events_remain_orderable"][
        "classificationRuling"
    ]
    assert bindings["events_remain_orderable"]["currentStatus"] == "source_proven"
    assert bindings["events_remain_orderable"]["surfaces"] == ["time_river"]


def test_time_twin_star_import_does_not_touch_nas_paths(monkeypatch):
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
    projection = tiandao.time_twin_star_projection()

    assert projection["nas_runtime_dependency"] is False
    assert not any(path.startswith("/Volumes/洪荒体系笔记") for path in checked_paths)


def test_time_twin_star_turn_loop_definition_splits_probe_from_behavior():
    from tiandao import time_twin_star_turn_loop_definition_of_proven

    definition = time_twin_star_turn_loop_definition_of_proven()
    levels = {item["id"]: item for item in definition["levels"]}

    assert definition["contract"] == "time_twin_star_turn_loop_probe.v1"
    assert definition["current_target"] == "turn_loop_probe_present"
    assert definition["agent_turn_loop_status"] == "agent_turn_loop_not_proven"
    assert definition["turn_loop_behavior_status"] == "turn_loop_behavior_not_proven"
    assert "turn_loop_probe_present" in levels
    assert "turn_loop_behavior_proven" in levels
    assert "ordinary_chat_handled_false" in levels["turn_loop_probe_present"]["required_observations"]
    assert "actual_agent_turn_loop_invoked" in levels["turn_loop_behavior_proven"]["required_observations"]
    assert "repository_tests_only" in levels["turn_loop_behavior_proven"]["not_allowed_as_substitute"]
    assert definition["read_only"] is True
    assert definition["runtime_behavior_changed"] is False


def test_time_twin_star_turn_loop_probe_classifies_passive_first_without_behavior_claim():
    from tiandao import time_twin_star_turn_loop_probe_from_observations

    result = time_twin_star_turn_loop_probe_from_observations(
        ordinary_result={
            "handled": False,
            "reason": "openclaw_before_dispatch_requires_explicit_zhiyi_entry",
            "action": "pass_through",
        },
        explicit_result={
            "handled": True,
            "chain": "F3_zhiyi_direct",
            "answer": "探针入口已到达。",
            "text": "探针入口已到达。",
            "platform_delivery": {"write_performed": False},
            "before_dispatch_raw_capture": {"write_performed": False},
            "before_dispatch_dedupe": {"write_performed": False},
            "usage_log": {"usage_log_write_performed": False},
        },
        write_observations={"platform_action_performed": False},
    )

    assert result["ok"] is True
    assert result["turn_loop_probe_status"] == "turn_loop_probe_present"
    assert result["agent_turn_loop_status"] == "agent_turn_loop_not_proven"
    assert result["turn_loop_behavior_status"] == "turn_loop_behavior_not_proven"
    assert result["observations"]["ordinary_passive_first"] is True
    assert result["observations"]["explicit_hook_observed"] is True
    assert result["observations"]["no_write_observed"] is True
    assert result["observations"]["no_model_call"] is True
    assert result["observations"]["no_platform_action"] is True
    assert result["write_performed"] is False
    assert result["model_call_performed"] is False
    assert result["runtime_behavior_changed"] is False
    assert "does_not_claim_agent_turn_loop_behavior_proven" in result["non_claims"]


def test_time_twin_star_turn_loop_probe_rejects_ordinary_chat_hijack():
    from tiandao import time_twin_star_turn_loop_probe_from_observations

    result = time_twin_star_turn_loop_probe_from_observations(
        ordinary_result={"handled": True, "reason": ""},
        explicit_result={"handled": True, "chain": "F3_zhiyi_direct", "answer": "入口已到达。"},
    )

    assert result["ok"] is False
    assert result["turn_loop_probe_status"] == "turn_loop_probe_unproven"
    assert result["observations"]["ordinary_passive_first"] is False


def test_time_twin_star_turn_loop_probe_tool_runs_read_only():
    from tools import time_twin_star_turn_loop_probe

    result = time_twin_star_turn_loop_probe.run_probe()

    assert result["ok"] is True
    assert result["turn_loop_probe_status"] == "turn_loop_probe_present"
    assert result["agent_turn_loop_status"] == "agent_turn_loop_not_proven"
    assert result["turn_loop_behavior_status"] == "turn_loop_behavior_not_proven"
    assert result["fixture_backed"] is True
    assert result["installed_runtime_touched"] is False
    assert result["platform_action_performed"] is False
    assert result["model_call_performed"] is False
    assert result["user_work_records_read"] is False
    assert result["read_only"] is True
    assert result["write_performed"] is False
    assert result["ordinary"]["handled"] is False
    assert result["explicit"]["handled"] is True


def test_time_twin_star_turn_loop_trace_gate_definition_is_read_only():
    from tiandao import time_twin_star_turn_loop_trace_gate_definition

    definition = time_twin_star_turn_loop_trace_gate_definition()

    assert definition["contract"] == "time_twin_star_turn_loop_trace_gate.v1"
    assert definition["gate_status"] == "turn_loop_trace_gate_present"
    assert definition["target_status"] == "turn_loop_behavior_proven"
    assert definition["current_behavior_status"] == "turn_loop_behavior_not_proven"
    assert "actual_agent_turn_loop_invoked" in definition["required_observations"]
    assert "repository_tests_only" in definition["forbidden_substitutes"]
    assert definition["read_only"] is True
    assert definition["runtime_behavior_changed"] is False
    assert "does_not_collect_a_real_turn_trace_by_itself" in definition["non_claims"]


def test_time_twin_star_turn_loop_trace_gate_rejects_fixture_substitute():
    from tiandao import time_twin_star_turn_loop_trace_gate_from_observation

    result = time_twin_star_turn_loop_trace_gate_from_observation(
        {
            "trace_kind": "fixture_backed_model_trace",
            "repository_tests_only": True,
            "actual_agent_turn_loop_invoked": True,
            "evidence_packet_observed_before_judgment": True,
        }
    )

    assert result["trace_sufficient_for_behavior_proven"] is False
    assert result["turn_loop_behavior_status"] == "turn_loop_behavior_not_proven"
    assert "trace_kind_observed_real_agent_turn" in result["missing_observations"]
    assert "repository_tests_only" in result["forbidden_substitutes_present"]
    assert result["read_only"] is True
    assert result["write_performed"] is False


def test_time_twin_star_turn_loop_trace_gate_rejects_fixture_uri_even_if_kind_is_forged():
    from tiandao import time_twin_star_turn_loop_trace_gate_from_observation

    result = time_twin_star_turn_loop_trace_gate_from_observation(
        {
            "trace_kind": "observed_real_agent_turn",
            "source": "fixture://turn-loop-probe",
            "observations": {
                "actual_agent_turn_loop_invoked": True,
                "evidence_packet_observed_before_judgment": True,
                "passive_first_default_still_handled_false": True,
                "receipt_visible": True,
                "gap_visible_when_relevant": True,
                "unknown_visible_when_no_evidence": True,
                "time_rules_changed_real_user_answer_behavior": True,
                "changed_behavior_was_correct": True,
                "rollback_boundary_documented": True,
                "no_platform_action_without_separate_authorization": True,
            },
        }
    )

    assert result["trace_sufficient_for_behavior_proven"] is False
    assert "fixture_source_uri" in result["forbidden_substitutes_present"]


def test_time_twin_star_turn_loop_trace_gate_accepts_complete_external_real_trace():
    from tiandao import time_twin_star_turn_loop_trace_gate_from_observation

    result = time_twin_star_turn_loop_trace_gate_from_observation(
        {
            "trace_kind": "observed_real_agent_turn",
            "observations": {
                "actual_agent_turn_loop_invoked": True,
                "evidence_packet_observed_before_judgment": True,
                "passive_first_default_still_handled_false": True,
                "receipt_visible": True,
                "gap_visible_when_relevant": True,
                "unknown_visible_when_no_evidence": True,
                "time_rules_changed_real_user_answer_behavior": True,
                "changed_behavior_was_correct": True,
                "rollback_boundary_documented": True,
                "no_platform_action_without_separate_authorization": True,
            },
        }
    )

    assert result["trace_sufficient_for_behavior_proven"] is True
    assert result["turn_loop_behavior_status"] == "turn_loop_behavior_proven"
    assert result["agent_turn_loop_status"] == "agent_turn_loop_behavior_observed"
    assert result["missing_observations"] == []
    assert result["forbidden_substitutes_present"] == []
    assert result["runtime_behavior_changed"] is False
    assert "does_not_collect_a_real_turn_trace_by_itself" in result["non_claims"]


def test_time_twin_star_turn_loop_trace_gate_accepts_nested_behavior_proof_manifest():
    from tiandao import time_twin_star_turn_loop_trace_gate_from_observation

    result = time_twin_star_turn_loop_trace_gate_from_observation(
        {
            "contract": "time_twin_star_behavior_proof_manifest.v1",
            "proof_status": "behavior_proven",
            "trace": {
                "trace_kind": "observed_real_agent_turn",
                "source": "installed_openclaw_before_dispatch_raw_capture_and_usage_log",
                "observations": {
                    "actual_agent_turn_loop_invoked": True,
                    "evidence_packet_observed_before_judgment": True,
                    "passive_first_default_still_handled_false": True,
                    "receipt_visible": True,
                    "gap_visible_when_relevant": True,
                    "unknown_visible_when_no_evidence": True,
                    "time_rules_changed_real_user_answer_behavior": True,
                    "changed_behavior_was_correct": True,
                    "rollback_boundary_documented": True,
                    "no_platform_action_without_separate_authorization": True,
                },
            },
        }
    )

    assert result["trace_sufficient_for_behavior_proven"] is True
    assert result["missing_observations"] == []
    assert result["forbidden_substitutes_present"] == []


def test_time_twin_star_turn_loop_trace_gate_tool_classifies_empty_trace_as_unproven():
    from tools import time_twin_star_turn_loop_trace_gate

    result = time_twin_star_turn_loop_trace_gate.time_twin_star_turn_loop_trace_gate_from_observation({})

    assert result["contract"] == "time_twin_star_turn_loop_trace_gate.v1"
    assert result["trace_sufficient_for_behavior_proven"] is False
    assert result["turn_loop_behavior_status"] == "turn_loop_behavior_not_proven"
    assert "trace_kind_observed_real_agent_turn" in result["missing_observations"]


def test_time_twin_star_passive_push_trace_gate_definition_matches_spec():
    from tiandao import time_twin_star_passive_push_trace_gate_definition

    definition = time_twin_star_passive_push_trace_gate_definition()

    assert definition["contract"] == "time_twin_star_passive_push_trace_gate.v1"
    assert definition["gate_status"] == "passive_push_trace_gate_present"
    assert definition["target_status"] == "passive_push_behavior_proven"
    assert definition["current_behavior_status"] == "passive_push_behavior_not_proven"
    assert definition["scope"] == "controlled_openclaw_model_in_loop_smoke_only"
    assert definition["push_coverage_delta_when_sufficient"] == "0/7_to_1/7_when_model_in_loop"
    assert "no_explicit_recall_call" in definition["required_observations"]
    assert "answer_uses_recalled_memory" in definition["required_observations"]
    assert "model_call_performed" in definition["required_observations"]
    assert "negative_arm_no_injection" in definition["required_observations"]
    assert "explicit_zhiyi_recall_call" in definition["forbidden_substitutes"]
    assert "direct_endpoint_controlled_smoke_only" in definition["forbidden_substitutes"]
    assert "fixture_evidence_bound_model" in definition["forbidden_substitutes"]
    assert "gateway_injected_model_only" in definition["forbidden_substitutes"]
    assert "substring_success_masquerading_as_vector" in definition["forbidden_substitutes"]
    assert definition["read_only"] is True


def test_time_twin_star_passive_push_trace_gate_rejects_explicit_pull_substitute():
    from tiandao import time_twin_star_passive_push_trace_gate_from_observation

    result = time_twin_star_passive_push_trace_gate_from_observation(
        {
            "trace_kind": "observed_real_agent_turn",
            "explicit_zhiyi_recall_call": True,
            "observations": {
                "actual_agent_turn_loop_invoked": True,
                "before_dispatch_auto_injection": True,
                "positive_memory_matched": True,
                "primary_recall_backend_vector": True,
                "matched_by_contains_vector": True,
                "evidence_packet_observed_before_judgment": True,
                "answer_uses_recalled_memory": True,
                "model_call_performed": True,
                "passive_first_default_still_handled_false": True,
                "negative_arm_no_injection": True,
                "receipt_visible": True,
                "source_ref_visible": True,
                "smoke_session_only": True,
                "no_real_person_touched": True,
                "flags_restored": True,
                "no_unauthorized_platform_write": True,
                "rollback_boundary_documented": True,
                "fallback_explicit_when_vector_miss": True,
            },
        }
    )

    assert result["trace_sufficient_for_passive_push_proven"] is False
    assert result["push_behavior_status"] == "passive_push_behavior_not_proven"
    assert "no_explicit_recall_call" in result["missing_observations"]
    assert "explicit_zhiyi_recall_call" in result["forbidden_substitutes_present"]
    assert result["push_coverage_delta"] == "0/7_still_unproven"


def test_time_twin_star_passive_push_trace_gate_rejects_endpoint_trace_without_model_call():
    from tiandao import time_twin_star_passive_push_trace_gate_from_observation

    trace = {
        "trace_kind": "observed_real_agent_turn",
        "provenance": "direct_installed_runtime_openclaw_before_dispatch_endpoint_controlled_smoke",
        "observations": {
            "actual_agent_turn_loop_invoked": True,
            "no_explicit_recall_call": True,
            "before_dispatch_auto_injection": True,
            "positive_memory_matched": True,
            "primary_recall_backend_vector": True,
            "matched_by_contains_vector": True,
            "evidence_packet_observed_before_judgment": True,
            "answer_uses_recalled_memory": True,
            "passive_first_default_still_handled_false": True,
            "negative_arm_no_injection": True,
            "receipt_visible": True,
            "source_ref_visible": True,
            "smoke_session_only": True,
            "no_real_person_touched": True,
            "flags_restored": True,
            "no_unauthorized_platform_write": True,
            "rollback_boundary_documented": True,
            "fallback_explicit_when_vector_miss": True,
        },
    }

    result = time_twin_star_passive_push_trace_gate_from_observation(trace)

    assert result["trace_sufficient_for_passive_push_proven"] is False
    assert result["push_behavior_status"] == "passive_push_behavior_not_proven"
    assert "model_call_performed" in result["missing_observations"]
    assert "direct_endpoint_controlled_smoke_only" in result["forbidden_substitutes_present"]
    assert result["push_coverage_delta"] == "0/7_still_unproven"


def test_time_twin_star_passive_push_trace_gate_rejects_fixture_or_gateway_model_answer():
    from tiandao import time_twin_star_passive_push_trace_gate_from_observation

    base = {
        "trace_kind": "observed_real_agent_turn",
        "observations": {
            "actual_agent_turn_loop_invoked": True,
            "no_explicit_recall_call": True,
            "before_dispatch_auto_injection": True,
            "positive_memory_matched": True,
            "primary_recall_backend_vector": True,
            "matched_by_contains_vector": True,
            "evidence_packet_observed_before_judgment": True,
            "answer_uses_recalled_memory": True,
            "model_call_performed": True,
            "passive_first_default_still_handled_false": True,
            "negative_arm_no_injection": True,
            "receipt_visible": True,
            "source_ref_visible": True,
            "smoke_session_only": True,
            "no_real_person_touched": True,
            "flags_restored": True,
            "no_unauthorized_platform_write": True,
            "rollback_boundary_documented": True,
            "fallback_explicit_when_vector_miss": True,
        },
    }

    fixture = time_twin_star_passive_push_trace_gate_from_observation(
        {**base, "answer_source": "fixture-evidence-bound-model"}
    )
    gateway = time_twin_star_passive_push_trace_gate_from_observation(
        {**base, "model_name": "gateway-injected"}
    )

    assert fixture["trace_sufficient_for_passive_push_proven"] is False
    assert "fixture_evidence_bound_model" in fixture["forbidden_substitutes_present"]
    assert gateway["trace_sufficient_for_passive_push_proven"] is False
    assert "gateway_injected_model_only" in gateway["forbidden_substitutes_present"]


def test_time_twin_star_passive_push_trace_gate_accepts_complete_openclaw_model_in_loop_smoke():
    from tiandao import time_twin_star_passive_push_trace_gate_from_observation

    result = time_twin_star_passive_push_trace_gate_from_observation(
        {
            "trace_kind": "observed_real_agent_turn",
            "answer_source": "evidence_bound_model_call",
            "model_name": "MiniMax-M2",
            "observations": {
                "actual_agent_turn_loop_invoked": True,
                "no_explicit_recall_call": True,
                "before_dispatch_auto_injection": True,
                "positive_memory_matched": True,
                "primary_recall_backend_vector": True,
                "matched_by_contains_vector": True,
                "evidence_packet_observed_before_judgment": True,
                "answer_uses_recalled_memory": True,
                "model_call_performed": True,
                "passive_first_default_still_handled_false": True,
                "negative_arm_no_injection": True,
                "receipt_visible": True,
                "source_ref_visible": True,
                "smoke_session_only": True,
                "no_real_person_touched": True,
                "flags_restored": True,
                "no_unauthorized_platform_write": True,
                "rollback_boundary_documented": True,
                "fallback_explicit_when_vector_miss": True,
            },
        }
    )

    assert result["trace_sufficient_for_passive_push_proven"] is True
    assert result["push_behavior_status"] == "passive_push_behavior_proven"
    assert result["push_platform_scope"] == "controlled_openclaw_model_in_loop_smoke_only"
    assert result["push_coverage_delta"] == "0/7_to_1/7"
    assert result["missing_observations"] == []
    assert result["forbidden_substitutes_present"] == []
    assert result["read_only"] is True
