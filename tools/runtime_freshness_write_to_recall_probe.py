#!/usr/bin/env python3
"""
Runtime freshness write-to-recall probe.

Measures how long it takes for a uniquely-tokened record written via the
real zhiyi case_memory.jsonl append path to become visible through the
installed front-door recall endpoint.

DEFAULT MODE: refuses to write real memory.  Outputs proof_layer=source_code
and status=blocked_not_proven unless --write-real is passed.

Connected-runtime proof requires:
  1. --write-real flag (or --confirm-write-real)
  2. front-door discovery file and gateway reachable
  3. Write target is the INSTALLED runtime zhiyi path, not a tempdir

Non-claims when run without --write-real:
  - Does NOT prove connected_runtime freshness
  - Does NOT prove write-to-recall latency
  - Only proves source_code path analysis and harness guard behavior
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.request
import urllib.error
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from port_discovery import front_door_url

try:
    DEFAULT_GATEWAY_ENDPOINT = front_door_url("/api/v1/raw/query")
    DEFAULT_HEALTH_ENDPOINT = front_door_url("/health")
except RuntimeError:
    DEFAULT_GATEWAY_ENDPOINT = ""
    DEFAULT_HEALTH_ENDPOINT = ""
INSTALLED_RUNTIME_ROOT = os.path.expanduser(
    "~/Library/Application Support/memcore-cloud"
)
INSTALLED_CASE_MEMORY = os.path.join(
    INSTALLED_RUNTIME_ROOT, "zhiyi", "case_memory", "case_memory.jsonl"
)
PROBE_CONTRACT = "runtime_freshness_write_to_recall_probe.v2026.6.29"
TOKEN_PREFIX = "freshness-probe-"
POLL_INTERVAL_SECONDS = 0.5
POLL_TIMEOUT_SECONDS = 30


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _generate_token() -> str:
    return TOKEN_PREFIX + uuid.uuid4().hex[:16]


def _token_hash(token: str) -> str:
    return _sha256_hex(token.encode("utf-8"))[:16]


def _gateway_health(endpoint: str, timeout: float = 3.0) -> dict:
    health_url = endpoint.replace("/api/v1/raw/query", "/health")
    try:
        req = urllib.request.Request(health_url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def _query_gateway(endpoint: str, query: str, timeout: float = 8.0) -> tuple[dict, str]:
    payload = {
        "query": query,
        "limit": 10,
        "excerpt_chars": 200,
        "consumer": "freshness-probe",
        "source_system": "openclaw",
    }
    try:
        req = urllib.request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        return result, ""
    except Exception as exc:
        return {}, f"{type(exc).__name__}: {exc}"


def _build_test_record(token: str) -> dict:
    now_display = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    return {
        "exp_id": f"exp-freshness-probe-{uuid.uuid4().hex[:12]}",
        "type": "case_memory",
        "canonical_window_id": "freshness-probe",
        "session_id": f"probe-session-{uuid.uuid4().hex[:8]}",
        "computer_id": "freshness-probe-harness",
        "source_system": "openclaw",
        "scope": "freshness-probe test",
        "summary": f"Freshness probe test record. Token: {token}. This record is ephemeral and will be cleaned up.",
        "detail": f"Written by runtime_freshness_write_to_recall_probe at {now_display}. Token hash: {_token_hash(token)}.",
        "source_refs": json.dumps({
            "source_system": "openclaw",
            "computer_name": "freshness-probe-harness",
            "canonical_window_id": "freshness-probe",
            "session_id": f"probe-session-{uuid.uuid4().hex[:8]}",
            "source_path": "freshness-probe-ephemeral",
            "msg_ids": [],
        }),
        "evidence_level": "probe",
        "score": 0.5,
        "extracted_at": now_display,
        "_freshness_probe": True,
        "_probe_token_hash": _token_hash(token),
    }


def _append_record(path: str, record: dict) -> float:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    line = json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
    with open(path, "a", encoding="utf-8") as f:
        f.write(line)
        f.flush()
        os.fsync(f.fileno())
    return time.time()


def _remove_last_record_if_probe(path: str, token_hash: str) -> bool:
    if not os.path.exists(path):
        return False
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
        if not lines:
            return False
        last = lines[-1].strip()
        if not last:
            return False
        rec = json.loads(last)
        if rec.get("_probe_token_hash") == token_hash:
            with open(path, "w", encoding="utf-8") as f:
                f.writelines(lines[:-1])
                f.flush()
                os.fsync(f.fileno())
            return True
    except Exception:
        pass
    return False


def _find_token_in_response(response: dict, token: str) -> bool:
    text = json.dumps(response, ensure_ascii=False).lower()
    return token.lower() in text


def _find_token_hash_in_response(response: dict, token_hash: str) -> bool:
    text = json.dumps(response, ensure_ascii=False).lower()
    return token_hash.lower() in text


def build_probe_result(body: dict) -> dict:
    body = body if isinstance(body, dict) else {}
    write_real = bool(body.get("write_real") or body.get("confirm_write_real"))
    endpoint = str(body.get("endpoint") or DEFAULT_GATEWAY_ENDPOINT)
    timeout = float(body.get("timeout_seconds") or POLL_TIMEOUT_SECONDS)
    no_cleanup = bool(body.get("no_cleanup"))
    installed_case_memory = str(body.get("installed_case_memory") or INSTALLED_CASE_MEMORY)

    result = {
        "ok": False,
        "contract": PROBE_CONTRACT,
        "created_at": _now_iso(),
        "write_real_requested": write_real,
        "write_performed": False,
        "cleanup_performed": False,
        "status": "blocked_not_proven",
        "proof_layer": "source_code",
        "nonClaims": [
            "connected_runtime freshness latency not measured",
            "write-to-recall visibility window not measured",
            "refresh_pending/stale_served behavior not observed in live gateway",
        ],
        "gateway_endpoint": endpoint,
        "installed_case_memory": installed_case_memory,
        "installed_runtime_exists": os.path.isdir(INSTALLED_RUNTIME_ROOT),
        "case_memory_exists": os.path.isfile(installed_case_memory),
        "gateway_health": {},
        "t_write_to_visible_seconds": None,
        "poll_count": 0,
        "poll_results": [],
        "refresh_pending_observed": False,
        "stale_served_observed": False,
        "memory_cache_statuses_seen": [],
        "freshness_boundaries_seen": [],
        "error": "",
        "harness_source_code_path": str(Path(__file__).resolve()),
        "next_action_for_Codex": (
            "Re-run with --write-real to attempt connected_runtime proof. "
            "Verify installed runtime zhiyi path and 9851 gateway are healthy first."
        ),
    }

    installed_exists = os.path.isdir(INSTALLED_RUNTIME_ROOT)
    case_memory_exists = os.path.isfile(installed_case_memory)
    result["installed_runtime_exists"] = installed_exists
    result["case_memory_exists"] = case_memory_exists

    if not write_real:
        result["nonClaims"].append(
            "harness refused real write: --write-real not passed"
        )
        result["next_action_for_Codex"] = (
            "Harness is in source_code-only mode. To prove connected_runtime, "
            "re-run with --write-real. The harness will append a test token to "
            f"{installed_case_memory} and poll {endpoint} for visibility."
        )
        return result

    if not installed_exists:
        result["status"] = "blocked_not_proven"
        result["error"] = f"installed runtime not found at {INSTALLED_RUNTIME_ROOT}"
        result["nonClaims"].append("installed runtime directory missing")
        return result

    if not case_memory_exists:
        result["status"] = "blocked_not_proven"
        result["error"] = f"case_memory.jsonl not found at {installed_case_memory}"
        result["nonClaims"].append("installed case_memory.jsonl missing")
        return result

    health = _gateway_health(endpoint)
    result["gateway_health"] = health
    if not health.get("ok"):
        result["status"] = "blocked_not_proven"
        result["error"] = f"gateway health check failed: {health.get('error', 'unknown')}"
        result["nonClaims"].append("9851 gateway not reachable")
        result["next_action_for_Codex"] = (
            f"Gateway at {endpoint} is not healthy. Check if memcore-cloud service is running. "
            f"Health response: {json.dumps(health, ensure_ascii=False)[:500]}"
        )
        return result

    token = _generate_token()
    token_hash = _token_hash(token)
    record = _build_test_record(token)

    write_time = _append_record(installed_case_memory, record)
    result["write_performed"] = True
    result["token_hash_prefix"] = token_hash
    result["write_timestamp"] = datetime.fromtimestamp(write_time, tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )

    query = token
    visible = False
    poll_count = 0
    t_visible = None

    while (time.time() - write_time) < timeout:
        poll_count += 1
        resp, err = _query_gateway(endpoint, query, timeout=5.0)
        now = time.time()

        memory_cache_status = ""
        refresh_status = ""
        refresh_pending = False
        freshness_boundary = ""

        if resp:
            memory_cache_status = str(resp.get("memory_cache_status") or "")
            refresh_status = str(resp.get("refresh_status") or "")
            refresh_pending = bool(resp.get("refresh_pending"))
            freshness_boundary = str(resp.get("freshness_boundary") or "")

            if memory_cache_status and memory_cache_status not in result["memory_cache_statuses_seen"]:
                result["memory_cache_statuses_seen"].append(memory_cache_status)
            if freshness_boundary and freshness_boundary not in result["freshness_boundaries_seen"]:
                result["freshness_boundaries_seen"].append(freshness_boundary)
            if refresh_pending:
                result["refresh_pending_observed"] = True
            if memory_cache_status == "stale_served":
                result["stale_served_observed"] = True

        found = _find_token_in_response(resp, token) or _find_token_hash_in_response(resp, token_hash)

        poll_entry = {
            "poll": poll_count,
            "elapsed_ms": round((now - write_time) * 1000, 1),
            "found": found,
            "error": err,
            "memory_cache_status": memory_cache_status,
            "refresh_status": refresh_status,
            "refresh_pending": refresh_pending,
            "freshness_boundary": freshness_boundary,
            "items_count": len(resp.get("items", []) or resp.get("evidence", []) or []),
        }
        result["poll_results"].append(poll_entry)

        if found:
            visible = True
            t_visible = round(now - write_time, 3)
            break

        time.sleep(POLL_INTERVAL_SECONDS)

    result["poll_count"] = poll_count
    if visible:
        result["ok"] = True
        result["status"] = "connected_runtime_zhiyi_append_to_gateway_proven"
        result["proof_layer"] = "connected_runtime_partial"
        result["t_write_to_visible_seconds"] = t_visible
        result["nonClaims"] = [
            "does not prove raw source write path (harness appends directly to zhiyi jsonl, bypassing raw session capture)",
            "does not prove p2_extract extraction path (no raw→zhiyi extraction was performed)",
            "does not prove user/agent platform capture path (no platform event triggered the write)",
            "does not prove production write-to-recall from raw session to zhiyi to gateway (full chain untested)",
            "does not prove vector recall path (used default recall_mode)",
            "does not prove lifecycle overlay freshness_score was applied",
            "does not prove BM25 index refresh (separate from memory cache refresh)",
            "single-token probe; not a sustained throughput or concurrency test",
        ]
        result["next_action_for_Codex"] = (
            f"Zhiyi-append-to-gateway proven. t_write_to_visible={t_visible}s, "
            f"poll_count={poll_count}. Verify gateway PID/SHA from health response, "
            "check poll_results for refresh_pending/stale_served sequence. "
            "To prove full-chain freshness: write a raw session record via the "
            "designated raw source path (or trigger a real platform event), "
            "run p2_extract to produce zhiyi experience, then poll 9851/MCP "
            "for recall visibility of the extracted record."
        )
    else:
        result["status"] = "connected_runtime_zhiyi_append_timeout"
        result["proof_layer"] = "connected_runtime_partial_incomplete"
        result["nonClaims"].append(
            f"token not visible within {timeout}s timeout ({poll_count} polls)"
        )
        result["next_action_for_Codex"] = (
            f"Token not visible within {timeout}s. Check poll_results for "
            "refresh_pending/stale_served patterns. The p3_recall background "
            "reload may have failed, or the gateway may be using a different "
            "zhiyi path than the installed runtime."
        )

    if write_real and not no_cleanup:
        cleaned = _remove_last_record_if_probe(installed_case_memory, token_hash)
        result["cleanup_performed"] = cleaned
        result["cleanup_note"] = (
            "Test record removed from case_memory.jsonl"
            if cleaned
            else "Could not verify/remove test record (may have been processed by p2)"
        )

    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Runtime freshness write-to-recall probe.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "DEFAULT: source_code-only mode (no real writes).\n"
            "Pass --write-real to attempt connected_runtime proof.\n"
            "WARNING: --write-real will append a test record to the installed "
            "runtime zhiyi case_memory.jsonl and may trigger gateway cache refresh."
        ),
    )
    parser.add_argument(
        "--write-real",
        action="store_true",
        help="Actually write a test token to installed runtime and poll gateway.",
    )
    parser.add_argument(
        "--confirm-write-real",
        action="store_true",
        help="Alias for --write-real.",
    )
    parser.add_argument(
        "--endpoint",
        default=DEFAULT_GATEWAY_ENDPOINT,
        help=f"Gateway recall endpoint. Default: {DEFAULT_GATEWAY_ENDPOINT}",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=POLL_TIMEOUT_SECONDS,
        help=f"Max seconds to poll for visibility. Default: {POLL_TIMEOUT_SECONDS}",
    )
    parser.add_argument(
        "--no-cleanup",
        action="store_true",
        help="Do not remove test record after probe.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print full JSON output.",
    )
    args = parser.parse_args()

    body = {
        "write_real": args.write_real or args.confirm_write_real,
        "endpoint": args.endpoint,
        "timeout_seconds": args.timeout_seconds,
        "no_cleanup": args.no_cleanup,
    }

    payload = build_probe_result(body)

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"contract: {payload.get('contract')}")
        print(f"status: {payload.get('status')}")
        print(f"proof_layer: {payload.get('proof_layer')}")
        print(f"write_real_requested: {payload.get('write_real_requested')}")
        print(f"write_performed: {payload.get('write_performed')}")
        print(f"installed_runtime_exists: {payload.get('installed_runtime_exists')}")
        print(f"case_memory_exists: {payload.get('case_memory_exists')}")
        print(f"gateway_health_ok: {payload.get('gateway_health', {}).get('ok')}")
        if payload.get("t_write_to_visible_seconds") is not None:
            print(f"t_write_to_visible: {payload['t_write_to_visible_seconds']}s")
        print(f"poll_count: {payload.get('poll_count', 0)}")
        print(f"refresh_pending_observed: {payload.get('refresh_pending_observed')}")
        print(f"stale_served_observed: {payload.get('stale_served_observed')}")
        print(f"memory_cache_statuses_seen: {payload.get('memory_cache_statuses_seen', [])}")
        print(f"freshness_boundaries_seen: {payload.get('freshness_boundaries_seen', [])}")
        nc = payload.get("nonClaims", [])
        if nc:
            print("nonClaims:")
            for item in nc:
                print(f"  - {item}")
        if payload.get("error"):
            print(f"error: {payload['error']}")
        print(f"next_action: {payload.get('next_action_for_Codex', '')}")

    return 0 if payload.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
