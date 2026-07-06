from tools import trusted_memory_user_work_trace_probe as probe


def _case(case: str, *, answer: str, used_refs: list[str]) -> dict:
    return {
        "case": case,
        "ordinary_handled": False,
        "ordinary_reason": "openclaw_before_dispatch_requires_explicit_zhiyi_entry",
        "explicit_handled": True,
        "answer": answer,
        "answer_source": "evidence_bound_model_call",
        "recall_count": 1,
        "model_called": True,
        "request_sent": True,
        "model_verdict": "insufficient_evidence" if answer == "UNKNOWN" else "answered",
        "model_validation_error": "",
        "unknown_reason": "missing_remote_release_receipt" if answer == "UNKNOWN" else "",
        "evidence_packet_refs": used_refs or ["exp-user-gap"],
        "used_source_refs": used_refs,
        "source_refs": [{"library_id": (used_refs or ["exp-user-gap"])[0], "source_path": "/tmp/source.jsonl"}],
        "receipt_status": "unknown" if answer == "UNKNOWN" else "source_backed",
        "unknown_boundary": answer == "UNKNOWN",
        "trace_status": "proven",
        "model_delivery_state": "observed",
        "missing_cells": [],
        "cells": {
            "passive_gate_observed": True,
            "model_evidence_receipt_observed": True,
            "answer_evidence_observed": True,
            "receipt_visibility_observed": True,
            "security_gate_observed": True,
        },
    }


def test_user_work_trace_probe_requires_scope_and_queries_before_reading_records():
    result = probe.run_probe()

    assert result["ok"] is False
    assert result["status"] == "scope_and_queries_required"
    assert result["user_work_records_read"] is False
    assert result["model_call_performed"] is False
    assert "--scope-filter" in result["missing"]
    assert "--source-query" in result["missing"]
    assert "--unknown-query" in result["missing"]
    assert result["install_authorization_model"] == "installed_connection_is_authorization"


def test_user_work_trace_probe_requires_scoped_queries_for_install_specific_proof():
    result = probe.run_probe(
        scope_filter="current-window",
    )

    assert result["ok"] is False
    assert result["user_work_records_read"] is False
    assert "--source-query" in result["missing"]
    assert "--unknown-query" in result["missing"]


def test_user_work_trace_probe_uses_deep_bounded_raw_fallback_budget():
    request = probe._work_preflight_request(
        "windows123 provider bucket custom 对齐 token 后 codex exec OK 的验证结果是什么？",
        "window/ssh-192-168-50-148-7f60287b",
        240,
    )

    assert request["deep_work_preflight"] is True
    assert request["force_raw_fallback"] is True
    assert request["raw_fallback_max_bytes"] == probe.USER_WORK_PROBE_RAW_FALLBACK_MAX_BYTES
    assert request["raw_fallback_max_lines"] == probe.USER_WORK_PROBE_RAW_FALLBACK_MAX_LINES
    assert request["raw_fallback_deadline_seconds"] == probe.USER_WORK_PROBE_RAW_FALLBACK_DEADLINE_SECONDS


def test_user_work_trace_probe_reports_authorized_proven_shape_without_platform_action(monkeypatch):
    cases = [
        _case("source_backed", answer="先核对 NAS，再实施下一刀。", used_refs=["exp-user-next"]),
        _case("unknown", answer="UNKNOWN", used_refs=[]),
    ]

    def fake_run_case(*_args, **kwargs):
        return next(item for item in cases if item["case"] == kwargs["case"])

    class FakeProxy:
        DEFAULT_FEATURE_FLAGS = {"zhiyi_direct": False}
        _flags = {}

        @staticmethod
        def record_zhiyi_usage_log(*_args, **_kwargs):
            return {"usage_log_write_performed": False}

        @staticmethod
        def audit_log(*_args, **_kwargs):
            return None

        @staticmethod
        def remember_openclaw_before_dispatch_handled(*_args, **_kwargs):
            return {"ok": True, "write_performed": False}

        @staticmethod
        def remember_openclaw_before_dispatch_raw(*_args, **_kwargs):
            return {"ok": True, "write_performed": False}

        class DialogEntryHandler:
            pass

    monkeypatch.setattr(probe, "_load_dialog_proxy", lambda _gateway_url="": FakeProxy)
    monkeypatch.setattr(probe, "_run_case", fake_run_case)

    result = probe.run_probe(
        scope_filter="current-window",
        source_query="下一步是什么？",
        unknown_query="远端发布完成了吗？",
    )

    assert result["ok"] is True
    assert result["status"] == "proven"
    assert result["user_work_records_read"] is True
    assert result["model_call_performed"] is True
    assert result["platform_action_performed"] is False
    assert result["install_authorization_model"] == "installed_connection_is_authorization"
    assert result["authorized_scope_filter"] == "current-window"
    assert result["authorized_caller_scope"] == {
        "canonical_window_id": "current-window",
        "source_system": "trusted_memory_probe",
        "computer_id": "local",
    }
    assert result["cases"][0]["trace_status"] == "proven"
    assert result["cases"][1]["answer"] == "UNKNOWN"
    assert result["cases"][1]["unknown_boundary"] is True


def test_user_work_trace_probe_requires_source_backed_used_refs(monkeypatch):
    cases = [
        _case("source_backed", answer="没有来源的答案", used_refs=[]),
        _case("unknown", answer="UNKNOWN", used_refs=[]),
    ]

    def fake_run_case(*_args, **kwargs):
        return next(item for item in cases if item["case"] == kwargs["case"])

    class FakeProxy:
        DEFAULT_FEATURE_FLAGS = {"zhiyi_direct": False}
        _flags = {}

        @staticmethod
        def record_zhiyi_usage_log(*_args, **_kwargs):
            return {"usage_log_write_performed": False}

        @staticmethod
        def audit_log(*_args, **_kwargs):
            return None

        @staticmethod
        def remember_openclaw_before_dispatch_handled(*_args, **_kwargs):
            return {"ok": True, "write_performed": False}

        @staticmethod
        def remember_openclaw_before_dispatch_raw(*_args, **_kwargs):
            return {"ok": True, "write_performed": False}

        class DialogEntryHandler:
            pass

    monkeypatch.setattr(probe, "_load_dialog_proxy", lambda _gateway_url="": FakeProxy)
    monkeypatch.setattr(probe, "_run_case", fake_run_case)

    result = probe.run_probe(
        scope_filter="current-window",
        source_query="下一步是什么？",
        unknown_query="远端发布完成了吗？",
    )

    assert result["ok"] is False
    assert result["status"] == "unproven"
    assert result["cases"][0]["receipt_status"] == "source_backed"
    assert result["cases"][0]["used_source_refs"] == []


def test_user_work_trace_probe_source_backed_uses_work_preflight_source_ref_path(monkeypatch):
    class FakeHandler:
        def handle_openclaw_before_dispatch(self, event):
            assert not str(event.get("message") or "").startswith("/zhiyi")
            return {
                "handled": False,
                "text": "",
                "reason": "openclaw_before_dispatch_requires_explicit_zhiyi_entry",
            }

    monkeypatch.setattr(probe, "_run_work_preflight", lambda **_kwargs: {
        "ok": True,
        "endpoint": "http://127.0.0.1:9851/api/v1/raw/query",
        "request": {
            "mode": "work_preflight",
            "canonical_window_id": "ssh-192-168-50-148-7f60287b",
            "deep_work_preflight": True,
        },
        "response": {
            "ok": True,
            "contract": "agent_work_preflight.v2026.6.20",
            "classification": "built_but_miswired",
            "decision": "surface",
            "recall_status": "ok",
            "memory_scope": "window",
            "matched_count": 1,
            "source_refs_count": 1,
            "raw_items_count": 1,
            "must_surface": [
                {
                    "library_id": "exp-provider-token",
                    "title": "windows123 provider bucket drift",
                    "summary": "windows123 provider bucket drift was fixed by switching Codex to token provider.",
                    "source_path": "/tmp/source.jsonl",
                    "msg_ids": ["m1"],
                    "canonical_window_id": "ssh-192-168-50-148-7f60287b",
                }
            ],
        },
        "error": "",
    })
    monkeypatch.setattr(probe, "_compact_evidence_from_work_preflight", lambda _response, **_kwargs: {
        "ok": True,
        "contract": "source_ref_compact_evidence.v2026.6.21",
        "items_count": 1,
        "answer_bearing_items_count": 1,
        "raw_backtrace_hits_count": 1,
        "items": [
            {
                "ok": True,
                "source_id": "exp-provider-token",
                "evidence_ref": "exp-provider-token",
                "library_id": "exp-provider-token",
                "text": "windows123 provider bucket drift was model_provider=custom while the relay route expected token.",
                "source_refs": {"source_path": "/tmp/source.jsonl", "msg_ids": ["m1"]},
            }
        ],
    })
    monkeypatch.setattr(probe, "_run_evidence_answer", lambda **_kwargs: {
        "model_call_performed": True,
        "answer": "windows123 provider bucket drift 是 model_provider=custom 和 token relay route 不匹配。",
        "verdict": "answered",
        "confidence": 0.9,
        "supporting_refs": ["exp-provider-token"],
        "validation_error": "",
        "unknown_reason": "",
    })

    result = probe._run_case(
        FakeHandler(),
        case="source_backed",
        query="windows123 Codex provider bucket drift 是什么问题？",
        scope_filter="window/ssh-192-168-50-148-7f60287b",
        gateway_url="",
        model_config=probe._model_config({"provider": "minimax", "timeout_seconds": 90}),
        include_answer=False,
    )

    assert result["trusted_memory_probe_evidence_path"] == "work_preflight_source_ref_compact_evidence"
    assert result["explicit_handled"] is True
    assert result["answer_omitted"] is True
    assert result["answer_is_unknown"] is False
    assert result["receipt_status"] == "source_backed"
    assert result["used_source_refs"] == ["exp-provider-token"]
    assert result["evidence_packet_refs"] == ["exp-provider-token"]
    assert result["work_preflight"]["response"]["source_refs_count"] == 1
    assert result["source_ref_compact_evidence"]["raw_backtrace_hits_count"] == 1


def test_user_work_trace_probe_accepts_work_preflight_evidence_field(monkeypatch):
    monkeypatch.setattr(probe, "_compact_evidence_from_work_preflight", lambda response, **_kwargs: {
        "ok": bool(probe._work_preflight_surfaces(response)),
        "contract": "source_ref_compact_evidence.v2026.6.21",
        "items_count": len(probe._work_preflight_surfaces(response)),
        "answer_bearing_items_count": len(probe._work_preflight_surfaces(response)),
        "raw_backtrace_hits_count": len(probe._work_preflight_surfaces(response)),
        "items": [
            {
                "ok": True,
                "source_id": item["library_id"],
                "evidence_ref": item["library_id"],
                "library_id": item["library_id"],
                "text": item["summary"],
                "source_refs": {"source_path": item["source_path"], "msg_ids": item["msg_ids"]},
            }
            for item in probe._work_preflight_surfaces(response)
        ],
    })

    compact = probe._compact_evidence_from_work_preflight({
        "ok": True,
        "contract": "agent_work_preflight.v2026.6.20",
        "source_refs_count": 1,
        "raw_items_count": 1,
        "evidence": [
            {
                "library_id": "evidence-field-ref",
                "summary": "work_preflight evidence field carries the source anchor.",
                "source_path": "/tmp/source.jsonl",
                "msg_ids": ["m1"],
            }
        ],
    })

    assert compact["items_count"] == 1
    assert compact["items"][0]["evidence_ref"] == "evidence-field-ref"


def test_user_work_trace_probe_rejects_insufficient_source_backed_verdict(monkeypatch):
    source_case = _case("source_backed", answer="忆凡尘定位为可信记忆。", used_refs=["exp-pref-a"])
    source_case["model_verdict"] = "insufficient_evidence"
    source_case["unknown_reason"] = "知意行策的定位信息在证据中不完整"
    cases = [
        source_case,
        _case("unknown", answer="UNKNOWN", used_refs=[]),
    ]

    def fake_run_case(*_args, **kwargs):
        return next(item for item in cases if item["case"] == kwargs["case"])

    class FakeProxy:
        DEFAULT_FEATURE_FLAGS = {"zhiyi_direct": False}
        _flags = {}

        @staticmethod
        def record_zhiyi_usage_log(*_args, **_kwargs):
            return {"usage_log_write_performed": False}

        @staticmethod
        def audit_log(*_args, **_kwargs):
            return None

        @staticmethod
        def remember_openclaw_before_dispatch_handled(*_args, **_kwargs):
            return {"ok": True, "write_performed": False}

        @staticmethod
        def remember_openclaw_before_dispatch_raw(*_args, **_kwargs):
            return {"ok": True, "write_performed": False}

        class DialogEntryHandler:
            pass

    monkeypatch.setattr(probe, "_load_dialog_proxy", lambda _gateway_url="": FakeProxy)
    monkeypatch.setattr(probe, "_run_case", fake_run_case)

    result = probe.run_probe(
        scope_filter="current-window",
        source_query="忆凡尘和知意行策的定位是什么？",
        unknown_query="远端发布完成了吗？",
    )

    assert result["ok"] is False
    assert result["status"] == "unproven"
    assert result["cases"][0]["used_source_refs"] == ["exp-pref-a"]
    assert result["cases"][0]["model_verdict"] == "insufficient_evidence"


def test_user_work_trace_probe_casefile_requires_scoped_cases(tmp_path):
    casefile = tmp_path / "cases.json"
    casefile.write_text(
        '{"cases":[{"name":"missing-scope","source_query":"Q","unknown_query":"U"}]}',
        encoding="utf-8",
    )

    result = probe.run_casefile(casefile=casefile)

    assert result["ok"] is False
    assert result["status"] == "casefile_invalid"
    assert result["user_work_records_read"] is False
    assert result["casefile_errors"][0]["case"] == "missing-scope"
    assert result["casefile_errors"][0]["error"] == "scope_and_queries_required"


def test_user_work_trace_probe_casefile_rejects_non_zhiyi_xingce_record_kind(tmp_path):
    casefile = tmp_path / "cases.json"
    casefile.write_text(
        """
        {
          "cases": [
            {
              "name": "wrong-kind",
              "record_kind": "private_memory",
              "scope_filter": "window/a",
              "source_query": "Q",
              "unknown_query": "U"
            }
          ]
        }
        """,
        encoding="utf-8",
    )

    result = probe.run_casefile(casefile=casefile)

    assert result["ok"] is False
    assert result["status"] == "casefile_invalid"
    assert result["user_work_records_read"] is False
    assert result["casefile_errors"][0] == {
        "case": "wrong-kind",
        "error": "unsupported_record_kind",
        "detail": "private_memory",
    }


def test_user_work_trace_probe_casefile_aggregates_scope_limited_traces(monkeypatch, tmp_path):
    casefile = tmp_path / "cases.json"
    casefile.write_text(
        """
        {
          "cases": [
            {
              "name": "pref-qclaw",
              "record_kind": "user_preference",
              "scope_filter": "window/ssh-192-168-50-148-7f60287b",
              "source_query": "QClaw",
              "unknown_query": "QClaw 的远端发布回执已经完成了吗？",
              "expected_metrics": {
                "ordinary_chats_checked": 2,
                "source_claims_checked": 1,
                "unknown_cases_checked": 1,
                "hijack_rate": "0/2",
                "unsupported_answer_rate": "0/1",
                "unknown_discipline": "1/1",
                "source_reachability": "1/1",
                "receipt_visibility": "2/2"
              }
            },
            {
              "name": "work-next",
              "record_kind": "work_record",
              "scope_filter": "window/ssh-192-168-50-148-7f60287b",
              "source_query": "下一步是什么？",
              "unknown_query": "不存在的远端回执完成了吗？",
              "expected_metrics": {
                "ordinary_chats_checked": 2,
                "source_claims_checked": 1,
                "unknown_cases_checked": 1,
                "hijack_rate": "0/2",
                "unsupported_answer_rate": "0/1",
                "unknown_discipline": "1/1",
                "source_reachability": "1/1",
                "receipt_visibility": "2/2"
              }
            }
          ]
        }
        """,
        encoding="utf-8",
    )

    def fake_run_probe(**kwargs):
        return {
            "ok": True,
            "contract": probe.PROBE_CONTRACT,
            "status": "proven",
            "read_only": True,
            "write_performed": False,
            "raw_write_performed": False,
            "memory_write_performed": False,
            "platform_write_performed": False,
            "model_call_performed": True,
            "user_work_records_read": True,
            "platform_action_performed": False,
            "authorized_scope_filter": kwargs["scope_filter"],
            "authorized_caller_scope": probe._caller_scope_from_scope_filter(kwargs["scope_filter"]),
            "cases": [
                _case("source_backed", answer="source-backed", used_refs=[f"exp-{kwargs['source_query']}"]),
                _case("unknown", answer="UNKNOWN", used_refs=[]),
            ],
        }

    monkeypatch.setattr(probe, "run_probe", fake_run_probe)

    result = probe.run_casefile(casefile=casefile)

    assert result["ok"] is True
    assert result["status"] == "proven"
    assert result["case_count"] == 2
    assert result["scope_count"] == 1
    assert result["scope_filters"] == ["window/ssh-192-168-50-148-7f60287b"]
    assert result["record_kinds"] == ["user_preference", "work_record"]
    assert result["user_work_records_read"] is True
    assert result["platform_action_performed"] is False
    assert result["write_performed"] is False
    assert [item["casefile_case"] for item in result["case_results"]] == ["pref-qclaw", "work-next"]
    assert [item["casefile_record_kind"] for item in result["case_results"]] == ["user_preference", "work_record"]
    assert result["case_results"][0]["casefile_expected_metrics"]["hijack_rate"] == "0/2"
    assert result["case_results"][1]["casefile_expected_metrics"]["source_reachability"] == "1/1"
    assert len(result["cases"]) == 4
    assert {item["casefile_case"] for item in result["cases"]} == {"pref-qclaw", "work-next"}
    assert {item["casefile_record_kind"] for item in result["cases"]} == {"user_preference", "work_record"}
    assert {item["casefile_expected_metrics"]["receipt_visibility"] for item in result["cases"]} == {"2/2"}
    assert {item["authorized_scope_filter"] for item in result["cases"]} == {"window/ssh-192-168-50-148-7f60287b"}
