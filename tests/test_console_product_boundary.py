import importlib
import json
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _reload_p6(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMCORE_ROOT", str(tmp_path / "memcore"))
    monkeypatch.setenv("MEMCORE_CONFIG", str(ROOT / "config" / "memcore.json"))
    for name in ["config_loader", "src.config_loader", "p6_console", "src.p6_console"]:
        sys.modules.pop(name, None)
    return importlib.import_module("p6_console")


def test_console_i18n_keeps_zh_cn_labels_chinese(tmp_path, monkeypatch):
    p6 = _reload_p6(tmp_path, monkeypatch)

    zh = p6.I18N["zh-CN"]
    assert zh["nav.settings"] == "设置"
    assert zh["nav.update"] == "系统更新"
    assert zh["nav.sourceSystems"] == "数据源"
    assert zh["runtime.refresh"] == "刷新"


def test_console_user_visible_text_has_no_internal_phase_codes(tmp_path, monkeypatch):
    p6 = _reload_p6(tmp_path, monkeypatch)

    visible_payload = json.dumps(p6.I18N, ensure_ascii=False) + p6.HTML_TEMPLATE

    assert "".join(["P9", "-Audit", "-Fix-1"]) not in visible_payload
    assert "".join(["Audit", "-Fix"]) not in visible_payload
    assert p6.I18N["zh-CN"]["dashboard.sealed"] == "本机服务就绪"
    assert p6.I18N["en-US"]["dashboard.sealed"] == "Local Service Ready"


def test_console_status_api_uses_public_phase_name(tmp_path, monkeypatch):
    p6 = _reload_p6(tmp_path, monkeypatch)
    monkeypatch.setattr(p6, "get_watcher_status", lambda: True)
    monkeypatch.setattr(p6, "get_raw_stats", lambda: {"sessions": 0})
    monkeypatch.setattr(p6, "get_zhiyi_stats", lambda: {"total": 0})

    overview = p6.m3_get_overview()

    assert overview["phase"] == "local-service-ready"
    assert "P9" not in json.dumps(overview, ensure_ascii=False)


def test_console_legacy_review_apis_hide_internal_phase_names(tmp_path, monkeypatch):
    p6 = _reload_p6(tmp_path, monkeypatch)

    payload = {
        "risk_backlog": p6.m4_get_risk_backlog(),
        "next_decision": p6.m4_get_next_decision_summary(),
    }
    serialized = json.dumps(payload, ensure_ascii=False)

    assert "".join(["P9", "-System"]) not in serialized
    assert "".join(["Audit", "-Fix"]) not in serialized
    assert payload["risk_backlog"]["risks"][0]["task"] == "runtime-status"
    assert payload["next_decision"]["current_phase"] == "local-console-review-complete"


def test_product_console_explains_zhiyi_xingce_in_both_languages():
    html = (ROOT / "web" / "console_product.html").read_text(encoding="utf-8")

    assert "知意负责看见，行策负责落地" in html
    assert "知行合一" in html
    assert "Zhiyi understands intent" in html
    assert "Xingce turns source-backed work into work experience" in html
    assert "Knowing and doing as one" in html
    assert "经验不是技能库" in html
    assert "Experience is not a skill library" in html
    assert "platform.rawCurrent" in html
    assert "archive-layout/audit" in html
    assert "理解某人的偏好" not in html
    assert "understanding a person" not in html


def test_product_console_hides_discovery_strategy_terms():
    html = (ROOT / "web" / "console_product.html").read_text(encoding="utf-8")

    hidden_terms = [
        "泛发现",
        "平台字典",
        "GitHub Watchlist",
        "github_top100",
        "Known adapter",
        "Generic surface",
        "support_level",
        "catalog_level",
        "stars ",
    ]
    for term in hidden_terms:
        assert term not in html
    assert "更多发现" in html
    assert "可接入应用" in html
    assert "More found" in html
    assert "Connectable app" in html
    assert "Memcore Cloud" in html


def test_p6_toolbook_candidate_dry_run_validates_without_writing(tmp_path, monkeypatch):
    p6 = _reload_p6(tmp_path, monkeypatch)

    result = p6.build_toolbook_candidate({
        "platform": "Hermes",
        "environment": "isolated probe",
        "observed_behavior": "profile config is read from the profile directory",
        "raw_source_path": "raw/probe_logs/hermes-profile-config.jsonl",
        "verbatim_excerpt": "profile config.yaml was read from profiles/default/config.yaml",
    })

    assert result["ok"] is True
    assert result["dry_run"] is True
    assert result["write_performed"] is False
    assert result["candidate"]["library_shelf"] == "toolbook"
    assert result["validation"]["checks"]["toolbook_raw_source"] is True


def test_p6_zhixing_library_exposes_loop_and_replay_offense_metric(tmp_path, monkeypatch):
    p6 = _reload_p6(tmp_path, monkeypatch)

    library = p6.query_zhixing_library()
    plan = p6.get_zhixing_replay_plan()
    replay = p6.run_replay_dry_run({
        "case": {
            "case_id": "p6-proactive",
            "query": "继续平台配置问题",
            "expected_proactive_resurfacing": ["profile 无 config 显示 auto"],
        },
        "records": [
            {
                "_type": "xingce_work_experience_candidate",
                "exp_id": "xingce-p6-proactive",
                "summary": "过去做对过：profile 无 config 显示 auto。",
                "source_refs": {
                    "source_system": "probe",
                    "source_path": "raw/probe_logs/hermes-profile.jsonl",
                },
                "verbatim_excerpt": "profile 无 config 显示 auto。",
                "supersedes": [],
                "conflicts_with": [],
                "_xingce": {"candidate_id": "xingce-p6-proactive", "lifecycle_status": "candidate"},
            },
        ],
    })

    assert library["loop"]["zh_name"] == "知行闭环"
    assert len(library["loop"]["steps"]) == 7
    assert plan["metrics"][-1] == "proactive_resurfacing"
    assert plan["loop"]["connector_persona"]["zh_name"] == "接引者"
    assert replay["summary"]["proactive_resurfacing_passed"] is True
    assert replay["write_performed"] is False
    assert replay["feedback_candidates"]["write_performed"] is False
    assert "proactive_resurfacing_candidate" in replay["feedback_candidates"]["candidate_types"]


def test_p6_state_ledger_and_context_unit_helpers_are_read_only(tmp_path, monkeypatch):
    p6 = _reload_p6(tmp_path, monkeypatch)

    ledger_plan = p6.get_state_ledger_plan()
    ledger = p6.build_state_ledger_snapshot({
        "topic": "QClaw naming",
        "records": [
            {
                "library_id": "ZX-ZHIYI-OLD",
                "status": "superseded",
                "updated_at": "2026-05-29T10:00:00Z",
                "source_refs": {"source_system": "codex", "source_path": "raw/codex/old.jsonl"},
                "verbatim_excerpt": "Windows 原生 OpenClaw 你称为 QClaw",
            },
            {
                "library_id": "ZX-ZHIYI-CURRENT",
                "status": "adopted",
                "updated_at": "2026-05-30T10:00:00Z",
                "source_refs": {"source_system": "codex", "source_path": "raw/codex/current.jsonl"},
                "verbatim_excerpt": "腾讯那个我会称呼 QClaw，不会和 openclaw 混说",
                "supersedes": ["ZX-ZHIYI-OLD"],
            },
        ],
    })
    unit_contract = p6.get_context_budget_unit_contract()
    unit = p6.build_context_budget_unit_candidate({
        "unit_text": "QClaw 指腾讯那个，不是 Windows 原生 OpenClaw。",
        "source_refs": {"source_system": "codex", "source_path": "raw/codex/qclaw.jsonl"},
        "verbatim_excerpt": "腾讯那个我会称呼 QClaw，不会和 openclaw 混说",
        "objective_link": "prevent QClaw naming drift",
    })

    assert ledger_plan["read_only"] is True
    assert ledger_plan["write_performed"] is False
    assert ledger["latest_trusted_judgment"]["record_id"] == "ZX-ZHIYI-CURRENT"
    assert ledger["write_performed"] is False
    assert ledger["write_flags"]["raw_write_performed"] is False
    assert unit_contract["read_only"] is True
    assert unit["ok"] is True
    assert unit["candidate"]["candidate_type"] == "context_budget_unit_candidate"
    assert unit["candidate"]["platform_write_performed"] is False


def test_p6_replay_feedback_apply_requires_authorization_and_writes_receipt_only(tmp_path, monkeypatch):
    p6 = _reload_p6(tmp_path, monkeypatch)
    replay = p6.run_replay_dry_run({
        "case": {
            "case_id": "p6-feedback-apply",
            "expected_library_ids": ["ZX-XINGCE-APPLY"],
            "expected_proactive_resurfacing": ["过去做对过的验收路径"],
        },
        "records": [
            {
                "_type": "xingce_work_experience_candidate",
                "library_id": "ZX-XINGCE-APPLY",
                "exp_id": "xingce-p6-apply",
                "summary": "过去做对过的验收路径。",
                "source_refs": {
                    "source_system": "probe",
                    "source_path": "raw/probe_logs/apply.jsonl",
                },
                "verbatim_excerpt": "过去做对过的验收路径。",
                "supersedes": [],
                "conflicts_with": [],
                "_xingce": {"candidate_id": "xingce-p6-apply", "lifecycle_status": "candidate"},
            },
        ],
    })
    candidate = next(
        item for item in replay["feedback_candidates"]["candidates"]
        if item["candidate_type"] == "proactive_resurfacing_candidate"
    )

    blocked = p6.apply_zhixing_replay_feedback_candidate({"candidate": candidate})
    assert blocked["ok"] is False
    assert blocked["write_performed"] is False
    assert "confirm_apply_replay_feedback" in blocked["authorization_missing"]

    applied = p6.apply_zhixing_replay_feedback_candidate({
        "candidate": candidate,
        "authorization": {
            "confirm_apply_replay_feedback": True,
            "confirm_write_replay_feedback_receipt": True,
            "confirm_no_raw_platform_or_memory_write": True,
            "operator": "test",
            "reason": "verify replay feedback apply gate",
        },
    })

    assert applied["ok"] is True
    assert applied["write_performed"] is True
    assert applied["replay_feedback_receipt_write_performed"] is True
    assert applied["production_experience_write_performed"] is False
    assert applied["raw_write_performed"] is False
    assert applied["zhiyi_write_performed"] is False
    assert applied["xingce_write_performed"] is False
    assert applied["hermes_write_performed"] is False
    assert applied["openclaw_write_performed"] is False
    assert p6.os.path.exists(applied["receipt_path"])
    assert p6.os.path.exists(applied["latest_path"])


def test_http_zhixing_loop_replay_and_capability_check_smoke(tmp_path, monkeypatch):
    p6 = _reload_p6(tmp_path, monkeypatch)
    for name in ["raw_consumption_gateway", "src.raw_consumption_gateway"]:
        sys.modules.pop(name, None)
    raw_gateway = importlib.import_module("src.raw_consumption_gateway")

    p6_server = p6.ThreadingHTTPServer(("127.0.0.1", 0), p6.Handler)
    raw_server = raw_gateway.HTTPServer(("127.0.0.1", 0), raw_gateway.Handler)
    servers = [p6_server, raw_server]
    threads = [
        threading.Thread(target=server.serve_forever, daemon=True)
        for server in servers
    ]
    for thread in threads:
        thread.start()

    def get_json(port, path):
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=8) as response:
            return response.status, json.loads(response.read().decode("utf-8"))

    def post_json(port, path, body):
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}{path}",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=8) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    try:
        p6_port = p6_server.server_address[1]
        raw_port = raw_server.server_address[1]

        status, loop = get_json(p6_port, "/api/v1/zhixing/loop")
        assert status == 200
        assert len(loop["steps"]) == 7
        assert loop["metric_shape"]["defense_count"] == 4
        assert loop["metric_shape"]["offense_metric"] == "proactive_resurfacing"
        assert loop["connector_persona"]["zh_name"] == "接引者"
        assert loop["connector_persona"]["zhiyi_remains_implicit"] is True

        status, plan = get_json(p6_port, "/api/v1/zhixing/replay/plan")
        assert status == 200
        assert plan["comparison_sets"] == ["no_memory", "zhiyi_only", "zhiyi_plus_xingce"]

        status, benchmark_plan = get_json(p6_port, "/api/v1/zhixing/benchmark/plan")
        assert status == 200
        assert benchmark_plan["comparison_sets"] == ["no_memory", "zhiyi_only", "zhiyi_plus_xingce"]
        assert benchmark_plan["promotion_rule"]["queue_should_wait_for_benchmark"] is True

        status, routes = get_json(p6_port, "/api/v1/dialog/intent-routes")
        assert status == 200
        assert routes["read_only"] is True
        assert routes["write_performed"] is False
        assert "correction_errata" in routes["routes"]
        assert "method_signal" in routes["routes"]
        assert "state_ledger" in routes["routes"]
        assert "context_unit" in routes["routes"]

        status, model_facts_plan = get_json(p6_port, "/api/v1/model-facts/plan")
        assert status == 200
        assert model_facts_plan["read_only"] is True
        assert model_facts_plan["write_performed"] is False
        assert "detected_is_not_runnable" in model_facts_plan["contracts"]
        assert "platform_configs_are_never_written" in model_facts_plan["contracts"]

        status, model_facts = get_json(p6_port, "/api/v1/model-facts")
        assert status == 200
        assert model_facts["read_only"] is True
        assert model_facts["platform_write_performed"] is False
        assert model_facts["runtime_boundary"]["yifanchen_is_not_a_model_center"] is True
        assert model_facts["runtime_boundary"]["platform_writeback_allowed"] is False
        assert model_facts["detected_is_not_runnable"] is True

        status, autodiscovery = get_json(p6_port, "/api/v1/platforms/autodiscovery")
        assert status == 200
        assert autodiscovery["name"] == "Memcore Cloud"
        assert autodiscovery["read_only"] is True
        assert autodiscovery["platform_write_performed"] is False
        assert autodiscovery["authorization_contract"]["skill_installation_is_not_body_read_consent"] is True
        assert autodiscovery["thin_adapter_registry"]["read_only"] is True
        assert "cursor" in autodiscovery["known_adapter_targets"]
        assert autodiscovery["platform_catalog"]["github_watchlist_entry_count"] == 100

        status, platform_catalog = get_json(p6_port, "/api/v1/platforms/catalog")
        assert status == 200
        assert platform_catalog["contract"] == "platform_catalog.v1"
        assert platform_catalog["read_only"] is True
        assert platform_catalog["platform_write_performed"] is False
        assert platform_catalog["curated_entry_count"] >= 12
        assert platform_catalog["github_watchlist_entry_count"] == 100

        status, package_inventory = get_json(p6_port, "/api/v1/platforms/package-manager-inventory")
        assert status == 200
        assert package_inventory["contract"] == "package_manager_agent_inventory.v1"
        assert package_inventory["read_only"] is True
        assert package_inventory["platform_write_performed"] is False
        assert package_inventory["global_guarantees"]["does_not_install_packages"] is True

        status, raw_layout = get_json(p6_port, "/api/v1/raw/archive-layout")
        assert status == 200
        assert raw_layout["contract"] == "raw_archive_layout.v1"
        assert raw_layout["read_only"] is True
        assert raw_layout["effective_from_version"] == "2026.6.1"
        assert raw_layout["new_install_default_layout"] == "computer_first"
        assert raw_layout["new_raw_writes_must_use_preferred_layout"] is True
        assert raw_layout["preferred_segment_order"] == [
            "computer_name",
            "source_system",
            "native_artifact_format",
        ]
        assert raw_layout["primary_partition_key"] == "computer_name"
        assert raw_layout["secondary_partition_key"] == "source_system"
        assert raw_layout["legacy_layout_status"] == "read_compatibility_only"
        assert raw_layout["legacy_layout_allowed_for_new_writes"] is False

        status, raw_layout_audit = get_json(p6_port, "/api/v1/raw/archive-layout/audit")
        assert status == 200
        assert raw_layout_audit["contract"] == "raw_archive_layout_audit.v1"
        assert raw_layout_audit["read_only"] is True
        assert raw_layout_audit["new_raw_writes_must_use_preferred_layout"] is True
        assert raw_layout_audit["legacy_layout_allowed_for_new_writes"] is False
        assert "computer_first_files" in raw_layout_audit["totals"]
        assert "legacy_source_first_files" in raw_layout_audit["totals"]

        status, thin_adapter_registry = get_json(p6_port, "/api/v1/platforms/thin-adapter-registry")
        assert status == 200
        assert thin_adapter_registry["contract"] == "thin_adapter_registry.v1"
        assert thin_adapter_registry["read_only"] is True
        assert thin_adapter_registry["platform_write_performed"] is False
        assert thin_adapter_registry["github_watchlist_entry_count"] == 100
        assert any(item["system"] == "cursor" for item in thin_adapter_registry["adapters"])
        assert any(
            item["system"] == "claude_code_cli"
            and item["current_focus"] is True
            and item["support_level"] == "adapter_candidate_separate_claude_surface"
            for item in thin_adapter_registry["adapters"]
        )
        assert all("connectable_now" in item for item in thin_adapter_registry["adapters"])
        assert all("mcp_config_detected" in item for item in thin_adapter_registry["adapters"])
        assert all("memcore_mcp_detected" in item for item in thin_adapter_registry["adapters"])
        assert thin_adapter_registry["generic_surface_discovery"]["contract"] == "generic_local_ai_surface_discovery.v1"

        status, discovery_dashboard = get_json(p6_port, "/api/v1/platforms/discovery-dashboard")
        assert status == 200
        assert discovery_dashboard["contract"] == "platform_discovery_dashboard.v1"
        assert discovery_dashboard["read_only"] is True
        assert discovery_dashboard["platform_write_performed"] is False
        assert discovery_dashboard["global_guarantees"]["does_not_parse_chat_bodies"] is True
        assert "ready_for_capability_check" in discovery_dashboard["counts"]
        assert discovery_dashboard["counts"]["catalog_watchlist"] == 100
        assert discovery_dashboard["links"]["platform_catalog"] == "/api/v1/platforms/catalog"
        assert discovery_dashboard["links"]["package_manager_inventory"] == "/api/v1/platforms/package-manager-inventory"
        assert discovery_dashboard["global_guarantees"]["raw_archive_layout_order"] == [
            "computer_name",
            "source_system",
            "native_artifact_format",
        ]
        assert discovery_dashboard["global_guarantees"]["raw_archive_primary_partition_key"] == "computer_name"
        assert discovery_dashboard["global_guarantees"]["raw_archive_secondary_partition_key"] == "source_system"
        assert discovery_dashboard["global_guarantees"]["raw_archive_effective_from_version"] == "2026.6.1"
        assert discovery_dashboard["global_guarantees"]["raw_archive_new_install_default_layout"] == "computer_first"
        assert discovery_dashboard["global_guarantees"]["raw_archive_legacy_layout_status"] == "read_compatibility_only"
        assert discovery_dashboard["global_guarantees"]["raw_archive_legacy_layout_allowed_for_new_writes"] is False
        assert all("safe_next_step" in item for item in discovery_dashboard["items"])
        assert all(item["writes_now"] is False for item in discovery_dashboard["items"])

        status, generic_surfaces = get_json(p6_port, "/api/v1/platforms/generic-local-ai-surfaces")
        assert status == 200
        assert generic_surfaces["contract"] == "generic_local_ai_surface_discovery.v1"
        assert generic_surfaces["read_only"] is True
        assert generic_surfaces["platform_write_performed"] is False

        status, auto_connect_dry_run = get_json(p6_port, "/api/v1/platforms/authorized-auto-connect/dry-run")
        assert status == 200
        assert auto_connect_dry_run["contract"] == "authorized_auto_connect_dry_run.v1"
        assert auto_connect_dry_run["read_only"] is True
        assert auto_connect_dry_run["platform_write_performed"] is False
        assert auto_connect_dry_run["apply_endpoint_status"] == "implemented_for_json_mcp_surfaces"
        assert "claude_code_cli" in auto_connect_dry_run["implemented_apply_systems"]
        assert "cursor" in auto_connect_dry_run["implemented_apply_systems"]
        assert "kiro" in auto_connect_dry_run["implemented_apply_systems"]
        assert auto_connect_dry_run["global_guarantees"]["does_not_parse_chat_bodies"] is True
        assert all("would_write" in item for item in auto_connect_dry_run["plans"])
        assert all("rollback_plan" in item for item in auto_connect_dry_run["plans"])

        status, cursor_connect_plan = get_json(p6_port, "/api/v1/platforms/cursor/authorized-connect-plan")
        assert status == 200
        assert cursor_connect_plan["system_filter"] == "cursor"
        assert cursor_connect_plan["read_only"] is True
        assert cursor_connect_plan["platform_write_performed"] is False
        assert len(cursor_connect_plan["plans"]) == 1

        status, apply_gate_blocked = post_json(p6_port, "/api/v1/platforms/authorized-auto-connect/apply-gate/dry-run", {
            "system": "cursor",
        })
        assert status == 200
        assert apply_gate_blocked["contract"] == "authorized_auto_connect_apply_gate.v1"
        assert apply_gate_blocked["read_only"] is True
        assert apply_gate_blocked["platform_write_performed"] is False
        assert apply_gate_blocked["status"] == "blocked"
        assert "confirm_user_requested_auto_connect" in apply_gate_blocked["missing_confirmations"]

        status, autoconnect_plan = get_json(p6_port, "/api/v1/platforms/authorized-auto-connect/plan")
        assert status == 200
        assert autoconnect_plan["read_only"] is True
        assert autoconnect_plan["apply_endpoint_status"] == "not_implemented"
        assert "confirm_no_chat_body_parser_without_separate_authorization" in autoconnect_plan["required_confirmations"]

        status, runnable_doctor_plan = get_json(p6_port, "/api/v1/model-facts/runnable-doctor/plan")
        assert status == 200
        assert runnable_doctor_plan["read_only"] is True
        assert runnable_doctor_plan["write_performed"] is False
        assert runnable_doctor_plan["smoke_endpoint"] == "/api/v1/model-facts/runnable-doctor/smoke"
        assert "confirm_live_runtime_smoke" in runnable_doctor_plan["authorization_required"]

        status, runnable_doctor_blocked = post_json(p6_port, "/api/v1/model-facts/runnable-doctor/smoke", {
            "platform": "hermes",
            "operator": "pytest-http-smoke",
            "reason": "missing confirmation",
        })
        assert status == 400
        assert runnable_doctor_blocked["ok"] is False
        assert runnable_doctor_blocked["runtime_smoke_performed"] is False
        assert runnable_doctor_blocked["write_performed"] is False
        assert "confirm_live_runtime_smoke" in runnable_doctor_blocked["missing_authorization"]

        status, method_contract = get_json(p6_port, "/api/v1/zhixing/method-signals/contract")
        assert status == 200
        assert method_contract["read_only"] is True
        assert method_contract["write_performed"] is False
        assert method_contract["candidate_type"] == "external_method_signal_candidate"
        assert "install_or_activate_skill" in method_contract["forbidden_by_default"]

        status, ledger_plan = get_json(p6_port, "/api/v1/zhixing/state-ledger/plan")
        assert status == 200
        assert ledger_plan["read_only"] is True
        assert ledger_plan["write_performed"] is False
        assert ledger_plan["temporal_index_role"] == "navigation_only_not_authority"

        status, unit_contract = get_json(p6_port, "/api/v1/zhixing/context-units/contract")
        assert status == 200
        assert unit_contract["read_only"] is True
        assert unit_contract["write_performed"] is False
        assert unit_contract["candidate_type"] == "context_budget_unit_candidate"

        status, replay = post_json(p6_port, "/api/v1/zhixing/replay/dry-run", {
            "case": {
                "case_id": "http-smoke",
                "expected_source_refs": ["raw/probe_logs/hermes-profile-effective-config.jsonl"],
                "expected_library_ids": ["ZX-XINGCE-HTTP"],
                "expected_behavior_markers": ["先查 profile config"],
                "forbidden_repeated_mistakes": ["改 root config 当默认继承"],
                "required_acceptance_checks": ["hermes profile show"],
                "expected_proactive_resurfacing": ["profile 无 config 显示 auto"],
            },
            "records": [
                {
                    "_type": "xingce_work_experience_candidate",
                    "library_id": "ZX-XINGCE-HTTP",
                    "exp_id": "xingce-http",
                    "summary": "Hermes 平台配置经验：先查 profile config，profile 无 config 显示 auto。",
                    "detail": "不要改 root config 当默认继承；验收用 hermes profile show。",
                    "source_refs": {
                        "source_system": "probe",
                        "source_path": "raw/probe_logs/hermes-profile-effective-config.jsonl",
                    },
                    "verbatim_excerpt": "profile 无 config 显示 auto；hermes profile show 可验收。",
                    "acceptance_checks": ["hermes profile show"],
                    "supersedes": [],
                    "conflicts_with": [],
                    "_xingce": {"candidate_id": "xingce-http", "lifecycle_status": "candidate"},
                },
            ],
        })
        assert status == 200
        assert replay["summary"]["best_mode"] == "zhiyi_plus_xingce"
        assert replay["summary"]["proactive_resurfacing_passed"] is True
        feedback = replay["feedback_candidates"]
        assert feedback["write_performed"] is False
        assert "replay_adoption_candidate" in feedback["candidate_types"]
        assert "proactive_resurfacing_candidate" in feedback["candidate_types"]

        status, benchmark = post_json(p6_port, "/api/v1/zhixing/benchmark/dry-run", {
            "cases": [
                {
                    "case_id": "http-benchmark",
                    "query": "继续 Hermes 配置真实生效验证",
                    "expected_source_refs": ["raw/probe_logs/hermes-profile-effective-config.jsonl"],
                    "expected_library_ids": ["ZX-XINGCE-HTTP"],
                    "expected_behavior_markers": ["先查 profile config"],
                    "forbidden_repeated_mistakes": ["改 root config 当默认继承"],
                    "required_acceptance_checks": ["hermes profile show"],
                    "expected_proactive_resurfacing": ["profile 无 config 显示 auto"],
                    "records": [
                        {
                            "_type": "xingce_work_experience_candidate",
                            "library_id": "ZX-XINGCE-HTTP",
                            "exp_id": "xingce-http",
                            "summary": "Hermes 平台配置经验：先查 profile config，profile 无 config 显示 auto。",
                            "detail": "不要改 root config 当默认继承；验收用 hermes profile show。",
                            "source_refs": {
                                "source_system": "probe",
                                "source_path": "raw/probe_logs/hermes-profile-effective-config.jsonl",
                            },
                            "verbatim_excerpt": "profile 无 config 显示 auto；hermes profile show 可验收。",
                            "acceptance_checks": ["hermes profile show"],
                            "supersedes": [],
                            "conflicts_with": [],
                            "_xingce": {"candidate_id": "xingce-http", "lifecycle_status": "candidate"},
                        },
                    ],
                },
            ],
        })
        assert status == 200
        assert benchmark["case_count"] == 1
        assert benchmark["summary"]["best_mode"] == "zhiyi_plus_xingce"
        assert benchmark["summary"]["xingce_signal_detected"] is True
        assert benchmark["summary"]["queue_should_wait_for_benchmark"] is True
        assert benchmark["summary"]["machine_ascension_not_claimed"] is True
        assert benchmark["write_performed"] is False

        status, routed = post_json(p6_port, "/api/v1/dialog/intent-route/dry-run", {
            "message": "这条记录不对，不是我的原话",
        })
        assert status == 200
        assert routed["route"] == "correction_errata"
        assert routed["action"] == "zhiyi_errata_candidate"
        assert routed["target_shelf"] == "errata"
        assert routed["write_performed"] is False

        status, routed_signal = post_json(p6_port, "/api/v1/dialog/intent-route/dry-run", {
            "message": "这个 GitHub repo 可能对忆凡尘有用，是个新方向",
        })
        assert status == 200
        assert routed_signal["route"] == "method_signal"
        assert routed_signal["action"] == "zhixing_method_signal_candidate"
        assert routed_signal["target_shelf"] == "incubator"
        assert routed_signal["write_performed"] is False

        status, errata = post_json(p6_port, "/api/v1/zhiyi/errata-candidates/dry-run", {
            "correction_text": "这条记录不对，不是我的原话",
            "target": {
                "library_id": "ZX-ZHIYI-HTTP",
                "source_refs": {
                    "source_system": "codex",
                    "source_path": "raw/codex/http-smoke.jsonl",
                },
            },
        })
        assert status == 200
        assert errata["ok"] is True
        assert errata["read_only"] is True
        assert errata["write_performed"] is False
        assert errata["candidate"]["candidate_type"] == "zhiyi_errata_candidate"
        assert errata["candidate"]["verbatim_feedback"] == "这条记录不对，不是我的原话"
        assert errata["candidate"]["raw_write_performed"] is False
        assert errata["candidate"]["zhiyi_write_performed"] is False
        assert errata["candidate"]["errata_write_performed"] is False

        status, method_signal = post_json(p6_port, "/api/v1/zhixing/method-signals/dry-run", {
            "title": "Tianlu feed-to-method",
            "signal": "这个 GitHub repo 可能对忆凡尘有用，是个新方向：把外部资讯变成方法候选。",
            "source_url": "https://github.com/strmforge/tianlu-skills",
            "source_refs": {
                "source_system": "github",
                "source_url": "https://github.com/strmforge/tianlu-skills",
                "commit": "f5ac7db",
            },
            "verbatim_excerpt": "The incubator is the entrance for new methods.",
            "proposed_trigger": "用户说新方向、外部仓库、可能对忆凡尘有用",
            "proposed_mechanism": "先生成 method_card_candidate，再由 Replay/Benchmark 决定是否升格。",
            "initial_scope": "Yifanchen method governance",
        })
        assert status == 200
        assert method_signal["ok"] is True
        assert method_signal["read_only"] is True
        assert method_signal["write_performed"] is False
        assert method_signal["candidate"]["candidate_type"] == "external_method_signal_candidate"
        assert method_signal["candidate"]["activation_allowed"] is False
        assert method_signal["candidate"]["install_allowed"] is False
        assert method_signal["candidate"]["skill_write_performed"] is False
        assert method_signal["candidate"]["platform_write_performed"] is False

        status, ledger = post_json(p6_port, "/api/v1/zhixing/state-ledger/dry-run", {
            "topic": "QClaw naming",
            "records": [
                {
                    "library_id": "ZX-ZHIYI-OLD",
                    "status": "superseded",
                    "updated_at": "2026-05-29T10:00:00Z",
                    "source_refs": {"source_system": "codex", "source_path": "raw/codex/old.jsonl"},
                    "verbatim_excerpt": "Windows 原生 OpenClaw 你称为 QClaw",
                },
                {
                    "library_id": "ZX-ZHIYI-CURRENT",
                    "status": "adopted",
                    "updated_at": "2026-05-30T10:00:00Z",
                    "source_refs": {"source_system": "codex", "source_path": "raw/codex/current.jsonl"},
                    "verbatim_excerpt": "腾讯那个我会称呼 QClaw，不会和 openclaw 混说",
                    "supersedes": ["ZX-ZHIYI-OLD"],
                },
            ],
        })
        assert status == 200
        assert ledger["latest_trusted_judgment"]["record_id"] == "ZX-ZHIYI-CURRENT"
        assert ledger["write_performed"] is False
        assert ledger["write_flags"]["raw_write_performed"] is False

        status, context_unit = post_json(p6_port, "/api/v1/zhixing/context-units/dry-run", {
            "unit_text": "QClaw 指腾讯那个，不是 Windows 原生 OpenClaw。",
            "source_refs": {"source_system": "codex", "source_path": "raw/codex/qclaw.jsonl"},
            "verbatim_excerpt": "腾讯那个我会称呼 QClaw，不会和 openclaw 混说",
            "objective_link": "prevent QClaw naming drift",
        })
        assert status == 200
        assert context_unit["ok"] is True
        assert context_unit["candidate"]["candidate_type"] == "context_budget_unit_candidate"
        assert context_unit["candidate"]["write_performed"] is False
        assert context_unit["candidate"]["platform_write_performed"] is False

        status, hermes_diff_plan = get_json(p6_port, "/api/v1/hermes/skill-experience-diff/plan")
        assert status == 200
        assert hermes_diff_plan["read_only"] is True
        assert hermes_diff_plan["write_performed"] is False
        assert "write_hermes_skill" in hermes_diff_plan["forbidden_by_default"]

        status, hermes_diff = post_json(p6_port, "/api/v1/hermes/skill-experience-diff/dry-run", {
            "skills": [
                {
                    "skill_id": "software-development/hermes-profile-config",
                    "title": "Hermes profile config",
                    "text": "# Hermes profile config\nProfile config.yaml is read from the profile directory. No root fallback. Validate with hermes profile show.",
                    "source_refs": {
                        "source_system": "hermes",
                        "artifact_type": "hermes_skill_file",
                        "source_path": "/tmp/hermes/skills/hermes-profile-config/SKILL.md",
                    },
                },
            ],
            "experiences": [
                {
                    "library_id": "ZX-XINGCE-HERMES-PROFILE",
                    "summary": "Hermes profile config is read from the profile directory.",
                    "detail": "Validate with hermes profile show.",
                    "source_refs": {
                        "source_system": "probe",
                        "source_path": "raw/probe_logs/hermes-profile.jsonl",
                    },
                    "verbatim_excerpt": "profile config.yaml was read from profiles/default/config.yaml",
                },
            ],
        })
        assert status == 200
        assert hermes_diff["ok"] is True
        assert hermes_diff["write_performed"] is False
        assert hermes_diff["summary"]["upgrade_candidate_count"] == 1
        assert hermes_diff["upgrade_candidates"]["candidates"][0]["candidate_type"] == "hermes_skill_experience_upgrade_candidate"

        status, hermes_receipt = post_json(p6_port, "/api/v1/hermes/consumption-receipts", {
            "event_type": "hermes_turn_consumption_receipt",
            "provider": "memcore_yifanchen",
            "session_id": "hermes-http-session",
            "memory_scope": "raw_pool",
            "user_content": "用户问题",
            "assistant_content": "Hermes 回答",
            "last_prefetch": {
                "ok": True,
                "request_id": "hermes-memcore-prefetch-http",
                "matched_count": 2,
                "source_refs_count": 2,
            },
        })
        assert status == 200
        assert hermes_receipt["ok"] is True
        assert hermes_receipt["consumption_receipt_write_performed"] is True
        assert hermes_receipt["raw_write_performed"] is False
        assert hermes_receipt["hermes_skill_write_performed"] is False

        status, hermes_receipts = get_json(p6_port, "/api/v1/hermes/consumption-receipts")
        assert status == 200
        assert hermes_receipts["read_only"] is True
        assert hermes_receipts["latest"]["receipt_id"] == hermes_receipt["receipt_id"]

        status, hermes_trigger_plan = get_json(p6_port, "/api/v1/hermes/native-learning/self-review/trigger/dry-run")
        assert status == 200
        assert hermes_trigger_plan["read_only"] is True
        assert hermes_trigger_plan["write_performed"] is False
        assert "confirm_live_hermes_trigger" in hermes_trigger_plan["authorization_required"]
        assert hermes_trigger_plan["write_boundary"]["hermes_skill_write_performed_by_yifanchen"] is False

        status, hermes_triggers = get_json(p6_port, "/api/v1/hermes/native-learning/self-review/triggers")
        assert status == 200
        assert hermes_triggers["read_only"] is True
        assert hermes_triggers["write_performed"] is False
        assert hermes_triggers["trigger_receipt_write_performed"] is False
        assert hermes_triggers["items"] == []

        status, hermes_trigger_blocked = post_json(p6_port, "/api/v1/hermes/native-learning/self-review/trigger", {
            "operator": "pytest-http-smoke",
            "reason": "verify trigger gate",
        })
        assert status == 400
        assert hermes_trigger_blocked["ok"] is False
        assert hermes_trigger_blocked["hermes_trigger_called"] is False
        assert hermes_trigger_blocked["write_performed"] is False
        assert "confirm_live_hermes_trigger" in hermes_trigger_blocked["missing_authorization"]

        status, skill_probe_plan = get_json(p6_port, "/api/v1/hermes/native-learning/skill-generation/probe/dry-run")
        assert status == 200
        assert skill_probe_plan["read_only"] is True
        assert skill_probe_plan["write_performed"] is False
        assert skill_probe_plan["probe_id"].startswith("hermes-skill-generation-probe-")
        assert skill_probe_plan["stage_gates"]["c_skill_artifact_change"] == "non-Yifanchen skill file is added or modified"
        assert skill_probe_plan["write_boundary"]["hermes_skill_write_performed_by_yifanchen"] is False

        status, skill_probes = get_json(p6_port, "/api/v1/hermes/native-learning/skill-generation/probes")
        assert status == 200
        assert skill_probes["read_only"] is True
        assert skill_probes["write_performed"] is False
        assert skill_probes["probe_receipt_write_performed"] is False
        assert skill_probes["items"] == []

        status, skill_probe_blocked = post_json(p6_port, "/api/v1/hermes/native-learning/skill-generation/probe", {
            "operator": "pytest-http-smoke",
            "reason": "verify skill probe gate",
        })
        assert status == 400
        assert skill_probe_blocked["ok"] is False
        assert skill_probe_blocked["hermes_trigger_called"] is False
        assert skill_probe_blocked["write_performed"] is False
        assert "confirm_live_hermes_skill_generation_probe" in skill_probe_blocked["missing_authorization"]

        status, skill_status_plan = get_json(p6_port, "/api/v1/hermes/native-learning/skill-artifact-status/plan")
        assert status == 200
        assert skill_status_plan["read_only"] is True
        assert skill_status_plan["write_performed"] is False
        assert skill_status_plan["record_endpoint"] == "/api/v1/hermes/native-learning/skill-artifact-status/record"
        assert skill_status_plan["status_draft"]["artifact_type"] == "hermes_skill_artifact_status"
        assert skill_status_plan["status_draft"]["write_boundary"]["hermes_skill_write_performed_by_yifanchen"] is False

        status, skill_statuses = get_json(p6_port, "/api/v1/hermes/native-learning/skill-artifact-statuses")
        assert status == 200
        assert skill_statuses["read_only"] is True
        assert skill_statuses["write_performed"] is False
        assert skill_statuses["status_receipt_write_performed"] is False
        assert skill_statuses["items"] == []

        status, skill_status_blocked = post_json(p6_port, "/api/v1/hermes/native-learning/skill-artifact-status/record", {
            "operator": "pytest-http-smoke",
            "reason": "verify skill artifact status gate",
        })
        assert status == 400
        assert skill_status_blocked["ok"] is False
        assert skill_status_blocked["write_performed"] is False
        assert "confirm_record_hermes_skill_artifact_status" in skill_status_blocked["missing_authorization"]
        assert "confirm_no_hermes_skill_write_by_yifanchen" in skill_status_blocked["missing_authorization"]

        status, self_review_report_plan = get_json(p6_port, "/api/v1/hermes/native-learning/self-review/report/plan")
        assert status == 200
        assert self_review_report_plan["read_only"] is True
        assert self_review_report_plan["write_performed"] is False
        assert self_review_report_plan["record_endpoint"] == "/api/v1/hermes/native-learning/self-review/report/record"

        status, self_review_report_blocked = post_json(p6_port, "/api/v1/hermes/native-learning/self-review/report/record", {
            "review_text": "## 忆凡尘原始记忆自审 — Review Report\n#### 候选 #1: 测试\n> 原话",
            "trigger_id": "hermes-self-review-http",
            "operator": "pytest-http-smoke",
            "reason": "missing confirmation",
        })
        assert status == 400
        assert self_review_report_blocked["ok"] is False
        assert self_review_report_blocked["write_performed"] is False
        assert "confirm_record_self_review_report_candidate" in self_review_report_blocked["missing_authorization"]

        candidate = feedback["candidates"][0]
        status, blocked = post_json(p6_port, "/api/v1/zhixing/replay/feedback-candidates/apply", {
            "candidate": candidate,
        })
        assert status == 400
        assert blocked["ok"] is False
        assert blocked["requires_authorization"] is True
        assert blocked["write_performed"] is False

        status, applied = post_json(p6_port, "/api/v1/zhixing/replay/feedback-candidates/apply", {
            "candidate": candidate,
            "confirm_apply_replay_feedback": True,
            "confirm_write_replay_feedback_receipt": True,
            "confirm_no_raw_platform_or_memory_write": True,
            "operator": "pytest-http-smoke",
            "reason": "verify HTTP replay feedback gate",
        })
        assert status == 200
        assert applied["replay_feedback_receipt_write_performed"] is True
        assert applied["production_experience_write_performed"] is False
        assert applied["raw_write_performed"] is False
        assert applied["zhiyi_write_performed"] is False
        assert applied["xingce_write_performed"] is False
        assert applied["hermes_write_performed"] is False
        assert applied["openclaw_write_performed"] is False

        status, capability = post_json(raw_port, "/api/v1/raw/query", {
            "query": "capability check",
            "mode": "capability_check",
            "consumer": "pytest-http-smoke",
            "request_id": "capability-http-smoke",
        })
        assert status == 200
        assert capability["mode"] == "capability_check"
        assert capability["recall_performed"] is False
        assert capability["raw_excerpt_returned"] is False
        assert capability["items"] == []
        assert capability["consumer_receipt"]["receipt_scope"] == "capability_check_no_recall"
    finally:
        for server in servers:
            server.shutdown()
            server.server_close()


def test_p6_hermes_native_learning_liveness_is_read_only(tmp_path, monkeypatch):
    p6 = _reload_p6(tmp_path, monkeypatch)
    home = tmp_path / "hermes"
    (home / "logs").mkdir(parents=True)
    (home / "logs" / "agent.log").write_text("plain chat\n", encoding="utf-8")
    skill = home / "skills" / "yifanchen" / "yifanchen-zhiyi" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("# Yifanchen\n", encoding="utf-8")

    result = p6.query_hermes_native_learning_liveness({"hermes_home": str(home)})

    assert result["ok"] is True
    assert result["read_only"] is True
    assert result["write_performed"] is False
    assert result["hermes_write_performed"] is False
    assert result["liveness_status"] == "cold"
    assert "no_skill_manage_seen" in result["cold_reasons"]
    assert result["self_review_signal"]["signal_type"] == "hermes_self_review_signal"
    assert result["self_review_signal"]["signal_status"] == "wake_signal"


def test_p6_hermes_skill_experience_diff_is_read_only(tmp_path, monkeypatch):
    p6 = _reload_p6(tmp_path, monkeypatch)

    plan = p6.get_hermes_skill_experience_diff_plan()
    result = p6.build_hermes_skill_experience_diff_dry_run({
        "skills": [
            {
                "skill_id": "software-development/hermes-profile-config",
                "title": "Hermes profile config",
                "text": "# Hermes profile config\nProfile config.yaml is read from the profile directory. No root fallback. Validate with hermes profile show.",
                "source_refs": {
                    "source_system": "hermes",
                    "artifact_type": "hermes_skill_file",
                    "source_path": "/tmp/hermes/skills/hermes-profile-config/SKILL.md",
                },
            },
        ],
        "experiences": [
            {
                "library_id": "ZX-XINGCE-HERMES-PROFILE",
                "summary": "Hermes profile config is read from the profile directory.",
                "detail": "Validate with hermes profile show.",
                "source_refs": {
                    "source_system": "probe",
                    "source_path": "raw/probe_logs/hermes-profile.jsonl",
                },
                "verbatim_excerpt": "profile config.yaml was read from profiles/default/config.yaml",
            },
        ],
    })

    assert plan["read_only"] is True
    assert result["ok"] is True
    assert result["write_performed"] is False
    assert result["summary"]["upgrade_candidate_count"] == 1
    candidate = result["upgrade_candidates"]["candidates"][0]
    assert candidate["candidate_type"] == "hermes_skill_experience_upgrade_candidate"
    assert candidate["write_boundary"]["hermes_write_performed"] is False
    assert candidate["write_boundary"]["production_experience_write_performed"] is False


def test_p6_hermes_consumption_receipt_records_sync_turn_without_memory_writes(tmp_path, monkeypatch):
    p6 = _reload_p6(tmp_path, monkeypatch)

    result = p6.persist_hermes_consumption_receipt({
        "event_type": "hermes_turn_consumption_receipt",
        "provider": "memcore_yifanchen",
        "session_id": "hermes-session",
        "memory_scope": "raw_pool",
        "user_content": "用户问题",
        "assistant_content": "Hermes 回答",
        "last_prefetch": {
            "ok": True,
            "request_id": "hermes-memcore-prefetch-test",
            "matched_count": 2,
            "source_refs_count": 2,
        },
    })
    receipts = p6.query_hermes_consumption_receipts({"limit": 5})

    assert result["ok"] is True
    assert result["write_performed"] is True
    assert result["consumption_receipt_write_performed"] is True
    assert result["raw_write_performed"] is False
    assert result["zhiyi_write_performed"] is False
    assert result["xingce_write_performed"] is False
    assert result["hermes_write_performed"] is False
    assert result["hermes_skill_write_performed"] is False
    assert result["production_experience_write_performed"] is False
    assert p6.os.path.exists(result["receipt_path"])
    assert receipts["ok"] is True
    assert receipts["read_only"] is True
    assert receipts["latest"]["receipt_id"] == result["receipt_id"]
    assert receipts["items"][0]["consumption_summary"]["prefetch_matched_count"] == 2


def test_p6_hermes_self_review_wake_and_receipt_boundaries(tmp_path, monkeypatch):
    p6 = _reload_p6(tmp_path, monkeypatch)
    home = tmp_path / "hermes"
    (home / "logs").mkdir(parents=True)
    (home / "logs" / "agent.log").write_text("plain chat\n", encoding="utf-8")
    skill = home / "skills" / "yifanchen" / "yifanchen-zhiyi" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("# Yifanchen\n", encoding="utf-8")

    dry = p6.build_hermes_self_review_wake_http_dry_run({
        "hermes_home": str(home),
        "operator": "pytest",
        "reason": "verify p6 boundary",
    })
    assert dry["ok"] is True
    assert dry["dry_run"] is True
    assert dry["write_performed"] is False
    assert dry["hermes_write_performed"] is False
    assert dry["wake_plan"]["read_scope"] == "all_raw_memory"
    assert dry["wake_plan"]["does_not_package_zhiyi_summary"] is True

    blocked = p6.apply_hermes_self_review_signal_receipt_http({
        "hermes_home": str(home),
        "operator": "pytest",
    })
    assert blocked["ok"] is False
    assert blocked["write_performed"] is False
    assert "confirm_record_signal_receipt" in blocked["missing_authorization"]

    applied = p6.apply_hermes_self_review_signal_receipt_http({
        "hermes_home": str(home),
        "authorization": {
            "operator": "pytest",
            "reason": "record p6 signal only",
            "confirm_record_signal_receipt": True,
            "confirm_no_hermes_write": True,
            "confirm_no_raw_zhiyi_xingce_write": True,
        },
    })
    assert applied["ok"] is True
    assert applied["signal_receipt_write_performed"] is True
    assert applied["raw_write_performed"] is False
    assert applied["zhiyi_write_performed"] is False
    assert applied["xingce_write_performed"] is False
    assert applied["hermes_write_performed"] is False
    assert applied["openclaw_write_performed"] is False
