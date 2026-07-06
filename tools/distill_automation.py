#!/usr/bin/env python3
"""CLI for Time Library automatic distillation coverage plumbing."""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import distill_automation as automation


def _load_json(path: str) -> dict:
    if not path:
        return {}
    return json.loads(Path(path).expanduser().read_text(encoding="utf-8"))


def _load_distiller(*, callable_spec: str = "", fixture_candidate_json: str = ""):
    if callable_spec and fixture_candidate_json:
        raise ValueError("choose either --distiller-callable or --fixture-candidate-json, not both")
    if fixture_candidate_json:
        fixture = _load_json(fixture_candidate_json)

        def fixture_distiller(session, model):
            return {"candidates": [dict(fixture)]}

        return fixture_distiller
    if not callable_spec:
        return None
    module_name, sep, attr_path = callable_spec.partition(":")
    if not sep or not module_name or not attr_path:
        raise ValueError("--distiller-callable must use module:function")
    module = importlib.import_module(module_name)
    target = module
    for part in attr_path.split("."):
        target = getattr(target, part)
    if not callable(target):
        raise ValueError(f"distiller callable is not callable: {callable_spec}")
    return target


def _print_json(obj: dict) -> int:
    print(json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if obj.get("ok") is not False else 1


def _default_records_db(root: Path) -> Path:
    return root / "output" / "records" / "records.db"


def _default_ledger(root: Path) -> Path:
    return root / "output" / "distill_coverage" / "coverage.jsonl"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default="", help="Memcore root; defaults to repo root for offline/source runs")
    parser.add_argument("--records-db", default="", help="Canonical records.db path")
    parser.add_argument("--ledger", default="", help="Coverage ledger JSONL path")
    sub = parser.add_subparsers(dest="cmd", required=True)

    reconcile = sub.add_parser("reconcile", help="Sync coverage ledger from canonical_sessions")
    reconcile.add_argument("--source-system", action="append", default=[])

    run_window = sub.add_parser("run-window", help="Run one bounded distillation window")
    run_window.add_argument("--source-system", action="append", default=[])
    run_window.add_argument("--max-sessions", type=int, default=20)
    run_window.add_argument("--provider", default="")
    run_window.add_argument("--model", default="")
    run_window.add_argument("--api-key", default="")
    run_window.add_argument("--target-shape", default="", help="Optional shape-specific pass, e.g. toolbook")
    run_window.add_argument("--distiller-callable", default="", help="Importable module:function distiller entry")
    run_window.add_argument("--fixture-candidate-json", default="", help="Offline-test-only candidate fixture")
    run_window.add_argument("--self-check-json", default="", help="Post-window self-check payload JSON")

    schedule = sub.add_parser("schedule-plan", help="Emit nightly/manual schedule decision")
    schedule.add_argument("--manual", action="store_true")
    schedule.add_argument("--now", default="", help="ISO timestamp for deterministic tests")

    registration = sub.add_parser("scheduler-registration-plan", help="Emit plan-only scheduler registration contract")
    registration.add_argument("--source-system", action="append", default=[])
    registration.add_argument("--distiller-callable", default="")
    registration.add_argument("--self-check-json", default="")

    args = parser.parse_args(argv)
    root = Path(args.root).expanduser() if args.root else ROOT
    records_db = Path(args.records_db).expanduser() if args.records_db else _default_records_db(root)
    ledger = Path(args.ledger).expanduser() if args.ledger else _default_ledger(root)

    if args.cmd == "reconcile":
        return _print_json(
            automation.reconcile_coverage_ledger(
                records_db_path=records_db,
                ledger_path=ledger,
                source_systems=args.source_system,
            )
        )
    if args.cmd == "run-window":
        model_config = {
            "provider": args.provider,
            "model": args.model,
            "api_key": args.api_key,
            "target_shape": args.target_shape,
        }
        try:
            distiller = _load_distiller(
                callable_spec=args.distiller_callable,
                fixture_candidate_json=args.fixture_candidate_json,
            )
            self_check_payload = _load_json(args.self_check_json) if args.self_check_json else None
        except Exception as exc:
            return _print_json({"ok": False, "status": "invalid_cli_configuration", "error": f"{type(exc).__name__}:{exc}"})
        return _print_json(
            automation.run_distill_window(
                records_db_path=records_db,
                ledger_path=ledger,
                candidate_root=root,
                model_config=model_config,
                distill_session=distiller,
                source_systems=args.source_system,
                max_sessions=args.max_sessions,
                self_check_inputs=self_check_payload,
                target_shape=args.target_shape,
            )
        )
    if args.cmd == "schedule-plan":
        now = datetime.fromisoformat(args.now) if args.now else None
        return _print_json(automation.build_nightly_schedule_plan(now=now, manual=args.manual))
    if args.cmd == "scheduler-registration-plan":
        return _print_json(
            automation.build_scheduler_registration_plan(
                {
                    "repo_root": str(root),
                    "source_systems": args.source_system,
                    "distiller_callable": args.distiller_callable,
                    "self_check_json": args.self_check_json,
                }
            )
        )
    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
