#!/usr/bin/env python3
"""Run trusted-memory trust metrics from repeatable probes."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from src.trusted_memory_trust_metrics import (
    CASE_EXPECTED_METRIC_FIELDS,
    build_case_expected_metrics_observation,
    build_trusted_memory_trust_metrics,
)
from tools import (
    trusted_memory_live_trace_probe,
    trusted_memory_real_memory_trace_probe,
    trusted_memory_user_work_trace_probe,
)


def _deterministic_probe(contract: str, *, controlled: bool = False) -> dict:
    prefix = "real" if controlled else "live"
    return {
        "ok": True,
        "contract": contract,
        "fixture_backed": not controlled,
        "controlled_temp_memory": controlled,
        "deterministic_contract_fixture": True,
        "user_work_records_read": False,
        "platform_action_performed": False,
        "cases": [
            {
                "case": "source_backed",
                "ordinary_handled": False,
                "explicit_handled": True,
                "answer": "先核对 NAS，再实施下一刀。",
                "answer_source": "evidence_bound_model_call",
                "model_called": True,
                "request_sent": True,
                "evidence_packet_refs": [f"exp-{prefix}-trace-next"],
                "used_source_refs": [f"exp-{prefix}-trace-next"],
                "source_refs": [{"library_id": f"exp-{prefix}-trace-next", "source_path": "/tmp/source.jsonl"}],
                "receipt_status": "source_backed",
                "unknown_boundary": False,
                "trace_status": "proven",
                "model_delivery_state": "observed",
            },
            {
                "case": "unknown",
                "ordinary_handled": False,
                "explicit_handled": True,
                "answer": "UNKNOWN",
                "answer_source": "evidence_bound_model_call",
                "model_called": True,
                "request_sent": True,
                "evidence_packet_refs": [f"exp-{prefix}-trace-gap"],
                "used_source_refs": [],
                "source_refs": [{"library_id": f"exp-{prefix}-trace-gap", "source_path": "/tmp/gap.jsonl"}],
                "receipt_status": "unknown",
                "unknown_boundary": True,
                "trace_status": "proven",
                "model_delivery_state": "observed",
            },
        ],
    }


def _user_work_missing(scope_filter: str, source_query: str, unknown_query: str) -> list[str]:
    missing: list[str] = []
    if not str(scope_filter or "").strip():
        missing.append("--scope-filter")
    if not str(source_query or "").strip():
        missing.append("--source-query")
    if not str(unknown_query or "").strip():
        missing.append("--unknown-query")
    return missing


def _missing_user_work_probe_result(missing: list[str]) -> dict:
    return {
        "ok": False,
        "contract": "trusted_memory_user_work_trace_probe.v2026.6.21",
        "status": "scope_and_queries_required",
        "read_only": True,
        "write_performed": False,
        "raw_write_performed": False,
        "memory_write_performed": False,
        "platform_write_performed": False,
        "model_call_performed": False,
        "user_work_records_read": False,
        "platform_action_performed": False,
        "install_authorization_model": "installed_connection_is_authorization",
        "missing": missing,
        "cases": [],
    }


def _case_evidence_from_user_probe(user_probe: dict) -> list[dict[str, object]]:
    """Return one audit-trail row per casefile case in a user/work probe."""

    evidence: list[dict[str, object]] = []
    seen: set[str] = set()
    for case in user_probe.get("cases") or []:
        if not isinstance(case, dict):
            continue
        casefile_case = str(case.get("casefile_case") or "").strip()
        if not casefile_case or casefile_case in seen:
            continue
        seen.add(casefile_case)
        evidence.append(
            {
                "casefile_case": casefile_case,
                "casefile_record_kind": str(case.get("casefile_record_kind") or "").strip(),
                "casefile_observed_at": str(case.get("casefile_observed_at") or "").strip(),
                "casefile_evidence_command": str(case.get("casefile_evidence_command") or "").strip(),
                "casefile_expected_metrics": case.get("casefile_expected_metrics") if isinstance(case.get("casefile_expected_metrics"), dict) else {},
                "authorized_scope_filter": str(case.get("authorized_scope_filter") or case.get("scope_filter") or "").strip(),
            }
        )
    return evidence


def _case_metric_evidence_from_user_probe(user_probe: dict) -> tuple[list[dict[str, object]], list[str]]:
    """Compare each casefile case's expected metrics to observed trace metrics."""

    grouped: dict[str, list[dict[str, object]]] = {}
    expected_by_case: dict[str, dict[str, object]] = {}
    meta_by_case: dict[str, dict[str, str]] = {}
    for case in user_probe.get("cases") or []:
        if not isinstance(case, dict):
            continue
        casefile_case = str(case.get("casefile_case") or "").strip()
        if not casefile_case:
            continue
        grouped.setdefault(casefile_case, []).append(case)
        expected = case.get("casefile_expected_metrics")
        if isinstance(expected, dict) and casefile_case not in expected_by_case:
            expected_by_case[casefile_case] = {
                field: expected.get(field)
                for field in CASE_EXPECTED_METRIC_FIELDS
                if field in expected
            }
        meta_by_case.setdefault(
            casefile_case,
            {
                "casefile_record_kind": str(case.get("casefile_record_kind") or "").strip(),
                "casefile_observed_at": str(case.get("casefile_observed_at") or "").strip(),
                "casefile_evidence_command": str(case.get("casefile_evidence_command") or "").strip(),
                "authorized_scope_filter": str(case.get("authorized_scope_filter") or case.get("scope_filter") or "").strip(),
            },
        )

    evidence: list[dict[str, object]] = []
    errors: list[str] = []
    for casefile_case, cases in grouped.items():
        expected = expected_by_case.get(casefile_case, {})
        observed = build_case_expected_metrics_observation(cases)
        mismatches = [
            field
            for field in CASE_EXPECTED_METRIC_FIELDS
            if field in expected and expected.get(field) != observed.get(field)
        ]
        if not expected:
            errors.append(f"user_work_case_expected_metrics_missing:{casefile_case}")
        for field in mismatches:
            errors.append(f"user_work_case_expected_metric_mismatch:{casefile_case}:{field}")
        evidence.append(
            {
                "casefile_case": casefile_case,
                **meta_by_case.get(casefile_case, {}),
                "casefile_expected_metrics": expected,
                "observed_metrics": observed,
                "expected_metrics_match": bool(expected) and not mismatches,
                "metric_mismatches": mismatches,
            }
        )
    return evidence, errors


def run_metrics(
    *,
    live_probes: bool = False,
    user_work_probe: bool = False,
    user_work_casefile: str = "",
    user_work_casefile_repeat: int = 1,
    scope_filter: str = "",
    source_query: str = "",
    unknown_query: str = "",
    gateway_url: str = "",
    provider: str = "minimax",
    model: str = "",
    timeout_seconds: int = 90,
) -> dict:
    if user_work_probe:
        missing = [] if user_work_casefile else _user_work_missing(scope_filter, source_query, unknown_query)
        repeat_count = max(1, int(user_work_casefile_repeat or 1))
        if user_work_casefile:
            user_probes = []
            for repeat_index in range(1, repeat_count + 1):
                user_probe = trusted_memory_user_work_trace_probe.run_casefile(
                    casefile=user_work_casefile,
                    gateway_url=gateway_url,
                    provider=provider,
                    model=model,
                    timeout_seconds=timeout_seconds,
                )
                user_probe["casefile_repeat_index"] = repeat_index
                user_probes.append(user_probe)
            user_probe = user_probes[-1]
        elif missing:
            user_probe = _missing_user_work_probe_result(missing)
            user_probes = [user_probe]
        else:
            user_probe = trusted_memory_user_work_trace_probe.run_probe(
                scope_filter=scope_filter,
                source_query=source_query,
                unknown_query=unknown_query,
                gateway_url=gateway_url,
                provider=provider,
                model=model,
                timeout_seconds=timeout_seconds,
            )
            user_probes = [user_probe]
        generated_by = "tools/trusted_memory_trust_metrics.py --user-work-probe"
        if user_work_casefile and repeat_count > 1:
            generated_by = f"{generated_by} --user-work-casefile-repeat {repeat_count}"
        result = build_trusted_memory_trust_metrics(
            user_probes,
            generated_by=generated_by,
        )
        result["live_model_probe_performed"] = any(bool(probe.get("model_call_performed")) for probe in user_probes)
        result["deterministic_contract_fixture"] = False
        result["installed_user_work_probe_performed"] = any(bool(probe.get("user_work_records_read")) for probe in user_probes)
        result["evaluation_scope"] = "scoped_installed_zhiyi_xingce_user_work_record_probe"
        result["user_work_scope_filter"] = scope_filter
        if user_work_casefile:
            result["user_work_casefile"] = user_work_casefile
            result["user_work_case_count"] = int(user_probe.get("case_count") or 0)
            result["user_work_scope_count"] = int(user_probe.get("scope_count") or 0)
            result["user_work_scope_filters"] = [
                str(item)
                for item in (user_probe.get("scope_filters") or [])
                if str(item)
            ]
            result["user_work_record_kinds"] = [
                str(item)
                for item in (user_probe.get("record_kinds") or [])
                if str(item)
            ]
            result["user_work_case_evidence"] = _case_evidence_from_user_probe(user_probe)
            metric_runs: list[dict[str, object]] = []
            all_metric_errors: list[str] = []
            for repeat_index, repeated_probe in enumerate(user_probes, start=1):
                run_metric_evidence, run_metric_errors = _case_metric_evidence_from_user_probe(repeated_probe)
                metric_runs.append(
                    {
                        "repeat_index": repeat_index,
                        "probe_ok": bool(repeated_probe.get("ok")),
                        "expected_metrics_checked": bool(run_metric_evidence),
                        "expected_metrics_match": bool(run_metric_evidence) and not run_metric_errors,
                        "case_metric_evidence": run_metric_evidence,
                        "metric_errors": run_metric_errors,
                    }
                )
                if repeat_count == 1:
                    all_metric_errors.extend(run_metric_errors)
                else:
                    all_metric_errors.extend(
                        f"user_work_casefile_repeat_{repeat_index}:{error}"
                        for error in run_metric_errors
                    )
            metric_evidence = metric_runs[-1]["case_metric_evidence"] if metric_runs else []
            result["user_work_case_metric_evidence"] = metric_evidence
            result["user_work_case_expected_metrics_checked"] = bool(metric_runs) and all(
                bool(run.get("expected_metrics_checked")) for run in metric_runs
            )
            result["user_work_case_expected_metrics_match"] = bool(metric_runs) and all(
                bool(run.get("expected_metrics_match")) for run in metric_runs
            )
            result["user_work_casefile_repeat_requested"] = repeat_count
            result["user_work_casefile_repeat_completed"] = len(user_probes)
            result["user_work_casefile_stable"] = (
                len(user_probes) == repeat_count
                and all(bool(probe.get("ok")) for probe in user_probes)
                and result["user_work_case_expected_metrics_match"] is True
            )
            if repeat_count > 1:
                result["user_work_case_metric_evidence_runs"] = metric_runs
                result.setdefault("limitations", []).append(
                    "user_work_casefile_repeat_is_live_stability_diagnostic_not_broad_proof"
                )
            if all_metric_errors:
                result.setdefault("errors", []).extend(all_metric_errors)
                result["ok"] = False
            if repeat_count > 1 and not result["user_work_casefile_stable"]:
                result.setdefault("errors", []).append("user_work_casefile_repeat_not_stable")
                result["ok"] = False
        if isinstance(user_probe.get("authorized_caller_scope"), dict):
            result["user_work_caller_scope"] = user_probe["authorized_caller_scope"]
        if missing:
            result.setdefault("limitations", []).append("user_work_probe_requires_scope_filter_and_two_queries")
            result["public_claim_boundary"] = (
                "User/work trust metrics were requested but no installed records were read because scoped "
                "filter and source/UNKNOWN queries were missing."
            )
        elif user_work_casefile:
            result.setdefault("limitations", []).append("installed_user_work_casefile_is_scope_limited_not_platform_wide")
            result["public_claim_boundary"] = (
                "Can cite this only as scoped installed Zhiyi/Xingce user/work-record trust traces for the supplied "
                "casefile, not as all-record or platform-wide proof."
            )
        else:
            result.setdefault("limitations", []).append("installed_user_work_probe_is_scope_limited_not_platform_wide")
            result["public_claim_boundary"] = (
                "Can cite this only as a scoped installed Zhiyi/Xingce user/work-record trust trace for the supplied "
                "scope and queries, not as platform-wide proof."
            )
        return result

    if live_probes:
        fixture_probe = trusted_memory_live_trace_probe.run_probe()
        controlled_probe = trusted_memory_real_memory_trace_probe.run_probe()
        generated_by = "tools/trusted_memory_trust_metrics.py --live-probes"
    else:
        fixture_probe = _deterministic_probe("trusted_memory_live_trace_probe.v2026.6.21")
        controlled_probe = _deterministic_probe("trusted_memory_real_memory_trace_probe.v2026.6.21", controlled=True)
        generated_by = "tools/trusted_memory_trust_metrics.py"
    result = build_trusted_memory_trust_metrics(
        [fixture_probe, controlled_probe],
        generated_by=generated_by,
    )
    result["live_model_probe_performed"] = bool(live_probes)
    result["deterministic_contract_fixture"] = not bool(live_probes)
    if not live_probes:
        limitations = result.setdefault("limitations", [])
        limitations.append("deterministic_contract_fixture_is_not_a_live_model_probe")
        result["public_claim_boundary"] = (
            "Can cite these deterministic trust metrics as a contract fixture for the trust axis. "
            "Run --live-probes for live-model diagnostics; do not present deterministic fixtures as broad installed "
            "Zhiyi/Xingce user/work-record or platform-wide proof."
        )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Run trusted-memory trust metrics.")
    parser.add_argument("--json", action="store_true", help="print JSON")
    parser.add_argument("--live-probes", action="store_true", help="run live model probes instead of deterministic contract fixtures")
    parser.add_argument("--user-work-probe", action="store_true", help="run scoped installed Zhiyi/Xingce user/work-record probe")
    parser.add_argument("--user-work-casefile", default="", help="JSON casefile for multiple scoped installed user/work probes")
    parser.add_argument("--user-work-casefile-repeat", type=int, default=1, help="repeat a scoped user/work casefile to expose live-model variance")
    parser.add_argument("--scope-filter", default="", help="required with --user-work-probe")
    parser.add_argument("--source-query", default="", help="required with --user-work-probe")
    parser.add_argument("--unknown-query", default="", help="required with --user-work-probe")
    parser.add_argument("--gateway-url", default="", help="optional existing /inject gateway URL for --user-work-probe")
    parser.add_argument("--provider", default="minimax", help="evidence-bound model provider for --user-work-probe")
    parser.add_argument("--model", default="", help="model name override for --user-work-probe")
    parser.add_argument("--timeout-seconds", type=int, default=90)
    args = parser.parse_args()
    if args.live_probes and args.user_work_probe:
        raise SystemExit("--live-probes and --user-work-probe are separate modes")
    if args.live_probes and args.user_work_casefile:
        raise SystemExit("--live-probes and --user-work-casefile are separate modes")
    result = run_metrics(
        live_probes=args.live_probes,
        user_work_probe=args.user_work_probe or bool(args.user_work_casefile),
        user_work_casefile=args.user_work_casefile,
        user_work_casefile_repeat=args.user_work_casefile_repeat,
        scope_filter=args.scope_filter,
        source_query=args.source_query,
        unknown_query=args.unknown_query,
        gateway_url=args.gateway_url,
        provider=args.provider,
        model=args.model,
        timeout_seconds=args.timeout_seconds,
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("PASS" if result.get("ok") else "FAIL")
        for name, metric in result.get("metrics", {}).items():
            print(f"{name}: {metric.get('numerator')}/{metric.get('denominator')} ({metric.get('percent')}%)")
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
