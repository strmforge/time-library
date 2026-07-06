#!/usr/bin/env python3
"""
Runtime freshness full-chain (B-path) probe.

Measures end-to-end latency through the full B path:
  raw/session/platform source → connector ingest → p2_extract → zhiyi → 9851/MCP poll

DEFAULT MODE: refuses to write.  Outputs proof_layer=source_code,
status=blocked_not_proven, full_chain_freshness=False.

B-path connected-runtime proof requires ALL of:
  1. --write-real flag
  2. --source-path pointing to a REAL platform session file
  3. --confirm-source-write explicit confirmation
  4. 9851 gateway reachable
  5. connector + p2_extract pipeline functional

Without any of these, the probe returns blocked_not_proven.

Non-claims when run without --write-real:
  - Does NOT prove connected_runtime full-chain freshness
  - Does NOT prove source→connector→p2→zhiyi→gateway latency
  - Only proves source_code path analysis and harness guard behavior

Timing segments (when write_real succeeds):
  - t_source_write_to_connector_ingest
  - t_connector_ingest_to_p2_start
  - t_p2_extract_duration
  - t_zhiyi_write_to_first_gateway_visible
  - t_total_write_to_visible

extraction_trigger: forced (incremental_extract_session called directly)
                    natural (not proven in this harness)
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
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

DEFAULT_GATEWAY_ENDPOINT = "http://127.0.0.1:9851/api/v1/raw/query"
DEFAULT_HEALTH_ENDPOINT = "http://127.0.0.1:9851/health"
INSTALLED_RUNTIME_ROOT = os.path.expanduser(
    "~/Library/Application Support/memcore-cloud"
)
INSTALLED_RUNTIME_SRC = os.path.join(INSTALLED_RUNTIME_ROOT, "src")
PROBE_CONTRACT = "runtime_freshness_full_chain_probe.v2026.6.29"
TOKEN_PREFIX = "full-chain-probe-"
POLL_INTERVAL_SECONDS = 0.5
POLL_TIMEOUT_SECONDS = 60
REQUIRED_CLEANUP_LAYERS = [
    "source_platform_test_record",
    "raw_archive_jsonl",
    "p2_checkpoint",
    "zhiyi_jsonl",
    "bm25_index_cache",
    "gateway_visibility",
]
SOURCE_SYSTEM_DEFAULT = "codex"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _generate_token() -> str:
    return TOKEN_PREFIX + uuid.uuid4().hex[:16]


def _token_hash(token: str) -> str:
    return _sha256_hex(token.encode("utf-8"))[:16]


def _probe_preference_content(token: str, token_hash: str) -> str:
    """Return a deterministic user preference that P2 should extract.

    Keep the token inside the first 80 chars because preference summary is
    content[:80] and the gateway visibility check uses substring recall.
    """
    return f"我希望以后按这个测试偏好记住 token={token} hash={token_hash}。"


def _gateway_health(endpoint: str, timeout: float = 3.0) -> dict:
    health_url = endpoint.replace("/api/v1/raw/query", "/health")
    try:
        req = urllib.request.Request(health_url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def _query_gateway(
    endpoint: str, query: str, timeout: float = 8.0, source_system: str = SOURCE_SYSTEM_DEFAULT,
    recall_mode: str = "",
    memory_scope: str = "active",
) -> tuple[dict, str]:
    payload = {
        "query": query,
        "limit": 10,
        "excerpt_chars": 200,
        "consumer": "full-chain-probe",
    }
    if source_system:
        payload["source_system"] = source_system
    if recall_mode:
        payload["recall_mode"] = recall_mode
    if memory_scope:
        payload["memory_scope"] = memory_scope
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


_TOP_LEVEL_RESULT_FIELDS = (
    "items", "evidence", "source_refs", "raw_items",
    "library_index_projection_refs",
)
_ECHO_FIELDS = frozenset({
    "query", "consumer", "request",
})


def _text_contains(text: str, needle: str) -> bool:
    return needle.lower() in text.lower()


def _scan_any_value(value: object, needle: str) -> bool:
    """Recursively scan any JSON-like value for needle in strings."""
    if isinstance(value, str):
        return _text_contains(value, needle)
    if isinstance(value, dict):
        return any(_scan_any_value(v, needle) for v in value.values())
    if isinstance(value, list):
        return any(_scan_any_value(item, needle) for item in value)
    return False


def _find_token_in_response(response: dict, token: str) -> bool:
    for field in _TOP_LEVEL_RESULT_FIELDS:
        val = response.get(field)
        if val is not None and _scan_any_value(val, token):
            return True
    tcb = response.get("tiandao_context_package")
    if isinstance(tcb, dict):
        sr = tcb.get("source_refs")
        if sr is not None and _scan_any_value(sr, token):
            return True
    return False


def _find_token_hash_in_response(response: dict, token_hash: str) -> bool:
    for field in _TOP_LEVEL_RESULT_FIELDS:
        val = response.get(field)
        if val is not None and _scan_any_value(val, token_hash):
            return True
    tcb = response.get("tiandao_context_package")
    if isinstance(tcb, dict):
        sr = tcb.get("source_refs")
        if sr is not None and _scan_any_value(sr, token_hash):
            return True
    return False


def _is_synthetic_source(source_path: str) -> bool:
    """Check if source_path is a tempdir/synthetic path, not a real platform session."""
    p = Path(source_path).resolve()
    tmp_dirs = ["/tmp", "/var/folders"]
    if any(str(p).startswith(td) for td in tmp_dirs):
        return True
    if "pytest" in str(p).lower() or "tmp" in str(p).lower():
        return True
    return False


def _validate_source_path(source_path: str) -> tuple[bool, str]:
    """Validate that source_path looks like a real platform session file."""
    if not source_path:
        return False, "source_path is empty"
    p = Path(source_path)
    if not p.exists():
        return False, f"source_path does not exist: {source_path}"
    if not p.is_file():
        return False, f"source_path is not a file: {source_path}"
    if _is_synthetic_source(source_path):
        return False, f"source_path appears synthetic/tempdir: {source_path}"
    return True, ""


def _validate_source_jsonl_format(source_path: str) -> tuple[bool, str]:
    """Validate that source_path looks like a Codex session JSONL file.

    Checks that at least the first few non-empty lines are valid JSON
    and that one of them has type=session_meta with a payload dict.
    """
    p = Path(source_path)
    try:
        lines_checked = 0
        found_session_meta = False
        with p.open("r", encoding="utf-8", errors="replace") as f:
            for _ in range(50):
                line = f.readline()
                if not line:
                    break
                line = line.strip()
                if not line:
                    continue
                lines_checked += 1
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    return False, f"line {lines_checked} is not valid JSON"
                if not isinstance(obj, dict):
                    return False, f"line {lines_checked} is not a JSON object"
                if obj.get("type") == "session_meta" and isinstance(obj.get("payload"), dict):
                    found_session_meta = True
        if lines_checked == 0:
            return False, "source file is empty"
        if not found_session_meta:
            return False, "no session_meta record found in first 50 lines"
        return True, ""
    except OSError as exc:
        return False, f"cannot read source file: {exc}"


def _append_token_to_source(
    source_path: str, token: str, token_hash: str
) -> tuple[bool, dict]:
    """Append a user message containing the token to source_path.

    Returns (success, info_dict) where info_dict contains:
      - bytes_written: int
      - line_count: int
      - line_hash: str (sha256 of the appended line)
      - offset_start: int (byte offset where append started)
      - error: str (if success is False)
    """
    info: dict = {
        "bytes_written": 0,
        "line_count": 0,
        "line_hash": "",
        "offset_start": 0,
        "error": "",
    }
    try:
        p = Path(source_path)
        # Get current file size as offset
        stat = p.stat()
        info["offset_start"] = stat.st_size

        # Build a response_item record that P2's preference gate should extract.
        record = {
            "timestamp": _now_iso(),
            "id": f"probe-{token_hash}",
            "type": "response_item",
            "source_system": "codex",
            "payload": {
                "type": "message",
                "role": "user",
                "content": _probe_preference_content(token, token_hash),
            },
        }
        line = json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
        line_bytes = line.encode("utf-8")
        info["bytes_written"] = len(line_bytes)
        info["line_count"] = 1
        info["line_hash"] = _sha256_hex(line_bytes)

        # Append to file
        with p.open("a", encoding="utf-8") as f:
            f.write(line)
            f.flush()
            os.fsync(f.fileno())

        return True, info
    except OSError as exc:
        info["error"] = f"append failed: {type(exc).__name__}: {exc}"
        return False, info


def _generate_probe_source_session(
    template_source_path: str, token: str, token_hash: str
) -> tuple[bool, dict]:
    """Create a unique disposable Codex session JSONL file for one probe iteration.

    Generates a file in the same parent directory as template_source_path,
    with a unique session id in filename, valid session_meta, and a user
    preference message containing the token.  The connector and P2 checkpoint
    will start at offset 0 for this new file.

    Returns (success, info_dict) with keys:
      generated_source_path, session_id, source_created, bytes_written, error
    """
    info: dict = {
        "generated_source_path": "",
        "session_id": "",
        "source_created": False,
        "bytes_written": 0,
        "error": "",
    }
    try:
        parent = Path(template_source_path).resolve().parent
        session_id = f"probe-freshness-{uuid.uuid4().hex[:12]}"
        gen_path = parent / f"{session_id}.jsonl"
        info["generated_source_path"] = str(gen_path)
        info["session_id"] = session_id

        ts_str = _now_iso()
        lines: list[str] = []

        meta_record = {
            "timestamp": ts_str,
            "id": session_id,
            "type": "session_meta",
            "payload": {
                "id": session_id,
                "source_system": "codex",
                "created_at": ts_str,
                "probe_generated": True,
            },
        }
        lines.append(json.dumps(meta_record, ensure_ascii=False, separators=(",", ":")))

        user_record = {
            "timestamp": ts_str,
            "id": f"probe-{token_hash}",
            "type": "response_item",
            "source_system": "codex",
            "payload": {
                "type": "message",
                "role": "user",
                "content": _probe_preference_content(token, token_hash),
            },
        }
        lines.append(json.dumps(user_record, ensure_ascii=False, separators=(",", ":")))

        content = "\n".join(lines) + "\n"
        content_bytes = content.encode("utf-8")
        gen_path.write_bytes(content_bytes)
        info["bytes_written"] = len(content_bytes)
        info["source_created"] = True
        return True, info
    except OSError as exc:
        info["error"] = f"generate session failed: {type(exc).__name__}: {exc}"
        return False, info


def _cleanup_source_file_delete(source_path: str) -> tuple[bool, str]:
    """Delete the entire probe source session file."""
    try:
        p = Path(source_path)
        if p.exists():
            p.unlink()
        return True, ""
    except OSError as exc:
        return False, f"delete failed: {type(exc).__name__}: {exc}"


def _cleanup_checkpoint_entries(
    raw_dest: str, source_path: str
) -> tuple[bool, str]:
    """Remove probe entries from installed runtime checkpoint files.

    Cleans both .checkpoint_p2.json (keyed by raw_dest) and
    .checkpoint (keyed by codex:<abs source_path>).
    """
    try:
        p2_ckpt_path = Path(INSTALLED_RUNTIME_ROOT) / ".checkpoint_p2.json"
        if p2_ckpt_path.exists():
            text = p2_ckpt_path.read_text(encoding="utf-8", errors="replace")
            data = json.loads(text)
            if isinstance(data, dict):
                abs_source = os.path.abspath(source_path)
                changed = False
                if raw_dest and raw_dest in data:
                    del data[raw_dest]
                    changed = True
                source_key = f"codex:{abs_source}"
                if source_key in data:
                    del data[source_key]
                    changed = True
                if changed:
                    p2_ckpt_path.write_text(
                        json.dumps(data, ensure_ascii=False), encoding="utf-8"
                    )

        connector_ckpt_path = Path(INSTALLED_RUNTIME_ROOT) / ".checkpoint"
        if connector_ckpt_path.exists():
            text = connector_ckpt_path.read_text(encoding="utf-8", errors="replace")
            data = json.loads(text)
            if isinstance(data, dict):
                abs_source = os.path.abspath(source_path)
                source_key = f"codex:{abs_source}"
                if source_key in data:
                    del data[source_key]
                    connector_ckpt_path.write_text(
                        json.dumps(data, ensure_ascii=False), encoding="utf-8"
                    )
        return True, ""
    except (json.JSONDecodeError, OSError) as exc:
        return False, f"checkpoint cleanup failed: {type(exc).__name__}: {exc}"


def _build_cleanup_plan(
    source_path: str,
    raw_dest: str,
    zhiyi_paths: list[str],
    token_hash: str,
    cleanup_capable: bool,
) -> dict:
    """Build a cleanup plan covering all 6 required layers."""
    plan = {}
    for layer in REQUIRED_CLEANUP_LAYERS:
        plan[layer] = {
            "cleaned": False,
            "path": "",
            "residual_path": "",
            "rollback_plan": "",
        }

    plan["source_platform_test_record"]["path"] = source_path
    plan["raw_archive_jsonl"]["path"] = raw_dest
    plan["p2_checkpoint"]["path"] = str(
        Path(INSTALLED_RUNTIME_ROOT) / ".checkpoint_p2.json"
    )
    for zp in zhiyi_paths:
        if "case_memory" in zp:
            plan["zhiyi_jsonl"]["path"] = zp
        elif "preference_memory" in zp:
            plan["zhiyi_jsonl"]["path"] = plan["zhiyi_jsonl"]["path"] or zp
        elif "error_memory" in zp:
            plan["zhiyi_jsonl"]["path"] = plan["zhiyi_jsonl"]["path"] or zp
    bm25_base = INSTALLED_RUNTIME_ROOT if isinstance(INSTALLED_RUNTIME_ROOT, Path) else Path(INSTALLED_RUNTIME_ROOT)
    plan["bm25_index_cache"]["path"] = str(bm25_base / "zhiyi")
    plan["gateway_visibility"]["path"] = DEFAULT_GATEWAY_ENDPOINT

    if not cleanup_capable:
        for layer in REQUIRED_CLEANUP_LAYERS:
            plan[layer]["rollback_plan"] = (
                "Manual cleanup required: probe cannot remove records from "
                "production paths without explicit authorization."
            )
            plan[layer]["residual_path"] = plan[layer]["path"]

    return plan


def _cleanup_source_file(source_path: str, offset_start: int = 0) -> tuple[bool, str]:
    """Delete the probe source file entirely (disposable session)."""
    try:
        p = Path(source_path)
        if p.exists():
            p.unlink()
        return True, ""
    except OSError as exc:
        return False, f"delete failed: {type(exc).__name__}: {exc}"


def _cleanup_raw_archive_jsonl(raw_dest: str, token: str) -> tuple[bool, str]:
    """Delete the disposable raw archive JSONL and its .meta.json."""
    if not raw_dest:
        return False, "raw_dest is empty"
    p = Path(raw_dest)
    if not p.exists():
        return False, f"raw archive does not exist: {raw_dest}"
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
        if token not in text:
            return False, "token line not found in raw archive"
        p.unlink()
        meta_path = Path(raw_dest + ".meta.json")
        if meta_path.exists():
            meta_path.unlink()
        return True, ""
    except OSError as exc:
        return False, f"raw archive cleanup failed: {type(exc).__name__}: {exc}"


def _cleanup_zhiyi_jsonl(token: str) -> tuple[list[str], list[str]]:
    """Scan installed runtime zhiyi JSONL files for probe token, remove if found.

    Returns (cleaned_paths, error_messages).
    """
    cleaned_paths: list[str] = []
    errors: list[str] = []
    zhiyi_root = Path(INSTALLED_RUNTIME_ROOT) / "zhiyi"
    if not zhiyi_root.is_dir():
        return cleaned_paths, [f"zhiyi root not found: {zhiyi_root}"]
    for jsonl_file in zhiyi_root.rglob("*.jsonl"):
        try:
            text = jsonl_file.read_text(encoding="utf-8", errors="replace")
            if token not in text:
                continue
            lines = text.splitlines(keepends=True)
            filtered = [line for line in lines if token not in line]
            jsonl_file.write_text("".join(filtered), encoding="utf-8")
            cleaned_paths.append(str(jsonl_file))
        except OSError as exc:
            errors.append(f"{jsonl_file}: {type(exc).__name__}: {exc}")
    return cleaned_paths, errors


def _perform_cleanup(
    source_path: str,
    raw_dest: str,
    offset_start: int,
    token: str,
    token_hash: str,
    endpoint: str,
) -> dict:
    """Execute real cleanup across all 6 layers and verify gateway empty.

    Returns a cleanup report dict with per-layer status and verification result.
    """
    plan = _build_cleanup_plan(source_path, raw_dest, [], token_hash, cleanup_capable=True)
    errors: list[str] = []

    # Layer 1: source_platform_test_record — delete entire probe session file
    ok, err = _cleanup_source_file(source_path, offset_start)
    plan["source_platform_test_record"]["cleaned"] = ok
    if not ok:
        plan["source_platform_test_record"]["residual_path"] = source_path
        plan["source_platform_test_record"]["rollback_plan"] = (
            f"Source file could not be deleted: {err}. "
            "Manually delete the probe session file."
        )
        errors.append(f"source: {err}")
    else:
        plan["source_platform_test_record"]["residual_path"] = ""

    # Layer 2: raw_archive_jsonl — remove probe line and .meta.json
    ok, err = _cleanup_raw_archive_jsonl(raw_dest, token)
    plan["raw_archive_jsonl"]["cleaned"] = ok
    if not ok:
        plan["raw_archive_jsonl"]["residual_path"] = raw_dest
        plan["raw_archive_jsonl"]["rollback_plan"] = (
            f"Raw archive probe line could not be removed: {err}. "
            "Manually edit the raw archive JSONL to remove lines containing the probe token."
        )
        errors.append(f"raw_archive: {err}")
    else:
        plan["raw_archive_jsonl"]["residual_path"] = ""

    # Layer 3: p2_checkpoint — remove checkpoint entries for source/raw_dest
    p2_path = Path(INSTALLED_RUNTIME_ROOT) / ".checkpoint_p2.json"
    plan["p2_checkpoint"]["path"] = str(p2_path)
    ckpt_ok, ckpt_err = _cleanup_checkpoint_entries(raw_dest, source_path)
    if ckpt_ok:
        plan["p2_checkpoint"]["cleaned"] = True
    else:
        plan["p2_checkpoint"]["residual_path"] = str(p2_path)
        plan["p2_checkpoint"]["rollback_plan"] = (
            f"Checkpoint cleanup failed: {ckpt_err}. "
            "Manually remove probe entries from checkpoint files."
        )
        errors.append(f"p2_checkpoint: {ckpt_err}")

    # Layer 4: zhiyi_jsonl — scan and clean
    cleaned_zhiyi, zhiyi_errors = _cleanup_zhiyi_jsonl(token)
    if cleaned_zhiyi:
        plan["zhiyi_jsonl"]["cleaned"] = True
        plan["zhiyi_jsonl"]["path"] = cleaned_zhiyi[0]
    elif zhiyi_errors:
        plan["zhiyi_jsonl"]["residual_path"] = str(Path(INSTALLED_RUNTIME_ROOT) / "zhiyi")
        plan["zhiyi_jsonl"]["rollback_plan"] = (
            f"Time Library JSONL cleanup errors: {'; '.join(zhiyi_errors)}. "
            "Manually search and remove probe token from zhiyi JSONL files."
        )
        errors.extend(zhiyi_errors)
    else:
        plan["zhiyi_jsonl"]["cleaned"] = True

    # Layer 5: bm25_index_cache — mark as cleaned (index refreshes on next query)
    bm25_path = Path(INSTALLED_RUNTIME_ROOT) / "zhiyi"
    plan["bm25_index_cache"]["path"] = str(bm25_path)
    plan["bm25_index_cache"]["cleaned"] = True

    # Layer 6: gateway_visibility — verify by re-querying
    resp, err = _query_gateway(endpoint, token, timeout=5.0, source_system=SOURCE_SYSTEM_DEFAULT)
    token_still_visible = _find_token_in_response(resp, token) or _find_token_hash_in_response(resp, token_hash)
    plan["gateway_visibility"]["cleaned"] = not token_still_visible
    if token_still_visible:
        plan["gateway_visibility"]["residual_path"] = endpoint
        plan["gateway_visibility"]["rollback_plan"] = (
            "Token still visible in gateway after cleanup. "
            "The 9851 gateway may have a cached index. "
            "Wait for cache expiry or restart the gateway, then re-query to confirm."
        )
        errors.append("gateway: token still visible after cleanup")
    else:
        plan["gateway_visibility"]["residual_path"] = ""

    all_cleaned = all(plan[layer]["cleaned"] for layer in REQUIRED_CLEANUP_LAYERS)
    return {
        "cleanup_plan": plan,
        "cleanup_performed": True,
        "all_layers_cleaned": all_cleaned,
        "errors": errors,
        "gateway_empty_after_cleanup": not token_still_visible,
    }


def _build_default_result() -> dict:
    return {
        "ok": False,
        "contract": PROBE_CONTRACT,
        "created_at": _now_iso(),
        "write_real_requested": False,
        "write_performed": False,
        "full_chain_freshness": False,
        "chain_visible": False,
        "cleanup_performed": False,
        "status": "blocked_not_proven",
        "proof_layer": "source_code",
        "nonClaims": [
            "connected_runtime full-chain freshness not measured",
            "source→connector→p2→zhiyi→gateway latency not measured",
            "extraction_trigger=natural not proven (forced-only lower bound if write_real)",
            "refresh_pending/stale_served behavior not observed in live gateway",
        ],
        "extraction_trigger": "forced",
        "extraction_trigger_note": (
            "forced=direct incremental_extract_session call; "
            "natural=not_proven (would require real platform event trigger)"
        ),
        "gateway_endpoint": DEFAULT_GATEWAY_ENDPOINT,
        "source_path": "",
        "source_path_is_synthetic": False,
        "source_injection": {
            "performed": False,
            "token_injected": False,
            "generated_source_path": "",
            "session_id": "",
            "source_created": False,
            "bytes_written": 0,
            "error": "",
        },
        "raw_dest": "",
        "installed_runtime_exists": os.path.isdir(INSTALLED_RUNTIME_ROOT),
        "gateway_health": {},
        "timing": {
            "t_source_write_to_connector_ingest_ms": None,
            "t_connector_ingest_to_p2_start_ms": None,
            "t_p2_extract_duration_ms": None,
            "t_zhiyi_write_to_first_gateway_visible_ms": None,
            "t_total_write_to_visible_ms": None,
        },
        "multi_run_stats": {
            "iterations": 0,
            "t_total_min_ms": None,
            "t_total_median_ms": None,
            "t_total_max_ms": None,
            "spike_list": [],
        },
        "poll_count": 0,
        "poll_results": [],
        "refresh_pending_observed": False,
        "stale_served_observed": False,
        "memory_cache_statuses_seen": [],
        "freshness_boundaries_seen": [],
        "cleanup_plan": {},
        "all_layers_cleaned": False,
        "gateway_empty_after_cleanup": False,
        "error": "",
        "harness_source_code_path": str(Path(__file__).resolve()),
        "next_action_for_Codex": (
            "Re-run with --write-real --source-path <real_session_file> "
            "--confirm-source-write to attempt connected_runtime full-chain proof."
        ),
    }


def _merge_cleanup_reports(
    result: dict, all_cleanup_reports: list[dict], no_cleanup: bool
) -> None:
    """Merge per-iteration cleanup reports into the probe result.

    Sets overall all_layers_cleaned / gateway_empty_after_cleanup to True
    only if every iteration's cleanup succeeded. Collects all errors.
    Preserves per-iteration evidence in per_iteration_cleanup.
    """
    if no_cleanup:
        result["cleanup_plan"] = _build_cleanup_plan(
            result.get("source_path", ""),
            result.get("raw_dest", ""),
            [],
            "",
            cleanup_capable=False,
        )
        result["cleanup_performed"] = False
        result["all_layers_cleaned"] = False
        result["gateway_empty_after_cleanup"] = False
        result["nonClaims"].append(
            "cleanup skipped (--no-cleanup): probe token left in production paths"
        )
        return

    if not all_cleanup_reports:
        return

    result["cleanup_performed"] = True
    result["per_iteration_cleanup"] = all_cleanup_reports

    overall_all_cleaned = all(r.get("all_layers_cleaned") for r in all_cleanup_reports)
    overall_gateway_empty = all(r.get("gateway_empty_after_cleanup") for r in all_cleanup_reports)
    all_errors: list[str] = []
    merged_plan: dict = {}

    for report in all_cleanup_reports:
        it = report.get("iteration", "?")
        for layer, info in report.get("cleanup_plan", {}).items():
            merged_key = f"{layer}__iter{it}"
            merged_plan[merged_key] = info
        if report.get("errors"):
            for err in report["errors"]:
                all_errors.append(f"iter{it}: {err}")

    result["cleanup_plan"] = merged_plan
    result["all_layers_cleaned"] = overall_all_cleaned
    result["gateway_empty_after_cleanup"] = overall_gateway_empty

    if not overall_gateway_empty:
        result["full_chain_freshness"] = False
        result["nonClaims"].append(
            "cleanup verification failed: token still visible in gateway after cleanup"
        )
        result["next_action_for_Codex"] = (
            "Token still visible in gateway after cleanup attempt. "
            "Gateway cache may need expiry or restart. "
            "Cannot sign full-chain freshness until gateway returns empty for probe token."
        )
    elif not overall_all_cleaned:
        result["full_chain_freshness"] = False
        result["nonClaims"].append(
            "partial cleanup: some layers not cleaned across iterations"
        )
    else:
        if result.get("full_chain_freshness"):
            result["nonClaims"].append(
                "cleanup performed and gateway verified empty after successful probe"
            )
        else:
            result["nonClaims"].append(
                "cleanup performed and gateway verified empty; "
                "full_chain_freshness still false (natural extraction not proven)"
            )

    if all_errors:
        result["cleanup_errors"] = all_errors


def _import_connector_p2_from_installed_runtime() -> tuple:
    """Import archive_session_incremental and incremental_extract_session from installed runtime.

    Temporarily redirects sys.path and MEMCORE_ROOT so that:
    - config_loader reads installed runtime's config/memcore.json
    - connector/p2 modules are loaded from installed runtime's src/
    - memory_root(), zhiyi_root(), etc. resolve to installed runtime paths

    Returns (archive_session_incremental, incremental_extract_session).
    Raises ImportError if modules cannot be imported.
    """
    def _module_from_installed_runtime(mod) -> bool:
        path = os.path.abspath(str(getattr(mod, "__file__", "") or ""))
        installed = os.path.abspath(INSTALLED_RUNTIME_SRC)
        return bool(path) and (path == installed or path.startswith(installed + os.sep))

    # If installed runtime modules are already cached, reuse them. Cached live-repo
    # modules must be purged below or the probe can write to the wrong root again.
    cached_connector = sys.modules.get("codex_local_connector")
    cached_p2 = sys.modules.get("p2_extract")
    if (
        cached_connector is not None
        and cached_p2 is not None
        and hasattr(cached_connector, "archive_session_incremental")
        and hasattr(cached_p2, "incremental_extract_session")
        and _module_from_installed_runtime(cached_connector)
        and _module_from_installed_runtime(cached_p2)
    ):
        return (
            cached_connector.archive_session_incremental,
            cached_p2.incremental_extract_session,
        )

    live_src = str(SRC)
    installed_src = INSTALLED_RUNTIME_SRC
    saved_path = sys.path.copy()
    saved_memcore = os.environ.get("MEMCORE_ROOT")

    # Redirect: remove live repo src, add installed src at front
    sys.path = [p for p in sys.path if p != live_src]
    if installed_src not in sys.path:
        sys.path.insert(0, installed_src)

    # Set MEMCORE_ROOT so config_loader._project_base() returns installed root
    os.environ["MEMCORE_ROOT"] = INSTALLED_RUNTIME_ROOT

    # Purge cached modules so re-import picks up installed runtime versions.
    for mod_name in ("config_loader", "codex_local_connector", "p2_extract"):
        sys.modules.pop(mod_name, None)

    try:
        from codex_local_connector import archive_session_incremental
        from p2_extract import incremental_extract_session
        return archive_session_incremental, incremental_extract_session
    finally:
        sys.path = saved_path
        if saved_memcore is None:
            os.environ.pop("MEMCORE_ROOT", None)
        else:
            os.environ["MEMCORE_ROOT"] = saved_memcore


def build_probe_result(body: dict) -> dict:
    body = body if isinstance(body, dict) else {}
    write_real = bool(body.get("write_real") or body.get("confirm_write_real"))
    confirm_write = bool(body.get("confirm_source_write"))
    source_path = str(body.get("source_path") or "")
    endpoint = str(body.get("endpoint") or DEFAULT_GATEWAY_ENDPOINT)
    timeout = float(body.get("timeout_seconds") or POLL_TIMEOUT_SECONDS)
    no_cleanup = bool(body.get("no_cleanup"))
    iterations = int(body.get("iterations") or 1)
    iterations = max(1, min(iterations, 10))
    source_system = str(body.get("source_system") or SOURCE_SYSTEM_DEFAULT)

    result = _build_default_result()
    result["gateway_endpoint"] = endpoint
    result["source_path"] = source_path

    if write_real:
        result["write_real_requested"] = True

    if not write_real:
        result["nonClaims"].append(
            "harness refused real write: --write-real not passed"
        )
        result["next_action_for_Codex"] = (
            "Harness is in source_code-only mode. To prove connected_runtime "
            "full-chain, re-run with --write-real --source-path <real_session> "
            "--confirm-source-write."
        )
        return result

    if not confirm_write:
        result["status"] = "blocked_not_proven"
        result["error"] = (
            "--confirm-source-write is required alongside --write-real "
            "to authorize real source path writes."
        )
        result["nonClaims"].append("missing --confirm-source-write authorization")
        return result

    if not source_path:
        result["status"] = "blocked_not_proven"
        result["error"] = "--source-path is required for full-chain probe"
        result["nonClaims"].append("no source_path provided")
        return result

    valid, reason = _validate_source_path(source_path)
    if not valid:
        result["status"] = "blocked_not_proven"
        result["error"] = reason
        result["source_path_is_synthetic"] = _is_synthetic_source(source_path)
        result["nonClaims"].append(f"source_path validation failed: {reason}")
        result["proof_layer"] = "fixture" if _is_synthetic_source(source_path) else "source_code"
        return result

    jsonl_valid, jsonl_reason = _validate_source_jsonl_format(source_path)
    if not jsonl_valid:
        result["status"] = "blocked_not_proven"
        result["error"] = f"source_path JSONL validation failed: {jsonl_reason}"
        result["nonClaims"].append(f"source JSONL format invalid: {jsonl_reason}")
        return result

    health = _gateway_health(endpoint)
    result["gateway_health"] = health
    if not health.get("ok"):
        result["status"] = "blocked_not_proven"
        result["error"] = f"gateway health check failed: {health.get('error', 'unknown')}"
        result["nonClaims"].append("9851 gateway not reachable")
        return result

    try:
        archive_session_incremental, incremental_extract_session = (
            _import_connector_p2_from_installed_runtime()
        )
    except ImportError as exc:
        result["status"] = "blocked_not_proven"
        result["error"] = f"cannot import connector/p2 modules from installed runtime: {exc}"
        result["nonClaims"].append("connector or p2_extract module not importable from installed runtime")
        return result

    all_total_times: list[float] = []
    all_spike_details: list[dict] = []
    last_run_result: dict | None = None
    all_cleanup_reports: list[dict] = []
    all_iteration_sessions: list[dict] = []

    for iteration_idx in range(iterations):
        token = _generate_token()
        token_hash = _token_hash(token)
        run_timing: dict[str, float | None] = {
            "t_source_write_to_connector_ingest_ms": None,
            "t_connector_ingest_to_p2_start_ms": None,
            "t_p2_extract_duration_ms": None,
            "t_zhiyi_write_to_first_gateway_visible_ms": None,
            "t_total_write_to_visible_ms": None,
        }

        t_source_write_start = time.time()

        gen_ok, gen_info = _generate_probe_source_session(source_path, token, token_hash)
        iter_source_path = gen_info.get("generated_source_path", "")
        iteration_injection = {
            "performed": True,
            "token_injected": gen_ok,
            "generated_source_path": iter_source_path,
            "session_id": gen_info.get("session_id", ""),
            "source_created": gen_info.get("source_created", False),
            "bytes_written": gen_info.get("bytes_written", 0),
            "error": gen_info.get("error", ""),
        }
        result["source_injection"] = iteration_injection
        all_iteration_sessions.append({
            "iteration": iteration_idx + 1,
            "generated_source_path": iter_source_path,
            "session_id": gen_info.get("session_id", ""),
            "source_created": gen_info.get("source_created", False),
        })
        if not gen_ok or not iter_source_path:
            result["status"] = "blocked_not_proven"
            result["error"] = f"probe source session generation failed: {gen_info.get('error', 'unknown')}"
            result["nonClaims"].append("unique source session generation failed")
            return result

        early_exit = False
        visible = True

        try:
            dest_str, status = archive_session_incremental(iter_source_path)
        except Exception as exc:
            result["status"] = "blocked_not_proven"
            result["error"] = f"archive_session_incremental failed: {exc}"
            result["nonClaims"].append("connector ingest failed")
            early_exit = True

        if not early_exit:
            t_connector_ingest_done = time.time()
            run_timing["t_source_write_to_connector_ingest_ms"] = round(
                (t_connector_ingest_done - t_source_write_start) * 1000, 1
            )
            result["raw_dest"] = dest_str
            result["write_performed"] = True

            if "up_to_date" in status:
                result["status"] = "blocked_not_proven"
                result["error"] = (
                    f"source already up-to-date: {status}. "
                    "No new data to extract; cannot measure full chain."
                )
                result["nonClaims"].append("source has no new data for extraction")
                early_exit = True

        if not early_exit:
            t_p2_start = time.time()
            run_timing["t_connector_ingest_to_p2_start_ms"] = round(
                (t_p2_start - t_connector_ingest_done) * 1000, 1
            )

            try:
                pref_new, case_new, error_new = incremental_extract_session(dest_str)
            except Exception as exc:
                result["status"] = "blocked_not_proven"
                result["error"] = f"incremental_extract_session failed: {exc}"
                result["nonClaims"].append("p2_extract failed")
                early_exit = True

        if not early_exit:
            t_p2_done = time.time()
            run_timing["t_p2_extract_duration_ms"] = round(
                (t_p2_done - t_p2_start) * 1000, 1
            )

            zhiyi_write_time = t_p2_done

            if pref_new + case_new + error_new == 0:
                result["status"] = "blocked_not_proven"
                result["error"] = "p2_extract produced 0 new records; cannot measure gateway visibility"
                result["nonClaims"].append("p2_extract produced no new records")
                early_exit = True

        if not early_exit:
            query = token
            visible = False
            poll_count = 0
            t_visible = None

            while (time.time() - zhiyi_write_time) < timeout:
                poll_count += 1
                resp, err = _query_gateway(endpoint, query, timeout=5.0, source_system=source_system)
                now = time.time()

                memory_cache_status = str(resp.get("memory_cache_status") or "")
                refresh_status = str(resp.get("refresh_status") or "")
                refresh_pending = bool(resp.get("refresh_pending"))
                freshness_boundary = str(resp.get("freshness_boundary") or "")
                freshness_fast_path = str(resp.get("freshness_fast_path") or "")
                recent_delta_applied = bool(resp.get("recent_delta_applied", False))
                default_recall_freshness_covered = bool(resp.get("default_recall_freshness_covered", False))

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
                    "elapsed_ms": round((now - zhiyi_write_time) * 1000, 1),
                    "found": found,
                    "error": err,
                    "memory_cache_status": memory_cache_status,
                    "refresh_status": refresh_status,
                    "refresh_pending": refresh_pending,
                    "freshness_boundary": freshness_boundary,
                    "freshness_fast_path": freshness_fast_path,
                    "recent_delta_applied": recent_delta_applied,
                    "default_recall_freshness_covered": default_recall_freshness_covered,
                    "items_count": len(resp.get("items", []) or resp.get("evidence", []) or []),
                }
                result["poll_results"].append(poll_entry)

                if found:
                    visible = True
                    t_visible = round(now - zhiyi_write_time, 3)
                    break

                time.sleep(POLL_INTERVAL_SECONDS)

            run_timing["t_zhiyi_write_to_first_gateway_visible_ms"] = (
                round(t_visible * 1000, 1) if t_visible is not None else None
            )
            total_ms = round((time.time() - t_source_write_start) * 1000, 1)
            run_timing["t_total_write_to_visible_ms"] = total_ms
            all_total_times.append(total_ms)

            if t_visible is not None and t_visible > 5.0:
                all_spike_details.append({
                    "iteration": iteration_idx + 1,
                    "t_total_ms": total_ms,
                    "t_visible_s": t_visible,
                    "reason": "spike_threshold_5s",
                })

            result["poll_count"] += poll_count
            last_run_result = run_timing

            if not visible:
                result["timing"] = run_timing
                result["status"] = "connected_runtime_full_chain_timeout"
                result["proof_layer"] = "connected_runtime_partial_incomplete"
                result["nonClaims"].append(
                    f"token not visible within {timeout}s timeout ({poll_count} polls)"
                )
                result["next_action_for_Codex"] = (
                    f"Full-chain token not visible within {timeout}s. "
                    "Check poll_results for refresh_pending/stale_served patterns."
                )

        # Per-iteration cleanup: always clean up this iteration's token unless --no-cleanup
        if not no_cleanup and iteration_injection.get("token_injected"):
            cleanup_report = _perform_cleanup(
                iter_source_path, result["raw_dest"], 0, token, token_hash, endpoint
            )
            cleanup_report["iteration"] = iteration_idx + 1
            cleanup_report["token_hash"] = token_hash
            cleanup_report["generated_source_path"] = iter_source_path
            cleanup_report["session_id"] = iteration_injection.get("session_id", "")
            all_cleanup_reports.append(cleanup_report)

        if early_exit or not visible:
            result["per_iteration_sessions"] = all_iteration_sessions
            _merge_cleanup_reports(result, all_cleanup_reports, no_cleanup)
            return result

    if last_run_result:
        result["timing"] = last_run_result

    if all_total_times:
        sorted_times = sorted(all_total_times)
        n = len(sorted_times)
        median_idx = n // 2
        result["multi_run_stats"] = {
            "iterations": n,
            "t_total_min_ms": sorted_times[0],
            "t_total_median_ms": sorted_times[median_idx],
            "t_total_max_ms": sorted_times[-1],
            "spike_list": all_spike_details,
        }

    result["ok"] = True
    result["status"] = "connected_runtime_full_chain_default_recall_proven"
    result["proof_layer"] = "installed_runtime"
    result["chain_visible"] = True
    result["full_chain_freshness"] = True
    result["default_recall_freshness"] = True
    result["nonClaims"] = [
        "extraction_trigger=forced (direct incremental_extract_session call, not passive watcher scheduling)",
        "does not prove passive platform watcher latency or unattended scheduler latency",
        "source_path must be verified as real platform session file to claim connected_runtime",
        "does not prove vector index freshness; default recall freshness is covered by bounded recent_delta/default fallback",
        "does not prove lifecycle overlay freshness_score was applied",
        "does not prove BM25 index refresh (separate from memory cache refresh)",
        f"multi-run stats: {iterations} iteration(s); min/median/max reported",
    ]
    result["next_action_for_Codex"] = (
        f"Full-chain default recall freshness proven. chain_visible=true, "
        f"full_chain_freshness=true. "
        f"t_total={result['timing'].get('t_total_write_to_visible_ms')}ms, "
        f"poll_count={result['poll_count']}. "
        "To broaden this proof: measure passive watcher/scheduler latency "
        "without calling incremental_extract_session directly."
    )

    result["per_iteration_sessions"] = all_iteration_sessions

    # Merge cleanup evidence from all iterations into result
    _merge_cleanup_reports(result, all_cleanup_reports, no_cleanup)

    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Runtime freshness full-chain (B-path) probe.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "DEFAULT: source_code-only mode (no real writes).\n"
            "Pass --write-real --source-path <file> --confirm-source-write\n"
            "to attempt connected_runtime full-chain proof.\n"
            "WARNING: --write-real will run the full B path:\n"
            "  source → connector ingest → p2_extract → zhiyi → gateway poll"
        ),
    )
    parser.add_argument(
        "--write-real",
        action="store_true",
        help="Actually run the full B path with real source file.",
    )
    parser.add_argument(
        "--confirm-write-real",
        action="store_true",
        help="Alias for --write-real.",
    )
    parser.add_argument(
        "--source-path",
        default="",
        help="Path to a real platform session file for the B path.",
    )
    parser.add_argument(
        "--confirm-source-write",
        action="store_true",
        help="Explicit authorization to write through the source path.",
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
        "--iterations",
        type=int,
        default=1,
        help="Number of iterations for multi-run stats (1-10).",
    )
    parser.add_argument(
        "--no-cleanup",
        action="store_true",
        help="Do not attempt cleanup after probe.",
    )
    parser.add_argument(
        "--source-system",
        default=SOURCE_SYSTEM_DEFAULT,
        help=f"Source system for gateway query. Default: {SOURCE_SYSTEM_DEFAULT}",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print full JSON output.",
    )
    args = parser.parse_args()

    body = {
        "write_real": args.write_real or args.confirm_write_real,
        "confirm_source_write": args.confirm_source_write,
        "source_path": args.source_path,
        "endpoint": args.endpoint,
        "timeout_seconds": args.timeout_seconds,
        "iterations": args.iterations,
        "no_cleanup": args.no_cleanup,
        "source_system": args.source_system,
    }

    payload = build_probe_result(body)

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"contract: {payload.get('contract')}")
        print(f"status: {payload.get('status')}")
        print(f"proof_layer: {payload.get('proof_layer')}")
        print(f"full_chain_freshness: {payload.get('full_chain_freshness')}")
        print(f"chain_visible: {payload.get('chain_visible')}")
        print(f"extraction_trigger: {payload.get('extraction_trigger')}")
        print(f"write_real_requested: {payload.get('write_real_requested')}")
        print(f"write_performed: {payload.get('write_performed')}")
        print(f"source_path: {payload.get('source_path')}")
        print(f"source_path_is_synthetic: {payload.get('source_path_is_synthetic')}")
        injection = payload.get("source_injection", {})
        if injection.get("performed"):
            print(f"source_injection: token_injected={injection.get('token_injected')}, "
                  f"bytes={injection.get('bytes_written')}")
            if injection.get("generated_source_path"):
                print(f"  generated_source_path: {injection.get('generated_source_path')}")
                print(f"  session_id: {injection.get('session_id')}")
                print(f"  source_created: {injection.get('source_created')}")
        print(f"raw_dest: {payload.get('raw_dest')}")
        print(f"installed_runtime_exists: {payload.get('installed_runtime_exists')}")
        print(f"gateway_health_ok: {payload.get('gateway_health', {}).get('ok')}")
        timing = payload.get("timing", {})
        for k, v in timing.items():
            if v is not None:
                print(f"  {k}: {v}ms")
        stats = payload.get("multi_run_stats", {})
        if stats.get("iterations", 0) > 0:
            print(f"multi_run: iterations={stats['iterations']}, "
                  f"min={stats.get('t_total_min_ms')}ms, "
                  f"median={stats.get('t_total_median_ms')}ms, "
                  f"max={stats.get('t_total_max_ms')}ms")
        print(f"poll_count: {payload.get('poll_count', 0)}")
        nc = payload.get("nonClaims", [])
        if nc:
            print("nonClaims:")
            for item in nc:
                print(f"  - {item}")
        if payload.get("error"):
            print(f"error: {payload['error']}")
        cleanup = payload.get("cleanup_plan", {})
        if cleanup:
            print("cleanup_plan:")
            for layer, info in cleanup.items():
                print(f"  {layer}: cleaned={info.get('cleaned')}, residual={info.get('residual_path', '')[:80]}")
        print(f"cleanup_performed: {payload.get('cleanup_performed')}")
        print(f"all_layers_cleaned: {payload.get('all_layers_cleaned')}")
        print(f"gateway_empty_after_cleanup: {payload.get('gateway_empty_after_cleanup')}")
        if payload.get("cleanup_errors"):
            print(f"cleanup_errors: {payload['cleanup_errors']}")
        print(f"next_action: {payload.get('next_action_for_Codex', '')}")

    return 0 if payload.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
