#!/usr/bin/env python3
"""Run one installed automatic distillation window with live delivery self-check."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import distill_automation as automation
from src.distill_runtime_adapter import distill_session


RUNTIME_WINDOW_CONTRACT = "time_library_distill_runtime_window.v1"


def _now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _hydrate_minimax_api_key(api_key_env: str) -> dict[str, Any]:
    """Populate the process env from mmx CLI auth without printing the key."""

    target = (api_key_env or "MINIMAX_API_KEY").strip()
    if str(os.environ.get(target) or "").strip():
        return {"api_key_env": target, "api_key_present": True, "source": "environment", "loaded_from_mmx": False}
    config = _read_json(Path.home() / ".mmx" / "config.json")
    key = str(config.get("api_key") or config.get("minimax_api_key") or "").strip()
    if key.lower() in {"sk-xxxxx", "placeholder", "changeme"}:
        key = ""
    if key and target in {"MINIMAX_API_KEY", "MINIMAX_CN_API_KEY", "MEMCORE_ZHIYI_API_KEY"}:
        os.environ[target] = key
        if target != "MINIMAX_API_KEY" and not os.environ.get("MINIMAX_API_KEY"):
            os.environ["MINIMAX_API_KEY"] = key
        return {"api_key_env": target, "api_key_present": True, "source": "mmx_config", "loaded_from_mmx": True}
    return {"api_key_env": target, "api_key_present": False, "source": "missing", "loaded_from_mmx": False}


def _http_json(url: str, *, timeout: int = 20) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(url, timeout=max(1, int(timeout))) as response:
            data = json.loads(response.read().decode("utf-8"))
        return data if isinstance(data, dict) else {"ok": False, "error": "non_object_response"}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}:{exc}"}


def _collect_ids_from_projection(value: Any, out: set[str]) -> None:
    if isinstance(value, str):
        if value.startswith(("ZX-", "WB-", "PH-")):
            out.add(value)
    elif isinstance(value, dict):
        for key, item in value.items():
            if key in {"library_id", "catalog_id", "record_id"} and isinstance(item, str) and item.startswith(("ZX-", "WB-", "PH-")):
                out.add(item)
            else:
                _collect_ids_from_projection(item, out)
    elif isinstance(value, list):
        for item in value:
            _collect_ids_from_projection(item, out)


def collect_live_self_check(result: dict[str, Any], *, port: int, char_budget: int = 1500) -> dict[str, Any]:
    base = f"http://127.0.0.1:{int(port)}"
    catalog = _http_json(f"{base}/catalog-inject?include_raw_index=1")
    visible: set[str] = set()
    for entry in catalog.get("catalog") or []:
        if isinstance(entry, dict) and str(entry.get("library_id") or "").startswith("ZX-"):
            visible.add(str(entry["library_id"]))
    _collect_ids_from_projection(catalog.get("reading_area_projection"), visible)

    borrow_results: dict[str, dict[str, Any]] = {}
    produced_ids = []
    for library_id in result.get("produced_library_ids") or []:
        produced_ids.append(str(library_id))
    for library_id in result.get("produced_project_history_ids") or []:
        produced_ids.append(str(library_id))
    for library_id in sorted(set(item for item in produced_ids if item)):
        query = urllib.parse.urlencode({"library_id": str(library_id), "include_raw_index": "1"})
        borrow_results[str(library_id)] = _http_json(f"{base}/catalog-card?{query}")

    return {
        "catalog_library_ids": sorted(visible),
        "project_history_record_ids": sorted(item for item in visible if item.startswith("PH-")),
        "project_page_history_ids": sorted(item for item in visible if item.startswith("PH-")),
        "borrow_results": borrow_results,
        "instructions_char_count": int(catalog.get("instructions_char_count") or 0),
        "contains_body_markers": bool(catalog.get("contains_body_markers") or catalog.get("reading_area_contains_body_markers")),
        "char_budget": int(char_budget),
        "catalog_fetch_ok": bool(catalog.get("ok")),
        "catalog_entry_count": int(catalog.get("catalog_entry_count") or 0),
        "startup_instruction_mode": catalog.get("startup_instruction_mode", ""),
    }


def _status_counts(ledger_path: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    if not ledger_path.is_file():
        return counts
    for line in ledger_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        status = str(row.get("status") or "unknown")
        counts[status] = counts.get(status, 0) + 1
    return counts


def _write_receipt(root: Path, payload: dict[str, Any], receipt_dir: str = "") -> Path:
    directory = Path(receipt_dir).expanduser() if receipt_dir else root / "output" / "distill_coverage" / "window_receipts"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"distill-window-{_now_stamp()}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("--records-db", default="")
    parser.add_argument("--ledger", default="")
    parser.add_argument("--source-system", action="append", default=[])
    parser.add_argument("--reading-area-registry", default="")
    parser.add_argument("--mimocode-root", default="")
    parser.add_argument("--project-id", action="append", default=[])
    parser.add_argument("--series-id", action="append", default=[])
    parser.add_argument("--max-sessions", type=int, default=20)
    parser.add_argument("--provider", default="minimax")
    parser.add_argument("--model", default="MiniMax-M3")
    parser.add_argument("--api-key-env", default="MINIMAX_API_KEY")
    parser.add_argument("--target-shape", default="", help="Optional shape-specific pass, e.g. toolbook")
    parser.add_argument("--port", type=int, default=9840)
    parser.add_argument("--char-budget", type=int, default=1500)
    parser.add_argument("--receipt-dir", default="")
    args = parser.parse_args(argv)

    root = Path(args.root).expanduser()
    records_db = Path(args.records_db).expanduser() if args.records_db else root / "output" / "records" / "records.db"
    ledger = Path(args.ledger).expanduser() if args.ledger else root / "output" / "distill_coverage" / "coverage.jsonl"
    os.environ["TIME_LIBRARY_DISTILL_ROOT"] = str(root)
    os.environ["TIME_LIBRARY_DISTILL_RECORDS_DB"] = str(records_db)
    os.environ["TIME_LIBRARY_DISTILL_PROVIDER"] = args.provider
    os.environ["TIME_LIBRARY_DISTILL_MODEL"] = args.model
    os.environ["TIME_LIBRARY_DISTILL_API_KEY_ENV"] = args.api_key_env
    if args.target_shape:
        os.environ["TIME_LIBRARY_DISTILL_TARGET_SHAPE"] = args.target_shape
    if args.provider == "minimax":
        os.environ.setdefault("MEMCORE_ZHIYI_PROVIDER", "minimax")
        os.environ.setdefault("MEMCORE_ZHIYI_MODEL", args.model)
        os.environ.setdefault("MINIMAX_MODEL", args.model)
    api_key_status = _hydrate_minimax_api_key(args.api_key_env) if args.provider == "minimax" else {
        "api_key_env": args.api_key_env,
        "api_key_present": bool(os.environ.get(args.api_key_env)),
        "source": "environment",
        "loaded_from_mmx": False,
    }

    before = _status_counts(ledger)
    result = automation.run_distill_window(
        records_db_path=records_db,
        ledger_path=ledger,
        candidate_root=root,
        model_config={"provider": args.provider, "model": args.model, "api_key_env": args.api_key_env, "target_shape": args.target_shape},
        distill_session=distill_session,
        source_systems=args.source_system,
        reading_area_registry_path=args.reading_area_registry or None,
        mimocode_root=args.mimocode_root or None,
        project_ids=args.project_id,
        series_ids=args.series_id,
        max_sessions=args.max_sessions,
        self_check_inputs=lambda window: collect_live_self_check(window, port=args.port, char_budget=args.char_budget),
        target_shape=args.target_shape,
    )
    after = _status_counts(ledger)
    payload = {
        "ok": bool(result.get("ok")),
        "contract": RUNTIME_WINDOW_CONTRACT,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "root": str(root),
        "records_db": str(records_db),
        "ledger": str(ledger),
        "source_systems": args.source_system,
        "max_sessions": args.max_sessions,
        "model": {"provider": args.provider, "model": args.model, **api_key_status},
        "target_shape": args.target_shape,
        "ledger_status_counts_before": before,
        "ledger_status_counts_after": after,
        "window_result": result,
        "non_claims": [
            "first_window_only_not_full_coverage",
            "token_usage_is_model_attempt_count_not_provider_billing_meter",
            "cross_machine_not_tested",
            "freshness_vector_fts5_release_auto_connect_not_touched",
        ],
    }
    receipt = _write_receipt(root, payload, receipt_dir=args.receipt_dir)
    payload["receipt_path"] = str(receipt)
    receipt.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
