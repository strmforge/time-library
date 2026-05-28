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
    assert "理解某人的偏好" not in html
    assert "understanding a person" not in html


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
