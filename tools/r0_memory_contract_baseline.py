#!/usr/bin/env python3
"""Reproducible R0 contract baseline and sanitized live inventory.

The deterministic mode executes isolated pure functions from the released Git
snapshot against synthetic fixtures. Live mode reads aggregate counters only.
Neither mode writes a memory store, changes recall, or calls a model.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import math
import os
import subprocess
import sys
import types
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.port_discovery import front_door_url
DEFAULT_SNAPSHOT = "3d470e2c9769f48cefbb00ccb52fafd82c667bc9"
DEFAULT_FIXTURE = ROOT / "tests" / "fixtures" / "time_library_r0_baseline_cases.json"
CONTRACT = "time_library.r0_memory_contract_baseline.v2026.7.13"
LIVE_CONTRACT = "time_library.r0_live_inventory.v2026.7.13"
MANIFEST_CONTRACT = "time_library.r0_zero_write_manifest.v2026.7.13"
MANIFEST_COMPARISON_CONTRACT = "time_library.r0_zero_write_comparison.v2026.7.13"
FAILURE_BUCKETS = (
    "exact_source",
    "current_state_update",
    "historical_as_of",
    "conflict_unknown",
    "long_range_multi_session",
    "delivery_adoption",
    "poisoned_memory",
)
LAYERS = ("state", "retrieval", "delivery", "security")
PLATFORM_DELIVERY_BASELINE = {
    platform: "not_measured"
    for platform in (
        "openclaw",
        "hermes",
        "codex",
        "claude_desktop",
        "claude_code_cli",
        "cursor",
        "pi",
    )
}
PRICE_PROFILES = {
    "low_sensitivity": {"input_usd_per_million": 0.20, "output_usd_per_million": 1.00},
    "reference_planning": {"input_usd_per_million": 1.00, "output_usd_per_million": 5.00},
    "high_sensitivity": {"input_usd_per_million": 3.00, "output_usd_per_million": 15.00},
}


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _payload_digest(payload: Dict[str, Any]) -> str:
    clean = dict(payload)
    clean.pop("deterministic_digest_sha256", None)
    clean.pop("manifest_digest_sha256", None)
    return _sha256_bytes(_canonical_json(clean).encode("utf-8"))


def _git_text(repo_root: Path, snapshot: str, relative_path: str) -> str:
    result = subprocess.run(
        ["git", "show", "%s:%s" % (snapshot, relative_path)],
        cwd=str(repo_root),
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result.stdout.decode("utf-8")


def _git_commit(repo_root: Path, snapshot: str) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "%s^{commit}" % snapshot],
        cwd=str(repo_root),
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return result.stdout.strip()


def _snapshot_module(source: str, name: str) -> types.ModuleType:
    module = types.ModuleType(name)
    module.__file__ = "git-snapshot://%s" % name
    exec(compile(source, module.__file__, "exec"), module.__dict__)
    return module


def _ast_namespace(
    source: str,
    *,
    functions: Iterable[str],
    assignments: Iterable[str] = (),
    globals_map: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    wanted_functions = set(functions)
    wanted_assignments = set(assignments)
    selected: List[ast.AST] = []
    for node in ast.parse(source).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in wanted_functions:
            selected.append(node)
        elif isinstance(node, ast.Assign):
            names = {target.id for target in node.targets if isinstance(target, ast.Name)}
            if names & wanted_assignments:
                selected.append(node)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id in wanted_assignments:
                selected.append(node)
    namespace: Dict[str, Any] = dict(globals_map or {})
    namespace.setdefault("__builtins__", __builtins__)
    module = ast.fix_missing_locations(ast.Module(body=selected, type_ignores=[]))
    exec(compile(module, "git-snapshot://ast-subset", "exec"), namespace)
    return namespace


def _line_anchor(snapshot: str, relative_path: str, source: str, needle: str) -> Dict[str, str]:
    line = next((index for index, text in enumerate(source.splitlines(), 1) if needle in text), 0)
    return {
        "source_system": "git_snapshot",
        "evidence_ref": "%s:%s:%d" % (snapshot, relative_path, line),
    }


def _case_result(
    case: Dict[str, Any],
    status: str,
    observed: Dict[str, Any],
    reasons: Iterable[str] = (),
) -> Dict[str, Any]:
    return {
        "case_id": case["case_id"],
        "family": case["family"],
        "layer": case["layer"],
        "failure_bucket": case["failure_bucket"],
        "status": status,
        "expected": case["expected"],
        "observed": observed,
        "reasons": list(reasons),
        "source_refs": case["source_refs"],
        "source_span": case["source_span"],
    }


def _build_snapshot_runtime(repo_root: Path, snapshot: str) -> Dict[str, Any]:
    atom_source = _git_text(repo_root, snapshot, "src/evidence_atom_vocabulary.py")
    state_source = _git_text(repo_root, snapshot, "src/zhixing_state_ledger.py")
    p2_source = _git_text(repo_root, snapshot, "src/p2_extract.py")
    p3_source = _git_text(repo_root, snapshot, "src/p3_recall.py")
    granite_source = _git_text(repo_root, snapshot, "src/granite_vector_assets.py")

    atom = _snapshot_module(atom_source, "r0_snapshot_evidence_atom")
    state = _snapshot_module(state_source, "r0_snapshot_state_ledger")
    p2 = _ast_namespace(
        p2_source,
        functions=("is_noise",),
        assignments=("ANTI_NOISE_KW",),
    )
    p3 = _ast_namespace(
        p3_source,
        functions=(
            "_query_terms",
            "_source_refs_for_filter",
            "_normalize_source_filter",
            "_is_project_status_memory",
            "filter_memories",
            "_is_noise_memory",
            "_apply_lifecycle_overlay",
            "_rrf_fuse",
            "_tokenize_bm25",
            "_bm25_score_single",
        ),
        globals_map={"json": json, "re": __import__("re")},
    )
    return {
        "atom": atom,
        "state": state,
        "p2": p2,
        "p3": p3,
        "sources": {
            "atom": atom_source,
            "state": state_source,
            "p2": p2_source,
            "p3": p3_source,
            "granite": granite_source,
        },
    }


def _evaluate_case(case: Dict[str, Any], runtime: Dict[str, Any]) -> Dict[str, Any]:
    atom = runtime["atom"]
    state = runtime["state"]
    p2 = runtime["p2"]
    p3 = runtime["p3"]
    family = case["family"]

    if family == "exact_source":
        validation = atom.validate_memory_atom_shape(case["record"])
        matched = p3["filter_memories"]([case["record"]], query=case["query"])
        exact_present = bool(matched) and case["query"] in (
            str(matched[0].get("content") or "")
            + " "
            + str(matched[0].get("summary") or "")
        )
        passed = bool(validation.get("ok")) and exact_present
        return _case_result(
            case,
            "pass" if passed else "fail",
            {
                "existing_atom_validator_ok": bool(validation.get("ok")),
                "exact_token_present": exact_present,
                "matched_count": len(matched),
            },
            () if passed else ("source_backed_exact_retrieval_contract_not_met",),
        )

    if family == "current_state":
        snapshot = state.build_state_ledger_snapshot({"topic": case["query"], "records": case["records"]})
        latest = snapshot.get("latest_trusted_judgment") or {}
        observed_id = latest.get("record_id")
        passed = observed_id == case["expected"]["record_id"]
        reason = (
            ""
            if passed
            else "recorded_time_sort_does_not_implement_valid_time_current_semantics"
        )
        return _case_result(
            case,
            "pass" if passed else "fail",
            {
                "record_id": observed_id,
                "state_role": latest.get("status_category"),
                "subtype": case.get("subtype"),
                "old_states_remain_visible": bool(snapshot.get("temporal_index")),
            },
            (reason,) if reason else (),
        )

    if family == "historical_as_of":
        snapshot = state.build_state_ledger_snapshot({"topic": case["query"], "records": case["records"]})
        latest = snapshot.get("latest_trusted_judgment") or {}
        observed_id = latest.get("record_id")
        passed = observed_id == case["expected"]["record_id"]
        return _case_result(
            case,
            "pass" if passed else "fail",
            {
                "record_id": observed_id,
                "requested_time_view_honored": passed,
                "requested_time_view": case["as_of"],
            },
            () if passed else ("state_ledger_has_no_as_of_selection_semantics",),
        )

    if family == "conflict_unknown":
        snapshot = state.build_state_ledger_snapshot({"topic": case["query"], "records": case["records"]})
        latest = snapshot.get("latest_trusted_judgment") or {}
        conflict_visible = bool((snapshot.get("state_ledger") or {}).get("conflicting"))
        unknown_emitted = not bool(latest)
        passed = conflict_visible and unknown_emitted
        return _case_result(
            case,
            "pass" if passed else "fail",
            {
                "conflict_visible": conflict_visible,
                "record_id": latest.get("record_id"),
                "unknown_emitted": unknown_emitted,
            },
            () if passed else ("conflict_is_visible_but_current_projection_still_selects_a_record",),
        )

    if family == "long_range_multi_session":
        matched = p3["filter_memories"](case["records"], query=case["query"])
        matched_ids = [str(item.get("exp_id") or "") for item in matched]
        required = set(case["expected"]["required_exp_ids"])
        retrieval_complete = required.issubset(set(matched_ids))
        if case["expected"].get("answer_operator_required"):
            return _case_result(
                case,
                "not_measured",
                {
                    "required_records_retrieved": retrieval_complete,
                    "matched_record_count": len(matched_ids),
                    "answer_operator_observed": False,
                },
                ("current_retrieval_returns_records_but_no_measured_multi_session_aggregation_operator",),
            )
        return _case_result(
            case,
            "pass" if retrieval_complete else "fail",
            {
                "required_records_retrieved": retrieval_complete,
                "matched_record_count": len(matched_ids),
            },
            () if retrieval_complete else ("long_range_exact_record_not_retrieved",),
        )

    if family == "delivery_security" and case["layer"] == "delivery":
        observed = PLATFORM_DELIVERY_BASELINE.get(case["platform"], "not_measured")
        return _case_result(
            case,
            "not_measured",
            {
                "platform": case["platform"],
                "delivered_to_model": observed,
                "platform_delivery_proven": False,
                "used_state": "unknown",
            },
            ("latest_auditable_platform_matrix_is_0_of_7_model_delivery_proven",),
        )

    if family == "delivery_security" and case["layer"] == "security":
        write_blocked = bool(p2["is_noise"](case["attack"]))
        recall_blocked = bool(p3["_is_noise_memory"](case["memory"]))
        passed = write_blocked and recall_blocked
        reasons = []
        if not write_blocked:
            reasons.append("generic_instruction_like_memory_passes_current_p2_anti_noise_gate")
        if not recall_blocked:
            reasons.append("generic_instruction_like_memory_with_source_refs_passes_current_p3_noise_gate")
        return _case_result(
            case,
            "pass" if passed else "fail",
            {
                "write_blocked": write_blocked,
                "recall_blocked": recall_blocked,
                "relay_voiceprint_is_defense": False,
            },
            reasons,
        )

    raise ValueError("unsupported R0 case: %s" % case.get("case_id"))


def _count_statuses(results: Iterable[Dict[str, Any]]) -> Dict[str, int]:
    counts = Counter(item["status"] for item in results)
    return {
        "denominator": sum(counts.values()),
        "pass": counts.get("pass", 0),
        "fail": counts.get("fail", 0),
        "not_measured": counts.get("not_measured", 0),
    }


def _existing_chain_capabilities(snapshot: str, runtime: Dict[str, Any]) -> Dict[str, Any]:
    p3 = runtime["p3"]
    source = runtime["sources"]["p3"]
    state_source = runtime["sources"]["state"]
    granite_source = runtime["sources"]["granite"]

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz: Any = None) -> "FrozenDateTime":
            value = cls(2026, 7, 13, 0, 0, 0)
            return value.replace(tzinfo=tz) if tz else value

    overlay = {
        "superseded": {"conflict_decision": "superseded", "status": "superseded"},
        "historical": {
            "conflict_decision": "historical_only",
            "status": "historical",
            "effective_from": "2026-06-13 00:00:00",
        },
        "active": {
            "conflict_decision": "active",
            "status": "active",
            "effective_from": "2026-07-12 00:00:00",
        },
    }
    p3["datetime"] = FrozenDateTime
    p3["timezone"] = timezone
    p3["_get_lifecycle_overlay"] = lambda: overlay
    lifecycle = p3["_apply_lifecycle_overlay"](
        [
            {"exp_id": "superseded", "score": 0.7},
            {"exp_id": "historical", "score": 0.7},
            {"exp_id": "active", "score": 0.7},
        ]
    )
    lifecycle_by_id = {item["exp_id"]: item for item in lifecycle}
    superseded_filtered = "superseded" not in lifecycle_by_id
    historical_downweighted = lifecycle_by_id["historical"]["_adjusted_score"] < 0.7
    effective_from_applied = lifecycle_by_id["active"]["_lifecycle"]["freshness_score"] < 1.0

    bm25_exact = p3["_bm25_score_single"](
        {"summary": "needle", "detail": ""}, ["needle"], {"needle": 1.0}, 1.0
    )
    bm25_other = p3["_bm25_score_single"](
        {"summary": "other", "detail": ""}, ["needle"], {"needle": 1.0}, 1.0
    )
    rrf = p3["_rrf_fuse"](
        [
            [(1.0, {"exp_id": "a"}), (0.5, {"exp_id": "b"})],
            [(1.0, {"exp_id": "b"}), (0.5, {"exp_id": "c"})],
        ]
    )

    return {
        "p3_lifecycle_superseded_exclusion": {
            "status": "source_behavior_proven",
            "observed": superseded_filtered,
            "source_refs": [_line_anchor(snapshot, "src/p3_recall.py", source, 'conflict_decision == "superseded"')],
        },
        "p3_historical_downweight": {
            "status": "source_behavior_proven",
            "observed": historical_downweighted,
            "source_refs": [_line_anchor(snapshot, "src/p3_recall.py", source, 'conflict_decision == "historical_only"')],
        },
        "p3_effective_from_freshness": {
            "status": "source_behavior_proven",
            "observed": effective_from_applied,
            "source_refs": [_line_anchor(snapshot, "src/p3_recall.py", source, 'effective_from_str = lo.get("effective_from"')],
        },
        "p3_bm25": {
            "status": "source_behavior_proven",
            "observed": bm25_exact > bm25_other,
            "source_refs": [_line_anchor(snapshot, "src/p3_recall.py", source, "def _compute_bm25_scores")],
        },
        "p3_fts5": {
            "status": "source_integration_present",
            "observed": "_fts5_ordered_memories" in source and "sqlite_fts5_trigram_bm25" in source,
            "source_refs": [_line_anchor(snapshot, "src/p3_recall.py", source, "_fts5_ordered_memories")],
            "non_claims": ["static integration anchor is not a live freshness claim"],
        },
        "p3_rrf": {
            "status": "source_behavior_proven",
            "observed": bool(rrf) and rrf[0][1].get("exp_id") == "b",
            "source_refs": [_line_anchor(snapshot, "src/p3_recall.py", source, "def _rrf_fuse")],
        },
        "granite_vector_path": {
            "status": "source_integration_present",
            "observed": "granite-embedding-97m" in granite_source,
            "source_refs": [
                _line_anchor(snapshot, "src/granite_vector_assets.py", granite_source, "granite-embedding-97m")
            ],
            "non_claims": ["live model and table state are reported only by live mode"],
        },
        "state_ledger_conflict_display": {
            "status": "source_behavior_proven",
            "observed": "conflicting_records_visible_for_errata_review" in state_source,
            "source_refs": [
                _line_anchor(
                    snapshot,
                    "src/zhixing_state_ledger.py",
                    state_source,
                    "conflicting_records_visible_for_errata_review",
                )
            ],
            "boundary": "display_exists_but_conflict_does_not_force_unknown_projection",
        },
        "unified_bitemporal_current_as_of": {
            "status": "gap_confirmed",
            "observed": False,
            "source_refs": [
                _line_anchor(snapshot, "src/zhixing_state_ledger.py", state_source, "def build_state_ledger_snapshot")
            ],
            "boundary": "no_valid_time_current_or_as_of_selection_interface",
        },
    }


def build_deterministic_baseline(
    *,
    repo_root: Path = ROOT,
    snapshot: str = DEFAULT_SNAPSHOT,
    fixture_path: Path = DEFAULT_FIXTURE,
) -> Dict[str, Any]:
    repo_root = Path(repo_root)
    fixture_path = Path(fixture_path)
    resolved_snapshot = _git_commit(repo_root, snapshot)
    if resolved_snapshot != snapshot:
        snapshot = resolved_snapshot
    fixture_bytes = fixture_path.read_bytes()
    fixture = json.loads(fixture_bytes.decode("utf-8"))
    cases = fixture.get("cases") if isinstance(fixture, dict) else None
    if not isinstance(cases, list) or len(cases) != 120:
        raise ValueError("R0 fixture must contain exactly 120 cases")
    runtime = _build_snapshot_runtime(repo_root, snapshot)
    results = [_evaluate_case(case, runtime) for case in cases]
    layers = {
        layer: _count_statuses(item for item in results if item["layer"] == layer)
        for layer in LAYERS
    }
    buckets = {
        bucket: _count_statuses(item for item in results if item["failure_bucket"] == bucket)
        for bucket in FAILURE_BUCKETS
    }
    payload: Dict[str, Any] = {
        "ok": True,
        "contract": CONTRACT,
        "snapshot": snapshot,
        "snapshot_verified": True,
        "fixture_sha256": _sha256_bytes(fixture_bytes),
        "fixture_case_count": len(cases),
        "synthetic_and_public_safe": bool(fixture.get("synthetic_and_public_safe")),
        "deterministic": True,
        "read_only": True,
        "write_performed": False,
        "raw_write_performed": False,
        "memory_write_performed": False,
        "platform_write_performed": False,
        "model_call_performed": False,
        "proof_layer": "released_snapshot_source_behavior_plus_synthetic_fixture",
        "no_overall_score": True,
        "layers": layers,
        "failure_buckets": buckets,
        "existing_chain_capabilities": _existing_chain_capabilities(snapshot, runtime),
        "platform_delivery_baseline": {
            "audit_state": "latest_auditable_snapshot",
            "proven": 0,
            "denominator": 7,
            "platforms": PLATFORM_DELIVERY_BASELINE,
            "source_refs": [
                {
                    "source_system": "release_feature_audit",
                    "evidence_ref": "output/release_feature_audit_20260711/platform-delivery-matrix.json",
                }
            ],
        },
        "relay_voiceprint_boundary": {
            "status": "attribution_material_only",
            "poisoning_defense_proven": False,
        },
        "cases": results,
        "non_claims": [
            "synthetic baseline does not prove connected or installed runtime behavior",
            "delivery remains not_measured without platform model-request evidence",
            "no as-of product entry or production bitemporal state path is claimed",
            "no poisoning defense is claimed from relay attribution material",
            "no single aggregate score represents the system",
        ],
    }
    payload["deterministic_digest_sha256"] = _payload_digest(payload)
    return payload


def _source_refs_present(value: Any) -> bool:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except Exception:
            return False
    refs = value if isinstance(value, list) else [value]
    for ref in refs:
        if not isinstance(ref, dict) or not ref.get("source_system"):
            continue
        if any(ref.get(key) for key in ("source_path", "artifact_id", "library_id", "evidence_ref")):
            return True
    return False


def inventory_runtime_objects(runtime_root: Path) -> Dict[str, Any]:
    runtime_root = Path(runtime_root)
    zhiyi_root = runtime_root / "zhiyi"
    by_kind: Dict[str, int] = {}
    object_count = 0
    source_refs_count = 0
    aggregate_text_chars = 0
    content_hashes = set()
    deterministic_rule_resolved = 0
    ambiguous_text_chars = 0
    for kind in ("preference_memory", "case_memory", "error_memory"):
        path = zhiyi_root / kind / (kind + ".jsonl")
        count = 0
        if path.is_file():
            with path.open(encoding="utf-8") as handle:
                for line in handle:
                    try:
                        record = json.loads(line)
                    except Exception:
                        continue
                    if not isinstance(record, dict):
                        continue
                    count += 1
                    object_count += 1
                    if _source_refs_present(record.get("source_refs")):
                        source_refs_count += 1
                    text = "\n".join(
                        str(record.get(field) or "").strip()
                        for field in ("summary", "detail")
                        if str(record.get(field) or "").strip()
                    )
                    aggregate_text_chars += len(text)
                    content_hashes.add(_sha256_bytes(text.encode("utf-8")))
                    explicit_state = str(record.get("status") or "").lower() in {
                        "active",
                        "current",
                        "adopted",
                    }
                    has_conflict = any(
                        record.get(field) not in (None, "", [])
                        for field in ("conflicts_with", "supersedes", "superseded_by")
                    )
                    if explicit_state and not has_conflict and _source_refs_present(record.get("source_refs")):
                        deterministic_rule_resolved += 1
                    else:
                        ambiguous_text_chars += len(text)
        by_kind[kind.replace("_memory", "")] = count
    return {
        "object_count": object_count,
        "by_kind": by_kind,
        "source_refs_present_count": source_refs_count,
        "source_refs_coverage": round(source_refs_count / object_count, 6) if object_count else None,
        "aggregate_text_chars": aggregate_text_chars,
        "token_estimate": int(math.ceil(aggregate_text_chars / 3.0)),
        "token_estimator": "ceil(summary_plus_detail_characters_divided_by_3)",
        "token_estimator_quality": "planning_estimate_not_model_tokenizer",
        "unique_content_sha256_count": len(content_hashes),
        "sha_duplicate_count": max(0, object_count - len(content_hashes)),
        "deterministic_prescreen_resolved_count": deterministic_rule_resolved,
        "ambiguous_model_upper_bound_count": max(0, object_count - deterministic_rule_resolved),
        "ambiguous_text_chars": ambiguous_text_chars,
        "read_only": True,
    }


FetchResult = Tuple[Optional[int], Optional[Dict[str, Any]], str]


def _fetch_json(url: str, timeout: float = 5.0) -> FetchResult:
    try:
        request = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
            return int(response.status), body if isinstance(body, dict) else {}, ""
    except urllib.error.HTTPError as exc:
        return int(exc.code), None, "http_error"
    except Exception as exc:
        return None, None, type(exc).__name__


def _normalize_fetch(value: Any) -> FetchResult:
    if isinstance(value, tuple) and len(value) == 3:
        return value
    if isinstance(value, dict):
        return 200, value, ""
    return None, None, "invalid_fetch_result"


def _cost(input_tokens: int, output_tokens: int, profile: Dict[str, float]) -> float:
    value = (
        input_tokens * profile["input_usd_per_million"]
        + output_tokens * profile["output_usd_per_million"]
    ) / 1_000_000.0
    return round(value, 4)


def _costed_scenario(
    *,
    name: str,
    model_objects: int,
    input_tokens: int,
    output_tokens_per_object: int,
    status: str = "estimated",
    assumptions: Iterable[str] = (),
) -> Dict[str, Any]:
    output_tokens = model_objects * output_tokens_per_object
    return {
        "scenario": name,
        "status": status,
        "model_object_count": model_objects,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": {
            key: _cost(input_tokens, output_tokens, value)
            for key, value in PRICE_PROFILES.items()
        },
        "assumptions": list(assumptions),
    }


def build_spend_scenarios(inventory: Dict[str, Any]) -> Dict[str, Any]:
    objects = int(inventory.get("object_count") or 0)
    unique = int(inventory.get("unique_content_sha256_count") or 0)
    input_tokens = int(inventory.get("token_estimate") or 0)
    ambiguous = int(inventory.get("ambiguous_model_upper_bound_count") or objects)
    ambiguous_tokens = int(math.ceil(int(inventory.get("ambiguous_text_chars") or 0) / 3.0))
    output_per_object = 160
    scenarios: List[Dict[str, Any]] = [
        _costed_scenario(
            name="naive_full",
            model_objects=objects,
            input_tokens=input_tokens,
            output_tokens_per_object=output_per_object,
            assumptions=("one extraction request per current object", "no cache or deterministic prescreen"),
        ),
        _costed_scenario(
            name="sha_cache_initial",
            model_objects=unique,
            input_tokens=input_tokens if unique == objects else input_tokens,
            output_tokens_per_object=output_per_object,
            assumptions=("identical summary+detail SHA is evaluated once",),
        ),
        _costed_scenario(
            name="sha_cache_unchanged_rerun",
            model_objects=0,
            input_tokens=0,
            output_tokens_per_object=output_per_object,
            assumptions=("the first-run SHA cache persists and the corpus is byte-identical",),
        ),
        _costed_scenario(
            name="deterministic_prescreen_then_ambiguous_only",
            model_objects=ambiguous,
            input_tokens=ambiguous_tokens,
            output_tokens_per_object=output_per_object,
            assumptions=(
                "only explicit active/current/adopted state with source refs and no conflict relation is resolved without a model",
                "all remaining objects are treated as ambiguous upper bound",
            ),
        ),
    ]
    scenarios.append(
        {
            "scenario": "incremental_after_first_snapshot",
            "status": "not_measured",
            "model_object_count": None,
            "input_tokens": None,
            "output_tokens": None,
            "cost_usd": {key: None for key in PRICE_PROFILES},
            "formula": "new_or_changed_unique_sha_only",
            "reason": "a second corpus snapshot is required to measure the real delta",
        }
    )
    reference_cost = scenarios[0]["cost_usd"]["reference_planning"] if scenarios else 0.0
    proposed_cap = max(5.0, math.ceil((reference_cost * 1.25) / 5.0) * 5.0)
    return {
        "status": "planning_estimate_not_authorized_budget",
        "input_measurement": {
            "object_count": objects,
            "aggregate_text_chars": int(inventory.get("aggregate_text_chars") or 0),
            "input_token_estimate": input_tokens,
            "input_token_estimator": inventory.get("token_estimator"),
            "output_tokens_per_model_object": output_per_object,
            "output_token_assumption": "planning assumption not measured model output",
        },
        "price_profiles": {
            key: dict(value, provenance="sensitivity_assumption_not_provider_quote")
            for key, value in PRICE_PROFILES.items()
        },
        "scenarios": scenarios,
        "proposed_budget_guard": {
            "status": "proposal_requires_owner_approval",
            "proposed_cap_usd": proposed_cap,
            "derivation": "ceil_to_5_usd_of_125_percent_reference_naive_full_with_5_usd_floor",
            "stop_conditions": [
                "actual_spend_reaches_owner_approved_cap",
                "any_raw_mutation_or_source_ref_loss",
                "any_production_experience_activation",
                "verifier_failure_rate_exceeds_5_percent_after_first_100_candidates",
                "local_or_cloud_comparison_fails_the_owner_approved_quality_gate",
            ],
            "not_policy_until_owner_approved": True,
        },
    }


def collect_live_observation(
    *,
    runtime_root: Path,
    repo_root: Path = ROOT,
    fetch_json: Callable[[str], Any] = _fetch_json,
) -> Dict[str, Any]:
    inventory = inventory_runtime_objects(runtime_root)
    try:
        service_config = json.loads((runtime_root / "config" / "memcore.json").read_text(encoding="utf-8-sig"))
    except Exception:
        service_config = {}
    services = service_config.get("services") if isinstance(service_config, dict) else {}
    p3_port = int((services or {}).get("internal_p3_port") or (services or {}).get("p3_recall_port") or 19300)
    p3_status, p3, p3_error = _normalize_fetch(fetch_json(f"http://127.0.0.1:{p3_port}/health"))
    guardian_status, guardian, guardian_error = _normalize_fetch(
        fetch_json(front_door_url("/api/v1/records/guardian/status?limit=120&mode=fast&compact=1", runtime_root, fallback=9850))
    )
    p3 = p3 or {}
    vector = p3.get("vector_recall") if isinstance(p3.get("vector_recall"), dict) else {}
    guardian = guardian or {}
    guardian_summary = guardian.get("summary") if isinstance(guardian.get("summary"), dict) else {}

    endpoint_survey = {}
    for label, url in (
        ("ollama_11434", "http://127.0.0.1:11434/api/tags"),
        ("openai_local_1234", "http://127.0.0.1:1234/v1/models"),
        ("unknown_8080", "http://127.0.0.1:8080/v1/models"),
    ):
        status, body, error = _normalize_fetch(fetch_json(url))
        models = []
        if isinstance(body, dict):
            candidate = body.get("models") or body.get("data") or []
            models = candidate if isinstance(candidate, list) else []
        endpoint_survey[label] = {
            "http_status": status,
            "metadata_reachable": status == 200,
            "model_count": len(models),
            "error_class": error,
            "generation_call_performed": False,
        }

    delivery_path = Path(repo_root) / "output" / "release_feature_audit_20260711" / "platform-delivery-matrix.json"
    delivery_counts: Dict[str, Any] = {"platforms_total": 7, "platform_delivery_proven": 0}
    if delivery_path.is_file():
        try:
            delivery = json.loads(delivery_path.read_text(encoding="utf-8"))
            if isinstance(delivery.get("counts"), dict):
                delivery_counts = {
                    "platforms_total": int(delivery["counts"].get("platforms_total") or 0),
                    "model_delivery_observed": int(delivery["counts"].get("model_delivery_observed") or 0),
                    "platform_delivery_proven": int(delivery["counts"].get("platform_delivery_proven") or 0),
                }
        except Exception:
            pass

    spend = build_spend_scenarios(inventory)
    payload = {
        "ok": True,
        "contract": LIVE_CONTRACT,
        "observed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "volatile_observation": True,
        "read_only": True,
        "write_performed": False,
        "raw_write_performed": False,
        "memory_write_performed": False,
        "platform_write_performed": False,
        "model_call_performed": False,
        "private_paths_emitted": False,
        "runtime_objects": inventory,
        "p3_health": {
            "http_status": p3_status,
            "error_class": p3_error,
            "status": p3.get("status"),
            "memory_count": p3.get("memory_count"),
            "vector": {
                "ok": vector.get("ok"),
                "model_id": vector.get("model_id"),
                "embedding_dim": vector.get("embedding_dim"),
                "storage": (vector.get("table_identity") or {}).get("storage")
                if isinstance(vector.get("table_identity"), dict)
                else None,
                "row_count": vector.get("row_count"),
                "model_loaded": vector.get("model_loaded"),
                "table_loaded": vector.get("table_loaded"),
            },
        },
        "guardian": {
            "http_status": guardian_status,
            "error_class": guardian_error,
            "ok": guardian.get("ok"),
            "read_only": guardian.get("read_only"),
            "write_performed": guardian.get("write_performed"),
            "summary": {
                key: guardian_summary.get(key)
                for key in (
                    "record_count",
                    "record_guarded_count",
                    "raw_not_current_count",
                    "raw_catching_up_count",
                    "lost_source_count",
                    "lost_raw_count",
                    "corrupt_record_count",
                )
            },
        },
        "platform_delivery": delivery_counts,
        "local_generative_endpoint_survey": endpoint_survey,
        "local_vs_cloud_extraction": {
            "status": "not_measured",
            "reason": "no authorized local/cloud state-extraction comparison was run",
            "granite_is_embedding_not_state_extraction_generator": True,
        },
        "r2_spend_gate": spend,
        "r2_decision": {
            "decision": "NO_GO",
            "reasons": [
                "local_vs_cloud_accuracy_and_latency_not_measured",
                "budget_cap_not_owner_approved",
            ],
        },
        "scope_notes": [
            "runtime object count, P3 memory count, and vector row count have different scopes",
            "live counters may change while background capture continues",
            "endpoint survey performs metadata GET only and no generation request",
        ],
    }
    return payload


def _tree_entries(base: Path, *, hash_content: bool) -> List[Dict[str, Any]]:
    if not base.exists():
        return []
    entries = []
    for path in sorted(item for item in base.rglob("*") if item.is_file() and not item.is_symlink()):
        relative = path.relative_to(base).as_posix()
        stat = path.stat()
        item: Dict[str, Any] = {
            "path_id": _sha256_bytes(relative.encode("utf-8")),
            "size": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
        }
        if hash_content:
            item["sha256"] = _sha256_file(path)
        entries.append(item)
    return entries


def build_zero_write_manifest(*, repo_root: Path, runtime_root: Path) -> Dict[str, Any]:
    repo_root = Path(repo_root)
    runtime_root = Path(runtime_root)
    readmes = []
    for relative in ("README.md", "README.zh-CN.md"):
        path = repo_root / relative
        if path.is_file():
            stat = path.stat()
            readmes.append(
                {
                    "path_id": relative,
                    "size": stat.st_size,
                    "mtime_ns": stat.st_mtime_ns,
                    "sha256": _sha256_file(path),
                }
            )
    payload: Dict[str, Any] = {
        "contract": MANIFEST_CONTRACT,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "paths_sanitized": True,
        "read_only_scan": True,
        "write_performed": False,
        "sections": {
            "repo_readmes": readmes,
            "repo_config": _tree_entries(repo_root / "config", hash_content=True),
            "installed_config": _tree_entries(runtime_root / "config", hash_content=True),
            "installed_zhiyi": _tree_entries(runtime_root / "zhiyi", hash_content=True),
            "installed_xingce": _tree_entries(
                runtime_root / "output" / "xingce_work_experience", hash_content=True
            ),
            "installed_raw_stats": _tree_entries(runtime_root / "memory", hash_content=False),
        },
    }
    payload["manifest_digest_sha256"] = _payload_digest(payload)
    return payload


def compare_zero_write_manifests(before: Dict[str, Any], after: Dict[str, Any]) -> Dict[str, Any]:
    protected_sections = ("repo_readmes", "repo_config", "installed_config", "installed_zhiyi", "installed_xingce")
    before_sections = before.get("sections") if isinstance(before.get("sections"), dict) else {}
    after_sections = after.get("sections") if isinstance(after.get("sections"), dict) else {}
    protected_changes = {}
    for section in protected_sections:
        old = {item["path_id"]: item for item in before_sections.get(section, [])}
        new = {item["path_id"]: item for item in after_sections.get(section, [])}
        changed = sorted(
            path_id
            for path_id in set(old) | set(new)
            if old.get(path_id) != new.get(path_id)
        )
        protected_changes[section] = {
            "changed_count": len(changed),
            "changed_path_ids": changed,
        }

    old_raw = {item["path_id"]: item for item in before_sections.get("installed_raw_stats", [])}
    new_raw = {item["path_id"]: item for item in after_sections.get("installed_raw_stats", [])}
    removed = sorted(set(old_raw) - set(new_raw))
    added = sorted(set(new_raw) - set(old_raw))
    shrunk = sorted(
        path_id
        for path_id in set(old_raw) & set(new_raw)
        if int(new_raw[path_id].get("size") or 0) < int(old_raw[path_id].get("size") or 0)
    )
    grown = sorted(
        path_id
        for path_id in set(old_raw) & set(new_raw)
        if int(new_raw[path_id].get("size") or 0) > int(old_raw[path_id].get("size") or 0)
    )
    protected_unchanged = all(not value["changed_count"] for value in protected_changes.values())
    raw_monotonic = not removed and not shrunk
    return {
        "ok": protected_unchanged and raw_monotonic,
        "contract": MANIFEST_COMPARISON_CONTRACT,
        "protected_unchanged": protected_unchanged,
        "protected_sections": protected_changes,
        "raw_observation": {
            "monotonic_by_size": raw_monotonic,
            "added_count": len(added),
            "grown_count": len(grown),
            "removed_count": len(removed),
            "shrunk_count": len(shrunk),
            "added_path_ids": added,
            "grown_path_ids": grown,
            "removed_path_ids": removed,
            "shrunk_path_ids": shrunk,
            "boundary": "background_capture_may_independently_append_raw_during_r0",
        },
        "non_claims": [
            "size monotonicity does not attribute raw appends to a specific process",
            "manifest comparison does not prove runtime behavior",
        ],
    }


def _default_runtime_root() -> Path:
    explicit = os.environ.get("MEMCORE_ROOT")
    if explicit:
        return Path(explicit).expanduser()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "time-library"
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "time-library"
    return Path.home() / ".local" / "share" / "time-library"


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Time Library R0 read-only contract baseline")
    parser.add_argument(
        "--mode",
        choices=("deterministic", "live", "manifest", "compare-manifests"),
        default="deterministic",
    )
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--runtime-root", type=Path, default=_default_runtime_root())
    parser.add_argument("--snapshot", default=DEFAULT_SNAPSHOT)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--before", type=Path)
    parser.add_argument("--after", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    if args.mode == "deterministic":
        payload = build_deterministic_baseline(
            repo_root=args.repo_root,
            snapshot=args.snapshot,
            fixture_path=args.fixture,
        )
    elif args.mode == "live":
        payload = collect_live_observation(runtime_root=args.runtime_root, repo_root=args.repo_root)
    elif args.mode == "manifest":
        payload = build_zero_write_manifest(repo_root=args.repo_root, runtime_root=args.runtime_root)
    else:
        if not args.before or not args.after:
            parser.error("--before and --after are required for compare-manifests")
        payload = compare_zero_write_manifests(
            json.loads(args.before.read_text(encoding="utf-8")),
            json.loads(args.after.read_text(encoding="utf-8")),
        )

    if args.output:
        _write_json(args.output, payload)
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
