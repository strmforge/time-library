import json
from pathlib import Path

from tools.r0_memory_contract_baseline import (
    DEFAULT_SNAPSHOT,
    build_deterministic_baseline,
    build_spend_scenarios,
    build_zero_write_manifest,
    collect_live_observation,
    compare_zero_write_manifests,
    inventory_runtime_objects,
)


ROOT = Path(__file__).resolve().parents[1]


def _write_runtime_fixture(root):
    records = {
        "preference_memory": [
            {
                "exp_id": "pref-1",
                "summary": "Synthetic preference",
                "detail": "Keep source refs visible.",
                "status": "active",
                "source_refs": {
                    "source_system": "r0_synthetic",
                    "source_path": "synthetic/pref.jsonl",
                },
            }
        ],
        "case_memory": [
            {
                "exp_id": "case-1",
                "summary": "Synthetic case",
                "detail": "A state remains ambiguous.",
                "source_refs": json.dumps(
                    {"source_system": "r0_synthetic", "source_path": "synthetic/case.jsonl"}
                ),
            }
        ],
        "error_memory": [
            {
                "exp_id": "error-1",
                "summary": "Synthetic error",
                "detail": "A verifier failed.",
                "source_refs": {
                    "source_system": "r0_synthetic",
                    "source_path": "synthetic/error.jsonl",
                },
            }
        ],
    }
    for kind, items in records.items():
        path = root / "zhiyi" / kind / (kind + ".jsonl")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(item) + "\n" for item in items), encoding="utf-8")


def test_deterministic_baseline_repeats_without_an_overall_score():
    first = build_deterministic_baseline(repo_root=ROOT, snapshot=DEFAULT_SNAPSHOT)
    second = build_deterministic_baseline(repo_root=ROOT, snapshot=DEFAULT_SNAPSHOT)

    assert first == second
    assert first["deterministic_digest_sha256"] == second["deterministic_digest_sha256"]
    assert first["fixture_case_count"] == 120
    assert first["no_overall_score"] is True
    assert "overall_score" not in first
    assert first["read_only"] is True
    assert first["write_performed"] is False
    assert first["model_call_performed"] is False


def test_baseline_has_independent_denominators_and_honest_failure_buckets():
    report = build_deterministic_baseline(repo_root=ROOT)

    assert report["layers"] == {
        "state": {"denominator": 60, "pass": 10, "fail": 50, "not_measured": 0},
        "retrieval": {"denominator": 40, "pass": 30, "fail": 0, "not_measured": 10},
        "delivery": {"denominator": 10, "pass": 0, "fail": 0, "not_measured": 10},
        "security": {"denominator": 10, "pass": 0, "fail": 10, "not_measured": 0},
    }
    assert set(report["failure_buckets"]) == {
        "exact_source",
        "current_state_update",
        "historical_as_of",
        "conflict_unknown",
        "long_range_multi_session",
        "delivery_adoption",
        "poisoned_memory",
    }
    assert report["failure_buckets"]["current_state_update"] == {
        "denominator": 20,
        "pass": 10,
        "fail": 10,
        "not_measured": 0,
    }
    assert report["failure_buckets"]["delivery_adoption"]["not_measured"] == 10
    assert report["failure_buckets"]["poisoned_memory"]["fail"] == 10
    assert all(item["source_refs"] for item in report["cases"] if item["status"] != "pass")


def test_baseline_does_not_strawman_existing_p3_or_relay_voiceprint():
    report = build_deterministic_baseline(repo_root=ROOT)
    capabilities = report["existing_chain_capabilities"]

    for key in (
        "p3_lifecycle_superseded_exclusion",
        "p3_historical_downweight",
        "p3_effective_from_freshness",
        "p3_bm25",
        "p3_fts5",
        "p3_rrf",
        "granite_vector_path",
        "state_ledger_conflict_display",
    ):
        assert capabilities[key]["observed"] is True
    assert capabilities["unified_bitemporal_current_as_of"]["status"] == "gap_confirmed"
    assert report["relay_voiceprint_boundary"] == {
        "status": "attribution_material_only",
        "poisoning_defense_proven": False,
    }
    assert report["platform_delivery_baseline"]["proven"] == 0
    assert report["platform_delivery_baseline"]["denominator"] == 7


def test_runtime_inventory_and_spend_scenarios_are_measured_not_assumed(tmp_path):
    _write_runtime_fixture(tmp_path)
    inventory = inventory_runtime_objects(tmp_path)
    spend = build_spend_scenarios(inventory)

    assert inventory["object_count"] == 3
    assert inventory["source_refs_present_count"] == 3
    assert inventory["unique_content_sha256_count"] == 3
    assert inventory["deterministic_prescreen_resolved_count"] == 1
    assert inventory["ambiguous_model_upper_bound_count"] == 2
    scenarios = {item["scenario"]: item for item in spend["scenarios"]}
    assert scenarios["naive_full"]["model_object_count"] == 3
    assert scenarios["sha_cache_unchanged_rerun"]["model_object_count"] == 0
    assert scenarios["deterministic_prescreen_then_ambiguous_only"]["model_object_count"] == 2
    assert scenarios["incremental_after_first_snapshot"]["status"] == "not_measured"
    assert spend["proposed_budget_guard"]["status"] == "proposal_requires_owner_approval"
    assert all(
        profile["provenance"] == "sensitivity_assumption_not_provider_quote"
        for profile in spend["price_profiles"].values()
    )


def test_live_observation_sanitizes_paths_and_keeps_model_comparison_not_measured(tmp_path):
    _write_runtime_fixture(tmp_path)

    def fake_fetch(url):
        if url.endswith("19300/health"):
            return {
                "status": "ok",
                "memory_count": 3,
                "vector_recall": {
                    "ok": True,
                    "model_id": "ibm-granite/granite-embedding-97m-multilingual-r2",
                    "embedding_dim": 384,
                    "row_count": 3,
                    "model_loaded": True,
                    "table_loaded": True,
                    "table_identity": {"storage": "LanceDB"},
                    "model_path": str(tmp_path / "private-model-path"),
                },
            }
        if "guardian/status" in url:
            return {
                "ok": True,
                "read_only": True,
                "write_performed": False,
                "summary": {
                    "record_count": 3,
                    "record_guarded_count": 3,
                    "raw_not_current_count": 0,
                    "raw_catching_up_count": 0,
                    "lost_source_count": 0,
                    "lost_raw_count": 0,
                    "corrupt_record_count": 0,
                },
                "private_path": str(tmp_path / "private-record"),
            }
        return 404, None, "http_error"

    report = collect_live_observation(runtime_root=tmp_path, repo_root=tmp_path, fetch_json=fake_fetch)
    serialized = json.dumps(report, sort_keys=True)

    assert report["runtime_objects"]["object_count"] == 3
    assert report["p3_health"]["vector"]["storage"] == "LanceDB"
    assert report["guardian"]["summary"]["record_guarded_count"] == 3
    assert report["local_vs_cloud_extraction"]["status"] == "not_measured"
    assert report["r2_decision"]["decision"] == "NO_GO"
    assert str(tmp_path) not in serialized
    assert "private-model-path" not in serialized


def test_zero_write_manifest_comparison_allows_only_monotonic_raw_append(tmp_path):
    repo = tmp_path / "repo"
    runtime = tmp_path / "runtime"
    repo.mkdir()
    (repo / "config").mkdir()
    (repo / "README.md").write_text("README", encoding="utf-8")
    (repo / "README.zh-CN.md").write_text("README zh", encoding="utf-8")
    (repo / "config" / "model.json").write_text("{}", encoding="utf-8")
    _write_runtime_fixture(runtime)
    raw = runtime / "memory" / "node" / "session.jsonl"
    raw.parent.mkdir(parents=True)
    raw.write_text("one\n", encoding="utf-8")

    before = build_zero_write_manifest(repo_root=repo, runtime_root=runtime)
    raw.write_text("one\ntwo\n", encoding="utf-8")
    after = build_zero_write_manifest(repo_root=repo, runtime_root=runtime)
    result = compare_zero_write_manifests(before, after)

    assert result["ok"] is True
    assert result["protected_unchanged"] is True
    assert result["raw_observation"]["grown_count"] == 1
    assert result["raw_observation"]["shrunk_count"] == 0

    (repo / "README.md").write_text("changed", encoding="utf-8")
    changed = build_zero_write_manifest(repo_root=repo, runtime_root=runtime)
    result = compare_zero_write_manifests(after, changed)
    assert result["ok"] is False
    assert result["protected_sections"]["repo_readmes"]["changed_count"] == 1
