import importlib
import json

from src.evidence_bound_model import (
    EVIDENCE_BOUND_MODEL_CONTRACT,
    EVIDENCE_BOUND_FAST_AUDIT_SCHEMA,
    EVIDENCE_OBJECT_STATE_DIAGNOSTIC_SCHEMA,
    build_evidence_bound_answer_prompt,
    build_evidence_bound_fast_audit_prompt,
    build_evidence_object_state_prompt,
    default_model_config,
    plan_evidence_bound_answer_model_use,
    run_evidence_bound_answer,
    run_evidence_bound_fast_audit,
    run_evidence_bound_experience_refinement,
    run_evidence_object_state_diagnostic,
)


def test_default_model_config_uses_current_fast_defaults(monkeypatch):
    for key in (
        "MEMCORE_ZHIYI_MODEL",
        "MEMCORE_ZHIYI_BASE_URL",
        "MEMCORE_ZHIYI_API_KEY",
        "MINIMAX_MODEL",
        "MINIMAX_CN_MODEL",
        "DEEPSEEK_MODEL",
    ):
        monkeypatch.delenv(key, raising=False)

    minimax = default_model_config(provider="minimax")
    deepseek = default_model_config(provider="deepseek")

    assert minimax.model == "MiniMax-M2.7-highspeed"
    assert deepseek.model == "deepseek-v4-flash"


def test_default_model_config_respects_explicit_model(monkeypatch):
    monkeypatch.setenv("MINIMAX_MODEL", "MiniMax-M2.7")
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-v4-pro")

    assert default_model_config(provider="minimax").model == "MiniMax-M2.7"
    assert default_model_config(provider="deepseek").model == "deepseek-v4-pro"


def test_default_model_config_reads_installed_user_default_binding(tmp_path, monkeypatch):
    for key in (
        "MEMCORE_ZHIYI_PROVIDER",
        "MEMCORE_ZHIYI_MODEL",
        "MEMCORE_ZHIYI_BASE_URL",
        "MEMCORE_ZHIYI_API_KEY",
        "MEMCORE_ZHIYI_API_KEY_ENV",
        "MINIMAX_API_KEY",
        "MINIMAX_CN_API_KEY",
        "DEEPSEEK_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)
    root = tmp_path / "memcore"
    config_dir = root / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "zhiyi_model_binding.user.json").write_text(
        json.dumps(
            {
                "provider": "Hermes",
                "provider_id": "custom:minimax",
                "selected_option_id": "hermes-config:custom:minimax:MiniMax-M3",
                "model_name": "MiniMax-M3",
                "base_url": "https://api.minimaxi.com/v1",
                "api_key_env": "MINIMAX_API_KEY",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("MEMCORE_ROOT", str(root))
    monkeypatch.setenv("MINIMAX_API_KEY", "dummy")

    module = importlib.import_module("src.evidence_bound_model")
    cfg = module.default_model_config()

    assert cfg.provider == "minimax"
    assert cfg.model == "MiniMax-M3"
    assert cfg.base_url == "https://api.minimaxi.com/v1"
    assert cfg.api_key_env == "MINIMAX_API_KEY"
    assert cfg.api_key_present is True


def test_default_model_config_falls_back_to_present_minimax_env_for_custom_binding(tmp_path, monkeypatch):
    for key in (
        "MEMCORE_ZHIYI_PROVIDER",
        "MEMCORE_ZHIYI_MODEL",
        "MEMCORE_ZHIYI_BASE_URL",
        "MEMCORE_ZHIYI_API_KEY",
        "MEMCORE_ZHIYI_API_KEY_ENV",
        "MINIMAX_API_KEY",
        "MINIMAX_CN_API_KEY",
        "DEEPSEEK_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)
    root = tmp_path / "memcore"
    config_dir = root / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "zhiyi_model_binding.user.json").write_text(
        json.dumps(
            {
                "provider": "Hermes",
                "provider_id": "custom:minimax",
                "selected_option_id": "hermes-config:custom:minimax:MiniMax-M3",
                "model_name": "MiniMax-M3",
                "base_url": "",
                "api_key_env": "MEMCORE_ZHIYI_API_KEY",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("MEMCORE_ROOT", str(root))
    monkeypatch.setenv("MINIMAX_API_KEY", "dummy")

    cfg = default_model_config()

    assert cfg.provider == "minimax"
    assert cfg.model == "MiniMax-M3"
    assert cfg.base_url == "https://api.minimaxi.com/v1"
    assert cfg.api_key_env == "MINIMAX_API_KEY"
    assert cfg.api_key_present is True


def test_no_evidence_returns_unknown_without_model_call():
    result = run_evidence_bound_answer("What does the user prefer?", [], execute=True, client=lambda *_: (_ for _ in ()).throw(AssertionError("should not call")))

    assert result["contract"] == EVIDENCE_BOUND_MODEL_CONTRACT
    assert result["answer"] == "UNKNOWN"
    assert result["verdict"] == "unknown"
    assert result["unknown_reason"] == "no_evidence"
    assert result["model_call_performed"] is False
    assert result["raw_write_performed"] is False
    assert result["memory_write_performed"] is False
    assert result["platform_write_performed"] is False


def test_dry_run_builds_prompt_but_does_not_call_model():
    evidence = [{"source_id": "s1", "evidence_ref": "D1:1", "session_id": "D1", "text": "User prefers dark mode."}]
    result = run_evidence_bound_answer("What theme?", evidence, draft_answer="dark mode")

    assert result["verdict"] == "dry_run"
    assert result["answer"] == "UNKNOWN"
    assert result["model_call_performed"] is False
    assert result["draft_answer_present"] is True
    assert result["prompt_messages"][0]["role"] == "system"
    prompt_payload = json.loads(result["prompt_messages"][1]["content"])
    assert prompt_payload["draft_answer"] == "dark mode"
    assert prompt_payload["evidence"][0]["evidence_ref"] == "D1:1"
    assert prompt_payload["evidence"][0]["session_id"] == "D1"
    assert "Use only the supplied evidence." in prompt_payload["rules"]
    assert any("draft_answer is a candidate" in rule for rule in prompt_payload["rules"])
    assert any("same session" in rule for rule in prompt_payload["rules"])


def test_model_call_gating_skips_short_stable_draft_but_calls_for_noisy_draft():
    evidence = [{"source_id": "s1", "evidence_ref": "D1:1", "text": "The user's degree is Business Administration."}]

    skipped = plan_evidence_bound_answer_model_use(
        "What degree did I get?",
        evidence,
        draft_answer="Business Administration",
        policy="auto",
    )
    called = plan_evidence_bound_answer_model_use(
        "What degree did I get?",
        evidence * 4,
        draft_answer="I graduated with a degree in Business Administration, which has definitely helped me in my new role. Do you have any advice?",
        policy="auto",
    )

    assert skipped["should_call_model"] is False
    assert skipped["reason"] == "auto_skip_short_stable_draft"
    assert called["should_call_model"] is True
    assert "draft_too_long" in called["signals"]
    assert "draft_contains_chat_tail" in called["signals"]


def test_fake_client_answer_with_supporting_refs_is_accepted():
    evidence = [
        {
            "source_id": "case-1:D1:1",
            "evidence_ref": "D1:1",
            "text": "On Monday, user said the deployment target is NAS first.",
            "source_refs": {"source_system": "test", "line": 1},
        }
    ]

    def client(messages, config):
        assert messages
        assert config.api_key_present is False
        return {
            "content": json.dumps(
                {
                    "answer": "NAS first",
                    "verdict": "answered",
                    "confidence": 0.9,
                    "supporting_refs": ["D1:1"],
                    "unknown_reason": "",
                }
            )
        }

    result = run_evidence_bound_answer(
        "What is first?",
        evidence,
        model_config={"provider": "test", "model": "fake", "base_url": "", "api_key_env": ""},
        execute=True,
        client=client,
    )

    assert result["model_call_performed"] is True
    assert result["answer"] == "NAS first"
    assert result["verdict"] == "answered"
    assert result["supporting_refs"] == ["D1:1"]
    assert result["supporting_source_refs"] == [{"source_system": "test", "line": 1}]


def test_fake_client_hallucinated_ref_is_rejected_to_unknown():
    evidence = [{"source_id": "real-source", "evidence_ref": "D1:1", "text": "The user likes concise answers."}]

    def client(messages, config):
        return {
            "content": json.dumps(
                {
                    "answer": "The user likes verbose answers.",
                    "verdict": "answered",
                    "confidence": 0.8,
                    "supporting_refs": ["D9:9"],
                }
            )
        }

    result = run_evidence_bound_answer("What answer style?", evidence, execute=True, client=client)

    assert result["answer"] == "UNKNOWN"
    assert result["verdict"] == "unknown"
    assert result["supporting_refs"] == []
    assert result["validation_error"] == "supporting_refs_not_in_evidence"
    assert result["invalid_supporting_refs"] == ["D9:9"]


def test_answer_without_supporting_refs_is_rejected():
    evidence = [{"source_id": "real-source", "evidence_ref": "D1:1", "text": "The user likes concise answers."}]

    result = run_evidence_bound_answer(
        "What answer style?",
        evidence,
        execute=True,
        client=lambda *_: {"content": json.dumps({"answer": "Concise", "verdict": "answered", "confidence": 0.7, "supporting_refs": []})},
    )

    assert result["answer"] == "UNKNOWN"
    assert result["validation_error"] == "answer_without_supporting_refs"


def test_model_response_with_think_prefix_and_embedded_evidence_json_is_parsed():
    evidence = [{"source_id": "smoke-1", "evidence_ref": "smoke-1", "text": "The stated deployment target is NAS first."}]
    content = """
<think>
Evidence includes {"source_id": "smoke-1", "evidence_ref": "smoke-1"}.
</think>
{"answer":"NAS first","verdict":"answered","confidence":0.9,"supporting_refs":["smoke-1"],"unknown_reason":""}
"""

    result = run_evidence_bound_answer(
        "What deployment target?",
        evidence,
        execute=True,
        client=lambda *_: {"content": content},
    )

    assert result["answer"] == "NAS first"
    assert result["verdict"] == "answered"
    assert result["supporting_refs"] == ["smoke-1"]
    assert "validation_error" not in result


def test_experience_refinement_is_candidate_only_and_source_bound():
    evidence = [{"source_id": "s1", "evidence_ref": "D1:1", "text": "When MCP times out, first check platform scan before tuning recall."}]
    candidate = {"type": "case_memory", "summary": "MCP timeout handling"}

    result = run_evidence_bound_experience_refinement(
        candidate,
        evidence,
        execute=True,
        client=lambda *_: {
            "content": json.dumps(
                {
                    "verdict": "refined",
                    "summary": "MCP timeout triage starts with platform scan health.",
                    "detail": "Check platform scan health before changing recall ranking.",
                    "confidence": 0.86,
                    "supporting_refs": ["D1:1"],
                    "review_notes": "candidate only",
                }
            )
        },
    )

    assert result["verdict"] == "refined"
    assert result["summary"].startswith("MCP timeout triage")
    assert result["supporting_refs"] == ["D1:1"]
    assert result["memory_write_performed"] is False
    assert result["raw_write_performed"] is False


def test_prompt_builder_uses_json_only_source_bound_contract():
    messages = build_evidence_bound_answer_prompt(
        "Question?",
        [{"source_id": "s1", "evidence_ref": "D1:1", "text": "Answer is A."}],
    )

    payload = json.loads(messages[1]["content"])
    assert payload["response_schema"]["schema"] == "evidence_bound_answer.v1"
    assert payload["rules"][0] == "Use only the supplied evidence."
    assert payload["evidence"][0]["source_id"] == "s1"


def test_prompt_builder_marks_assistant_messages_as_context_not_user_fact():
    messages = build_evidence_bound_answer_prompt(
        "How much will I save by taking the bus instead of a taxi?",
        [
            {
                "source_id": "u1",
                "evidence_ref": "u1",
                "role": "user",
                "authority": "user_fact",
                "text": "user: The taxi costs around $60.",
            },
            {
                "source_id": "a1",
                "evidence_ref": "a1",
                "role": "assistant",
                "authority": "assistant_response",
                "text": "assistant: The bus might cost $10 to $20.",
            },
        ],
        question_context={"question_id": "q_abs"},
    )

    payload = json.loads(messages[1]["content"])

    assert payload["evidence"][0]["authority"] == "user_fact"
    assert payload["evidence"][1]["authority"] == "assistant_response"
    assert any("user's own messages are authoritative" in rule for rule in payload["rules"])
    assert any("assistant estimates or recommendations do not count" in rule for rule in payload["rules"])


def test_prompt_builder_blocks_missing_receipt_from_becoming_negative_fact():
    messages = build_evidence_bound_answer_prompt(
        "Has the remote release completed?",
        [{"source_id": "s1", "evidence_ref": "D1:1", "text": "The local tests passed, but no remote release receipt was found."}],
    )

    payload = json.loads(messages[1]["content"])
    joined_rules = " ".join(payload["rules"])
    assert "Absence of evidence is not evidence of absence" in joined_rules
    assert "receipt/proof is missing, answer UNKNOWN" in joined_rules
    assert "explicitly states it did not happen or failed" in joined_rules


def test_prompt_builder_adds_narrow_aggregation_rules_when_question_needs_it():
    messages = build_evidence_bound_answer_prompt(
        "How many items did I buy before the most recent trip?",
        [{"source_id": "s1", "evidence_ref": "D1:1", "text": "Bought shoes before the trip."}],
    )

    payload = json.loads(messages[1]["content"])
    joined_rules = " ".join(payload["rules"])
    assert "count, total, money, or difference questions" in joined_rules
    assert "candidate ledger" in joined_rules
    assert "exclude unrelated budgets/bids/prices/savings" in joined_rules
    assert "overly terse subset answers" in joined_rules
    assert "count plus concise labels/details" in joined_rules
    assert "calculation_items" in payload["response_schema"]
    assert "temporal, current-state, or most-recent questions" in joined_rules
    assert "older superseded values as included=false" in joined_rules
    assert payload["response_schema"]["calculation_notes"].startswith("short string")


def test_prompt_builder_adds_question_date_context_for_relative_time():
    messages = build_evidence_bound_answer_prompt(
        "How many days ago did I buy a smoker?",
        [{"source_id": "s1", "evidence_ref": "D1:1", "timestamp": "2023/03/15", "text": "I just got a smoker today."}],
        question_context={"question_date": "2023/03/25 (Sat) 21:28", "question_type": "temporal-reasoning"},
    )

    payload = json.loads(messages[1]["content"])
    joined_rules = " ".join(payload["rules"])
    assert payload["question_context"]["question_date"] == "2023/03/25 (Sat) 21:28"
    assert "question_context.question_date" in joined_rules
    assert "do not silently discard matching event/action evidence" in joined_rules
    assert "Preserve necessary answer qualifiers" in joined_rules
    assert "earliest dated qualifying event" in joined_rules


def test_prompt_builder_keeps_complete_single_fact_phrase():
    messages = build_evidence_bound_answer_prompt(
        "What game did I finally beat last weekend?",
        [{"source_id": "s1", "evidence_ref": "D1:1", "text": "I finally beat that last boss in the Dark Souls 3 DLC last weekend."}],
    )

    payload = json.loads(messages[1]["content"])
    joined_rules = " ".join(payload["rules"])
    assert "complete answer phrase" in joined_rules
    assert "DLC" in joined_rules
    assert "at a small startup" in joined_rules
    assert "full location hierarchy" in joined_rules
    assert "GPS system not functioning correctly" in joined_rules
    assert "Data Analysis using Python webinar" in joined_rules
    assert "Rachel and Mike" in joined_rules


def test_prompt_builder_adds_absence_rule_for_abs_questions():
    messages = build_evidence_bound_answer_prompt(
        "At which university did I present a poster for my undergrad course research project?",
        [{"source_id": "s1", "evidence_ref": "D1:1", "text": "I attended a conference at Harvard."}],
        question_context={"question_id": "a96c20ee_abs", "question_type": "multi-session"},
    )

    payload = json.loads(messages[1]["content"])
    joined_rules = " ".join(payload["rules"])
    assert "absence/insufficient-information question" in joined_rules
    assert "related but different fact" in joined_rules


def test_prompt_builder_adds_preference_profile_rules_for_preference_task():
    messages = build_evidence_bound_answer_prompt(
        "Can you suggest some accessories?",
        [{"source_id": "s1", "evidence_ref": "D1:1", "text": "The user uses a Sony camera."}],
        task_kind="preference_profile_answer",
    )

    payload = json.loads(messages[1]["content"])
    joined_rules = " ".join(payload["rules"])
    assert payload["task_kind"] == "preference_profile_answer"
    assert "preference-profile question" in joined_rules
    assert "Do not return a standalone recommendation list" in joined_rules
    assert "The user would prefer" in joined_rules


def test_fast_audit_dry_run_merges_top_and_pack_once():
    top = [{"source_id": "s1", "evidence_ref": "D1:1", "text": "Top says the user packed snacks."}]
    pack = [
        {"source_id": "s1", "evidence_ref": "D1:1", "text": "Top says the user packed snacks."},
        {"source_id": "s2", "evidence_ref": "D1:2", "text": "Pack says the user also went camping."},
    ]

    result = run_evidence_bound_fast_audit("What activity?", top, pack, draft_answer="camping")

    assert result["schema"] == EVIDENCE_BOUND_FAST_AUDIT_SCHEMA
    assert result["model_call_performed"] is False
    assert result["top_verdict"] == "dry_run"
    assert result["pack_verdict"] == "dry_run"
    assert result["combined_evidence_count"] == 2
    payload = json.loads(result["prompt_messages"][1]["content"])
    assert payload["task_kind"] == "fast_evidence_audit"
    assert payload["evidence"][0]["evidence_scope"] == "top+pack"
    assert payload["evidence"][1]["evidence_scope"] == "pack"
    assert payload["response_schema"]["schema"] == EVIDENCE_BOUND_FAST_AUDIT_SCHEMA
    assert any("evidence auditor" in rule for rule in payload["rules"])


def test_fast_audit_accepts_pack_supported_answer_from_single_call():
    top = [{"source_id": "top", "evidence_ref": "D1:1", "text": "Melanie packed snacks."}]
    pack = [
        {"source_id": "pack1", "evidence_ref": "D1:2", "text": "Melanie painted with her kids."},
        {"source_id": "pack2", "evidence_ref": "D1:4", "text": "Melanie also went camping with her family."},
    ]

    def client(messages, config):
        payload = json.loads(messages[1]["content"])
        assert payload["top_refs"] == ["D1:1"]
        assert payload["pack_refs"] == ["D1:2", "D1:4"]
        return {
            "content": json.dumps(
                {
                    "answer": "painting and camping",
                    "verdict": "answered",
                    "confidence": 0.9,
                    "supporting_refs": ["D1:2", "D1:4"],
                    "top_verdict": "unknown",
                    "pack_verdict": "answered",
                    "top_supporting_refs": [],
                    "pack_supporting_refs": ["D1:2", "D1:4"],
                    "needs_careful_mode": False,
                    "careful_reason": "",
                    "contradiction_detected": False,
                    "evidence_gap_reason": "top only mentions snacks",
                    "unknown_reason": "",
                }
            )
        }

    result = run_evidence_bound_fast_audit("What activities?", top, pack, execute=True, client=client)

    assert result["model_call_performed"] is True
    assert result["answer"] == "painting and camping"
    assert result["verdict"] == "answered"
    assert result["top_verdict"] == "unknown"
    assert result["pack_verdict"] == "answered"
    assert result["supporting_refs"] == ["D1:2", "D1:4"]
    assert result["pack_supporting_refs"] == ["D1:2", "D1:4"]
    assert result["needs_careful_mode"] is False


def test_fast_audit_rejects_refs_outside_scope():
    top = [{"source_id": "top", "evidence_ref": "D1:1", "text": "Top says snacks."}]
    pack = [{"source_id": "pack", "evidence_ref": "D1:2", "text": "Pack says camping."}]

    result = run_evidence_bound_fast_audit(
        "What activity?",
        top,
        pack,
        execute=True,
        client=lambda *_: {
            "content": json.dumps(
                {
                    "answer": "camping",
                    "verdict": "answered",
                    "confidence": 0.9,
                    "supporting_refs": ["D1:9"],
                    "top_verdict": "answered",
                    "pack_verdict": "answered",
                    "top_supporting_refs": ["D1:2"],
                    "pack_supporting_refs": ["D1:2"],
                }
            )
        },
    )

    assert result["answer"] == "UNKNOWN"
    assert result["verdict"] == "unknown"
    assert "supporting_refs_not_in_evidence" in result["validation_error"]
    assert "top_supporting_refs_not_in_top_evidence" in result["validation_error"]
    assert result["supporting_refs"] == []


def test_fast_audit_derives_scoped_refs_from_total_supporting_refs():
    top = [{"source_id": "top", "evidence_ref": "D1:1", "text": "Melanie packed snacks."}]
    pack = [{"source_id": "pack", "evidence_ref": "D1:2", "text": "Melanie went camping."}]

    result = run_evidence_bound_fast_audit(
        "What activity?",
        top,
        pack,
        execute=True,
        client=lambda *_: {
            "content": json.dumps(
                {
                    "answer": "camping",
                    "verdict": "answered",
                    "confidence": 0.8,
                    "supporting_refs": ["D1:2"],
                    "top_verdict": "unknown",
                    "pack_verdict": "answered",
                    "top_supporting_refs": [],
                    "pack_supporting_refs": [],
                    "needs_careful_mode": False,
                    "contradiction_detected": False,
                    "evidence_gap_reason": "top only has snacks",
                }
            )
        },
    )

    assert result["answer"] == "camping"
    assert result["supporting_refs"] == ["D1:2"]
    assert result["pack_supporting_refs"] == ["D1:2"]
    assert result["top_supporting_refs"] == []
    assert "validation_error" not in result


def test_evidence_object_state_dry_run_is_diagnostic_only():
    gold = [{"source_id": "g1", "evidence_ref": "D1:3", "text": "Caroline went to the support group yesterday."}]
    top = [{"source_id": "t1", "evidence_ref": "D2:4", "text": "Caroline talked about a book club."}]

    result = run_evidence_object_state_diagnostic(
        "When did Caroline go to the support group?",
        gold,
        top,
    )

    assert result["schema"] == EVIDENCE_OBJECT_STATE_DIAGNOSTIC_SCHEMA
    assert result["support_verdict"] == "dry_run"
    assert result["model_call_performed"] is False
    assert result["diagnostic_only"] is True
    assert result["ranking_unchanged"] is True
    assert result["memory_write_performed"] is False
    assert result["raw_write_performed"] is False
    payload = json.loads(result["prompt_messages"][1]["content"])
    assert payload["task_kind"] == "evidence_object_state_diagnostic"
    assert payload["gold_evidence"][0]["evidence_ref"] == "D1:3"
    assert payload["top_evidence"][0]["evidence_ref"] == "D2:4"


def test_evidence_object_state_fake_client_same_fact_is_accepted():
    gold = [{"source_id": "gold", "evidence_ref": "D1:3", "text": "Caroline went to the support group yesterday."}]
    top = [{"source_id": "top", "evidence_ref": "D1:3", "text": "Caroline went to the support group yesterday."}]

    result = run_evidence_object_state_diagnostic(
        "When did Caroline go to the support group?",
        gold,
        top,
        execute=True,
        client=lambda *_: {
            "content": json.dumps(
                {
                    "object_topic": "Caroline support group visit",
                    "state_fact": "Caroline went to the support group yesterday.",
                    "action_relation": "went to",
                    "time_hint": "historical",
                    "support_verdict": "same_fact",
                    "confidence": 0.88,
                    "gold_supporting_refs": ["D1:3"],
                    "top_supporting_refs": ["D1:3"],
                    "mismatch_reason": "",
                    "unknown_reason": "",
                }
            )
        },
    )

    assert result["support_verdict"] == "same_fact"
    assert result["gold_supporting_refs"] == ["D1:3"]
    assert result["top_supporting_refs"] == ["D1:3"]
    assert result["model_call_performed"] is True


def test_evidence_object_state_rejects_hallucinated_refs():
    gold = [{"source_id": "gold", "evidence_ref": "D1:3", "text": "Caroline went to the support group yesterday."}]
    top = [{"source_id": "top", "evidence_ref": "D2:4", "text": "Caroline talked about a book club."}]

    result = run_evidence_object_state_diagnostic(
        "When did Caroline go to the support group?",
        gold,
        top,
        execute=True,
        client=lambda *_: {
            "content": json.dumps(
                {
                    "object_topic": "Caroline support group visit",
                    "state_fact": "Caroline went to the support group yesterday.",
                    "action_relation": "went to",
                    "time_hint": "historical",
                    "support_verdict": "same_fact",
                    "confidence": 0.9,
                    "gold_supporting_refs": ["D9:9"],
                    "top_supporting_refs": ["D2:4"],
                }
            )
        },
    )

    assert result["support_verdict"] == "unknown"
    assert result["validation_error"] == "supporting_refs_not_in_evidence"
    assert result["gold_supporting_refs"] == []
    assert result["top_supporting_refs"] == []


def test_evidence_object_state_prompt_builder_uses_two_evidence_sets():
    messages = build_evidence_object_state_prompt(
        "Question?",
        [{"source_id": "g1", "evidence_ref": "D1:1", "text": "Gold fact."}],
        [{"source_id": "t1", "evidence_ref": "D2:1", "text": "Top fact."}],
        expected_answer="Gold answer",
    )

    payload = json.loads(messages[1]["content"])
    assert payload["response_schema"]["schema"] == EVIDENCE_OBJECT_STATE_DIAGNOSTIC_SCHEMA
    assert payload["gold_evidence"][0]["evidence_ref"] == "D1:1"
    assert payload["top_evidence"][0]["evidence_ref"] == "D2:1"
    assert payload["expected_answer"] == "Gold answer"
