#!/usr/bin/env python3
"""Read-only multi-host runner for core-record reliability audits."""

from __future__ import annotations

import argparse
import base64
import json
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = "memcore_core_record_multi_host_audit.v1"
AUDIENCE = "agent_maintainer_runbook_not_product_ui"
DEFAULT_REMOTE_HOSTS = ("windows191", "windows123")


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _repo_ssh_config() -> Path:
    parent = ROOT.parent
    candidate = parent / ".ssh" / "config"
    return candidate if candidate.exists() else Path(".ssh/config")


def _default_install_root() -> Path:
    home = Path.home()
    system = platform.system().lower()
    if system == "windows":
        base = Path(os.environ.get("LOCALAPPDATA") or home / "AppData" / "Local")
        return base / "memcore-cloud"
    if system == "darwin":
        return home / "Library" / "Application Support" / "memcore-cloud"
    return home / ".local" / "share" / "memcore-cloud"


def default_snapshot_dir() -> Path:
    return _default_install_root() / "logs" / "agent_self_checks" / "core_record_multi_host"


def _safe_snapshot_stamp(value: str) -> str:
    stamp = (value or _utc_now()).strip().replace(":", "-")
    return "".join(ch for ch in stamp if ch.isalnum() or ch in {"-", "_", "T", "Z"})


def save_snapshot(report: dict[str, Any], *, snapshot_dir: Path | None = None) -> Path:
    target_dir = snapshot_dir or default_snapshot_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    stamp = _safe_snapshot_stamp(str(report.get("generated_at") or ""))
    path = target_dir / f"{stamp}-core-record-multi-host.json"
    report["read_only"] = False
    report["write_performed"] = True
    report["snapshot_write_performed"] = True
    report["snapshot"] = {
        "saved": True,
        "scope": "local_agent_runbook_only",
        "path": str(path),
    }
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def latest_snapshot_path(*, snapshot_dir: Path | None = None) -> Path | None:
    target_dir = snapshot_dir or default_snapshot_dir()
    if not target_dir.exists():
        return None
    candidates = sorted(target_dir.glob("*-core-record-multi-host.json"))
    return candidates[-1] if candidates else None


def load_latest_snapshot(*, snapshot_dir: Path | None = None) -> tuple[dict[str, Any] | None, Path | None]:
    path = latest_snapshot_path(snapshot_dir=snapshot_dir)
    if path is None:
        return None, None
    return json.loads(path.read_text(encoding="utf-8")), path


def _summary_value(report: dict[str, Any], key: str) -> int:
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    try:
        return int(summary.get(key) or 0)
    except Exception:
        return 0


def _hosts_by_name(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    hosts = report.get("hosts") if isinstance(report.get("hosts"), list) else []
    return {
        str(item.get("host")): item
        for item in hosts
        if isinstance(item, dict) and str(item.get("host") or "")
    }


def compare_with_baseline(current: dict[str, Any], baseline: dict[str, Any] | None) -> dict[str, Any]:
    if baseline is None:
        return {
            "baseline_available": False,
            "status": "baseline_missing",
            "issue_count": 0,
            "issues": [],
            "summary_delta": {},
            "host_deltas": [],
        }

    issue_keys = (
        "raw_attention_count",
        "backfill_recommended_count",
        "lost_source_count",
        "lost_raw_count",
    )
    summary_delta = {
        key: _summary_value(current, key) - _summary_value(baseline, key)
        for key in ("record_count", *issue_keys)
    }
    issues: list[str] = []
    for key in issue_keys:
        if summary_delta[key] > 0:
            issues.append(f"{key}_increased")

    current_hosts = _hosts_by_name(current)
    baseline_hosts = _hosts_by_name(baseline)
    host_deltas: list[dict[str, Any]] = []
    for host in sorted(set(current_hosts) | set(baseline_hosts)):
        now = current_hosts.get(host, {})
        before = baseline_hosts.get(host, {})
        now_summary = now.get("summary") if isinstance(now.get("summary"), dict) else {}
        before_summary = before.get("summary") if isinstance(before.get("summary"), dict) else {}
        delta = {
            "host": host,
            "status_before": before.get("audit_status", ""),
            "status_now": now.get("audit_status", ""),
            "record_count_delta": int(now_summary.get("record_count") or 0) - int(before_summary.get("record_count") or 0),
            "raw_attention_delta": int(now_summary.get("raw_attention_count") or 0) - int(before_summary.get("raw_attention_count") or 0),
            "backfill_delta": int(now_summary.get("backfill_recommended_count") or 0) - int(before_summary.get("backfill_recommended_count") or 0),
            "lost_source_delta": int(now_summary.get("lost_source_count") or 0) - int(before_summary.get("lost_source_count") or 0),
            "lost_raw_delta": int(now_summary.get("lost_raw_count") or 0) - int(before_summary.get("lost_raw_count") or 0),
        }
        if not before:
            delta["status"] = "new_host"
        elif not now:
            delta["status"] = "missing_host"
            issues.append(f"{host}_missing")
        elif any(delta[key] > 0 for key in ("raw_attention_delta", "backfill_delta", "lost_source_delta", "lost_raw_delta")):
            delta["status"] = "regressed"
            issues.append(f"{host}_record_issue_increased")
        else:
            delta["status"] = "ok"
        host_deltas.append(delta)

    unique_issues = sorted(set(issues))
    return {
        "baseline_available": True,
        "status": "regressed" if unique_issues else "ok",
        "issue_count": len(unique_issues),
        "issues": unique_issues,
        "summary_delta": summary_delta,
        "host_deltas": host_deltas,
    }


def _first_json_object(text: str) -> dict[str, Any]:
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            value, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise ValueError("no JSON object found in command output")


def _host_summary(host: str, report: dict[str, Any], *, transport: str) -> dict[str, Any]:
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    runtime = report.get("runtime") if isinstance(report.get("runtime"), dict) else {}
    source_statuses = report.get("source_statuses") if isinstance(report.get("source_statuses"), list) else []
    return {
        "host": host,
        "transport": transport,
        "ok": bool(report.get("ok")),
        "audit_status": report.get("audit_status", ""),
        "record_chain_proven": bool(report.get("record_chain_proven")),
        "runtime_root": runtime.get("runtime_root", ""),
        "runtime_root_source": runtime.get("runtime_root_source", ""),
        "ignored_invalid_env_root": runtime.get("ignored_invalid_env_root", ""),
        "summary": {
            "record_count": int(summary.get("record_count") or 0),
            "record_guarded_count": int(summary.get("record_guarded_count") or 0),
            "raw_attention_count": int(summary.get("raw_attention_count") or 0),
            "backfill_recommended_count": int(summary.get("backfill_recommended_count") or 0),
            "lost_source_count": int(summary.get("lost_source_count") or 0),
            "lost_raw_count": int(summary.get("lost_raw_count") or 0),
            "corrupt_record_count": int(summary.get("corrupt_record_count") or 0),
            "raw_catching_up_count": int(summary.get("raw_catching_up_count") or 0),
            "max_raw_lag_milliseconds": int(summary.get("max_raw_lag_milliseconds") or 0),
        },
        "source_statuses": [
            {
                "source_system": item.get("source_system", ""),
                "state": item.get("state", ""),
                "record_count": int(item.get("record_count") or 0),
                "guarded_record_count": int(item.get("guarded_record_count") or 0),
                "attention_record_count": int(item.get("attention_record_count") or 0),
            }
            for item in source_statuses
            if isinstance(item, dict)
        ],
    }


def summarize_hosts(hosts: list[dict[str, Any]]) -> dict[str, Any]:
    issue_hosts = [
        item["host"]
        for item in hosts
        if not item.get("ok")
        or item.get("audit_status") in {"attention", "needs_backfill"}
        or item.get("summary", {}).get("raw_attention_count")
        or item.get("summary", {}).get("backfill_recommended_count")
        or item.get("summary", {}).get("lost_source_count")
        or item.get("summary", {}).get("lost_raw_count")
    ]
    observe_hosts = [
        item["host"]
        for item in hosts
        if item.get("audit_status") == "observe" and item["host"] not in issue_hosts
    ]
    return {
        "host_count": len(hosts),
        "ok_host_count": len([item for item in hosts if item.get("ok")]),
        "pass_host_count": len([item for item in hosts if item.get("audit_status") == "pass"]),
        "observe_host_count": len(observe_hosts),
        "issue_host_count": len(issue_hosts),
        "issue_hosts": issue_hosts,
        "observe_hosts": observe_hosts,
        "record_count": sum(item.get("summary", {}).get("record_count", 0) for item in hosts),
        "raw_attention_count": sum(item.get("summary", {}).get("raw_attention_count", 0) for item in hosts),
        "backfill_recommended_count": sum(
            item.get("summary", {}).get("backfill_recommended_count", 0)
            for item in hosts
        ),
        "lost_source_count": sum(item.get("summary", {}).get("lost_source_count", 0) for item in hosts),
        "lost_raw_count": sum(item.get("summary", {}).get("lost_raw_count", 0) for item in hosts),
    }


def _local_command(limit: int, mode: str) -> list[str]:
    return [
        sys.executable,
        str(ROOT / "tools" / "core_record_reliability_audit.py"),
        "--format",
        "json",
        "--mode",
        mode,
        "--limit",
        str(limit),
    ]


def _remote_powershell(limit: int, mode: str) -> str:
    return rf"""
$OutputEncoding = [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$root = Join-Path $env:LOCALAPPDATA 'memcore-cloud'
$py = Join-Path $root '.venv\Scripts\python.exe'
if (!(Test-Path $py)) {{ $py = (Get-Command python -ErrorAction Stop).Source }}
Set-Location $root
& $py tools\core_record_reliability_audit.py --format json --mode {mode} --limit {int(limit)}
"""


def _remote_command(host: str, ssh_config: Path, limit: int, mode: str) -> list[str]:
    encoded = base64.b64encode(_remote_powershell(limit, mode).encode("utf-16le")).decode("ascii")
    return [
        "ssh",
        "-F",
        str(ssh_config),
        host,
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-EncodedCommand",
        encoded,
    ]


def _run_json_command(cmd: list[str], *, cwd: Path, timeout: int) -> tuple[dict[str, Any], str, str]:
    proc = subprocess.run(
        cmd,
        cwd=str(cwd),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        errors="replace",
        timeout=timeout,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"command exited {proc.returncode}: {proc.stderr.strip() or proc.stdout.strip()}")
    return _first_json_object(proc.stdout), proc.stdout, proc.stderr


def run_local_host(*, limit: int, mode: str, timeout: int) -> dict[str, Any]:
    report, _, _ = _run_json_command(_local_command(limit, mode), cwd=ROOT, timeout=timeout)
    return _host_summary("local", report, transport="local")


def run_remote_host(host: str, *, ssh_config: Path, limit: int, mode: str, timeout: int) -> dict[str, Any]:
    report, _, stderr = _run_json_command(
        _remote_command(host, ssh_config, limit, mode),
        cwd=ROOT.parent,
        timeout=timeout,
    )
    item = _host_summary(host, report, transport=f"ssh:{ssh_config}")
    if stderr.strip():
        item["stderr_note"] = stderr.strip().splitlines()[:3]
    return item


def build_multi_host_audit(
    *,
    include_local: bool = True,
    remote_hosts: tuple[str, ...] = DEFAULT_REMOTE_HOSTS,
    ssh_config: Path | None = None,
    limit: int = 80,
    mode: str = "fast",
    timeout: int = 60,
) -> dict[str, Any]:
    hosts: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    if include_local:
        try:
            hosts.append(run_local_host(limit=limit, mode=mode, timeout=timeout))
        except Exception as exc:
            errors.append({"host": "local", "error": str(exc)})
    resolved_ssh_config = ssh_config or _repo_ssh_config()
    for host in remote_hosts:
        try:
            hosts.append(
                run_remote_host(
                    host,
                    ssh_config=resolved_ssh_config,
                    limit=limit,
                    mode=mode,
                    timeout=timeout,
                )
            )
        except Exception as exc:
            errors.append({"host": host, "error": str(exc)})
    summary = summarize_hosts(hosts)
    ok = not errors and summary["issue_host_count"] == 0
    return {
        "ok": ok,
        "contract": CONTRACT,
        "audience": AUDIENCE,
        "generated_at": _utc_now(),
        "read_only": True,
        "write_performed": False,
        "snapshot_write_performed": False,
        "service_call_performed": False,
        "product_ui_write_performed": False,
        "public_docs_write_performed": False,
        "mode": mode,
        "limit": limit,
        "ssh_config": str(resolved_ssh_config),
        "summary": summary,
        "hosts": hosts,
        "errors": errors,
        "snapshot": {"saved": False},
        "comparison": {"performed": False},
        "notes": [
            "Agent-maintainer runbook only; this is not a user feature or product UI.",
            "Read-only patrol; it does not restart services or mutate platform config.",
            "Snapshot saving is disabled by default and only writes a local agent runbook JSON when explicitly requested.",
            "Snapshot comparison is explicit and uses local agent runbook JSON only.",
            "Use 遗失源 / 遗失 raw wording for record-chain incidents.",
        ],
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Agent 多机核心记录自检",
        "",
        f"- 合同: `{report['contract']}`",
        f"- 受众: `{report['audience']}`",
        f"- 状态: `{'pass' if report['ok'] else 'attention'}`",
        f"- 只读: `{report['read_only']}`",
        f"- 快照写入: `{report.get('snapshot_write_performed', False)}`",
        f"- 快照对比: `{report.get('comparison', {}).get('performed', False)}`",
        "",
        "## 机器",
        "",
    ]
    for host in report.get("hosts", []):
        summary = host.get("summary", {})
        lines.append(
            f"- `{host['host']}`: `{host['audit_status']}` "
            f"records={summary.get('record_count', 0)} "
            f"raw_attention={summary.get('raw_attention_count', 0)} "
            f"backfill={summary.get('backfill_recommended_count', 0)}"
        )
    if report.get("errors"):
        lines.extend(["", "## 错误", ""])
        for error in report["errors"]:
            lines.append(f"- `{error['host']}`: {error['error']}")
    comparison = report.get("comparison")
    if isinstance(comparison, dict) and comparison.get("performed"):
        lines.extend(["", "## 快照对比", ""])
        lines.append(f"- baseline: `{comparison.get('baseline_path', '')}`")
        lines.append(f"- status: `{comparison.get('status', '')}`")
        lines.append(f"- issues: `{comparison.get('issue_count', 0)}`")
        delta = comparison.get("summary_delta") if isinstance(comparison.get("summary_delta"), dict) else {}
        for key in ("record_count", "raw_attention_count", "backfill_recommended_count", "lost_source_count", "lost_raw_count"):
            lines.append(f"- {key}_delta: `{delta.get(key, 0)}`")
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run read-only multi-host core-record audit patrol.")
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    parser.add_argument("--limit", type=int, default=80)
    parser.add_argument("--mode", choices=("fast", "full"), default="fast")
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--ssh-config", type=Path, default=None)
    parser.add_argument("--remote-host", action="append", default=None)
    parser.add_argument("--no-local", action="store_true")
    parser.add_argument("--save-snapshot", action="store_true")
    parser.add_argument("--snapshot-dir", type=Path, default=None)
    parser.add_argument("--compare-latest", action="store_true")
    args = parser.parse_args()

    report = build_multi_host_audit(
        include_local=not args.no_local,
        remote_hosts=tuple(args.remote_host) if args.remote_host else DEFAULT_REMOTE_HOSTS,
        ssh_config=args.ssh_config,
        limit=args.limit,
        mode=args.mode,
        timeout=args.timeout,
    )
    if args.compare_latest:
        baseline, baseline_path = load_latest_snapshot(snapshot_dir=args.snapshot_dir)
        comparison = compare_with_baseline(report, baseline)
        comparison["performed"] = True
        comparison["baseline_path"] = str(baseline_path or "")
        report["comparison"] = comparison
    if args.save_snapshot:
        save_snapshot(report, snapshot_dir=args.snapshot_dir)
    if args.format == "markdown":
        print(render_markdown(report), end="")
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
