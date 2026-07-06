import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "core_record_multi_host_audit.py"


def _load_audit():
    spec = importlib.util.spec_from_file_location("core_record_multi_host_audit_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _report(status="pass", *, ok=True, records=1, source="codex"):
    return {
        "ok": ok,
        "audit_status": status,
        "record_chain_proven": status in {"pass", "observe"},
        "runtime": {
            "runtime_root": "/tmp/memcore-cloud",
            "runtime_root_source": "auto_install_root",
        },
        "summary": {
            "record_count": records,
            "record_guarded_count": records,
            "raw_attention_count": 0,
            "backfill_recommended_count": 0,
            "lost_source_count": 0,
            "lost_raw_count": 0,
            "corrupt_record_count": 0,
            "raw_catching_up_count": 1 if status == "observe" else 0,
            "max_raw_lag_milliseconds": 12 if status == "observe" else 0,
        },
        "source_statuses": [
            {
                "source_system": source,
                "state": "guarded" if status == "pass" else "observing_raw_catching_up",
                "record_count": records,
                "guarded_record_count": records,
                "attention_record_count": 0,
            }
        ],
    }


def _multi_report(records=3, *, raw_attention=0, backfill=0, lost_source=0, lost_raw=0):
    return {
        "ok": raw_attention == 0 and backfill == 0 and lost_source == 0 and lost_raw == 0,
        "summary": {
            "record_count": records,
            "raw_attention_count": raw_attention,
            "backfill_recommended_count": backfill,
            "lost_source_count": lost_source,
            "lost_raw_count": lost_raw,
        },
        "hosts": [
            {
                "host": "local",
                "audit_status": "pass",
                "summary": {
                    "record_count": records,
                    "raw_attention_count": raw_attention,
                    "backfill_recommended_count": backfill,
                    "lost_source_count": lost_source,
                    "lost_raw_count": lost_raw,
                },
            }
        ],
    }


def test_multi_host_json_parser_skips_powershell_noise():
    audit = _load_audit()
    text = "#< CLIXML\r\nnoise before json\r\n" + '{"ok": true, "audit_status": "pass"}'

    parsed = audit._first_json_object(text)

    assert parsed == {"ok": True, "audit_status": "pass"}


def test_json_command_accepts_nonzero_when_stdout_contains_json(monkeypatch):
    audit = _load_audit()

    class Proc:
        returncode = 2
        stdout = '#< CLIXML\r\n{"ok": false, "audit_status": "needs_backfill"}\n'
        stderr = "progress noise"

    monkeypatch.setattr(audit.subprocess, "run", lambda *_, **__: Proc())

    report, stdout, stderr, returncode = audit._run_json_command(["ignored"], cwd=ROOT, timeout=1)

    assert report["audit_status"] == "needs_backfill"
    assert stdout.startswith("#< CLIXML")
    assert stderr == "progress noise"
    assert returncode == 2


def test_multi_host_summary_treats_observe_as_non_issue():
    audit = _load_audit()
    hosts = [
        audit._host_summary("local", _report("observe", records=2), transport="local"),
        audit._host_summary("windows123", _report("pass", records=3), transport="ssh:.ssh/config"),
    ]

    summary = audit.summarize_hosts(hosts)

    assert summary["host_count"] == 2
    assert summary["issue_host_count"] == 0
    assert summary["observe_hosts"] == ["local"]
    assert summary["record_count"] == 5


def test_multi_host_summary_marks_attention_host():
    audit = _load_audit()
    bad = _report("needs_backfill", ok=False, records=1)
    bad["summary"]["raw_attention_count"] = 1
    hosts = [audit._host_summary("windows191", bad, transport="ssh:.ssh/config")]

    summary = audit.summarize_hosts(hosts)

    assert summary["issue_host_count"] == 1
    assert summary["issue_hosts"] == ["windows191"]
    assert summary["raw_attention_count"] == 1


def test_multi_host_report_defaults_to_no_snapshot_write(monkeypatch):
    audit = _load_audit()
    local = audit._host_summary("local", _report("pass", records=2), transport="local")
    monkeypatch.setattr(audit, "run_local_host", lambda **_: local)

    report = audit.build_multi_host_audit(include_local=True, remote_hosts=())

    assert report["ok"] is True
    assert report["read_only"] is True
    assert report["write_performed"] is False
    assert report["snapshot_write_performed"] is False
    assert report["snapshot"] == {"saved": False}


def test_multi_host_compare_missing_baseline_is_not_failure():
    audit = _load_audit()

    comparison = audit.compare_with_baseline(_multi_report(), None)

    assert comparison["baseline_available"] is False
    assert comparison["status"] == "baseline_missing"
    assert comparison["issue_count"] == 0


def test_multi_host_compare_reports_record_growth_without_issue():
    audit = _load_audit()

    comparison = audit.compare_with_baseline(_multi_report(records=5), _multi_report(records=3))

    assert comparison["baseline_available"] is True
    assert comparison["status"] == "ok"
    assert comparison["summary_delta"]["record_count"] == 2
    assert comparison["issue_count"] == 0


def test_multi_host_compare_marks_record_issue_regression():
    audit = _load_audit()

    comparison = audit.compare_with_baseline(
        _multi_report(records=4, raw_attention=1),
        _multi_report(records=3, raw_attention=0),
    )

    assert comparison["status"] == "regressed"
    assert "raw_attention_count_increased" in comparison["issues"]
    assert "local_record_issue_increased" in comparison["issues"]
    assert comparison["host_deltas"][0]["status"] == "regressed"


def test_multi_host_render_markdown_includes_comparison_summary():
    audit = _load_audit()
    report = _multi_report(records=5)
    report.update({
        "contract": audit.CONTRACT,
        "audience": audit.AUDIENCE,
        "read_only": True,
        "snapshot_write_performed": False,
        "comparison": audit.compare_with_baseline(_multi_report(records=5), _multi_report(records=3)) | {
            "performed": True,
            "baseline_path": "/tmp/baseline.json",
        },
        "errors": [],
    })

    markdown = audit.render_markdown(report)

    assert "## 快照对比" in markdown
    assert "record_count_delta: `2`" in markdown


def test_multi_host_save_snapshot_is_explicit_local_runbook_write(tmp_path):
    audit = _load_audit()
    report = {
        "ok": True,
        "generated_at": "2026-06-08T14:40:01Z",
        "read_only": True,
        "write_performed": False,
        "snapshot_write_performed": False,
        "summary": {"record_count": 3},
    }

    path = audit.save_snapshot(report, snapshot_dir=tmp_path)

    assert path.name == "2026-06-08T14-40-01Z-core-record-multi-host.json"
    assert path.exists()
    assert report["read_only"] is False
    assert report["write_performed"] is True
    assert report["snapshot_write_performed"] is True
    assert report["snapshot"]["scope"] == "local_agent_runbook_only"
    assert "local_agent_runbook_only" in path.read_text(encoding="utf-8")


def test_multi_host_default_hosts_are_scope_specific_windows_routes():
    audit = _load_audit()

    assert audit.DEFAULT_REMOTE_HOSTS == ("windows191", "windows123")
    assert audit.AUDIENCE == "agent_maintainer_runbook_not_product_ui"


def test_multi_host_remote_command_uses_workspace_ssh_config_and_encoded_powershell(tmp_path):
    audit = _load_audit()
    ssh_config = tmp_path / "config"

    cmd = audit._remote_command("windows123", ssh_config, limit=80, mode="fast")

    assert cmd[:4] == ["ssh", "-F", str(ssh_config), "windows123"]
    assert "-EncodedCommand" in cmd
    assert "powershell" in cmd
