#!/usr/bin/env python3
"""Compare Memcore eval run summaries."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_run(path: str | Path) -> dict[str, Any]:
    root = Path(path).expanduser()
    summary = _load_json(root / "summary.json")
    ledger = _load_json(root / "run-ledger.json")
    results = summary.get("benchmark_result", {}).get("results", [])
    result = results[0] if results else {}
    return {
        "run_dir": str(root),
        "dataset": result.get("dataset", ledger.get("dataset", "")),
        "split": result.get("split", ledger.get("split", "")),
        "case_count": result.get("case_count", ledger.get("actual_case_count", 0)),
        "top_k": result.get("top_k", ledger.get("top_k", 0)),
        "exact_source_recall": result.get("exact_source_recall", 0),
        "bundled_source_recall": result.get("bundled_source_recall", 0),
        "near_source_recall": result.get("near_source_recall", 0),
        "session_recall": result.get("session_recall", 0),
        "gold_anchor_recall": result.get("gold_anchor_recall", 0),
        "elapsed_ms": ledger.get("elapsed_ms", summary.get("elapsed_ms", 0)),
        "rss_peak_bytes": ledger.get("rss_peak_bytes", summary.get("rss_peak_bytes", 0)),
        "process_tree_peak_rss_bytes": ledger.get("process_tree_peak_rss_bytes", 0),
        "watcher_active_source": ledger.get("watcher_active_source", summary.get("watcher_active_source", "")),
        "tokens_in": ledger.get("tokens_in", 0),
        "tokens_out": ledger.get("tokens_out", 0),
        "status": ledger.get("status", summary.get("status", "")),
        "official_leaderboard_score": summary.get("benchmark_result", {}).get("boundary", {}).get("official_leaderboard_score", False),
        "no_model_call": summary.get("benchmark_result", {}).get("boundary", {}).get("no_model_call", True),
        "no_memory_write": summary.get("benchmark_result", {}).get("boundary", {}).get("no_memory_write", True),
    }


def build_report(run_dirs: list[str | Path]) -> dict[str, Any]:
    runs = [load_run(path) for path in run_dirs]
    return {
        "ok": True,
        "contract": "memcore_eval_run_compare.v2026.6.19",
        "run_count": len(runs),
        "runs": runs,
        "boundary": {
            "official_leaderboard_score": False,
            "no_model_call": all(bool(item.get("no_model_call", True)) for item in runs),
            "no_memory_write": all(bool(item.get("no_memory_write", True)) for item in runs),
        },
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Memcore Eval Run Compare",
        "",
        f"- runs: {report.get('run_count', 0)}",
        "- official_leaderboard_score: false",
        f"- no_model_call: {str(report.get('boundary', {}).get('no_model_call', True)).lower()}",
        f"- no_memory_write: {str(report.get('boundary', {}).get('no_memory_write', True)).lower()}",
        "",
        "| dataset | cases | top_k | exact | bundled | session | gold anchor | elapsed ms | rss MB |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for item in report.get("runs", []):
        rss_mb = float(item.get("rss_peak_bytes") or 0) / 1024 / 1024
        lines.append(
            "| {dataset} | {case_count} | {top_k} | {exact:.2f} | {bundled:.2f} | {session:.2f} | {anchor:.2f} | {elapsed:.3f} | {rss:.1f} |".format(
                dataset=item.get("dataset", ""),
                case_count=int(item.get("case_count") or 0),
                top_k=int(item.get("top_k") or 0),
                exact=float(item.get("exact_source_recall") or 0),
                bundled=float(item.get("bundled_source_recall") or 0),
                session=float(item.get("session_recall") or 0),
                anchor=float(item.get("gold_anchor_recall") or 0),
                elapsed=float(item.get("elapsed_ms") or 0),
                rss=rss_mb,
            )
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compare Memcore eval run summaries.")
    parser.add_argument("run_dirs", nargs="+")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--output", default="")
    args = parser.parse_args(argv)
    report = build_report(args.run_dirs)
    text = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) if args.json else render_markdown(report)
    if args.output:
        Path(args.output).expanduser().write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0 if report.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
