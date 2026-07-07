#!/usr/bin/env python3
"""Run the scored Memcore preflight doctor in one read-only command."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from runtime_bootstrap import ensure_repo_import_paths, memcore_root  # noqa: E402

ROOT = ensure_repo_import_paths(__file__)

from preflight_doctor import build_preflight_doctor  # noqa: E402


def _print_text(payload: dict) -> None:
    print("# Time Library Preflight Doctor")
    print()
    print(f"status: {'ok' if payload.get('ok') else 'attention'}")
    print(f"contract: {payload.get('contract', '')}")
    if payload.get("diagnostic_profile"):
        print(f"profile: {payload.get('diagnostic_profile')}")
    print(f"overall: {payload.get('overall_score', 0)}/100")
    print()
    print("## Scores")
    print(f"- connection: {payload.get('connection_health_score', 0)}/100")
    print(f"- binding: {payload.get('binding_health_score', 0)}/100")
    print(f"- fast path: {payload.get('fast_path_health_score', 0)}/100")
    print(f"- latency: {payload.get('latency_score', 0)}/100")
    print(f"- recall: {payload.get('recall_score', 0)}/100")
    print(f"- source-backed: {payload.get('source_backed_score', 0)}/100")
    print(f"- raw traceability: {payload.get('raw_traceability_score', 0)}/100")
    print(f"- projection explainability: {payload.get('projection_explainability_score', 0)}/100")
    print(f"- answer debug: {payload.get('answer_debug_score', 0)}/100")
    print(f"- experience intervention: {payload.get('experience_intervention_score', 0)}/100")
    print(f"- behavior change: {payload.get('behavior_change_score', 0)}/100")
    print(f"- acceptance checks: {payload.get('acceptance_check_score', 0)}/100")
    readiness = payload.get("benchmark_readiness", {}) if isinstance(payload.get("benchmark_readiness"), dict) else {}
    print(f"- benchmark readiness: {readiness.get('score', payload.get('benchmark_readiness_score', 0))}/100 ({readiness.get('readiness_level', '')})")
    print()
    print("## Boundary")
    print(f"- read only: {payload.get('read_only', True)}")
    print(f"- official leaderboard score: {readiness.get('official_leaderboard_score', False)}")
    print(f"- tiny diagnostic is official score: {not readiness.get('tiny_diagnostic_is_not_official_score', True)}")
    smoke = payload.get("live_work_preflight_smoke", {}) if isinstance(payload.get("live_work_preflight_smoke"), dict) else {}
    if smoke:
        response = smoke.get("response", {}) if isinstance(smoke.get("response"), dict) else {}
        latency = smoke.get("latency_summary", {}) if isinstance(smoke.get("latency_summary"), dict) else {}
        sample_text = ""
        if latency:
            sample_text = f", samples={latency.get('sample_count', 0)}, p95={latency.get('p95_ms', 0)} ms, max={latency.get('max_ms', 0)} ms"
        print(f"- live work preflight smoke: {smoke.get('ok', False)} ({smoke.get('elapsed_ms', 0)} ms{sample_text}, {response.get('decision', '')})")
    if payload.get("critical_attention"):
        print()
        print("## Attention")
        for item in payload.get("critical_attention", []):
            print(f"- {item}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the read-only scored preflight doctor.")
    parser.add_argument("--query", default="", help="Work query to feed into the preflight loops.")
    parser.add_argument("--memcore-root", default="", help="Runtime Memcore root. Defaults to MEMCORE_ROOT or repo root.")
    parser.add_argument("--home", default="", help="Home directory to scan for local agent configs.")
    parser.add_argument("--include-generic", action="store_true", help="Include generic local AI surface discovery.")
    parser.add_argument("--skip-platform-scan", action="store_true", help="Skip local platform scanning for deterministic tests.")
    parser.add_argument("--include-productized-payload", action="store_true", help="Include the full underlying productized loop payload.")
    parser.add_argument("--diagnostic-profile", choices=["full", "smoke"], default="smoke", help="Use smoke for the hot-path work_preflight check or full for heavy doctor scores.")
    parser.add_argument("--live-work-preflight-smoke", action="store_true", help="Run a read-only local 9851 work_preflight smoke and feed its measured latency/shape into the score.")
    parser.add_argument("--live-work-preflight-smoke-samples", type=int, default=None, help="Run N read-only work_preflight smoke samples and score latency by median while reporting outliers.")
    parser.add_argument("--live-work-preflight-endpoint", default="", help="Endpoint for --live-work-preflight-smoke. Defaults to local 9851 raw query.")
    parser.add_argument("--live-work-preflight-query", default="", help="Query for --live-work-preflight-smoke.")
    parser.add_argument("--live-work-preflight-timeout-seconds", type=float, default=None, help="Timeout for --live-work-preflight-smoke.")
    parser.add_argument("--canonical-window-id", default="", help="Window id to pass into live work_preflight smoke.")
    parser.add_argument("--no-default-work-anchor", action="store_true", help="Do not default unanchored daily smoke to canonical_window_id=codex-current.")
    parser.add_argument("--session-id", default="", help="Session id to pass into live work_preflight smoke.")
    parser.add_argument("--project-id", default="", help="Project id to pass into live work_preflight smoke.")
    parser.add_argument("--project-root", default="", help="Project root to pass into live work_preflight smoke.")
    parser.add_argument("--workstream-id", default="", help="Workstream id to pass into live work_preflight smoke.")
    parser.add_argument("--task-id", default="", help="Task id to pass into live work_preflight smoke.")
    parser.add_argument("--latency-ms", type=float, default=None, help="Optional measured MCP/preflight latency in milliseconds.")
    parser.add_argument("--fast-window-preflight", action="store_true", help="Mark a real preflight smoke as using the fast current-window path.")
    parser.add_argument("--fast-recall-path", default="", help="Optional measured fast recall path, such as canonical_window_index.")
    parser.add_argument("--fast-window-index-status", default="", help="Optional measured fast window index status, such as hit.")
    parser.add_argument("--zhiyi-layer-skipped-for-fast-preflight", action="store_true", help="Mark the deep Zhiyi layer as skipped for a real fast preflight smoke.")
    parser.add_argument("--library-index-projection-used", action="store_true", help="Mark Library Index Projection as triggered in the measured preflight payload.")
    parser.add_argument("--library-index-projection-refs-count", type=int, default=None, help="Number of Library Index Projection refs surfaced by the measured preflight payload.")
    parser.add_argument("--library-index-projection-policy", default="", help="Measured projection authority policy, such as navigation_hint_only_raw_evidence_required.")
    parser.add_argument("--library-index-projection-soft-weight-policy", default="", help="Measured soft-weight policy, such as library_index_projection_is_soft_navigation_signal_only.")
    parser.add_argument("--library-index-projection-soft-weight", type=int, default=None, help="Measured projection soft weight used for rerank diagnostics.")
    parser.add_argument("--json", action="store_true", help="Print full JSON instead of a compact text report.")
    args = parser.parse_args()

    body = {
        "query": args.query,
        "include_generic": args.include_generic,
        "skip_platform_scan": args.skip_platform_scan,
        "include_productized_payload": args.include_productized_payload,
        "diagnostic_profile": args.diagnostic_profile,
    }
    if args.live_work_preflight_smoke:
        body["live_work_preflight_smoke"] = True
    if args.live_work_preflight_smoke_samples is not None:
        body["live_work_preflight_smoke_samples"] = args.live_work_preflight_smoke_samples
    if args.live_work_preflight_endpoint:
        body["live_work_preflight_endpoint"] = args.live_work_preflight_endpoint
    if args.live_work_preflight_query:
        body["live_work_preflight_query"] = args.live_work_preflight_query
    if args.live_work_preflight_timeout_seconds is not None:
        body["live_work_preflight_timeout_seconds"] = args.live_work_preflight_timeout_seconds
    if args.no_default_work_anchor:
        body["disable_default_work_anchor"] = True
    for key, value in {
        "canonical_window_id": args.canonical_window_id,
        "session_id": args.session_id,
        "project_id": args.project_id,
        "project_root": args.project_root,
        "workstream_id": args.workstream_id,
        "task_id": args.task_id,
    }.items():
        if value:
            body[key] = value
    if args.latency_ms is not None:
        body["latency_ms"] = args.latency_ms
    if args.fast_window_preflight:
        body["fast_window_preflight"] = True
    if args.fast_recall_path:
        body["fast_recall_path"] = args.fast_recall_path
    if args.fast_window_index_status:
        body["fast_window_index_status"] = args.fast_window_index_status
    if args.zhiyi_layer_skipped_for_fast_preflight:
        body["zhiyi_layer_skipped_for_fast_preflight"] = True
    if args.library_index_projection_used:
        body["library_index_projection_used"] = True
    if args.library_index_projection_refs_count is not None:
        body["library_index_projection_refs_count"] = args.library_index_projection_refs_count
    if args.library_index_projection_policy:
        body["library_index_projection_policy"] = args.library_index_projection_policy
    if args.library_index_projection_soft_weight_policy:
        body["library_index_projection_soft_weight_policy"] = args.library_index_projection_soft_weight_policy
    if args.library_index_projection_soft_weight is not None:
        body["library_index_projection_soft_weight"] = args.library_index_projection_soft_weight
    payload = build_preflight_doctor(
        body,
        memcore_root=args.memcore_root or memcore_root(__file__),
        home=args.home or None,
    )
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        _print_text(payload)
    return 0 if payload.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
