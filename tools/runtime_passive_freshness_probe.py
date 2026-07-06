#!/usr/bin/env python3
"""Passive-trigger freshness probe.

Proof target:
  real/quasi-real watched source write -> existing passive watcher/ingest ->
  p2 extract -> zhiyi -> default recall visible

Red lines:
  - do not call incremental_extract_session directly
  - do not call manual scan_sessions/catch-up helpers
  - do not claim vector/BM25 refresh as passive freshness
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import statistics
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import codex_local_connector
from raw_archive_layout import preferred_raw_archive_path
import runtime_freshness_full_chain_probe as forced_probe

UTC = timezone.utc
PROBE_CONTRACT = "runtime_passive_freshness_probe.v2026.7.4"
TOKEN_PREFIX = "passive-freshness-probe-"
DEFAULT_GATEWAY_ENDPOINT = "http://127.0.0.1:9851/api/v1/raw/query"
DEFAULT_WATCHER_LOG = Path.home() / "Library" / "Logs" / "memcore-cloud" / "p0-watcher.out.log"
INSTALLED_RUNTIME_ROOT = Path.home() / "Library" / "Application Support" / "memcore-cloud"
DEFAULT_TEMPLATE_SOURCE = Path.home() / ".codex" / "sessions" / "2026" / "07" / "01" / "rollout-2026-07-01T12-44-39-019f1bfe-50ac-7e80-baf0-25d0c637f69f.jsonl"
POLL_INTERVAL_SECONDS = 0.25
POLL_TIMEOUT_SECONDS = 20.0


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _generate_token() -> str:
    return TOKEN_PREFIX + uuid.uuid4().hex[:16]


def _token_hash(token: str) -> str:
    return _sha256_hex(token.encode("utf-8"))[:16]


def _query_gateway(endpoint: str, query: str) -> Tuple[dict, str]:
    return forced_probe._query_gateway(
        endpoint,
        query,
        timeout=8.0,
        source_system="codex",
        recall_mode="",
        memory_scope="active",
    )


def _find_token_in_response(response: dict, token: str, token_hash: str) -> bool:
    return forced_probe._find_token_in_response(response, token) or forced_probe._find_token_hash_in_response(response, token_hash)


def _compute_installed_raw_dest(source_path: str) -> str:
    artifact = codex_local_connector.artifact_from_path(Path(source_path))
    return str(
        preferred_raw_archive_path(
            INSTALLED_RUNTIME_ROOT / "memory",
            computer_name=artifact.get("computer_name") or "local",
            source_system=artifact.get("source_system") or "codex",
            native_format=artifact.get("artifact_type") or "codex_session_jsonl",
            native_scope=artifact.get("canonical_window_id") or artifact.get("project_id") or "no-cwd",
            session_id=artifact.get("session_id") or Path(source_path).stem,
        )
    )


def _watcher_log_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _tail_new_watcher_lines(path: Path, offset: int) -> List[str]:
    try:
        with path.open("rb") as handle:
            handle.seek(offset)
            data = handle.read()
        return [line for line in data.decode("utf-8", errors="replace").splitlines() if line.strip()]
    except OSError:
        return []


def _log_mentions_session(lines: List[str], session_id: str) -> bool:
    for line in lines:
        if session_id[:8] in line or session_id in line:
            return True
    return False


def _sample_gateway_hit(response: dict) -> dict:
    for field in ("items", "evidence", "raw_items"):
        items = response.get(field)
        if isinstance(items, list) and items:
            first = items[0]
            if isinstance(first, dict):
                return {
                    "field": field,
                    "library_id": first.get("library_id", ""),
                    "summary": first.get("summary") or first.get("title") or first.get("detail") or "",
                    "matched_by": first.get("matched_by") or response.get("matched_by") or "",
                    "source_ref": first.get("source_ref") or first.get("source_refs") or "",
                }
    return {}


def _perform_cleanup(source_path: str, raw_dest: str, token: str, token_hash: str, endpoint: str) -> dict:
    return forced_probe._perform_cleanup(source_path, raw_dest, 0, token, token_hash, endpoint)


def build_probe_result(body: dict[str, Any]) -> dict[str, Any]:
    template_source = Path(str(body.get("template_source_path") or DEFAULT_TEMPLATE_SOURCE)).expanduser()
    endpoint = str(body.get("endpoint") or DEFAULT_GATEWAY_ENDPOINT)
    timeout_seconds = float(body.get("timeout_seconds") or POLL_TIMEOUT_SECONDS)
    iterations = max(1, min(int(body.get("iterations") or 1), 5))
    no_cleanup = bool(body.get("no_cleanup"))
    watcher_log = Path(str(body.get("watcher_log") or DEFAULT_WATCHER_LOG)).expanduser()

    result: dict[str, Any] = {
        "ok": False,
        "contract": PROBE_CONTRACT,
        "created_at": _now_iso(),
        "proof_layer": "installed_runtime",
        "status": "blocked_not_proven",
        "write_performed": False,
        "passive_write_detected": False,
        "default_recall_visible": False,
        "extraction_trigger": "watcher",
        "extraction_trigger_note": "watcher=existing p0 watcher/connector path triggered by source file write; no direct incremental_extract_session call in probe",
        "gateway_endpoint": endpoint,
        "watcher_log": str(watcher_log),
        "template_source_path": str(template_source),
        "iterations": iterations,
        "poll_interval_seconds": POLL_INTERVAL_SECONDS,
        "poll_timeout_seconds": timeout_seconds,
        "runs": [],
        "cleanup_performed": False,
        "all_layers_cleaned": False,
        "gateway_empty_after_cleanup": False,
        "nonClaims": [
            "does not prove cross-machine/Hermes/release/vector or BM25 refresh freshness",
            "does not prove every passive source path behaves the same as codex watcher path",
            "does not call incremental_extract_session directly; if passive path fails this remains honest deferred",
        ],
    }

    if not template_source.exists():
        result["status"] = "template_source_missing"
        result["error"] = f"template source missing: {template_source}"
        return result

    totals: List[float] = []
    cleanup_reports: List[dict] = []

    for idx in range(iterations):
        token = _generate_token()
        token_hash = _token_hash(token)
        log_offset = _watcher_log_size(watcher_log)
        started_at = time.time()
        generated_ok, generated = forced_probe._generate_probe_source_session(str(template_source), token, token_hash)
        run: dict[str, Any] = {
            "iteration": idx + 1,
            "token": token,
            "token_hash": token_hash,
            "generated": generated,
            "found_in_raw": False,
            "found_in_gateway": False,
            "watcher_log_mentions_session": False,
            "timing": {
                "t_write_to_raw_visible_ms": None,
                "t_raw_visible_to_gateway_visible_ms": None,
                "t_total_write_to_visible_ms": None,
            },
            "gateway_hit": {},
            "poll_results": [],
        }
        result["runs"].append(run)
        if not generated_ok:
            run["error"] = generated.get("error") or "generate_failed"
            result["status"] = "generate_failed"
            result["error"] = run["error"]
            break

        source_path = generated["generated_source_path"]
        session_id = generated["session_id"]
        raw_dest = _compute_installed_raw_dest(source_path)
        run["source_path"] = source_path
        run["raw_dest"] = raw_dest
        result["write_performed"] = True

        raw_visible_time = None
        gateway_visible_time = None
        visible = False
        while time.time() - started_at < timeout_seconds:
            now = time.time()
            raw_exists = Path(raw_dest).exists()
            if raw_exists and raw_visible_time is None:
                raw_visible_time = now
                run["found_in_raw"] = True
                run["timing"]["t_write_to_raw_visible_ms"] = round((raw_visible_time - started_at) * 1000, 1)

            response, err = _query_gateway(endpoint, token)
            found = _find_token_in_response(response, token, token_hash)
            if found and not raw_exists and Path(raw_dest).exists():
                raw_exists = True
                if raw_visible_time is None:
                    raw_visible_time = now
                    run["found_in_raw"] = True
                    run["timing"]["t_write_to_raw_visible_ms"] = round((raw_visible_time - started_at) * 1000, 1)
            run["poll_results"].append({
                "elapsed_ms": round((now - started_at) * 1000, 1),
                "raw_exists": raw_exists,
                "found": found,
                "error": err,
                "memory_cache_status": response.get("memory_cache_status", ""),
                "freshness_boundary": response.get("freshness_boundary", ""),
                "recent_delta_applied": response.get("recent_delta_applied"),
                "matched_by": response.get("matched_by", ""),
            })
            if found:
                gateway_visible_time = now
                visible = True
                run["found_in_gateway"] = True
                run["gateway_hit"] = _sample_gateway_hit(response)
                break
            time.sleep(POLL_INTERVAL_SECONDS)

        new_log_lines = _tail_new_watcher_lines(watcher_log, log_offset)
        run["watcher_log_tail"] = new_log_lines[-20:]
        run["watcher_log_mentions_session"] = _log_mentions_session(new_log_lines, session_id)

        if raw_visible_time is not None and gateway_visible_time is not None:
            run["timing"]["t_raw_visible_to_gateway_visible_ms"] = round((gateway_visible_time - raw_visible_time) * 1000, 1)
            total_ms = round((gateway_visible_time - started_at) * 1000, 1)
            run["timing"]["t_total_write_to_visible_ms"] = total_ms
            totals.append(total_ms)
            result["passive_write_detected"] = True
            result["default_recall_visible"] = True

        if not no_cleanup:
            cleanup = _perform_cleanup(source_path, raw_dest, token, token_hash, endpoint)
            cleanup["iteration"] = idx + 1
            cleanup_reports.append(cleanup)

        if not visible:
            result["status"] = "passive_timeout"
            result["error"] = (
                f"token not visible within {timeout_seconds}s; raw_exists={run['found_in_raw']} "
                f"watcher_log_mentions_session={run['watcher_log_mentions_session']}"
            )
            result["nonClaims"].append("passive path did not prove automatic default recall visibility within timeout")
            break

    if cleanup_reports:
        result["cleanup_performed"] = True
        result["all_layers_cleaned"] = all(item.get("all_layers_cleaned") for item in cleanup_reports)
        result["gateway_empty_after_cleanup"] = all(item.get("gateway_empty_after_cleanup") for item in cleanup_reports)
        result["cleanup_reports"] = cleanup_reports

    if result["default_recall_visible"] and totals and result.get("status") != "passive_timeout":
        result["ok"] = True
        result["status"] = "connected_runtime_passive_default_recall_proven"
        result["timing_summary"] = {
            "iterations": len(totals),
            "t_total_min_ms": min(totals),
            "t_total_median_ms": round(statistics.median(totals), 1),
            "t_total_max_ms": max(totals),
        }
        result["next_action_for_Codex"] = "Passive freshness proven on codex watcher path; write receipt and keep Opus focused on extraction_trigger!=forced plus default recall hit."
    elif result.get("status") == "blocked_not_proven":
        result["status"] = "honest_deferred"
        result["next_action_for_Codex"] = "Passive path not yet proven; inspect watcher coverage, session enrollment, and default recall visibility without forced extraction."

    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Passive-trigger freshness probe.")
    parser.add_argument("--template-source-path", default=str(DEFAULT_TEMPLATE_SOURCE))
    parser.add_argument("--endpoint", default=DEFAULT_GATEWAY_ENDPOINT)
    parser.add_argument("--watcher-log", default=str(DEFAULT_WATCHER_LOG))
    parser.add_argument("--timeout-seconds", type=float, default=POLL_TIMEOUT_SECONDS)
    parser.add_argument("--iterations", type=int, default=1)
    parser.add_argument("--no-cleanup", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    payload = build_probe_result(
        {
            "template_source_path": args.template_source_path,
            "endpoint": args.endpoint,
            "watcher_log": args.watcher_log,
            "timeout_seconds": args.timeout_seconds,
            "iterations": args.iterations,
            "no_cleanup": args.no_cleanup,
        }
    )
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"contract: {payload.get('contract')}")
        print(f"status: {payload.get('status')}")
        print(f"proof_layer: {payload.get('proof_layer')}")
        print(f"extraction_trigger: {payload.get('extraction_trigger')}")
        print(f"passive_write_detected: {payload.get('passive_write_detected')}")
        print(f"default_recall_visible: {payload.get('default_recall_visible')}")
        if payload.get("timing_summary"):
            print(json.dumps(payload["timing_summary"], ensure_ascii=False))
        if payload.get("error"):
            print(f"error: {payload['error']}")
    return 0 if payload.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
