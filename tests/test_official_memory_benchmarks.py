import json
import subprocess
import sys
from pathlib import Path

from src.evidence_bound_model import EVIDENCE_BOUND_MODEL_CONTRACT
from src.official_memory_benchmarks import (
    _answer_synthesis_for_mode,
    _answer_from_ranked_context,
    _answer_candidate_supplements_for_model,
    _ranked_context_to_evidence_items,
    _longmemeval_local_rough_alignment,
    _longmemeval_rough_alignment_match,
    _select_ranked_context_for_model,
    load_cases,
    normalize_locomo,
    run_official_evaluator_preflight,
    run_official_qa_trial,
    run_official_memory_diagnostic,
    run_retrieval_diagnostic,
)
from src.free_memory_benchmark import (
    FREE_BENCHMARK_CONTRACT,
    render_free_benchmark_markdown,
    run_free_memory_benchmark_suite,
)
from src.codex_memory_judge import (
    CODEX_JUDGE_CONTRACT,
    CODEX_JUDGE_SAMPLE_TIERS,
    LAYERED_SCORE_REPORT_CONTRACT,
    build_codex_judge_prompt,
    codex_judge_preflight,
    codex_judge_schema,
    load_longmemeval_judge_items,
    longmemeval_reference_alignment,
    run_codex_assisted_judge,
    select_longmemeval_judge_sample,
    write_codex_judge_outputs,
)
from tools.model_heavy_qa_runner import _load_case_id_filter


ROOT = Path(__file__).resolve().parents[1]


def test_model_heavy_runner_loads_case_id_filter_from_text_and_inline(tmp_path):
    path = tmp_path / "ids.txt"
    path.write_text("q1\n# comment\nq2\n", encoding="utf-8")

    assert _load_case_id_filter(str(path), "q3, q4") == {"q1", "q2", "q3", "q4"}


def test_adaptive_aggregation_pack_expands_model_evidence_for_count_questions():
    case = {
        "question_id": "q-count",
        "question": "How many projects have I led?",
        "question_type": "multi-session",
        "source_units": [],
    }
    ranked = [
        {
            "source_id": f"s{i}",
            "evidence_ref": f"s{i}",
            "session_id": f"session-{i}",
            "text": f"Project evidence {i}",
            "score": 1.0 / i,
        }
        for i in range(1, 61)
    ]
    seen = {}

    def client(messages, _config):
        payload = json.loads(messages[1]["content"])
        seen["evidence_count"] = len(payload["evidence"])
        return {
            "content": json.dumps(
                {
                    "answer": "2",
                    "verdict": "answered",
                    "confidence": 0.8,
                    "supporting_refs": ["s1"],
                }
            )
        }

    result = _answer_synthesis_for_mode(
        case,
        ranked,
        answer_mode="evidence-bound-model",
        run_answer_model=True,
        answer_model_call_policy="always",
        answer_model_max_evidence_items=20,
        answer_model_evidence_pack_mode="adaptive-aggregation",
        answer_model_client=client,
    )

    assert seen["evidence_count"] == 50
    assert result["model_max_evidence_items"] == 50
    assert result["model_requested_max_evidence_items"] == 20
    assert result["model_adaptive_aggregation_applied"] is True


def test_adaptive_aggregation_pack_frontloads_receipt_evidence_for_money_questions():
    case = {
        "question_id": "q-workshop-money",
        "question": "How much total money did I spend on attending workshops in the last four months?",
        "question_type": "multi-session",
        "source_units": [
            {
                "source_id": "q:s1:t1",
                "evidence_ref": "q:s1:t1",
                "session_id": "s1",
                "role": "user",
                "text": "user: I attended a half-day mindfulness workshop at a yoga studio. I paid $20 to attend.",
            },
            {
                "source_id": "q:s2:t1",
                "evidence_ref": "q:s2:t1",
                "session_id": "s2",
                "role": "user",
                "text": "user: I just attended a digital marketing workshop at the city convention center. I paid $500 to attend.",
            },
            {
                "source_id": "q:s3:t1",
                "evidence_ref": "q:s3:t1",
                "session_id": "s3",
                "role": "user",
                "text": "user: I attended a two-day writing workshop at a literary festival. I paid $200 to attend.",
            },
            {
                "source_id": "q:s4:t1",
                "evidence_ref": "q:s4:t1",
                "session_id": "s4",
                "role": "user",
                "text": "user: I set a daily budget of $20 for Facebook Ads after a workshop.",
            },
        ],
    }
    ranked = [
        {
            "source_id": "q:s4:t1",
            "evidence_ref": "q:s4:t1",
            "session_id": "s4",
            "role": "user",
            "text": "user: I set a daily budget of $20 for Facebook Ads after a workshop.",
            "score": 9.0,
        },
        {
            "source_id": "q:s1:t1",
            "evidence_ref": "q:s1:t1",
            "session_id": "s1",
            "role": "user",
            "text": "user: I attended a half-day mindfulness workshop at a yoga studio. I paid $20 to attend.",
            "score": 4.0,
        },
    ]

    selected = _select_ranked_context_for_model(
        case,
        ranked,
        max_items=5,
        pack_mode="adaptive-aggregation",
    )

    selected_ids = [item["source_id"] for item in selected]
    assert selected_ids[:3] == ["q:s1:t1", "q:s2:t1", "q:s3:t1"]
    assert "q:s4:t1" in selected_ids


def test_answer_candidate_supplement_frontloads_relevant_user_turns_without_gold_label():
    case = {
        "question_id": "q-current-sneakers",
        "question": "Where do I currently keep my old sneakers?",
        "question_type": "knowledge-update",
        "source_units": [
            {
                "source_id": "q:s1:t1",
                "evidence_ref": "q:s1:t1",
                "session_id": "s1",
                "role": "user",
                "text": "user: I used to keep my old sneakers under my bed for storage.",
                "metadata": {"has_answer": False},
            },
            {
                "source_id": "q:s2:t1",
                "evidence_ref": "q:s2:t1",
                "session_id": "s2",
                "role": "user",
                "text": "user: I need to organize my closet this weekend, and my old sneakers are currently in a shoe rack in my closet.",
                "metadata": {"has_answer": False},
            },
            {
                "source_id": "q:s2:t2",
                "evidence_ref": "q:s2:t2",
                "session_id": "s2",
                "role": "assistant",
                "text": "assistant: Here are many general closet organization tips.",
            },
        ],
    }
    ranked = [case["source_units"][2], case["source_units"][0]]

    supplements = _answer_candidate_supplements_for_model(case, ranked)
    selected = _select_ranked_context_for_model(
        case,
        ranked,
        max_items=3,
        pack_mode="adaptive-aggregation",
    )

    assert supplements[0]["source_id"] == "q:s2:t1"
    assert supplements[0]["model_answer_candidate_supplement_used"] is True
    assert [item["source_id"] for item in selected][:2] == ["q:s2:t1", "q:s1:t1"]


def test_answer_candidate_supplement_frontloads_attended_wedding_user_facts():
    case = {
        "question_id": "q-weddings",
        "question": "How many weddings have I attended in this year?",
        "question_type": "multi-session",
        "source_units": [
            {
                "source_id": "q:s1:t1",
                "evidence_ref": "q:s1:t1",
                "session_id": "s1",
                "role": "assistant",
                "text": "assistant: Here are generic wedding venue ideas and guest list tips.",
            },
            {
                "source_id": "q:s2:t1",
                "evidence_ref": "q:s2:t1",
                "session_id": "s2",
                "role": "user",
                "text": "user: I just got back from my college roommate's wedding in the city. My friend Emily finally got to tie the knot with her partner Sarah.",
            },
            {
                "source_id": "q:s3:t1",
                "evidence_ref": "q:s3:t1",
                "session_id": "s3",
                "role": "user",
                "text": "user: I need recommendations for my own wedding ceremony music.",
            },
        ],
    }

    selected = _select_ranked_context_for_model(
        case,
        [case["source_units"][0], case["source_units"][2]],
        max_items=3,
        pack_mode="adaptive-aggregation",
    )

    assert selected[0]["source_id"] == "q:s2:t1"
    assert selected[0]["model_answer_candidate_supplement_used"] is True


def test_ranked_context_to_evidence_items_infers_role_and_authority_from_text_prefix():
    evidence = _ranked_context_to_evidence_items(
        [
            {"source_id": "u1", "evidence_ref": "u1", "text": "user: The taxi cost was $60."},
            {"source_id": "a1", "evidence_ref": "a1", "text": "assistant: A bus may cost $10 to $20."},
        ]
    )

    assert evidence[0]["role"] == "user"
    assert evidence[0]["authority"] == "user_fact"
    assert evidence[1]["role"] == "assistant"
    assert evidence[1]["authority"] == "assistant_response"


def test_evidence_bound_model_prefers_user_fact_ref_over_numeric_draft():
    case = {
        "question_id": "q-bass",
        "question": "How many largemouth bass did I catch on my fishing trip to Lake Michigan?",
        "question_type": "single-session-user",
        "source_units": [],
    }
    ranked = [
        {
            "source_id": "q:s1:t1",
            "evidence_ref": "q:s1:t1",
            "session_id": "s1",
            "role": "assistant",
            "text": "assistant: Size 2 hooks are a common recommendation for largemouth bass.",
            "score": 9.0,
        },
        {
            "source_id": "q:s1:t2",
            "evidence_ref": "q:s1:t2",
            "session_id": "s1",
            "role": "user",
            "text": "user: I caught 12 largemouth bass on my last trip to Lake Michigan.",
            "score": 8.0,
        },
    ]

    def fake_draft(_case, _ranked):
        return {
            "answer": "2",
            "strategy": "extractive_synthesis:count",
            "supporting_refs": ["q:s1:t1", "q:s1:t2"],
        }

    def client(_messages, _config):
        return {
            "content": json.dumps(
                {
                    "answer": "12",
                    "verdict": "answered",
                    "confidence": 0.86,
                    "supporting_refs": ["q:s1:t2"],
                }
            )
        }

    import src.official_memory_benchmarks as bench

    original_draft = bench._answer_synthesis_from_ranked_context
    bench._answer_synthesis_from_ranked_context = fake_draft
    try:
        result = _answer_synthesis_for_mode(
            case,
            ranked,
            answer_mode="evidence-bound-model",
            run_answer_model=True,
            answer_model_call_policy="always",
            answer_model_evidence_pack_mode="adaptive-aggregation",
            answer_model_client=client,
        )
    finally:
        bench._answer_synthesis_from_ranked_context = original_draft

    assert result["extractive_draft_answer"] == "2"
    assert result["answer"] == "12"
    assert result["model_draft_fallback_applied"] is False
    assert result["model_user_fact_ref_confident"] is True


def test_evidence_bound_model_keeps_source_backed_aggregate_draft_when_model_undercounts():
    case = {
        "question_id": "q-workshop-money",
        "question": "How much total money did I spend on attending workshops in the last four months?",
        "question_type": "multi-session",
        "source_units": [
            {
                "source_id": "q:s1:t1",
                "evidence_ref": "q:s1:t1",
                "session_id": "s1",
                "role": "user",
                "text": "user: I attended a half-day mindfulness workshop at a yoga studio. I paid $20 to attend.",
            },
            {
                "source_id": "q:s2:t1",
                "evidence_ref": "q:s2:t1",
                "session_id": "s2",
                "role": "user",
                "text": "user: I just attended a digital marketing workshop at the city convention center. I paid $500 to attend.",
            },
            {
                "source_id": "q:s3:t1",
                "evidence_ref": "q:s3:t1",
                "session_id": "s3",
                "role": "user",
                "text": "user: I attended a two-day writing workshop at a literary festival. I paid $200 to attend.",
            },
        ],
    }
    ranked = list(case["source_units"])

    def client(_messages, _config):
        return {
            "content": json.dumps(
                {
                    "answer": "$220",
                    "verdict": "answered",
                    "confidence": 0.8,
                    "supporting_refs": ["q:s1:t1", "q:s3:t1"],
                    "calculation_items": [
                        {"label": "mindfulness workshop", "value": "$20", "included": True, "refs": ["q:s1:t1"]},
                        {"label": "writing workshop", "value": "$200", "included": True, "refs": ["q:s3:t1"]},
                    ],
                }
            )
        }

    result = _answer_synthesis_for_mode(
        case,
        ranked,
        answer_mode="evidence-bound-model",
        run_answer_model=True,
        answer_model_call_policy="always",
        answer_model_max_evidence_items=20,
        answer_model_evidence_pack_mode="adaptive-aggregation",
        answer_model_local_postprocess_policy="legacy",
        answer_model_client=client,
    )

    assert result["answer"] == "$720"
    assert result["supporting_refs"] == ["q:s1:t1", "q:s2:t1", "q:s3:t1"]
    assert result["model_draft_fallback_applied"] is True
    assert result["model_aggregation_draft_guardrail_applied"] is True
    assert result["model_calculation_items"][0]["label"] == "mindfulness workshop"


def test_evidence_bound_model_default_minimal_does_not_override_answered_model_with_aggregate_draft():
    case = {
        "question_id": "q-workshop-money",
        "question": "How much total money did I spend on attending workshops in the last four months?",
        "question_type": "multi-session",
        "source_units": [
            {
                "source_id": "q:s1:t1",
                "evidence_ref": "q:s1:t1",
                "session_id": "s1",
                "role": "user",
                "text": "user: I attended a half-day mindfulness workshop at a yoga studio. I paid $20 to attend.",
            },
            {
                "source_id": "q:s2:t1",
                "evidence_ref": "q:s2:t1",
                "session_id": "s2",
                "role": "user",
                "text": "user: I just attended a digital marketing workshop at the city convention center. I paid $500 to attend.",
            },
            {
                "source_id": "q:s3:t1",
                "evidence_ref": "q:s3:t1",
                "session_id": "s3",
                "role": "user",
                "text": "user: I attended a two-day writing workshop at a literary festival. I paid $200 to attend.",
            },
        ],
    }

    def client(_messages, _config):
        return {
            "content": json.dumps(
                {
                    "answer": "$220",
                    "verdict": "answered",
                    "confidence": 0.8,
                    "supporting_refs": ["q:s1:t1", "q:s3:t1"],
                }
            )
        }

    result = _answer_synthesis_for_mode(
        case,
        list(case["source_units"]),
        answer_mode="evidence-bound-model",
        run_answer_model=True,
        answer_model_call_policy="always",
        answer_model_max_evidence_items=20,
        answer_model_evidence_pack_mode="adaptive-aggregation",
        answer_model_client=client,
    )

    assert result["model_local_postprocess_policy"] == "minimal"
    assert result["answer"] == "$220"
    assert result["model_draft_fallback_applied"] is False
    assert result["model_aggregation_draft_guardrail_applied"] is False


def test_evidence_bound_model_prefers_source_backed_model_ledger_over_numeric_draft():
    case = {
        "question_id": "q-lake-bass",
        "question": "How many largemouth bass did I catch on my fishing trip to Lake Michigan?",
        "question_type": "single-session-user",
        "source_units": [],
    }
    ranked = [
        {
            "source_id": "q:s1:t1",
            "evidence_ref": "q:s1:t1",
            "session_id": "s1",
            "role": "user",
            "text": "user: I was exhausted after my Lake Michigan trip. I caught 2 smallmouth bass and 12 largemouth bass.",
            "score": 1.0,
        }
    ]

    def client(_messages, _config):
        return {
            "content": json.dumps(
                {
                    "answer": "12",
                    "verdict": "answered",
                    "confidence": 0.9,
                    "supporting_refs": ["q:s1:t1"],
                    "calculation_items": [
                        {
                            "label": "largemouth bass caught on Lake Michigan trip",
                            "value": 12,
                            "included": True,
                            "refs": ["q:s1:t1"],
                        }
                    ],
                }
            )
        }

    result = _answer_synthesis_for_mode(
        case,
        ranked,
        answer_mode="evidence-bound-model",
        run_answer_model=True,
        answer_model_call_policy="always",
        answer_model_evidence_pack_mode="adaptive-aggregation",
        answer_model_client=client,
    )

    assert result["extractive_draft_answer"] == "2"
    assert result["answer"] == "12"
    assert result["model_draft_fallback_applied"] is False
    assert result["model_aggregation_draft_guardrail_applied"] is False
    assert result["model_calculation_ledger_confident"] is True


def test_evidence_bound_model_prefers_latest_model_ledger_over_stale_draft():
    case = {
        "question_id": "q-camera-trips",
        "question": "How many trips have I taken my Canon EOS 80D camera on?",
        "question_type": "knowledge-update",
        "source_units": [],
    }
    ranked = [
        {
            "source_id": "q:s1:t1",
            "evidence_ref": "q:s1:t1",
            "session_id": "s1",
            "role": "user",
            "text": "user: I have 55 favorite travel photos from my Canon EOS 80D, and I used to say it had been on 3 trips.",
            "score": 1.0,
        },
        {
            "source_id": "q:s2:t1",
            "evidence_ref": "q:s2:t1",
            "session_id": "s2",
            "role": "user",
            "text": "user: Update: I've had my Canon EOS 80D with me on five trips now.",
            "score": 0.8,
        },
    ]

    def client(_messages, _config):
        return {
            "content": json.dumps(
                {
                    "answer": "5",
                    "verdict": "answered",
                    "confidence": 0.9,
                    "supporting_refs": ["q:s2:t1"],
                    "calculation_items": [
                        {
                            "label": "trips with Canon EOS 80D",
                            "value": "5",
                            "included": True,
                            "reason": "later update says five trips now",
                            "refs": ["q:s2:t1"],
                        },
                        {
                            "label": "earlier trip count",
                            "value": "3",
                            "included": False,
                            "reason": "superseded by later update",
                            "refs": ["q:s1:t1"],
                        },
                    ],
                }
            )
        }

    result = _answer_synthesis_for_mode(
        case,
        ranked,
        answer_mode="evidence-bound-model",
        run_answer_model=True,
        answer_model_call_policy="always",
        answer_model_evidence_pack_mode="adaptive-aggregation",
        answer_model_client=client,
    )

    assert result["extractive_draft_answer"] == "55"
    assert result["answer"] == "5"
    assert result["model_draft_fallback_applied"] is False
    assert result["model_aggregation_draft_guardrail_applied"] is False
    assert result["model_calculation_ledger_confident"] is True


def test_evidence_bound_model_expands_short_model_answer_from_source_phrase():
    case = {
        "question_id": "q-location",
        "question": "Where did I decide to study abroad?",
        "question_type": "single-session-user",
        "source_units": [],
    }
    ranked = [
        {
            "source_id": "q:s1:t1",
            "evidence_ref": "q:s1:t1",
            "session_id": "s1",
            "role": "user",
            "text": "user: I decided to study abroad at the University of Melbourne in Australia.",
            "score": 1.0,
        }
    ]

    def client(_messages, _config):
        return {
            "content": json.dumps(
                {
                    "answer": "the University of Melbourne",
                    "verdict": "answered",
                    "confidence": 0.86,
                    "supporting_refs": ["q:s1:t1"],
                }
            )
        }

    result = _answer_synthesis_for_mode(
        case,
        ranked,
        answer_mode="evidence-bound-model",
        run_answer_model=True,
        answer_model_call_policy="always",
        answer_model_local_postprocess_policy="legacy",
        answer_model_client=client,
    )

    assert result["answer"] == "the University of Melbourne in Australia"
    assert result["model_source_phrase_expander_applied"] is True
    assert result["model_source_phrase_expander_original_answer"] == "the University of Melbourne"
    assert result["model_source_phrase_expander_ref"] == "q:s1:t1"


def test_evidence_bound_model_default_minimal_does_not_expand_source_phrase():
    ranked = [
        {
            "source_id": "q:s1:t1",
            "evidence_ref": "q:s1:t1",
            "session_id": "s1",
            "role": "user",
            "text": "user: I decided to study abroad at the University of Melbourne in Australia.",
            "score": 1.0,
        }
    ]

    def client(_messages, _config):
        return {
            "content": json.dumps(
                {
                    "answer": "the University of Melbourne",
                    "verdict": "answered",
                    "confidence": 0.86,
                    "supporting_refs": ["q:s1:t1"],
                }
            )
        }

    result = _answer_synthesis_for_mode(
        {
            "question_id": "q-location",
            "question": "Where did I decide to study abroad?",
            "question_type": "single-session-user",
        },
        ranked,
        answer_mode="evidence-bound-model",
        run_answer_model=True,
        answer_model_call_policy="always",
        answer_model_client=client,
    )

    assert result["model_local_postprocess_policy"] == "minimal"
    assert result["answer"] == "the University of Melbourne"
    assert result["model_source_phrase_expander_applied"] is False


def test_evidence_bound_model_expands_country_from_same_turn_before_answer():
    ranked = [
        {
            "source_id": "q:s1:t1",
            "evidence_ref": "q:s1:t1",
            "session_id": "s1",
            "role": "user",
            "text": (
                "user: I've been to the Great Ocean Road before, and it's definitely a must-see in Australia. "
                "I actually went there with some friends during my study abroad program at the University of Melbourne."
            ),
            "score": 1.0,
        }
    ]

    def client(_messages, _config):
        return {
            "content": json.dumps(
                {
                    "answer": "the University of Melbourne",
                    "verdict": "answered",
                    "confidence": 0.86,
                    "supporting_refs": ["q:s1:t1"],
                }
            )
        }

    result = _answer_synthesis_for_mode(
        {
            "question_id": "q-study-abroad",
            "question": "Where did I attend for my study abroad program?",
            "question_type": "single-session-user",
        },
        ranked,
        answer_mode="evidence-bound-model",
        run_answer_model=True,
        answer_model_call_policy="always",
        answer_model_local_postprocess_policy="legacy",
        answer_model_client=client,
    )

    assert result["answer"] == "the University of Melbourne in Australia"
    assert result["model_source_phrase_expander_applied"] is True
    assert result["model_source_phrase_expander_reason"] == "answer_substring_with_same_turn_country_before_answer"


def test_evidence_bound_model_expands_dlc_and_small_startup_qualifiers():
    examples = [
        (
            "Which game expansion did I buy?",
            "user: I bought Dark Souls 3 DLC during the sale.",
            "Dark Souls 3",
            "Dark Souls 3 DLC",
        ),
        (
            "What job did I take?",
            "user: I took a marketing specialist at a small startup role.",
            "marketing specialist",
            "marketing specialist at a small startup role",
        ),
    ]
    for question, text, short_answer, expected_answer in examples:
        ranked = [
            {
                "source_id": "q:s1:t1",
                "evidence_ref": "q:s1:t1",
                "session_id": "s1",
                "role": "user",
                "text": text,
                "score": 1.0,
            }
        ]

        def client(_messages, _config, answer=short_answer):
            return {
                "content": json.dumps(
                    {
                        "answer": answer,
                        "verdict": "answered",
                        "confidence": 0.8,
                        "supporting_refs": ["q:s1:t1"],
                    }
                )
            }

        result = _answer_synthesis_for_mode(
            {"question_id": "q", "question": question, "question_type": "single-session-user"},
            ranked,
            answer_mode="evidence-bound-model",
            run_answer_model=True,
            answer_model_call_policy="always",
            answer_model_local_postprocess_policy="legacy",
            answer_model_client=client,
        )

        assert result["answer"] == expected_answer
        assert result["model_source_phrase_expander_applied"] is True


def test_evidence_bound_model_completes_bare_count_from_matching_ledger():
    case = {
        "question_id": "q-count-details",
        "question": "How many weddings have I attended this year?",
        "question_type": "multi-session",
        "source_units": [],
    }
    ranked = [
        {
            "source_id": "q:s1:t1",
            "evidence_ref": "q:s1:t1",
            "session_id": "s1",
            "role": "user",
            "text": "user: I attended Rachel and Mike's wedding.",
            "score": 1.0,
        },
        {
            "source_id": "q:s2:t1",
            "evidence_ref": "q:s2:t1",
            "session_id": "s2",
            "role": "user",
            "text": "user: I also attended Emily and Sarah's wedding.",
            "score": 1.0,
        },
        {
            "source_id": "q:s3:t1",
            "evidence_ref": "q:s3:t1",
            "session_id": "s3",
            "role": "user",
            "text": "user: Jen and Tom's wedding was last weekend.",
            "score": 1.0,
        },
    ]

    def client(_messages, _config):
        return {
            "content": json.dumps(
                {
                    "answer": "3",
                    "verdict": "answered",
                    "confidence": 0.82,
                    "supporting_refs": ["q:s1:t1", "q:s2:t1", "q:s3:t1"],
                    "calculation_items": [
                        {"label": "Rachel and Mike's wedding", "included": True, "refs": ["q:s1:t1"]},
                        {"label": "Emily and Sarah's wedding", "included": True, "refs": ["q:s2:t1"]},
                        {"label": "Jen and Tom's wedding", "included": True, "refs": ["q:s3:t1"]},
                    ],
                }
            )
        }

    result = _answer_synthesis_for_mode(
        case,
        ranked,
        answer_mode="evidence-bound-model",
        run_answer_model=True,
        answer_model_call_policy="always",
        answer_model_local_postprocess_policy="legacy",
        answer_model_client=client,
    )

    assert result["answer"] == "3: Rachel and Mike's wedding; Emily and Sarah's wedding; Jen and Tom's wedding"
    assert result["model_count_answer_completion_applied"] is True
    assert result["model_count_answer_completion_original_answer"] == "3"


def test_evidence_bound_model_default_minimal_does_not_complete_bare_count_from_ledger():
    case = {
        "question_id": "q-count-details",
        "question": "How many weddings have I attended this year?",
        "question_type": "multi-session",
        "source_units": [],
    }
    ranked = [
        {
            "source_id": "q:s1:t1",
            "evidence_ref": "q:s1:t1",
            "session_id": "s1",
            "role": "user",
            "text": "user: I attended Rachel and Mike's wedding.",
            "score": 1.0,
        },
        {
            "source_id": "q:s2:t1",
            "evidence_ref": "q:s2:t1",
            "session_id": "s2",
            "role": "user",
            "text": "user: I also attended Emily and Sarah's wedding.",
            "score": 1.0,
        },
        {
            "source_id": "q:s3:t1",
            "evidence_ref": "q:s3:t1",
            "session_id": "s3",
            "role": "user",
            "text": "user: Jen and Tom's wedding was last weekend.",
            "score": 1.0,
        },
    ]

    def client(_messages, _config):
        return {
            "content": json.dumps(
                {
                    "answer": "3",
                    "verdict": "answered",
                    "confidence": 0.82,
                    "supporting_refs": ["q:s1:t1", "q:s2:t1", "q:s3:t1"],
                    "calculation_items": [
                        {"label": "Rachel and Mike's wedding", "included": True, "refs": ["q:s1:t1"]},
                        {"label": "Emily and Sarah's wedding", "included": True, "refs": ["q:s2:t1"]},
                        {"label": "Jen and Tom's wedding", "included": True, "refs": ["q:s3:t1"]},
                    ],
                }
            )
        }

    result = _answer_synthesis_for_mode(
        case,
        ranked,
        answer_mode="evidence-bound-model",
        run_answer_model=True,
        answer_model_call_policy="always",
        answer_model_client=client,
    )

    assert result["model_local_postprocess_policy"] == "minimal"
    assert result["answer"] == "3"
    assert result["model_count_answer_completion_applied"] is False


def test_evidence_bound_model_deduplicates_emily_wedding_labels_when_completing_count():
    ranked = [
        {
            "source_id": "q:s1:t1",
            "evidence_ref": "q:s1:t1",
            "session_id": "s1",
            "role": "user",
            "text": "user: I attended Rachel's wedding, Emily's wedding, Emily and Sarah's wedding, and Jen and Tom's wedding.",
            "score": 1.0,
        }
    ]

    def client(_messages, _config):
        return {
            "content": json.dumps(
                {
                    "answer": "3",
                    "verdict": "answered",
                    "confidence": 0.82,
                    "supporting_refs": ["q:s1:t1"],
                    "calculation_items": [
                        {"label": "Rachel's vineyard wedding", "included": True, "refs": ["q:s1:t1"]},
                        {"label": "Cousin Emily's city wedding", "included": True, "refs": ["q:s1:t1"]},
                        {"label": "Emily and Sarah's wedding", "included": True, "refs": ["q:s1:t1"]},
                        {"label": "Jen and Tom's wedding", "included": True, "refs": ["q:s1:t1"]},
                    ],
                }
            )
        }

    result = _answer_synthesis_for_mode(
        {
            "question_id": "q-wedding-dedupe",
            "question": "How many weddings have I attended this year?",
            "question_type": "multi-session",
        },
        ranked,
        answer_mode="evidence-bound-model",
        run_answer_model=True,
        answer_model_call_policy="always",
        answer_model_local_postprocess_policy="legacy",
        answer_model_client=client,
    )

    assert result["answer"] == "3: Rachel's vineyard wedding; Emily and Sarah's wedding; Jen and Tom's wedding"
    assert result["model_count_answer_completion_applied"] is True


def test_evidence_bound_model_does_not_complete_count_when_ledger_count_mismatches_answer():
    ranked = [
        {
            "source_id": "q:s1:t1",
            "evidence_ref": "q:s1:t1",
            "session_id": "s1",
            "role": "user",
            "text": "user: I viewed A, B, C, and target D.",
            "score": 1.0,
        }
    ]

    def client(_messages, _config):
        return {
            "content": json.dumps(
                {
                    "answer": "3",
                    "verdict": "answered",
                    "confidence": 0.82,
                    "supporting_refs": ["q:s1:t1"],
                    "calculation_items": [
                        {"label": "A", "included": True, "refs": ["q:s1:t1"]},
                        {"label": "B", "included": True, "refs": ["q:s1:t1"]},
                        {"label": "C", "included": True, "refs": ["q:s1:t1"]},
                        {"label": "target D", "included": True, "refs": ["q:s1:t1"]},
                    ],
                }
            )
        }

    result = _answer_synthesis_for_mode(
        {
            "question_id": "q-count-mismatch",
            "question": "How many properties did I view before making an offer?",
            "question_type": "multi-session",
        },
        ranked,
        answer_mode="evidence-bound-model",
        run_answer_model=True,
        answer_model_call_policy="always",
        answer_model_local_postprocess_policy="legacy",
        answer_model_client=client,
    )

    assert result["answer"] == "3"
    assert result["model_count_answer_completion_applied"] is False


def test_evidence_bound_model_uses_preference_task_kind_for_preference_questions():
    case = {
        "question_id": "q-pref",
        "question": "Can you suggest some accessories that fit my setup?",
        "question_type": "single-session-preference",
        "source_units": [],
    }
    ranked = [
        {
            "source_id": "s1",
            "evidence_ref": "s1",
            "session_id": "session-1",
            "text": "user: I use a Sony A7R IV camera and want high-quality accessories.",
            "score": 1.0,
        }
    ]
    seen = {}

    def client(messages, _config):
        payload = json.loads(messages[1]["content"])
        seen["task_kind"] = payload["task_kind"]
        return {
            "content": json.dumps(
                {
                    "answer": "The user would prefer Sony-compatible high-quality accessories.",
                    "verdict": "answered",
                    "confidence": 0.8,
                    "supporting_refs": ["s1"],
                }
            )
        }

    result = _answer_synthesis_for_mode(
        case,
        ranked,
        answer_mode="evidence-bound-model",
        run_answer_model=True,
        answer_model_call_policy="always",
        answer_model_client=client,
    )

    assert seen["task_kind"] == "preference_profile_answer"
    assert result["model_task_kind"] == "preference_profile_answer"
    assert result["answer"].startswith("The user would prefer")


def test_evidence_bound_model_passes_question_context_to_answer_prompt():
    case = {
        "question_id": "q-time",
        "question": "How many days ago did I buy a smoker?",
        "question_type": "temporal-reasoning",
        "question_date": "2023/03/25 (Sat) 21:28",
        "source_units": [],
    }
    ranked = [
        {
            "source_id": "s1",
            "evidence_ref": "s1",
            "session_id": "session-1",
            "timestamp": "2023/03/15 (Wed) 10:44",
            "text": "user: I just got a smoker today.",
            "score": 1.0,
        }
    ]
    seen = {}

    def client(messages, _config):
        payload = json.loads(messages[1]["content"])
        seen["question_context"] = payload["question_context"]
        seen["rules"] = payload["rules"]
        return {
            "content": json.dumps(
                {
                    "answer": "10 days ago",
                    "verdict": "answered",
                    "confidence": 0.8,
                    "supporting_refs": ["s1"],
                }
            )
        }

    result = _answer_synthesis_for_mode(
        case,
        ranked,
        answer_mode="evidence-bound-model",
        run_answer_model=True,
        answer_model_call_policy="always",
        answer_model_client=client,
    )

    assert seen["question_context"]["question_date"] == "2023/03/25 (Sat) 21:28"
    assert seen["question_context"]["question_type"] == "temporal-reasoning"
    assert any("question_context.question_date" in rule for rule in seen["rules"])
    assert result["answer"] == "10 days ago"


def test_locomo_tiny_fixture_normalizes_and_hits_gold_evidence():
    path = ROOT / "tests" / "fixtures" / "locomo_tiny.json"
    cases = load_cases(dataset="locomo", data_path=path, max_questions=1)

    assert len(cases) == 1
    assert cases[0]["expected_source_refs"] == ["D1:2"]
    assert cases[0]["expected_session_ids"] == ["D1"]
    assert cases[0]["source_units"][1]["source_refs"]["source_system"] == "official_benchmark"

    result = run_retrieval_diagnostic(cases, top_k_values=[1, 3])

    assert result["mode"] == "retrieval_diagnostic"
    assert result["case_count"] == 1
    assert result["metrics"]["1"]["evidence_recall"] == 1.0
    assert result["metrics"]["1"]["source_recall"] == 1.0
    assert result["retrieval_mode"] == "rrf"
    assert result["context_window"] == 1
    assert result["metrics"]["1"]["near_source_recall"] == 0.0
    assert "internal_diagnostic_only" in result["notes"]
    assert "not_official_leaderboard_score" in result["notes"]
    assert "near_source_hit_is_not_exact_source_hit" in result["notes"]


def test_locomo_normalization_indexes_media_query_and_caption_fields():
    cases = normalize_locomo(
        [
            {
                "sample_id": "media-test",
                "conversation": {
                    "session_1_date_time": "8 May 2023",
                    "session_1": [
                        {
                            "speaker": "Melanie",
                            "dia_id": "D1:1",
                            "text": "By the way, take a look at this.",
                            "query": "painting sunrise",
                            "blip_caption": "a lake sunrise painting",
                            "img_url": ["https://example.test/sunrise.jpg"],
                        }
                    ],
                },
                "qa": [
                    {
                        "question": "Who shared a lake sunrise painting?",
                        "answer": "Melanie",
                        "evidence": ["D1:1"],
                        "category": 2,
                    }
                ],
            }
        ]
    )
    media_turn = cases[0]["source_units"][0]

    result = run_retrieval_diagnostic(
        cases,
        top_k_values=[1],
        retrieval_mode="bm25",
    )

    assert result["metrics"]["1"]["exact_source_recall"] == 1.0
    assert media_turn["metadata"]["query"] == "painting sunrise"
    assert "lake sunrise painting" in media_turn["searchable_text"]
    assert "sunrise.jpg" in media_turn["searchable_text"]
    assert "query" in media_turn["raw_index_fields"]
    assert "blip_caption" in media_turn["raw_index_fields"]
    assert "img_url" in result["per_case"][0]["top_results"][0]["raw_index_fields"]


def test_locomo_library_index_projection_is_navigation_only_and_source_backed():
    cases = normalize_locomo(
        [
            {
                "sample_id": "projection-test",
                "conversation": {
                    "session_1_date_time": "8 May 2023",
                    "session_1": [
                        {"speaker": "Caroline", "dia_id": "D1:1", "text": "We talked about generic planning."}
                    ],
                    "session_2_date_time": "9 May 2023",
                    "session_2": [
                        {"speaker": "Melanie", "dia_id": "D2:1", "text": "The answer is in this raw turn."}
                    ],
                },
                "session_summary": {
                    "session_1_summary": "Generic planning.",
                    "session_2_summary": "Melanie discussed the rare amber kiln decision.",
                },
                "event_summary": {
                    "events_session_2": {"Melanie": ["Melanie made a rare amber kiln decision."], "date": "9 May 2023"}
                },
                "observation": {
                    "session_2_observation": {
                        "Melanie": [["The rare amber kiln decision is important.", "D2:1"]]
                    }
                },
                "qa": [
                    {
                        "question": "Who discussed the rare amber kiln decision?",
                        "answer": "Melanie",
                        "evidence": ["D2:1"],
                        "category": 1,
                    }
                ],
            }
        ]
    )

    case = cases[0]
    assert case["library_index_units"][1]["session_id"] == "D2"
    assert "rare amber kiln" in case["library_index_units"][1]["searchable_text"]
    assert case["library_index_units"][1]["metadata"]["authority"] == "navigation_only_raw_turn_required"
    assert case["library_index_units"][1]["ai_readable_projection_profile"] == "five_shelf_ai_readable_projection.v2026.6.17"
    assert case["library_index_units"][1]["projection_layer"] == "L0_library_index_projection"
    assert case["library_index_units"][1]["source_authority_layer"] == "L2_raw_source_record"

    result = run_retrieval_diagnostic(
        cases,
        top_k_values=[1],
        retrieval_mode="library_index_bm25",
        library_index_candidates=1,
    )

    top = result["per_case"][0]["top_results"][0]
    assert result["metrics"]["1"]["exact_source_recall"] == 1.0
    assert top["source_id"] == "projection-test:D2:1"
    assert top["library_index_projection_used"] is True
    assert top["ai_readable_projection_profile"] == "five_shelf_ai_readable_projection.v2026.6.17"
    assert top["library_index_projection_layer"] == "L0_library_index_projection"
    assert top["source_authority_layer"] == "L2_raw_source_record"
    assert top["library_index_selected_sessions"] == ["D2"]
    assert top["library_index_authority"] == "navigation_only_raw_turn_required"
    assert top["library_index_raw_fallback"] is True


def test_locomo_observation_projection_routes_back_to_raw_turn():
    cases = normalize_locomo(
        [
            {
                "sample_id": "observation-projection-test",
                "conversation": {
                    "session_1_date_time": "8 May 2023",
                    "session_1": [
                        {"speaker": "Caroline", "dia_id": "D1:1", "text": "A short unrelated note."},
                        {"speaker": "Caroline", "dia_id": "D1:2", "text": "I keep the ceramic compass in my blue cabinet."},
                    ],
                    "session_2_date_time": "9 May 2023",
                    "session_2": [
                        {"speaker": "Melanie", "dia_id": "D2:1", "text": "A misleading cabinet comment without the answer."}
                    ],
                },
                "observation": {
                    "session_1_observation": {
                        "Caroline": [["Caroline stores the rare aurora keepsake in the blue cabinet.", "D1:2"]]
                    }
                },
                "qa": [
                    {
                        "question": "Where is Caroline's rare aurora keepsake?",
                        "answer": "blue cabinet",
                        "evidence": ["D1:2"],
                        "category": 1,
                    }
                ],
            }
        ]
    )

    result = run_retrieval_diagnostic(
        cases,
        top_k_values=[1],
        retrieval_mode="fused_library_index_bm25",
        library_index_candidates=1,
    )

    top = result["per_case"][0]["top_results"][0]
    assert result["metrics"]["1"]["exact_source_recall"] == 1.0
    assert top["evidence_ref"] == "D1:2"
    assert top["library_index_projection_raw_target_used"] is True
    assert top["library_index_projection_source_id"].startswith("observation-projection-test:observation:D1")
    assert top["library_index_authority"] == "rerank_hint_only_raw_turn_required"


def test_two_stage_session_scoped_bm25_keeps_session_receipt_and_raw_authority():
    cases = normalize_locomo(
        [
            {
                "sample_id": "two-stage-test",
                "conversation": {
                    "session_1_date_time": "8 May 2023",
                    "session_1": [
                        {"speaker": "Caroline", "dia_id": "D1:1", "text": "I chose the adoption agency because it supports LGBTQ families."},
                    ],
                    "session_2_date_time": "9 May 2023",
                    "session_2": [
                        {"speaker": "Caroline", "dia_id": "D2:1", "text": "Adoption agency adoption agency adoption agency process paperwork."},
                    ],
                },
                "session_summary": {
                    "session_1_summary": "Caroline explained why she chose an adoption agency.",
                    "session_2_summary": "Caroline discussed generic adoption paperwork.",
                },
                "qa": [
                    {
                        "question": "Why did Caroline choose the adoption agency?",
                        "answer": "it supports LGBTQ families",
                        "evidence": ["D1:1"],
                        "category": 4,
                    }
                ],
            }
        ]
    )

    result = run_retrieval_diagnostic(
        cases,
        top_k_values=[2],
        retrieval_mode="two_stage_session_scoped_bm25",
    )

    top = result["per_case"][0]["top_results"][1]
    assert result["metrics"]["2"]["exact_source_recall"] == 1.0
    assert top["retrieval_mode"] == "two_stage_session_scoped_bm25"
    assert top["two_stage_session_contract"] == "two_stage_session_scoped_bm25.v2026.6.19"
    assert top["two_stage_session_route"] == "fused_session_rrf"
    assert top["two_stage_final_evidence_authority"] == "raw_turn"
    assert "D1" in top["two_stage_selected_session_ids"]


def test_two_stage_session_internal_rerank_promotes_raw_neighbor_inside_selected_session():
    cases = normalize_locomo(
        [
            {
                "sample_id": "two-stage-session-internal-test",
                "conversation": {
                    "session_1_date_time": "8 May 2023",
                    "session_1": [
                        {"speaker": "Caroline", "dia_id": "D1:1", "text": "We discussed cedar planning in detail."},
                        {"speaker": "Melanie", "dia_id": "D1:2", "text": "The later decision was to use the staged rollout."},
                    ],
                    "session_2_date_time": "9 May 2023",
                    "session_2": [
                        {"speaker": "Caroline", "dia_id": "D2:1", "text": "A different cedar archive note without the decision."},
                    ],
                },
                "session_summary": {
                    "session_1_summary": "Caroline and Melanie discussed cedar planning and the later rollout decision.",
                    "session_2_summary": "Caroline mentioned a cedar archive note.",
                },
                "qa": [
                    {
                        "question": "What happened after cedar planning?",
                        "answer": "use the staged rollout",
                        "evidence": ["D1:2"],
                        "category": 4,
                    }
                ],
            }
        ]
    )

    result = run_retrieval_diagnostic(
        cases,
        top_k_values=[1],
        retrieval_mode="two_stage_session_internal_rerank_bm25",
        context_window=1,
    )

    top = result["per_case"][0]["top_results"][0]
    assert result["metrics"]["1"]["exact_source_recall"] == 1.0
    assert top["source_id"] == "two-stage-session-internal-test:D1:2"
    assert top["retrieval_mode"] == "two_stage_session_internal_rerank_bm25"
    assert top["two_stage_session_internal_contract"] == "two_stage_session_internal_rerank_bm25.v2026.6.19"
    assert top["two_stage_raw_turn_rank_source"] == "fused_library_index_bm25_with_directional_session_internal_supplements"
    assert top["two_stage_final_evidence_authority"] == "raw_turn"
    assert top["two_stage_internal_supplement_used"] is True
    assert top["two_stage_internal_supplement_policy"] == "directional_neighbor_only"
    assert top["session_internal_expanded_from"] == "two-stage-session-internal-test:D1:1"
    assert top["session_internal_distance"] == 1
    assert top["session_internal_direction_hint"] == "next"
    assert "D1" in top["two_stage_selected_session_ids"]


def test_locomo_compound_evidence_refs_are_expanded():
    cases = normalize_locomo(
        [
            {
                "sample_id": "compound-ref-test",
                "conversation": {
                    "session_1_date_time": "8 May 2023",
                    "session_1": [
                        {"speaker": "Caroline", "dia_id": "D1:1", "text": "A sunset painting is finished."},
                    ],
                    "session_2_date_time": "9 May 2023",
                    "session_2": [
                        {"speaker": "Melanie", "dia_id": "D2:1", "text": "Another sunset painting is finished."},
                    ],
                },
                "qa": [
                    {
                        "question": "What painting subject appears?",
                        "answer": "sunset",
                        "evidence": ["D1:1; D2:1"],
                        "category": 1,
                    }
                ],
            }
        ]
    )

    assert cases[0]["expected_source_refs"] == ["D1:1", "D2:1"]
    assert cases[0]["expected_session_ids"] == ["D1", "D2"]


def test_locomo_answer_support_diagnostic_marks_answer_text_without_exact_gold_ref():
    result = run_retrieval_diagnostic(
        [
            {
                "dataset": "locomo",
                "question_id": "answer-support",
                "question_type": "2",
                "question": "When did Melanie paint a sunrise?",
                "answer": "2022",
                "expected_source_refs": ["D1:1"],
                "expected_session_ids": ["D1"],
                "source_units": [
                    {
                        "source_id": "D1:2",
                        "session_id": "D1",
                        "evidence_ref": "D1:2",
                        "text": "Melanie: I painted that sunrise in 2022.",
                        "searchable_text": "Melanie: I painted that sunrise in 2022.",
                    },
                    {
                        "source_id": "D1:1",
                        "session_id": "D1",
                        "evidence_ref": "D1:1",
                        "text": "Caroline: Was that your own painting?",
                        "searchable_text": "Caroline: Was that your own painting?",
                    },
                ],
            }
        ],
        top_k_values=[1],
        retrieval_mode="bm25",
    )

    hit = result["per_case"][0]["hits"]["1"]
    assert hit["exact_source_hit"] is False
    assert hit["answer_supported_hit"] is True
    assert hit["answer_support"]["support_level"] == "top_result"
    assert hit["answer_support"]["matched_ref"] == "D1:2"
    assert result["metrics"]["1"]["exact_source_recall"] == 0.0
    assert result["metrics"]["1"]["answer_supported_recall"] == 1.0


def test_fused_library_index_keeps_raw_candidates_and_marks_hint_authority():
    cases = normalize_locomo(
        [
            {
                "sample_id": "fused-projection-test",
                "conversation": {
                    "session_1_date_time": "8 May 2023",
                    "session_1": [
                        {"speaker": "Caroline", "dia_id": "D1:1", "text": "The exact rare amber kiln decision is here."}
                    ],
                    "session_2_date_time": "9 May 2023",
                    "session_2": [
                        {"speaker": "Melanie", "dia_id": "D2:1", "text": "A misleading rare amber kiln side note."}
                    ],
                },
                "session_summary": {
                    "session_2_summary": "Melanie discussed the rare amber kiln decision.",
                },
                "qa": [
                    {
                        "question": "Where is the exact rare amber kiln decision?",
                        "answer": "D1",
                        "evidence": ["D1:1"],
                        "category": 1,
                    }
                ],
            }
        ]
    )

    result = run_retrieval_diagnostic(
        cases,
        top_k_values=[2],
        retrieval_mode="fused_library_index_bm25",
        library_index_candidates=1,
    )

    top_results = result["per_case"][0]["top_results"]
    assert result["metrics"]["2"]["exact_source_recall"] == 1.0
    assert {item["session_id"] for item in top_results} == {"D1", "D2"}
    assert top_results[0]["library_index_projection_used"] is True
    assert top_results[0]["library_index_authority"] == "rerank_hint_only_raw_turn_required"
    assert top_results[0]["ai_readable_projection_profile"] == "five_shelf_ai_readable_projection.v2026.6.17"
    assert top_results[0]["library_index_projection_layer"] == "L0_library_index_projection"
    assert top_results[0]["source_authority_layer"] == "L2_raw_source_record"


def test_longmemeval_tiny_fixture_normalizes_answer_session_and_turn():
    path = ROOT / "tests" / "fixtures" / "longmemeval_tiny.json"
    result = run_official_memory_diagnostic(
        dataset="longmemeval",
        split="oracle",
        data_path=path,
        top_k_values=[1, 5],
        retrieval_mode="bm25",
    )

    assert result["dataset"] == "longmemeval"
    assert result["split"] == "oracle"
    assert result["retrieval_mode"] == "bm25"
    assert result["case_count"] == 1
    assert result["metrics"]["1"]["evidence_recall"] == 1.0
    assert result["metrics"]["1"]["session_recall"] == 1.0
    assert result["full_qa_status"]["implemented"] is False
    assert result["full_qa_status"]["qa_trial_available"] is True
    assert "longmemeval_v2" in result["official_sources"]


def test_locomo_qa_trial_writes_official_compatible_output(tmp_path):
    path = ROOT / "tests" / "fixtures" / "locomo_tiny.json"
    out = tmp_path / "locomo_qa_trial.json"

    result = run_official_qa_trial(
        dataset="locomo",
        data_path=path,
        top_k=1,
        retrieval_mode="bm25",
        model_key="memcore_trial",
        output_path=out,
    )
    payload = json.loads(out.read_text(encoding="utf-8"))
    qa = payload[0]["qa"][0]

    assert result["mode"] == "official_qa_trial"
    assert result["dataset"] == "locomo"
    assert result["official_leaderboard_score"] is False
    assert result["metrics"]["question_count"] == 1
    assert result["metrics"]["prediction_key"] == "memcore_trial_prediction"
    assert result["metrics"]["official_like_local_recall"] == 1.0
    assert "memcore_trial_prediction" in qa
    assert "memcore_trial_f1" in qa
    assert qa["memcore_trial_context"] == ["D1:2"]
    assert result["official_evaluator_status"]["requires_official_script_for_public_reporting"] is True


def test_longmemeval_qa_trial_writes_hypothesis_jsonl_for_official_judge(tmp_path):
    path = ROOT / "tests" / "fixtures" / "longmemeval_tiny.json"
    out = tmp_path / "longmemeval_hyp.jsonl"

    result = run_official_qa_trial(
        dataset="longmemeval",
        split="oracle",
        data_path=path,
        top_k=1,
        retrieval_mode="bm25",
        output_path=out,
    )
    rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]

    assert result["mode"] == "official_qa_trial"
    assert result["dataset"] == "longmemeval"
    assert result["official_leaderboard_score"] is False
    assert result["official_evaluator_status"]["requires_llm_judge"] is True
    assert result["metrics"]["local_rough_alignment"]["official_leaderboard_score"] is False
    assert result["metrics"]["local_rough_alignment"]["score_type"] == "local_rough_numeric_literal_alignment"
    assert "src/evaluation/evaluate_qa.py gpt-4o" in result["official_evaluator_status"]["official_command"]
    assert rows[0]["question_id"] == "tiny_car_issue"
    assert "hypothesis" in rows[0]
    assert "memcore_context" in rows[0]


def test_longmemeval_qa_trial_can_use_evidence_bound_model_fake_client(tmp_path):
    path = ROOT / "tests" / "fixtures" / "longmemeval_tiny.json"
    out = tmp_path / "longmemeval_hyp_model.jsonl"

    def fake_client(messages, config):
        payload = json.loads(messages[1]["content"])
        ref = payload["evidence"][0]["evidence_ref"]
        assert payload["draft_answer"]
        return {
            "content": json.dumps(
                {
                    "answer": "GPS system issue",
                    "verdict": "answered",
                    "confidence": 0.91,
                    "supporting_refs": [ref],
                    "unknown_reason": "",
                }
            )
        }

    result = run_official_qa_trial(
        dataset="longmemeval",
        split="oracle",
        data_path=path,
        top_k=1,
        retrieval_mode="bm25",
        output_path=out,
        answer_mode="evidence-bound-model",
        run_answer_model=True,
        answer_model_client=fake_client,
    )
    rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]

    assert result["answer_mode"] == "evidence-bound-model"
    assert result["answer_model_contract"] == EVIDENCE_BOUND_MODEL_CONTRACT
    assert result["answer_model_calls_performed"] is True
    assert result["metrics"]["answer_model_call_stats"]["model_call_performed_count"] == 1
    assert result["metrics"]["answer_model_call_stats"]["gated_draft_count"] == 0
    assert result["official_leaderboard_score"] is False
    assert rows[0]["hypothesis"] == "GPS system issue"
    assert rows[0]["memcore_answer_mode"] == "evidence_bound_model"
    assert rows[0]["memcore_answer_model_call_performed"] is True
    assert rows[0]["memcore_answer_model_contract"] == EVIDENCE_BOUND_MODEL_CONTRACT
    assert rows[0]["memcore_answer_model_draft_answer_present"] is True
    assert rows[0]["memcore_extractive_draft_answer"]
    assert rows[0]["memcore_answer_supporting_refs"]


def test_evidence_bound_model_off_policy_does_not_fall_back_to_extractive_draft(tmp_path):
    path = ROOT / "tests" / "fixtures" / "longmemeval_tiny.json"
    out = tmp_path / "longmemeval_hyp_model_no_fallback.jsonl"

    result = run_official_qa_trial(
        dataset="longmemeval",
        split="oracle",
        data_path=path,
        top_k=1,
        retrieval_mode="bm25",
        output_path=out,
        answer_mode="evidence-bound-model",
        run_answer_model=True,
        answer_model_local_postprocess_policy="off",
        answer_model_client=lambda *_: {
            "content": json.dumps(
                {
                    "answer": "UNKNOWN",
                    "verdict": "insufficient_evidence",
                    "confidence": 0.2,
                    "supporting_refs": [],
                    "unknown_reason": "too conservative",
                }
            )
        },
    )
    rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]

    assert result["official_leaderboard_score"] is False
    assert result["answer_model_local_postprocess_policy"] == "off"
    assert rows[0]["hypothesis"] == "UNKNOWN"
    assert rows[0]["hypothesis"] != rows[0]["memcore_extractive_draft_answer"]
    assert rows[0]["memcore_answer_strategy"] == "evidence_bound_model:insufficient_evidence"
    assert rows[0]["memcore_answer_model_draft_fallback_applied"] is False
    assert rows[0]["memcore_answer_model_local_postprocess_policy"] == "off"
    assert rows[0]["memcore_answer_supporting_refs"] == []


def test_evidence_bound_model_default_uses_minimal_fallback_policy(tmp_path):
    path = ROOT / "tests" / "fixtures" / "longmemeval_tiny.json"
    out = tmp_path / "longmemeval_hyp_model_default_minimal.jsonl"

    result = run_official_qa_trial(
        dataset="longmemeval",
        split="oracle",
        data_path=path,
        top_k=1,
        retrieval_mode="bm25",
        output_path=out,
        answer_mode="evidence-bound-model",
        run_answer_model=True,
        answer_model_client=lambda *_: {
            "content": json.dumps(
                {
                    "answer": "UNKNOWN",
                    "verdict": "insufficient_evidence",
                    "confidence": 0.2,
                    "supporting_refs": [],
                    "unknown_reason": "too conservative",
                }
            )
        },
    )
    rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]

    assert result["answer_model_local_postprocess_policy"] == "minimal"
    assert rows[0]["memcore_answer_strategy"] == "evidence_bound_model:draft_fallback"
    assert rows[0]["memcore_answer_model_draft_fallback_applied"] is True
    assert rows[0]["memcore_answer_model_local_postprocess_policy"] == "minimal"


def test_evidence_bound_model_minimal_policy_allows_unknown_draft_fallback(tmp_path):
    path = ROOT / "tests" / "fixtures" / "longmemeval_tiny.json"
    out = tmp_path / "longmemeval_hyp_model_fallback.jsonl"

    result = run_official_qa_trial(
        dataset="longmemeval",
        split="oracle",
        data_path=path,
        top_k=1,
        retrieval_mode="bm25",
        output_path=out,
        answer_mode="evidence-bound-model",
        run_answer_model=True,
        answer_model_local_postprocess_policy="minimal",
        answer_model_client=lambda *_: {
            "content": json.dumps(
                {
                    "answer": "UNKNOWN",
                    "verdict": "insufficient_evidence",
                    "confidence": 0.2,
                    "supporting_refs": [],
                    "unknown_reason": "too conservative",
                }
            )
        },
    )
    rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]

    assert result["official_leaderboard_score"] is False
    assert result["answer_model_local_postprocess_policy"] == "minimal"
    assert rows[0]["hypothesis"] == rows[0]["memcore_extractive_draft_answer"]
    assert rows[0]["memcore_answer_strategy"] == "evidence_bound_model:draft_fallback"
    assert rows[0]["memcore_answer_model_draft_fallback_applied"] is True
    assert rows[0]["memcore_answer_model_local_postprocess_policy"] == "minimal"
    assert rows[0]["memcore_answer_supporting_refs"]


def test_evidence_bound_model_minimal_policy_never_overrides_answered_model_without_refs():
    ranked = [
        {
            "source_id": "q:s1:t1",
            "evidence_ref": "q:s1:t1",
            "session_id": "s1",
            "role": "user",
            "text": "user: I redeemed a $5 coupon on coffee creamer at Target.",
            "score": 1.0,
        }
    ]

    result = _answer_synthesis_for_mode(
        {
            "question_id": "q-coupon",
            "question": "Where did I redeem a $5 coupon on coffee creamer?",
            "question_type": "single-session-user",
            "source_units": ranked,
        },
        ranked,
        answer_mode="evidence-bound-model",
        run_answer_model=True,
        answer_model_call_policy="always",
        answer_model_local_postprocess_policy="minimal",
        answer_model_client=lambda *_: {
            "content": json.dumps(
                {
                    "answer": "grocery store",
                    "verdict": "answered",
                    "confidence": 0.65,
                    "supporting_refs": [],
                }
            )
        },
    )

    assert result["model_local_postprocess_policy"] == "minimal"
    assert result["answer"] == "UNKNOWN"
    assert result["supporting_refs"] == []
    assert result["model_draft_fallback_applied"] is False
    assert result["model_validation_error"] == "answer_without_supporting_refs"


def test_evidence_bound_model_minimal_policy_requires_source_backed_fallback():
    result = _answer_synthesis_for_mode(
        {
            "question_id": "q-no-evidence",
            "question": "Where did I leave my passport?",
            "question_type": "single-session-user",
            "source_units": [],
        },
        [],
        answer_mode="evidence-bound-model",
        run_answer_model=True,
        answer_model_call_policy="always",
        answer_model_local_postprocess_policy="minimal",
        answer_model_client=lambda *_: {
            "content": json.dumps(
                {
                    "answer": "UNKNOWN",
                    "verdict": "insufficient_evidence",
                    "confidence": 0.1,
                    "supporting_refs": [],
                    "unknown_reason": "no supporting evidence",
                }
            )
        },
    )

    assert result["model_local_postprocess_policy"] == "minimal"
    assert result["answer"] == "UNKNOWN"
    assert result["supporting_refs"] == []
    assert result["model_draft_fallback_applied"] is False


def test_evidence_bound_model_minimal_policy_does_not_rewrite_answer_text():
    ranked = [
        {
            "source_id": "q:s1:t1",
            "evidence_ref": "q:s1:t1",
            "session_id": "s1",
            "role": "user",
            "text": "user: During my study abroad program in Australia, I attended the University of Melbourne.",
            "score": 1.0,
        }
    ]

    def client(_messages, _config):
        return {
            "content": json.dumps(
                {
                    "answer": "the University of Melbourne",
                    "verdict": "answered",
                    "confidence": 0.88,
                    "supporting_refs": ["q:s1:t1"],
                    "calculation_items": [
                        {"label": "the University of Melbourne", "included": True, "refs": ["q:s1:t1"]}
                    ],
                }
            )
        }

    result = _answer_synthesis_for_mode(
        {
            "question_id": "q-school",
            "question": "Which university did I attend during my study abroad program?",
            "question_type": "single-session-user",
            "source_units": [],
        },
        ranked,
        answer_mode="evidence-bound-model",
        run_answer_model=True,
        answer_model_call_policy="always",
        answer_model_local_postprocess_policy="minimal",
        answer_model_client=client,
    )

    assert result["model_local_postprocess_policy"] == "minimal"
    assert result["answer"] == "the University of Melbourne"
    assert result["model_draft_fallback_applied"] is False
    assert result["model_source_phrase_expander_applied"] is False
    assert result["model_count_answer_completion_applied"] is False


def test_evidence_bound_model_auto_policy_can_skip_short_stable_draft(tmp_path):
    path = ROOT / "tests" / "fixtures" / "longmemeval_tiny.json"
    out = tmp_path / "longmemeval_hyp_model_auto.jsonl"

    result = run_official_qa_trial(
        dataset="longmemeval",
        split="oracle",
        data_path=path,
        top_k=1,
        retrieval_mode="bm25",
        output_path=out,
        answer_mode="evidence-bound-model",
        run_answer_model=True,
        answer_model_call_policy="auto",
        answer_model_client=lambda *_: (_ for _ in ()).throw(AssertionError("short stable draft should skip model")),
    )
    rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]

    assert result["answer_model_call_policy"] == "auto"
    assert result["metrics"]["answer_model_call_stats"]["model_call_performed_count"] == 0
    assert result["metrics"]["answer_model_call_stats"]["gated_draft_count"] == 1
    assert result["metrics"]["answer_model_call_stats"]["gating_reason_counts"]["auto_skip_short_stable_draft"] == 1
    assert rows[0]["memcore_answer_model_call_performed"] is False
    assert rows[0]["memcore_answer_strategy"] == "evidence_bound_model:gated_draft"
    assert rows[0]["memcore_answer_model_gating_policy"] == "auto"
    assert rows[0]["memcore_answer_model_gating_reason"] == "auto_skip_short_stable_draft"
    assert rows[0]["hypothesis"] == rows[0]["memcore_extractive_draft_answer"]


def test_longmemeval_local_rough_alignment_handles_literal_equivalents():
    assert _longmemeval_rough_alignment_match("4", "four") is True
    assert _longmemeval_rough_alignment_match("$2500", "$2,500") is True
    assert _longmemeval_rough_alignment_match("Yes.", "Yes") is True
    assert _longmemeval_rough_alignment_match("GPS system issue", "GPS system not functioning correctly") is True
    assert _longmemeval_rough_alignment_match("9 days", "One week. Answers ranging from 7 days to 10 days are also acceptable.") is True
    assert _longmemeval_rough_alignment_match(
        "Triple the amount paid.",
        "The painting is worth triple what I paid for it.",
    ) is True
    assert _longmemeval_rough_alignment_match(
        "3x what I paid.",
        "The painting is worth triple what I paid for it.",
    ) is True


def test_longmemeval_local_rough_alignment_handles_equivalent_evidence_gaps():
    assert _longmemeval_rough_alignment_match(
        "The available memory does not mention egg tarts.",
        "The information provided is not enough. You did not mention baking egg tarts.",
    ) is True
    assert _longmemeval_rough_alignment_match(
        "The available memory mentions Hawaii travel but does not mention Seattle trip duration.",
        "The information provided is not enough. You mentioned traveling for 10 days in Hawaii but did not mention anything about the trip to Seattle.",
    ) is True
    assert _longmemeval_rough_alignment_match(
        "The available memory does not mention violin practice.",
        "You did not mention this information. You mentioned practicing guitar everyday, but not violin.",
    ) is True
    assert _longmemeval_rough_alignment_match(
        "The available memory does not mention bus cost.",
        "The information provided is not enough. You did not mention how much will the bus take.",
    ) is True
    assert _longmemeval_rough_alignment_match(
        "The available memory does not mention bus cost.",
        "The information provided is not enough. You did not mention buying an iPad case.",
    ) is False


def test_longmemeval_answer_synthesis_extracts_issue_from_later_evidence():
    case = {
        "question": "What was the first issue I had with my new car after its first service?",
        "question_type": "temporal-reasoning",
    }
    ranked = [
        {
            "source_id": "q:s1:t1",
            "role": "user",
            "text": "user: I got my car serviced for the first time on March 15th, and it was a great experience.",
        },
        {
            "source_id": "q:s2:t4",
            "role": "assistant",
            "text": "assistant: That's great to hear that the dealership was able to fix your GPS issue!",
        },
    ]

    answer = _answer_from_ranked_context(case, ranked)

    assert "GPS" in answer
    assert "issue" in answer
    assert "serviced" not in answer


def test_longmemeval_answer_synthesis_extracts_personal_best_time():
    case = {
        "question": "What was my personal best time in the charity 5K run?",
        "question_type": "knowledge-update",
    }
    ranked = [
        {
            "source_id": "q:s2:t11",
            "role": "user",
            "text": "user: I'm hoping to beat my personal best time this time around.",
        },
        {
            "source_id": "q:s2:t1",
            "role": "user",
            "text": "user: I'm hoping to beat my personal best time of 25:50 this time around.",
        },
    ]

    assert _answer_from_ranked_context(case, ranked) == "25:50"


def test_longmemeval_answer_synthesis_selects_latest_state_updates_for_user_feel():
    examples = [
        (
            {
                "question": "For the coffee-to-water ratio in my French press, did I switch to more water per tablespoon of coffee, or less?",
                "question_type": "knowledge-update",
            },
            [
                {
                    "source_id": "q:answer_old_1:t1",
                    "role": "user",
                    "timestamp": "2023/05/20 (Sat) 09:00",
                    "text": "user: For my French press, I use 1 tablespoon of coffee every 6 ounces of water.",
                },
                {
                    "source_id": "q:answer_new_2:t1",
                    "role": "user",
                    "timestamp": "2023/05/21 (Sun) 09:00",
                    "text": "user: I changed my French press ratio to 1 tablespoon of coffee every 5 ounces of water.",
                },
            ],
            ("less", "5"),
        ),
        (
            {
                "question": "Do I go to the gym more frequently than I did previously?",
                "question_type": "knowledge-update",
            },
            [
                {
                    "source_id": "q:s1:t1",
                    "role": "user",
                    "text": "user: I go to the gym on Tuesdays, Thursdays, and Saturdays.",
                },
                {
                    "source_id": "q:s2:t1",
                    "role": "user",
                    "text": "user: I go to the gym four times a week now.",
                },
            ],
            ("Yes",),
        ),
        (
            {
                "question": "Did I mostly recently increase or decrease the limit on the number of cups of coffee in the morning?",
                "question_type": "knowledge-update",
            },
            [
                {
                    "source_id": "q:s1:t1",
                    "role": "user",
                    "text": "user: I cut back to just one cup of coffee in the morning.",
                },
                {
                    "source_id": "q:s2:t1",
                    "role": "user",
                    "text": "user: I increased the limit to two cups of coffee in the morning.",
                },
            ],
            ("increased", "2"),
        ),
        (
            {
                "question": "How often do I see my therapist, Dr. Smith?",
                "question_type": "knowledge-update",
            },
            [
                {
                    "source_id": "q:s1:t1",
                    "role": "user",
                    "text": "user: My therapy session with Dr. Smith is every two weeks.",
                },
                {
                    "source_id": "q:s2:t1",
                    "role": "user",
                    "text": "user: I see Dr. Smith every week now.",
                },
            ],
            ("every week",),
        ),
        (
            {
                "question": "How many Instagram followers do I currently have?",
                "question_type": "knowledge-update",
            },
            [
                {
                    "source_id": "q:s1:t1",
                    "role": "user",
                    "text": "user: I reached 500 followers on Instagram last week.",
                },
                {
                    "source_id": "q:s2:t1",
                    "role": "user",
                    "text": "user: I'm now at 600 followers on Instagram.",
                },
            ],
            ("600",),
        ),
        (
            {
                "question": "How many engineers do I lead when I just started my new role as Senior Software Engineer? How many engineers do I lead now?",
                "question_type": "knowledge-update",
            },
            [
                {
                    "source_id": "q:s1:t1",
                    "role": "user",
                    "text": "user: I just started as Senior Software Engineer, and I lead a team of 4 engineers.",
                },
                {
                    "source_id": "q:s2:t1",
                    "role": "user",
                    "text": "user: I now lead a team of five engineers.",
                },
            ],
            ("4", "5"),
        ),
        (
            {
                "question": "Where is the painting 'Ethereal Dreams' by Emma Taylor currently hanging?",
                "question_type": "knowledge-update",
            },
            [
                {
                    "source_id": "q:s1:t1",
                    "role": "user",
                    "text": "user: I put Ethereal Dreams above my living room sofa.",
                },
                {
                    "source_id": "q:s2:t1",
                    "role": "user",
                    "text": "user: I moved the Ethereal Dreams painting to my bedroom.",
                },
            ],
            ("bedroom",),
        ),
        (
            {
                "question": "How often do I play tennis with my friends at the local park previously? How often do I play now?",
                "question_type": "knowledge-update",
            },
            [
                {
                    "source_id": "q:s1:t1",
                    "role": "user",
                    "text": "user: I have weekly tennis sessions with friends at the local park.",
                },
                {
                    "source_id": "q:s2:t1",
                    "role": "user",
                    "text": "user: I'll play tennis with my friends this Sunday, like we do every other week.",
                },
            ],
            ("every week", "every other week"),
        ),
        (
            {
                "question": "How many stars do I need to reach the gold level on my Starbucks Rewards app?",
                "question_type": "knowledge-update",
            },
            [
                {
                    "source_id": "q:s1:t1",
                    "role": "assistant",
                    "text": "assistant: You need 300 stars to reach Gold.",
                },
                {
                    "source_id": "q:s2:t1",
                    "role": "user",
                    "text": "user: Actually, I need 120 stars to reach the gold level, not 300.",
                },
            ],
            ("120",),
        ),
        (
            {
                "question": "How many videos of Corey Schafer's Python programming series have I completed so far?",
                "question_type": "knowledge-update",
            },
            [
                {
                    "source_id": "q:s1:t1",
                    "role": "user",
                    "text": "user: I've completed 20 videos so far while watching Corey Schafer's Python programming series.",
                },
                {
                    "source_id": "q:s2:t1",
                    "role": "user",
                    "text": "user: I've completed 30 videos so far for Corey's series and will start the DataCamp course.",
                },
            ],
            ("30",),
        ),
        (
            {
                "question": "How many issues of National Geographic have I finished reading?",
                "question_type": "knowledge-update",
            },
            [
                {
                    "source_id": "q:s1:t1",
                    "role": "user",
                    "text": "user: I just finished my third National Geographic issue, and I'm currently on my fourth.",
                },
                {
                    "source_id": "q:s2:t1",
                    "role": "user",
                    "text": "user: I've been reading National Geographic and just finished my fifth issue.",
                },
            ],
            ("5",),
        ),
        (
            {
                "question": "How many pre-1920 American coins do I have in my collection?",
                "question_type": "knowledge-update",
            },
            [
                {
                    "source_id": "q:s1:t1",
                    "role": "user",
                    "timestamp": "2023/05/20 (Sat) 09:00",
                    "text": "user: I have a total of 37 coins in my pre-1920 American coins collection.",
                },
                {
                    "source_id": "q:s2:t1",
                    "role": "user",
                    "timestamp": "2023/05/24 (Wed) 09:00",
                    "text": "user: I just added a new coin to my collection of pre-1920 American coins - a 1915-S Barber quarter.",
                },
            ],
            ("38",),
        ),
    ]

    for case, ranked, expected_parts in examples:
        answer = _answer_from_ranked_context(case, ranked)
        for expected in expected_parts:
            assert expected in answer


def test_longmemeval_answer_synthesis_counts_pickups_and_returns_before_dates():
    case = {
        "question": "How many items of clothing do I need to pick up or return from a store?",
        "question_type": "multi-session",
    }
    ranked = [
        {
            "source_id": "q:s1:t5",
            "role": "user",
            "text": "user: I exchanged a pair of boots from Zara on 2/5, and I still need to pick up the new pair.",
        },
        {
            "source_id": "q:s2:t1",
            "role": "user",
            "text": "user: I still need to pick up my dry cleaning for the navy blue blazer.",
        },
    ]

    assert _answer_from_ranked_context(case, ranked) == "3"


def test_longmemeval_answer_synthesis_uses_relative_session_dates_for_first_event():
    examples = [
        (
            {
                "question": "Which event happened first, the purchase of the coffee maker or the malfunction of the stand mixer?",
                "question_type": "temporal-reasoning",
            },
            [
                {
                    "source_id": "q:s1:t1",
                    "role": "user",
                    "timestamp": "2023/05/22 (Mon) 09:38",
                    "text": "user: I bought my coffee maker about three weeks ago.",
                },
                {
                    "source_id": "q:s2:t1",
                    "role": "user",
                    "timestamp": "2023/05/22 (Mon) 11:58",
                    "text": "user: I had to take my stand mixer to a repair shop last month.",
                },
            ],
            "malfunction of the stand mixer",
        ),
        (
            {
                "question": "Which item did I purchase first, the dog bed for Max or the training pads for Luna?",
                "question_type": "temporal-reasoning",
            },
            [
                {
                    "source_id": "q:s1:t1",
                    "role": "user",
                    "timestamp": "2023/05/20 (Sat) 23:31",
                    "text": "user: I got a new Orthopedic Memory Foam dog bed for Max about three weeks ago from Petco.",
                },
                {
                    "source_id": "q:s2:t1",
                    "role": "user",
                    "timestamp": "2023/05/20 (Sat) 06:19",
                    "text": "user: I got eco-friendly training pads for Luna from Chewy.com about a month ago.",
                },
            ],
            "training pads for Luna",
        ),
        (
            {
                "question": "Which book did I finish reading first, 'The Hate U Give' or 'The Nightingale'?",
                "question_type": "temporal-reasoning",
            },
            [
                {
                    "source_id": "q:s1:t1",
                    "role": "user",
                    "timestamp": "2023/05/22 (Mon) 05:56",
                    "text": "user: I just finished 'The Hate U Give' for my book club two weeks ago.",
                },
                {
                    "source_id": "q:s2:t1",
                    "role": "user",
                    "timestamp": "2023/05/22 (Mon) 01:11",
                    "text": "user: I just finished reading three fiction novels, including 'The Nightingale'.",
                },
            ],
            "The Hate U Give",
        ),
    ]

    for case, ranked, expected in examples:
        assert _answer_from_ranked_context(case, ranked) == expected


def test_longmemeval_answer_synthesis_calculates_targeted_temporal_day_differences():
    examples = [
        (
            {
                "question": "How many days had passed between the 'Walk for Hunger' event and the 'Coastal Cleanup' event?",
                "question_type": "temporal-reasoning",
            },
            [
                {
                    "source_id": "q:s1:t1",
                    "role": "user",
                    "timestamp": "2023/03/14 (Tue) 03:58",
                    "text": "user: I just did the 'Walk for Hunger' 5K walk on February 21st.",
                },
                {
                    "source_id": "q:s2:t1",
                    "role": "user",
                    "timestamp": "2023/03/14 (Tue) 22:34",
                    "text": "user: I recently volunteered at the Coastal Cleanup event on March 7th.",
                },
            ],
            "14 days",
        ),
        (
            {
                "question": "How many days before I bought the iPhone 13 Pro did I attend the Holiday Market?",
                "question_type": "temporal-reasoning",
            },
            [
                {
                    "source_id": "q:s1:t1",
                    "role": "user",
                    "timestamp": "2023/12/10 (Sun) 11:49",
                    "text": "user: I got my iPhone 13 Pro from Best Buy on Black Friday.",
                },
                {
                    "source_id": "q:s2:t1",
                    "role": "user",
                    "timestamp": "2023/12/10 (Sun) 23:13",
                    "text": "user: I attended the annual Holiday Market at the local mall a week before Black Friday.",
                },
            ],
            "7 days",
        ),
        (
            {
                "question": "How many days had passed since I bought my Adidas running shoes when I realized one of the shoelaces on my old Converse sneakers had broken?",
                "question_type": "temporal-reasoning",
            },
            [
                {
                    "source_id": "q:s1:t1",
                    "role": "user",
                    "timestamp": "2023/02/03 (Fri) 03:08",
                    "text": "user: I got a new pair of Adidas running shoes on January 10th.",
                },
                {
                    "source_id": "q:s2:t1",
                    "role": "user",
                    "timestamp": "2023/02/03 (Fri) 23:38",
                    "text": "user: one of the shoelaces on my old Converse sneakers had broken on January 24th.",
                },
            ],
            "14 days",
        ),
        (
            {
                "question": "How many days did it take for me to find a house I loved after starting to work with Rachel?",
                "question_type": "temporal-reasoning",
            },
            [
                {
                    "source_id": "q:s1:t1",
                    "role": "user",
                    "text": "user: I started working with Rachel on 2/15 after we talked about my budget and preferred neighborhoods.",
                },
                {
                    "source_id": "q:s2:t1",
                    "role": "user",
                    "text": "user: I saw a house I loved on 3/1, though my first offer was $320,000.",
                },
            ],
            "15 days",
        ),
        (
            {
                "question": "How many days did it take for my laptop backpack to arrive after I bought it?",
                "question_type": "temporal-reasoning",
            },
            [
                {
                    "source_id": "q:s1:t1",
                    "role": "user",
                    "text": "user: I bought a laptop backpack from Amazon on 1/15.",
                },
                {
                    "source_id": "q:s2:t1",
                    "role": "user",
                    "text": "user: The laptop backpack arrived on 1/20 and has great padding.",
                },
            ],
            "5 days",
        ),
        (
            {
                "question": "How many days did it take for me to receive the new remote shutter release after I ordered it?",
                "question_type": "temporal-reasoning",
            },
            [
                {
                    "source_id": "q:s1:t1",
                    "role": "user",
                    "text": "user: I ordered a new remote shutter release on February 5th for night photography.",
                },
                {
                    "source_id": "q:s2:t1",
                    "role": "user",
                    "text": "user: The new remote shutter release arrived on February 10th.",
                },
            ],
            "5 days",
        ),
    ]

    for case, ranked, expected in examples:
        assert _answer_from_ranked_context(case, ranked) == expected


def test_longmemeval_answer_synthesis_calculates_remaining_pages_for_named_book():
    case = {
        "question": "How many pages do I have left to read in 'The Nightingale'?",
        "question_type": "multi-session",
    }
    ranked = [
        {
            "source_id": "q:s2:t1",
            "role": "user",
            "text": "user: I just got back to reading \"The Nightingale\" and I'm excited to finally finish it - it's a long one with 440 pages!",
        },
        {
            "source_id": "q:s1:t9",
            "role": "user",
            "text": "user: I'm currently on page 250 of 'The Nightingale' by Kristin Hannah.",
        },
        {
            "source_id": "q:s2:t2",
            "role": "assistant",
            "text": "assistant: You want to read 50 books by the end of the year.",
        },
    ]

    assert _answer_from_ranked_context(case, ranked) == "190"


def test_longmemeval_answer_synthesis_extracts_targeted_temporal_short_answers():
    vehicle_case = {
        "question": "Which vehicle did I take care of first in February, the bike or the car?",
        "question_type": "temporal-reasoning",
    }
    vehicle_ranked = [
        {
            "source_id": "q:s2:t1",
            "role": "user",
            "timestamp": "2023/03/10 (Fri) 22:50",
            "text": "user: I've been having some issues with my bike lately - in mid-February, I had to take it in for repairs because the gears were acting up.",
        },
        {
            "source_id": "q:s1:t1",
            "role": "user",
            "timestamp": "2023/03/10 (Fri) 08:11",
            "text": "user: I just washed my current Corolla on Monday, February 27th, after not doing so for over a month.",
        },
    ]
    shoes_case = {
        "question": "Which pair of shoes did I clean last month?",
        "question_type": "temporal-reasoning",
    }
    shoes_ranked = [
        {
            "source_id": "q:s1:t7",
            "role": "user",
            "timestamp": "2023/05/30 (Tue) 11:28",
            "text": "user: I'm glad I finally got around to cleaning my white Adidas sneakers last month, which I'd been meaning to do for weeks.",
        },
        {
            "source_id": "q:s1:t12",
            "role": "assistant",
            "text": "assistant: Keeping them fresh and clean will make them last longer.",
        },
    ]

    assert _answer_from_ranked_context(vehicle_case, vehicle_ranked) == "bike"
    assert _answer_from_ranked_context(shoes_case, shoes_ranked) == "white Adidas sneakers"


def test_longmemeval_answer_synthesis_extracts_short_answers_from_found_evidence():
    examples = [
        (
            {
                "question": "Where do I initially keep my old sneakers?",
                "question_type": "knowledge-update",
            },
            [
                {
                    "source_id": "q:s1:t3",
                    "role": "user",
                    "text": "user: By the way, I need to take care of my old sneakers, I've been keeping them under my bed for storage, and they're starting to smell.",
                },
                {
                    "source_id": "q:s1:t4",
                    "role": "assistant",
                    "text": "assistant: Keeping them under the bed can indeed cause them to smell.",
                },
            ],
            "under my bed",
        ),
        (
            {
                "question": "Did I finish reading 'The Nightingale' by Kristin Hannah?",
                "question_type": "knowledge-update",
            },
            [
                {
                    "source_id": "q:s2:t11",
                    "role": "user",
                    "text": "user: I loved \"The Nightingale\"! Yes, the ending was emotional, but it was also a perfect conclusion to the story.",
                }
            ],
            "Yes",
        ),
        (
            {
                "question": "Where did I get my guitar serviced?",
                "question_type": "knowledge-update",
            },
            [
                {
                    "source_id": "q:s2:t5",
                    "role": "user",
                    "text": "user: I remember the music shop on Main St where I got my guitar serviced, they're really good with guitar maintenance.",
                },
                {
                    "source_id": "q:s1:t10",
                    "role": "assistant",
                    "text": "assistant: You can use Google to find a good shop.",
                },
            ],
            "The music shop on Main St",
        ),
        (
            {
                "question": "Where am I planning to stay for my birthday trip to Hawaii?",
                "question_type": "knowledge-update",
            },
            [
                {
                    "source_id": "q:s2:t3",
                    "role": "user",
                    "text": "user: I'm actually planning to stay on Oahu, so the Hanauma Bay Nature Preserve and Shark's Cove sound perfect for me.",
                }
            ],
            "Oahu",
        ),
        (
            {
                "question": "What was my previous frequent flyer status on United Airlines before I got the current status?",
                "question_type": "knowledge-update",
            },
            [
                {
                    "source_id": "q:s1:t5",
                    "role": "user",
                    "timestamp": "2023/05/01 (Mon) 10:00",
                    "text": "user: I actually just hit 20,000 miles on United Airlines, which means I'm finally eligible for Premier Silver status.",
                },
                {
                    "source_id": "q:s2:t3",
                    "role": "user",
                    "timestamp": "2023/06/01 (Thu) 10:00",
                    "text": "user: Oh, and I do have a United Airlines MileagePlus account - I just reached Premier Gold status.",
                },
            ],
            "Premier Silver",
        ),
        (
            {
                "question": "How much time do I dedicate to coding exercises each day?",
                "question_type": "knowledge-update",
            },
            [
                {
                    "source_id": "q:s1:t5",
                    "role": "user",
                    "timestamp": "2023/05/01 (Mon) 10:00",
                    "text": "user: I've been dedicating about an hour each day to coding exercises.",
                },
                {
                    "source_id": "q:s2:t1",
                    "role": "user",
                    "timestamp": "2023/06/01 (Thu) 10:00",
                    "text": "user: I've been dedicating about two hours each day to coding exercises and I'm excited to see progress.",
                },
            ],
            "about two hours",
        ),
        (
            {
                "question": "What is my current record in the recreational volleyball league?",
                "question_type": "knowledge-update",
            },
            [
                {
                    "source_id": "q:s2:t1",
                    "role": "user",
                    "text": "user: Our volleyball team, the Net Ninjas, is doing well with a 5-2 record.",
                }
            ],
            "5-2",
        ),
        (
            {
                "question": "What type of vehicle model am I currently working on?",
                "question_type": "knowledge-update",
            },
            [
                {
                    "source_id": "q:s1:t1",
                    "role": "user",
                    "timestamp": "2023/05/01 (Mon) 10:00",
                    "text": "user: I'm working on a model of a Ford Mustang Shelby GT350R.",
                },
                {
                    "source_id": "q:s2:t3",
                    "role": "user",
                    "timestamp": "2023/06/01 (Thu) 10:00",
                    "text": "user: I have just wrapped up a model and switched to a Ford F-150 pickup truck.",
                },
            ],
            "Ford F-150 pickup truck",
        ),
        (
            {
                "question": "What new kitchen gadget did I invest in before getting the Air Fryer?",
                "question_type": "knowledge-update",
            },
            [
                {
                    "source_id": "q:s1:t3",
                    "role": "user",
                    "text": "user: I'm actually thinking of using my new Instant Pot to make some of these soups and stews.",
                },
                {
                    "source_id": "q:s2:t3",
                    "role": "user",
                    "text": "user: I'm actually thinking of using the Air Fryer I got yesterday to make some crispy sweet potato fries.",
                },
            ],
            "Instant Pot",
        ),
        (
            {
                "question": "I'm looking back at our previous chess game and I was wondering, what was the move you made after 27. Kg2 Bd5+?",
                "question_type": "single-session-assistant",
            },
            [
                {
                    "source_id": "q:s1:t20",
                    "role": "assistant",
                    "text": "assistant: 28. Kg3 would be my move.",
                }
            ],
            "28. Kg3",
        ),
        (
            {
                "question": "I was looking back at our previous conversation about buying unique engagement rings directly from designers. Can you remind me of the Instagram handle of the UK-based designer who works with unusual gemstones?",
                "question_type": "single-session-assistant",
            },
            [
                {
                    "source_id": "q:s1:t2",
                    "role": "assistant",
                    "text": "assistant: 1. Jessica Poole (@jessica\\_poole\\_jewellery): Jessica is a UK-based jewelry designer who works with unusual gemstones. 2. Lauren Hunt (@laurenhuntjewellery): Lauren is a New York-based jewelry designer.",
                }
            ],
            "@jessica_poole_jewellery",
        ),
        (
            {
                "question": "I was going through our previous chat. Can you remind me of the name of the last venue you recommended in the list of popular venues in Portland for indie music shows?",
                "question_type": "single-session-assistant",
            },
            [
                {
                    "source_id": "q:s1:t4",
                    "role": "assistant",
                    "text": "assistant: Sure! Here are some popular venues in Portland that are known to host indie music shows: 1. Mississippi Studios 2. Doug Fir Lounge 3. Wonder Ballroom 4. Crystal Ballroom 5. Holocene 6. Aladdin Theater 7. The Old Church 8. The Liquor Store 9. Alberta Street Pub 10. Revolution Hall",
                }
            ],
            "Revolution Hall",
        ),
        (
            {
                "question": "What breed is my dog?",
                "question_type": "single-session-user",
            },
            [
                {
                    "source_id": "q:s1:t9",
                    "role": "user",
                    "text": "user: I'm thinking of getting Max a new collar with a nice name tag. Do you have any recommendations for a good collar brand or type that would suit a Golden Retriever like Max?",
                }
            ],
            "Golden Retriever",
        ),
        (
            {
                "question": "How much RAM did I upgrade my laptop to?",
                "question_type": "single-session-user",
            },
            [
                {
                    "source_id": "q:s1:t3",
                    "role": "user",
                    "text": "user: Before the RAM upgrade to 16GB, I was getting around 6-7 hours of battery life.",
                }
            ],
            "16GB",
        ),
        (
            {
                "question": "Who did I have a conversation with about destiny?",
                "question_type": "single-session-user",
            },
            [
                {
                    "source_id": "q:s1:t1",
                    "role": "user",
                    "text": "user: I was just talking to my friend Sarah recently and she was saying how everything happens for a reason, which got me thinking about destiny.",
                },
                {
                    "source_id": "q:s1:t9",
                    "role": "user",
                    "text": "user: I've been thinking about my conversation with Sarah, and what she said about everything happening for a reason.",
                },
            ],
            "Sarah",
        ),
        (
            {
                "question": "Who gave me a new stand mixer as a birthday gift?",
                "question_type": "single-session-user",
            },
            [
                {
                    "source_id": "q:s1:t5",
                    "role": "user",
                    "text": "user: I actually got my new stand mixer as a birthday gift from my sister last month.",
                }
            ],
            "my sister",
        ),
        (
            {
                "question": "I received a piece of jewelry last Saturday from whom?",
                "question_type": "temporal-reasoning",
            },
            [
                {
                    "source_id": "q:s1:t1",
                    "role": "user",
                    "text": "user: I also got a stunning crystal chandelier from my aunt today, which used to belong to my grandmother.",
                }
            ],
            "my aunt",
        ),
        (
            {
                "question": "Who did I go with to the music event last Saturday?",
                "question_type": "temporal-reasoning",
            },
            [
                {
                    "source_id": "q:s3:t1",
                    "role": "user",
                    "text": "user: I just saw Queen live with Adam Lambert at the Prudential Center in Newark, NJ with my parents.",
                }
            ],
            "my parents",
        ),
        (
            {
                "question": "At which university did I present a poster on my thesis research?",
                "question_type": "multi-session",
            },
            [
                {
                    "source_id": "q:s2:t1",
                    "role": "user",
                    "text": "user: I've been to Harvard University to attend my first research conference and saw some interesting projects on AI in education.",
                },
                {
                    "source_id": "q:s3:t1",
                    "role": "user",
                    "text": "user: I actually just presented a poster on my thesis research at my first research conference over the summer.",
                },
            ],
            "Harvard University",
        ),
    ]

    for case, ranked, expected in examples:
        assert _answer_from_ranked_context(case, ranked) == expected


def test_longmemeval_answer_synthesis_avoids_vehicle_date_bleed_from_nearby_nouns():
    case = {
        "question": "Which vehicle did I take care of first in February, the bike or the car?",
        "question_type": "temporal-reasoning",
    }
    ranked = [
        {
            "source_id": "q:s2:t1",
            "role": "user",
            "timestamp": "2023/03/10 (Fri) 22:50",
            "text": "user: I'm thinking of getting a new bike rack for my car. By the way, I've been having some issues with my bike lately - in mid-February, I had to take it in for repairs because the gears were acting up.",
        },
        {
            "source_id": "q:s1:t1",
            "role": "user",
            "timestamp": "2023/03/10 (Fri) 08:11",
            "text": "user: I'm researching a new Corolla. By the way, I just washed my current Corolla on Monday, February 27th, after not doing so for over a month.",
        },
    ]

    assert _answer_from_ranked_context(case, ranked) == "bike"


def test_longmemeval_answer_synthesis_handles_temporal_long_tail_regressions():
    months_case = {
        "question": "How many months ago did I book the Airbnb in San Francisco?",
        "question_type": "temporal-reasoning",
    }
    months_ranked = [
        {
            "source_id": "q:s1:t1",
            "role": "user",
            "text": "user: I've had a great experience with Airbnb in the past, like when I stayed in Haight-Ashbury for my best friend's wedding and had to book three months in advance.",
        },
        {
            "source_id": "q:s2:t1",
            "role": "user",
            "text": "user: I've been to SF before, exactly two months ago, for my best friend's wedding - it was a 5-day trip.",
        },
    ]
    job_case = {
        "question": "How long have I been working before I started my current job at NovaTech?",
        "question_type": "temporal-reasoning",
    }
    job_ranked = [
        {
            "source_id": "q:s1:t3",
            "role": "user",
            "text": "user: I've been working professionally for 9 years and I'm currently using a physical notebook.",
        },
        {
            "source_id": "q:s2:t5",
            "role": "user",
            "text": "user: I've been working at NovaTech for about 4 years and 3 months now.",
        },
    ]
    book_group_case = {
        "question": "How long had I been a member of 'Book Lovers Unite' when I attended the meetup?",
        "question_type": "temporal-reasoning",
    }
    book_group_ranked = [
        {
            "source_id": "q:s2:t1",
            "role": "user",
            "timestamp": "2023/05/24 (Wed) 23:13",
            "text": "user: I attended a meetup organized by Book Lovers Unite last week where we discussed the book.",
        },
        {
            "source_id": "q:s1:t1",
            "role": "user",
            "timestamp": "2023/05/24 (Wed) 05:09",
            "text": "user: I recently joined a Facebook group called \"Book Lovers Unite\" three weeks ago and I've been loving the discussions.",
        },
    ]
    bbq_case = {
        "question": "What was the date on which I attended the first BBQ event in June?",
        "question_type": "temporal-reasoning",
    }
    bbq_ranked = [
        {
            "source_id": "q:s2:t1",
            "role": "user",
            "text": "user: I attended a backyard BBQ party at my colleague's house on the 3rd of June, and they had amazing BBQ sauces.",
        },
        {
            "source_id": "q:s1:t1",
            "role": "user",
            "text": "user: I recently used Sweet Baby Ray's at my friend's place last Saturday, which was on the 17th of June.",
        },
        {
            "source_id": "q:s2:t9",
            "role": "user",
            "text": "user: I made Korean-style BBQ on the 10th of June.",
        },
    ]

    assert _answer_from_ranked_context(months_case, months_ranked) == "5 months ago"
    assert _answer_from_ranked_context(job_case, job_ranked) == "4 years and 9 months"
    assert _answer_from_ranked_context(book_group_case, book_group_ranked) == "2 weeks"
    assert _answer_from_ranked_context(bbq_case, bbq_ranked) == "June 3rd"


def test_longmemeval_answer_synthesis_sums_targeted_book_durations_not_audiobook_lengths():
    case = {
        "question": "How long did I take to finish 'The Seven Husbands of Evelyn Hugo' and 'The Nightingale' combined?",
        "question_type": "temporal-reasoning",
    }
    ranked = [
        {
            "source_id": "q:s1:t8",
            "role": "assistant",
            "text": "assistant: The audiobook is 14 hours and 13 minutes long.",
        },
        {
            "source_id": "q:s2:t1",
            "role": "user",
            "text": "user: I just finished \"The Seven Husbands of Evelyn Hugo\", which took me two and a half weeks to finish.",
        },
        {
            "source_id": "q:s3:t1",
            "role": "user",
            "text": "user: I recently finished \"The Nightingale\" by Kristin Hannah, which took me three weeks to finish.",
        },
    ]

    assert _answer_from_ranked_context(case, ranked) == "5.5 weeks"


def test_longmemeval_answer_synthesis_extracts_targeted_temporal_durations():
    ikea_case = {
        "question": "How long did it take me to assemble the IKEA bookshelf?",
        "question_type": "temporal-reasoning",
    }
    ikea_ranked = [
        {
            "source_id": "q:s1:t8",
            "role": "assistant",
            "text": "assistant: IKEA coffee tables are often affordable and easy to assemble.",
        },
        {
            "source_id": "q:s1:t3",
            "role": "user",
            "text": "user: I just assembled an IKEA bookshelf recently and it took me 4 hours, which wasn't too bad.",
        },
    ]
    move_case = {
        "question": "How long did it take to move to the new apartment?",
        "question_type": "temporal-reasoning",
    }
    move_ranked = [
        {
            "source_id": "q:s1:t7",
            "role": "user",
            "text": "user: My new apartment is about 20 minutes away from my old place.",
        },
        {
            "source_id": "q:s1:t9",
            "role": "user",
            "text": "user: It took me and my friends around 5 hours to move everything into the new apartment.",
        },
    ]
    asylum_case = {
        "question": "How long did I wait for the decision on my asylum application?",
        "question_type": "temporal-reasoning",
    }
    asylum_ranked = [
        {
            "source_id": "q:s1:t5",
            "role": "user",
            "text": "user: It's crazy how long it took for my asylum application to get approved. Over a year of uncertainty was really tough.",
        },
        {
            "source_id": "q:s1:t4",
            "role": "assistant",
            "text": "assistant: A 15 minute search session can help you find rental listings.",
        },
    ]
    japan_case = {
        "question": "How long was I in Japan for?",
        "question_type": "temporal-reasoning",
    }
    japan_ranked = [
        {
            "source_id": "q:s1:t6",
            "role": "assistant",
            "text": "assistant: One Kyoto onsen is about 30 minutes away by train.",
        },
        {
            "source_id": "q:s1:t3",
            "role": "user",
            "text": "user: I visited Fushimi Inari Shrine when I was in Japan. I spent two weeks traveling solo around the country.",
        },
    ]
    instagram_case = {
        "question": "How much screen time have I been averaging on Instagram per day?",
        "question_type": "temporal-reasoning",
    }
    instagram_ranked = [
        {
            "source_id": "q:s1:t5",
            "role": "user",
            "text": "user: I've been averaging around 2 hours of screen time on Instagram per day, but I might set a time limit of 30 minutes per day.",
        },
    ]

    assert _answer_from_ranked_context(ikea_case, ikea_ranked) == "4 hours"
    assert _answer_from_ranked_context(move_case, move_ranked) == "5 hours"
    assert _answer_from_ranked_context(asylum_case, asylum_ranked) == "over a year"
    assert _answer_from_ranked_context(japan_case, japan_ranked) == "two weeks"
    assert _answer_from_ranked_context(instagram_case, instagram_ranked) == "2 hours"


def test_longmemeval_answer_synthesis_subtracts_event_age_from_current_duration():
    amp_case = {
        "question": "How long had I been taking guitar lessons when I bought the new guitar amp?",
        "question_type": "temporal-reasoning",
    }
    amp_ranked = [
        {
            "source_id": "q:s1:t1",
            "role": "user",
            "text": "user: I've been taking weekly guitar lessons with a new instructor for six weeks now.",
        },
        {
            "source_id": "q:s1:t7",
            "role": "user",
            "text": "user: I recently bought a new guitar amp two weeks ago, which has made a huge difference.",
        },
    ]
    rug_case = {
        "question": "How long had I been using the new area rug when I rearranged my living room furniture?",
        "question_type": "temporal-reasoning",
    }
    rug_ranked = [
        {
            "source_id": "q:s1:t1",
            "role": "user",
            "text": "user: I recently got a new area rug for my living room a month ago.",
        },
        {
            "source_id": "q:s2:t1",
            "role": "user",
            "text": "user: I recently rearranged the furniture three weeks ago.",
        },
    ]

    assert _answer_from_ranked_context(amp_case, amp_ranked) == "4 weeks"
    assert _answer_from_ranked_context(rug_case, rug_ranked) in {"7 days", "9 days", "1 week"}


def test_longmemeval_answer_synthesis_uses_source_dates_for_temporal_operators():
    birthday_case = {
        "question": "How many days before my best friend's birthday party did I order her gift?",
        "question_type": "temporal-reasoning",
    }
    birthday_ranked = [
        {
            "source_id": "q:s2:t5",
            "role": "user",
            "timestamp": "2022/05/15 (Sun) 16:58",
            "text": "user: I had a great time celebrating my best friend's 30th birthday party recently, it was on the 22nd of April.",
        },
        {
            "source_id": "q:s1:t7",
            "role": "user",
            "timestamp": "2022/05/15 (Sun) 17:17",
            "text": "user: I recently ordered a customized photo album from Shutterfly for my best friend's birthday. I ordered it on the 15th of April and it arrived on the 20th.",
        },
    ]
    trip_case = {
        "question": "Which trip did the narrator take first, the solo trip to Europe or the family road trip across the American Southwest?",
        "question_type": "temporal-reasoning",
    }
    trip_ranked = [
        {
            "source_id": "q:s2:t1",
            "role": "user",
            "timestamp": "2023/05/23 (Tue) 00:24",
            "text": "user: I've been to the Grand Canyon before with my family on a road trip across the American Southwest a few years ago.",
        },
        {
            "source_id": "q:s1:t11",
            "role": "user",
            "timestamp": "2023/05/23 (Tue) 16:49",
            "text": "user: I was just thinking about my solo trip to Europe last summer, where I spent two weeks backpacking.",
        },
    ]
    people_case = {
        "question": "Who did I meet first, Mark and Sarah or Tom?",
        "question_type": "temporal-reasoning",
    }
    people_ranked = [
        {
            "source_id": "q:s2:t1",
            "role": "user",
            "timestamp": "2023/05/28 (Sun) 02:02",
            "text": "user: A few months ago, I volunteered at a charity event and met a guy named Tom.",
        },
        {
            "source_id": "q:s1:t1",
            "role": "user",
            "timestamp": "2023/05/28 (Sun) 01:34",
            "text": "user: I'm planning a trip to visit my friends Mark and Sarah, who I met on a beach trip about a month ago.",
        },
    ]

    assert _answer_from_ranked_context(birthday_case, birthday_ranked) == "7 days"
    assert _answer_from_ranked_context(trip_case, trip_ranked) == "family road trip across the American Southwest"
    assert _answer_from_ranked_context(people_case, people_ranked) == "Tom"


def test_longmemeval_answer_synthesis_calculates_days_ago_from_question_date():
    service_case = {
        "question": "How many days ago did I attend the Maundy Thursday service at the Episcopal Church?",
        "question_date": "2023/04/10 (Mon) 07:43",
        "question_type": "temporal-reasoning",
    }
    service_ranked = [
        {
            "source_id": "q:s1:t7",
            "role": "user",
            "timestamp": "2023/04/06 (Thu) 19:35",
            "text": "user: I'm glad I got to attend the Maundy Thursday service at the Episcopal Church today.",
        },
        {
            "source_id": "q:s1:t8",
            "role": "assistant",
            "timestamp": "2023/04/06 (Thu) 19:35",
            "text": "assistant: Phone: 555-555-5555. Address: 123 Main St.",
        },
    ]
    smoker_case = {
        "question": "How many days ago did I buy a smoker?",
        "question_date": "2023/03/25 (Sat) 21:28",
        "question_type": "temporal-reasoning",
    }
    smoker_ranked = [
        {
            "source_id": "q:s1:t3",
            "role": "user",
            "timestamp": "2023/03/15 (Wed) 10:44",
            "text": "user: I just got a smoker today and I'm excited to experiment with different types of wood and meats.",
        },
        {
            "source_id": "q:s1:t6",
            "role": "assistant",
            "timestamp": "2023/03/15 (Wed) 10:44",
            "text": "assistant: Wood chips are typically 1-2 inches long and 1/4 inch thick.",
        },
    ]

    assert _answer_from_ranked_context(service_case, service_ranked) == "4 days ago"
    assert _answer_from_ranked_context(smoker_case, smoker_ranked) == "10 days ago"


def test_longmemeval_answer_synthesis_formats_source_date_ago_naturally():
    workshop_case = {
        "question": "How many weeks ago did I attend a bird watching workshop at the local Audubon society?",
        "question_date": "2023/05/01 (Mon) 08:00",
        "question_type": "temporal-reasoning",
    }
    workshop_ranked = [
        {
            "source_id": "q:s1:t1",
            "role": "user",
            "timestamp": "2023/04/01 (Sat) 08:00",
            "text": "user: I attended a bird watching workshop at the local Audubon society today.",
        }
    ]
    festival_case = {
        "question": "How many months ago did I attend the Seattle International Film Festival?",
        "question_date": "2023/06/15 (Thu) 08:00",
        "question_type": "temporal-reasoning",
    }
    festival_ranked = [
        {
            "source_id": "q:s1:t1",
            "role": "user",
            "timestamp": "2023/02/12 (Sun) 08:00",
            "text": "user: I attended the Seattle International Film Festival today and saw three documentaries.",
        }
    ]

    assert _answer_from_ranked_context(workshop_case, workshop_ranked) == "about 4 weeks ago"
    assert _answer_from_ranked_context(festival_case, festival_ranked) == "4 months ago"


def test_longmemeval_answer_synthesis_calculates_days_ago_relative_to_when_event():
    baking_case = {
        "question": "How many days ago did I attend a baking class at a local culinary school when I made my friend's birthday cake?",
        "question_date": "2022/04/15 (Fri) 14:21",
        "question_type": "temporal-reasoning",
    }
    baking_ranked = [
        {
            "source_id": "q:s2:t3",
            "role": "user",
            "timestamp": "2022/03/21 (Mon) 01:22",
            "text": "user: I've been obsessed with strawberries lately, especially after that amazing baking class I took at a local culinary school yesterday.",
        },
        {
            "source_id": "q:s1:t11",
            "role": "user",
            "timestamp": "2022/04/10 (Sun) 13:30",
            "text": "user: By the way, I just baked a chocolate cake for my friend's birthday party today that turned out amazing.",
        },
    ]
    website_case = {
        "question": "How many days ago did I launch my website when I signed a contract with my first client?",
        "question_date": "2023/03/25 (Sat) 17:23",
        "question_type": "temporal-reasoning",
    }
    website_ranked = [
        {
            "source_id": "q:s2:t1",
            "role": "user",
            "timestamp": "2023/03/01 (Wed) 16:51",
            "text": "user: I just signed a contract with my first client today, and I want to make sure I'm covering all my bases.",
        },
        {
            "source_id": "q:s1:t1",
            "role": "user",
            "timestamp": "2023/02/10 (Fri) 22:17",
            "text": "user: By the way, I just launched my website and created a business plan outline.",
        },
    ]

    assert _answer_from_ranked_context(baking_case, baking_ranked) == "21 days ago"
    assert _answer_from_ranked_context(website_case, website_ranked) == "19 days ago"


def test_longmemeval_answer_synthesis_prefers_event_timestamps_for_day_gaps():
    moma_case = {
        "question": "How many days passed between my visit to the Museum of Modern Art (MoMA) and the 'Ancient Civilizations' exhibit at the Metropolitan Museum of Art?",
        "question_date": "2023/02/01 (Wed) 13:01",
        "question_type": "temporal-reasoning",
    }
    moma_ranked = [
        {
            "source_id": "q:s2:t7",
            "role": "user",
            "timestamp": "2023/01/15 (Sun) 11:23",
            "text": 'user: I attended the "Ancient Civilizations" exhibit at the Metropolitan Museum of Art today.',
        },
        {
            "source_id": "q:s1:t1",
            "role": "user",
            "timestamp": "2023/01/08 (Sun) 06:46",
            "text": "user: I just got back from a guided tour at the Museum of Modern Art focused on 20th-century modern art movements.",
        },
        {
            "source_id": "q:s2:t10",
            "role": "assistant",
            "timestamp": "2023/01/15 (Sun) 11:23",
            "text": "assistant: The museum offers adult tours that can be booked from May 15.",
        },
    ]
    gardening_case = {
        "question": "How many days passed between the day I attended the gardening workshop and the day I planted the tomato saplings?",
        "question_date": "2023/05/08 (Mon) 21:01",
        "question_type": "temporal-reasoning",
    }
    gardening_ranked = [
        {
            "source_id": "q:s2:t1",
            "role": "user",
            "timestamp": "2023/04/21 (Fri) 20:28",
            "text": "user: I just planted 12 new tomato saplings today and I'm excited to see them grow.",
        },
        {
            "source_id": "q:s1:t1",
            "role": "user",
            "timestamp": "2023/04/15 (Sat) 18:09",
            "text": "user: I attended a gardening workshop in my neighborhood today where I learned about companion planting.",
        },
        {
            "source_id": "q:s2:t6",
            "role": "assistant",
            "timestamp": "2023/04/21 (Fri) 20:28",
            "text": "assistant: Water tomatoes in the morning; many gardeners start around May 15.",
        },
    ]

    assert _answer_from_ranked_context(moma_case, moma_ranked) == "7 days"
    assert _answer_from_ranked_context(gardening_case, gardening_ranked) == "6 days"


def test_longmemeval_answer_synthesis_handles_source_date_temporal_regressions():
    charity_case = {
        "question": "How many charity events did I participate in before the 'Run for the Cure' event?",
        "question_type": "temporal-reasoning",
    }
    charity_ranked = [
        {
            "source_id": "q:s1:t1",
            "role": "user",
            "timestamp": "2023/11/29 (Wed) 05:58",
            "text": 'user: I just ran 5 kilometers in the "Run for the Cure" event on October 15th and raised $250 for breast cancer research.',
        },
        {
            "source_id": "q:s6:t9",
            "role": "user",
            "timestamp": "2023/11/29 (Wed) 22:37",
            "text": 'user: I already participated in a dance marathon, the "Dance for a Cause" event on May 1st, where I danced for 6 hours to raise money for a local arts program.',
        },
        {
            "source_id": "q:s4:t1",
            "role": "user",
            "timestamp": "2023/11/29 (Wed) 13:02",
            "text": "user: I attended a charity golf tournament on July 17th, and while I had a blast playing with colleagues, I realized I need to work on my swing.",
        },
        {
            "source_id": "q:s2:t1",
            "role": "user",
            "timestamp": "2023/11/29 (Wed) 00:23",
            "text": 'user: I volunteered at the "Food for Thought" charity gala on September 25th, which was a great experience.',
        },
        {
            "source_id": "q:s5:t1",
            "role": "user",
            "timestamp": "2023/11/29 (Wed) 11:35",
            "text": "user: I volunteered at the Walk for Wildlife event in June, where we raised awareness and funds for conservation efforts.",
        },
    ]
    airline_case = {
        "question": "Which airline did I fly with the most in March and April?",
        "question_type": "temporal-reasoning",
    }
    airline_ranked = [
        {
            "source_id": "q:s2:t8",
            "role": "assistant",
            "timestamp": "2023/04/27 (Thu) 05:20",
            "text": "assistant: If you're flying with American Airlines, you can earn miles through their loyalty program.",
        },
        {
            "source_id": "q:s1:t3",
            "role": "user",
            "timestamp": "2023/04/27 (Thu) 13:15",
            "text": "user: In March, I took a business trip to Chicago with United Airlines, flying from my hometown to Chicago on the 10th and returning on the 12th, with two flights each way.",
        },
        {
            "source_id": "q:s3:t1",
            "role": "user",
            "timestamp": "2023/04/27 (Thu) 20:28",
            "text": "user: I took a direct flight with Southwest Airlines from my hometown to Las Vegas for a conference in March, from the 15th to the 18th.",
        },
        {
            "source_id": "q:s2:t1",
            "role": "user",
            "timestamp": "2023/04/27 (Thu) 05:20",
            "text": "user: We flew with American Airlines from our hometown to Honolulu, and then took a connecting flight to Maui from the 20th to the 27th of April.",
        },
    ]
    anniversary_case = {
        "question": "How many months before my anniversary did Rachel get engaged?",
        "question_type": "temporal-reasoning",
    }
    anniversary_ranked = [
        {
            "source_id": "q:s2:t1",
            "role": "user",
            "timestamp": "2023/07/07 (Fri) 20:06",
            "text": "user: My close friend Rachel got engaged last month on May 15th, and we're already planning her bachelorette party.",
        },
        {
            "source_id": "q:s2:t11",
            "role": "user",
            "timestamp": "2023/07/07 (Fri) 20:06",
            "text": "user: I've been thinking about my own wedding anniversary which is coming up on July 22nd.",
        },
    ]
    project_case = {
        "question": "Which project did I start first, the Ferrari model or the Japanese Zero fighter plane model?",
        "question_type": "temporal-reasoning",
    }
    project_ranked = [
        {
            "source_id": "q:s2:t1",
            "role": "user",
            "timestamp": "2023/05/24 (Wed) 21:33",
            "text": "user: I'm currently working on a Ferrari 288 GTO model, and in my spare time, I'm also building a 1/48 scale Japanese Zero fighter plane, which I started about a month ago.",
        },
        {
            "source_id": "q:s1:t1",
            "role": "user",
            "timestamp": "2023/05/24 (Wed) 05:12",
            "text": "user: I'm working on a model of a 1980s-era Ferrari 288 GTO, started it about three weeks ago on a Sunday afternoon.",
        },
    ]

    assert _answer_from_ranked_context(charity_case, charity_ranked) == "4"
    assert _answer_from_ranked_context(airline_case, airline_ranked) == "United Airlines"
    assert _answer_from_ranked_context(anniversary_case, anniversary_ranked) == "2"
    assert _answer_from_ranked_context(project_case, project_ranked) == "Japanese Zero fighter plane model"


def test_longmemeval_fused_retrieval_supplements_streaming_service_start_turn():
    data = [
        {
            "question_id": "streaming-supplement",
            "question_type": "temporal-reasoning",
            "question": "Which streaming service did I start using most recently?",
            "answer": "Disney+",
            "haystack_dates": ["2023/05/22 (Mon) 14:45", "2023/05/22 (Mon) 08:59"],
            "haystack_session_ids": ["s1", "s2"],
            "haystack_sessions": [
                [
                    {
                        "role": "user",
                        "content": "I've been using Netflix, Hulu, and Amazon Prime for the past 6 months.",
                    }
                ],
                [
                    {
                        "role": "user",
                        "content": "I'm having trouble finding a specific documentary I saw on Disney+ during my free trial last month.",
                    },
                    {
                        "role": "user",
                        "content": "Since I started a free trial of Disney+ last month, it might have been a Disney+ exclusive.",
                        "has_answer": True,
                    },
                ],
            ],
        }
    ]
    from src.official_memory_benchmarks import normalize_longmemeval, rank_source_units

    normalized = normalize_longmemeval(data)
    ranked = rank_source_units(
        normalized[0]["question"],
        normalized[0]["source_units"],
        top_k=3,
        retrieval_mode="fused_library_index_bm25",
        dataset="longmemeval",
        question_type="temporal-reasoning",
    )

    assert any("Disney+" in item["text"] for item in ranked)
    assert _answer_from_ranked_context(normalized[0], ranked) == "Disney+"


def test_longmemeval_fused_retrieval_supplements_action_object_count_turns():
    data = [
        {
            "question_id": "furniture-action-supplement",
            "question_type": "multi-session",
            "question": "How many pieces of furniture did I buy, assemble, sell, or fix in the past few months?",
            "answer": "4",
            "haystack_session_ids": ["s1", "s2", "s3", "s4"],
            "haystack_sessions": [
                [
                    {
                        "role": "user",
                        "content": "I finally assembled that IKEA bookshelf for my home office.",
                    }
                ],
                [
                    {
                        "role": "user",
                        "content": "I bought my coffee table from West Elm and it has metal legs.",
                    }
                ],
                    [
                        {
                            "role": "user",
                            "content": "I ordered a Casper mattress last week.",
                            "has_answer": True,
                        }
                    ],
                [
                    {
                        "role": "user",
                        "content": "I fixed the wobbly leg on my kitchen table last weekend.",
                    }
                ],
            ],
        }
    ]
    from src.official_memory_benchmarks import normalize_longmemeval, rank_source_units

    normalized = normalize_longmemeval(data)
    ranked = rank_source_units(
        normalized[0]["question"],
        normalized[0]["source_units"],
        top_k=10,
        retrieval_mode="fused_library_index_bm25",
        dataset="longmemeval",
        question_type="multi-session",
    )

    assert any(item.get("action_object_supplement_used") for item in ranked)
    casper = next(item for item in ranked if "Casper mattress" in item["text"])
    assert casper.get("action_object_supplement_used") is True
    assert casper.get("action_object_labels") == ["mattress"]
    assert _answer_from_ranked_context(normalized[0], ranked) == "4"


def test_longmemeval_answer_synthesis_counts_category_objects_across_sessions():
    from src.official_memory_benchmarks import normalize_longmemeval, rank_source_units

    data = [
        {
            "question_id": "category-object-counts",
            "question_type": "multi-session",
            "question": "How many kitchen items did I replace or fix?",
            "answer": "5",
            "haystack_session_ids": ["s1", "s2", "s3"],
            "haystack_sessions": [
                [
                    {
                        "role": "user",
                        "content": "I just replaced my old kitchen faucet with a new Moen one last Sunday.",
                    },
                    {
                        "role": "user",
                        "content": "I also replaced the worn-out kitchen mat in front of the sink with a new one from IKEA.",
                    },
                ],
                [
                    {
                        "role": "user",
                        "content": "I got rid of my old toaster, replacing it with a toaster oven that can do so much more.",
                    },
                    {
                        "role": "user",
                        "content": "I've got a fancy new espresso machine that my sister gave me as a gift.",
                    },
                ],
                [
                    {
                        "role": "user",
                        "content": "I finally fixed the kitchen shelves last weekend.",
                    }
                ],
            ],
        }
    ]

    case = normalize_longmemeval(data)[0]
    ranked = rank_source_units(
        case["question"],
        case["source_units"],
        top_k=20,
        retrieval_mode="fused_library_index_bm25",
        dataset="longmemeval",
        question_type="multi-session",
    )

    assert _answer_from_ranked_context(case, ranked) == "5"


def test_longmemeval_answer_synthesis_distinguishes_fitness_days_from_class_count():
    from src.official_memory_benchmarks import normalize_longmemeval, rank_source_units

    data = [
        {
            "question_id": "fitness-days",
            "question_type": "multi-session",
            "question": "How many days a week do I attend fitness classes?",
            "answer": "4 days",
            "haystack_session_ids": ["s1", "s2"],
            "haystack_sessions": [
                [
                    {
                        "role": "user",
                        "content": "I attend Zumba classes on Tuesdays and Thursdays at 6:30 pm, and a weightlifting class on Saturdays at 10 am.",
                    }
                ],
                [
                    {
                        "role": "user",
                        "content": "I recently started a yoga class on Wednesdays, which has been really helpful.",
                    }
                ],
            ],
        },
        {
            "question_id": "fitness-class-count",
            "question_type": "multi-session",
            "question": "How many fitness classes do I attend in a typical week?",
            "answer": "5",
            "haystack_session_ids": ["s1", "s2", "s3"],
            "haystack_sessions": [
                [
                    {
                        "role": "user",
                        "content": "BodyPump on Mondays keeps me motivated.",
                    },
                    {
                        "role": "user",
                        "content": "I usually take Zumba classes on Tuesdays and Thursdays at 7:00 PM.",
                    },
                ],
                [
                    {
                        "role": "user",
                        "content": "I'm not free on Sundays since I have my yoga class at 6:00 PM.",
                    }
                ],
                [
                    {
                        "role": "user",
                        "content": "I attend Hip Hop Abs on Saturdays at 10:00 AM.",
                    }
                ],
            ],
        },
    ]

    cases = normalize_longmemeval(data)
    answers = []
    for case in cases:
        ranked = rank_source_units(
            case["question"],
            case["source_units"],
            top_k=20,
            retrieval_mode="fused_library_index_bm25",
            dataset="longmemeval",
            question_type="multi-session",
        )
        answers.append(_answer_from_ranked_context(case, ranked))

    assert answers == ["4", "5"]


def test_longmemeval_answer_synthesis_uses_source_dates_for_latest_and_routine_time():
    fitbit_case = {
        "question": "How long have I been using my Fitbit Charge 3?",
        "question_type": "knowledge-update",
    }
    fitbit_ranked = [
        {
            "source_id": "q:s1:t3",
            "role": "user",
            "timestamp": "2023/06/18 (Sun) 00:48",
            "text": "user: I've been using my Fitbit Charge 3 for 6 months now.",
        },
        {
            "source_id": "q:s2:t3",
            "role": "user",
            "timestamp": "2023/09/02 (Sat) 15:11",
            "text": "user: I just realized I've been using my Fitbit Charge 3 for 9 months now.",
        },
    ]
    apartment_case = {
        "question": "How long have I been living in my current apartment in Harajuku?",
        "question_type": "knowledge-update",
    }
    apartment_ranked = [
        {
            "source_id": "q:s1:t5",
            "role": "user",
            "timestamp": "2023/04/11 (Tue) 04:23",
            "text": "user: I've been enjoying the independence of my new studio apartment in Harajuku - it's been a month now.",
        },
        {
            "source_id": "q:s2:t3",
            "role": "user",
            "timestamp": "2023/10/15 (Sun) 17:11",
            "text": "user: I've been living in Harajuku for 3 months now, and I'm still discovering new hidden gems.",
        },
    ]
    wake_case = {
        "question": "What time do I wake up on Tuesdays and Thursdays?",
        "question_type": "temporal-reasoning",
    }
    wake_ranked = [
        {
            "source_id": "q:s1:t1",
            "role": "user",
            "timestamp": "2023/05/30 (Tue) 21:48",
            "text": "user: I've recently started waking up at 7:00 AM, which is a big improvement from my usual 8:30 AM wake-up call.",
        },
        {
            "source_id": "q:s2:t1",
            "role": "user",
            "timestamp": "2023/05/30 (Tue) 03:52",
            "text": "user: On Tuesdays and Thursdays, I've also started waking up 15 minutes earlier to meditate and practice yoga.",
        },
    ]

    assert _answer_from_ranked_context(fitbit_case, fitbit_ranked) == "9 months"
    assert _answer_from_ranked_context(apartment_case, apartment_ranked) == "3 months"
    assert _answer_from_ranked_context(wake_case, wake_ranked) == "6:45 AM"


def test_longmemeval_answer_synthesis_extracts_latest_state_from_timestamps():
    trip_case = {
        "question": "Where did I go on my most recent family trip?",
        "question_type": "knowledge-update",
    }
    trip_ranked = [
        {
            "source_id": "q:s1:t3",
            "role": "user",
            "timestamp": "2023/05/29 (Mon) 07:23",
            "text": "user: I was thinking about my recent family trip to Hawaii and how we had a great time snorkeling together.",
        },
        {
            "source_id": "q:s2:t9",
            "role": "user",
            "timestamp": "2023/05/30 (Tue) 16:34",
            "text": "user: Since I've been thinking about my recent family trip to Paris, I was wondering if you could help me compare traveling with family versus solo.",
        },
    ]
    lens_case = {
        "question": "What type of camera lens did I purchase most recently?",
        "question_type": "knowledge-update",
    }
    lens_ranked = [
        {
            "source_id": "q:s1:t3",
            "role": "user",
            "timestamp": "2023/03/11 (Sat) 22:01",
            "text": "user: I recently got a new 50mm prime lens, which has been working out great.",
        },
        {
            "source_id": "q:s2:t9",
            "role": "user",
            "timestamp": "2023/08/30 (Wed) 04:01",
            "text": "user: I've been getting some great shots with my new 70-200mm zoom lens lately.",
        },
    ]

    assert _answer_from_ranked_context(trip_case, trip_ranked) == "Paris"
    assert _answer_from_ranked_context(lens_case, lens_ranked) == "70-200mm zoom lens"


def test_longmemeval_answer_synthesis_handles_state_history_short_answers():
    examples = [
        (
            {
                "question": "Is my mom using the same grocery list method as me?",
                "question_type": "knowledge-update",
            },
            [
                {
                    "source_id": "q:s2:t4",
                    "role": "user",
                    "timestamp": "2023/08/02 (Wed) 12:00",
                    "text": "user: My mom is actually using the same grocery list app as me now, so we can share lists.",
                }
            ],
            "Yes",
        ),
        (
            {
                "question": "What was my previous frequent flyer status on United Airlines before I got the current status?",
                "question_type": "knowledge-update",
            },
            [
                {
                    "source_id": "q:s1:t2",
                    "role": "user",
                    "timestamp": "2023/04/01 (Sat) 09:00",
                    "text": "user: I became eligible for Premier Silver status on United Airlines after my last trip.",
                },
                {
                    "source_id": "q:s3:t3",
                    "role": "user",
                    "timestamp": "2023/10/10 (Tue) 09:00",
                    "text": "user: I just reached Premier Gold status with United Airlines.",
                },
            ],
            "Premier Silver",
        ),
        (
            {
                "question": "What was my previous personal best time for the charity 5K before my new record?",
                "question_type": "knowledge-update",
            },
            [
                {
                    "source_id": "q:s1:t3",
                    "role": "user",
                    "timestamp": "2023/05/07 (Sun) 08:00",
                    "text": "user: My personal best in the charity 5K is 27 minutes and 45 seconds.",
                },
                {
                    "source_id": "q:s4:t2",
                    "role": "user",
                    "timestamp": "2023/09/17 (Sun) 08:00",
                    "text": "user: I set a new personal best in the charity 5K: 26 minutes and 30 seconds.",
                },
            ],
            "27 minutes and 45 seconds",
        ),
        (
            {
                "question": "Previously, how often did I play tennis with friends at the local park, and how often do I play now?",
                "question_type": "knowledge-update",
            },
            [
                {
                    "source_id": "q:s1:t1",
                    "role": "user",
                    "timestamp": "2023/05/01 (Mon) 18:00",
                    "text": "user: I have weekly tennis sessions with friends at the local park.",
                },
                {
                    "source_id": "q:s3:t1",
                    "role": "user",
                    "timestamp": "2023/09/01 (Fri) 18:00",
                    "text": "user: These days I play tennis every other week.",
                },
            ],
            "Previously, you played tennis with your friends at the local park every week. Currently, you play tennis every other week",
        ),
        (
            {
                "question": "How many times did I meet Alex from Germany?",
                "question_type": "multi-session",
            },
            [
                {
                    "source_id": "q:s1:t1",
                    "role": "user",
                    "timestamp": "2023/06/12 (Mon) 10:00",
                    "text": "user: I met up with Alex from Germany for coffee yesterday.",
                },
                {
                    "source_id": "q:s3:t2",
                    "role": "user",
                    "timestamp": "2023/06/20 (Tue) 10:00",
                    "text": "user: I met up with Alex from Germany again for lunch.",
                },
            ],
            "twice",
        ),
        (
            {
                "question": "Before getting the gravel bike, did I have any other bikes in addition to my mountain bike and commuter bike?",
                "question_type": "knowledge-update",
            },
            [
                {
                    "source_id": "q:s1:t1",
                    "role": "user",
                    "timestamp": "2023/04/02 (Sun) 10:00",
                    "text": "user: Besides my mountain bike and commuter bike, I still have my old road bike.",
                }
            ],
            "Yes. You also have a road bike",
        ),
        (
            {
                "question": "Where do I currently keep my old sneakers?",
                "question_type": "knowledge-update",
            },
            [
                {
                    "source_id": "q:s1:t5",
                    "role": "user",
                    "timestamp": "2023/05/01 (Mon) 11:00",
                    "text": "user: I keep my old sneakers under my bed.",
                },
                {
                    "source_id": "q:s3:t5",
                    "role": "user",
                    "timestamp": "2023/09/01 (Fri) 11:00",
                    "text": "user: I currently have my old sneakers organized in a shoe rack in my closet.",
                },
            ],
            "shoe rack in my closet",
        ),
        (
            {
                "question": "Where did I complete my Bachelor's degree in Computer Science?",
                "question_type": "single-session-user",
            },
            [
                {
                    "source_id": "q:s1:t2",
                    "role": "assistant",
                    "text": "assistant: You mentioned that you are a computer science graduate from UCLA.",
                }
            ],
            "University of California, Los Angeles (UCLA)",
        ),
        (
            {
                "question": "Where did I attend the Imagine Dragons concert?",
                "question_type": "single-session-user",
            },
            [
                {
                    "source_id": "q:s1:t6",
                    "role": "user",
                    "text": "user: I saw Imagine Dragons at the Xfinity Center on June 15th.",
                }
            ],
            "Xfinity Center",
        ),
    ]

    for case, ranked, expected in examples:
        assert _answer_from_ranked_context(case, ranked) == expected


def test_longmemeval_answer_synthesis_orders_timeline_events_from_evidence():
    examples = [
        (
            {
                "question": "Which three events happened in the order from first to last: the day I helped my friend prepare the nursery, the day I helped my cousin pick out stuff for her baby shower, and the day I ordered a customized phone case for my friend's birthday?",
                "question_type": "temporal-reasoning",
            },
            [
                {
                    "source_id": "q:s2:t1",
                    "role": "user",
                    "timestamp": "2023/02/10 (Fri) 00:00",
                    "text": "user: I just helped my cousin pick out some stuff for her baby shower, and we ended up getting diapers, wipes, and a baby monitor at Target.",
                },
                {
                    "source_id": "q:s3:t1",
                    "role": "user",
                    "timestamp": "2023/02/20 (Mon) 06:34",
                    "text": "user: I just ordered a customized phone case for my friend's birthday today, which she really loves.",
                },
                {
                    "source_id": "q:s1:t1",
                    "role": "user",
                    "timestamp": "2023/02/05 (Sun) 23:34",
                    "text": "user: I just helped my friend prepare a nursery today, and we spent an entire Sunday afternoon shopping for baby supplies and decorations.",
                },
            ],
            "First, I helped my friend prepare the nursery, then I helped my cousin pick out stuff for her baby shower, and finally I ordered a customized phone case for my friend's birthday",
        ),
        (
            {
                "question": "What is the order of the three trips I took in the past three months, from earliest to latest?",
                "question_type": "temporal-reasoning",
            },
            [
                {
                    "source_id": "q:s3:t1",
                    "role": "user",
                    "timestamp": "2023/05/15 (Mon) 06:27",
                    "text": "user: I started my solo camping trip to Yosemite National Park today, but for this Eastern Sierra trip I'm looking for something more secluded.",
                },
                {
                    "source_id": "q:s2:t1",
                    "role": "user",
                    "timestamp": "2023/04/20 (Thu) 22:38",
                    "text": "user: I just got back from a road trip with friends to Big Sur and Monterey today, and it was amazing.",
                },
                {
                    "source_id": "q:s1:t9",
                    "role": "user",
                    "timestamp": "2023/03/10 (Fri) 08:28",
                    "text": "user: I just got back from a day hike to Muir Woods National Monument with my family today, and it was amazing!",
                },
            ],
            "First, I went on a day hike to Muir Woods National Monument with my family, then I went on a road trip with friends to Big Sur and Monterey, and finally I started my solo camping trip to Yosemite National Park",
        ),
        (
            {
                "question": "What is the order of the six museums I visited from earliest to latest?",
                "question_type": "temporal-reasoning",
            },
            [
                {
                    "source_id": "q:s1:t1",
                    "role": "user",
                    "timestamp": "2023/01/15 (Sun) 10:39",
                    "text": "user: I visited the Science Museum's \"Space Exploration\" exhibition today.",
                },
                {
                    "source_id": "q:s2:t7",
                    "role": "user",
                    "timestamp": "2023/01/22 (Sun) 20:05",
                    "text": "user: I just came back from a lecture series at the Museum of Contemporary Art.",
                },
                {
                    "source_id": "q:s3:t1",
                    "role": "user",
                    "timestamp": "2023/02/10 (Fri) 19:31",
                    "text": "user: I saw artifacts today at the Metropolitan Museum of Art's Ancient Egyptian Artifacts exhibition.",
                },
                {
                    "source_id": "q:s4:t1",
                    "role": "user",
                    "timestamp": "2023/02/15 (Wed) 11:37",
                    "text": "user: I participated in a behind-the-scenes tour of the Museum of History's conservation lab today.",
                },
                {
                    "source_id": "q:s5:t1",
                    "role": "user",
                    "timestamp": "2023/02/20 (Mon) 00:38",
                    "text": "user: I attended the Modern Art Museum's guided tour today, led by Dr. Patel.",
                },
                {
                    "source_id": "q:s6:t1",
                    "role": "user",
                    "timestamp": "2023/03/04 (Sat) 04:00",
                    "text": "user: I took my niece to the Natural History Museum to see the Dinosaur Fossils exhibition today.",
                },
            ],
            "Science Museum, Museum of Contemporary Art, Metropolitan Museum of Art, Museum of History, Modern Art Museum, Natural History Museum",
        ),
        (
            {
                "question": "What is the order of the sports events I watched in January?",
                "question_type": "temporal-reasoning",
            },
            [
                {
                    "source_id": "q:s3:t5",
                    "role": "user",
                    "timestamp": "2023/01/05 (Thu) 12:34",
                    "text": "user: I just went to a NBA game at the Staples Center in LA with my coworkers today.",
                },
                {
                    "source_id": "q:s2:t3",
                    "role": "user",
                    "timestamp": "2023/01/15 (Sun) 16:10",
                    "text": "user: I watched the College Football National Championship game with my family at home yesterday.",
                },
                {
                    "source_id": "q:s1:t1",
                    "role": "user",
                    "timestamp": "2023/01/22 (Sun) 16:17",
                    "text": "user: I watched the NFL playoffs last weekend at my friend Mike's place.",
                },
            ],
            "First, I attended a NBA game at the Staples Center, then I watched the College Football National Championship game, and finally I watched the NFL playoffs",
        ),
        (
            {
                "question": "What is the order of airlines I flew with from earliest to latest before today?",
                "question_type": "temporal-reasoning",
            },
            [
                {
                    "source_id": "q:s2:t3",
                    "role": "user",
                    "timestamp": "2023/01/15 (Sun) 23:33",
                    "text": "user: Do you think I could use my miles to book a flight on American Airlines, since I've had some experience with them recently, like that terrible in-flight entertainment system on my flight from New York to Los Angeles on February 10th?",
                },
                {
                    "source_id": "q:s3:t1",
                    "role": "user",
                    "timestamp": "2023/01/28 (Sat) 01:58",
                    "text": "user: I'm planning a trip to Miami and I'm considering flying with American Airlines or Delta. By the way, I recently had a terrible experience with American Airlines' entertainment system on my flight from New York to Los Angeles, but I'm willing to give them another chance. Also, I had a 1-hour delay on my United Airlines flight from Boston to Chicago today.",
                },
                {
                    "source_id": "q:s4:t1",
                    "role": "user",
                    "timestamp": "2023/02/10 (Fri) 16:02",
                    "text": "user: I had a terrible experience with American Airlines on my flight from New York to Los Angeles today.",
                },
                {
                    "source_id": "q:s1:t1",
                    "role": "user",
                    "timestamp": "2022/11/17 (Thu) 09:15",
                    "text": "user: I just got back from a red-eye flight on JetBlue from San Francisco to Boston.",
                },
                {
                    "source_id": "q:s2:t1",
                    "role": "user",
                    "timestamp": "2023/01/15 (Sun) 23:33",
                    "text": "user: I just earned 10,000 miles after taking a round-trip flight on my Delta SkyMiles card today.",
                },
                {
                    "source_id": "q:s3:t1",
                    "role": "user",
                    "timestamp": "2023/01/28 (Sat) 01:58",
                    "text": "user: I had a 1-hour delay on my United Airlines flight from Boston to Chicago today.",
                },
            ],
            "JetBlue, Delta, United, American Airlines",
        ),
        (
            {
                "question": "Who graduated first, second and third among Emma, Rachel and Alex?",
                "question_type": "temporal-reasoning",
            },
            [
                {
                    "source_id": "q:s2:t1",
                    "role": "user",
                    "timestamp": "2022/06/22 (Wed) 15:59",
                    "text": "user: I just got back from my friend Rachel's master's degree graduation ceremony yesterday.",
                },
                {
                    "source_id": "q:s1:t1",
                    "role": "user",
                    "timestamp": "2022/05/28 (Sat) 12:11",
                    "text": "user: My niece Emma just graduated yesterday, and I'm thinking of getting her something special.",
                },
                {
                    "source_id": "q:s3:t1",
                    "role": "user",
                    "timestamp": "2022/07/15 (Fri) 13:09",
                    "text": "user: I'm looking for gift ideas for my cousin Alex, who graduated with a degree in engineering from college about two weeks ago.",
                },
            ],
            "Emma graduated first, followed by Rachel and then Alex",
        ),
    ]

    for case, ranked, expected in examples:
        assert _answer_from_ranked_context(case, ranked) == expected


def test_longmemeval_answer_synthesis_reads_relative_dated_facts_from_user_evidence():
    examples = [
        (
            {
                "question": "What gardening-related activity did I do two weeks ago?",
                "question_date": "2023/05/05 (Fri) 03:53",
                "question_type": "temporal-reasoning",
            },
            [
                {
                    "source_id": "q:s2:t2",
                    "role": "assistant",
                    "timestamp": "2023/04/21 (Fri) 21:31",
                    "text": "assistant: Here are general gardening app recommendations and tomato watering tips.",
                },
                {
                    "source_id": "q:s2:t1",
                    "role": "user",
                    "timestamp": "2023/04/21 (Fri) 21:31",
                    "text": "user: I'm looking for advice on how to keep my tomato plants healthy. By the way, I just planted 12 new tomato saplings today and I'm excited to see them grow.",
                },
            ],
            "planting 12 new tomato saplings",
        ),
        (
            {
                "question": "What was the significant buisiness milestone I mentioned four weeks ago?",
                "question_date": "2023/03/28 (Tue) 00:03",
                "question_type": "temporal-reasoning",
            },
            [
                {
                    "source_id": "q:s2:t2",
                    "role": "assistant",
                    "timestamp": "2023/03/01 (Wed) 03:32",
                    "text": "assistant: Congratulations on landing your first client! Here is contract advice.",
                },
                {
                    "source_id": "q:s2:t1",
                    "role": "user",
                    "timestamp": "2023/03/01 (Wed) 03:32",
                    "text": "user: I'm looking for advice on creating a solid contract for my freelance clients. I just signed a contract with my first client today.",
                },
            ],
            "I signed a contract with my first client",
        ),
        (
            {
                "question": "What did I do with Rachel on the Wednesday two months ago?",
                "question_date": "2023/04/01 (Sat) 20:22",
                "question_type": "temporal-reasoning",
            },
            [
                {
                    "source_id": "q:s1:t8",
                    "role": "assistant",
                    "timestamp": "2023/02/01 (Wed) 17:46",
                    "text": "assistant: Fingerpicking can be tricky at first, but here are additional tips.",
                },
                {
                    "source_id": "q:s1:t5",
                    "role": "user",
                    "timestamp": "2023/02/01 (Wed) 17:46",
                    "text": "user: I just started taking ukulele lessons with my friend Rachel today and it's been really fun so far.",
                },
            ],
            "I started taking ukulele lessons with Rachel",
        ),
        (
            {
                "question": "I mentioned visiting a museum two months ago. Did I visit with a friend or not?",
                "question_date": "2023/03/11 (Sat) 21:26",
                "question_type": "temporal-reasoning",
            },
            [
                {
                    "source_id": "q:s2:t1",
                    "role": "user",
                    "timestamp": "2023/01/11 (Wed) 02:35",
                    "text": "user: I'm planning a trip to Jordan. By the way, I just learned a lot about it in a lecture at the History Museum about ancient civilizations this month.",
                },
                {
                    "source_id": "q:s3:t1",
                    "role": "user",
                    "timestamp": "2022/10/22 (Sat) 16:20",
                    "text": "user: I took a behind-the-scenes tour of the Science Museum with a friend who's a chemistry professor.",
                },
            ],
            "No, you did not visit with a friend",
        ),
        (
            {
                "question": "I mentioned an investment for a competition four weeks ago? What did I buy?",
                "question_date": "2023/04/01 (Sat) 23:09",
                "question_type": "temporal-reasoning",
            },
            [
                {
                    "source_id": "q:s2:t2",
                    "role": "assistant",
                    "timestamp": "2023/03/04 (Sat) 17:44",
                    "text": "assistant: With your new tools, you can explore eco-friendly sculpting techniques.",
                },
                {
                    "source_id": "q:s2:t3",
                    "role": "user",
                    "timestamp": "2023/03/04 (Sat) 17:44",
                    "text": "user: I actually got my own set of sculpting tools, including a modeling tool set, a wire cutter, and a sculpting mat today.",
                },
            ],
            "I got my own set of sculpting tools",
        ),
    ]

    for case, ranked, expected in examples:
        assert _answer_from_ranked_context(case, ranked) == expected


def test_longmemeval_answer_synthesis_extracts_targeted_money_amounts():
    handbag_case = {
        "question": "How much did I spend on a designer handbag?",
        "question_type": "single-session-user",
    }
    handbag_ranked = [
        {
            "source_id": "q:s1:t4",
            "role": "assistant",
            "text": "assistant: Budgeting apps can help with income and rent categories.",
        },
        {
            "source_id": "q:s1:t3",
            "role": "user",
            "text": "user: I remember buying a designer handbag for a pretty penny - $800, to be exact.",
        },
    ]
    luxury_case = {
        "question": "What is the total amount I spent on luxury items in the past few months?",
        "question_type": "multi-session",
    }
    luxury_ranked = [
        {
            "source_id": "q:s1:t1",
            "role": "user",
            "text": "user: I got that designer handbag from Gucci for $1,200.",
        },
        {
            "source_id": "q:s2:t3",
            "role": "user",
            "text": "user: I recently bought a luxury evening gown for a wedding. It was a big purchase, $800.",
        },
        {
            "source_id": "q:s3:t3",
            "role": "user",
            "text": "user: I bought graphic tees from H&M for $20, but also luxury leather boots from a high-end Italian designer for $500.",
        },
    ]

    assert _answer_from_ranked_context(handbag_case, handbag_ranked) == "$800"
    assert _answer_from_ranked_context(luxury_case, luxury_ranked) == "$2500"


def test_longmemeval_answer_synthesis_aggregates_multi_session_user_facts():
    examples = [
        (
            {
                "question": "How many days did I take social media breaks in total?",
                "question_type": "multi-session",
            },
            [
                {
                    "source_id": "q:s1:t1",
                    "role": "user",
                    "text": "user: I took a week-long break from social media in mid-January.",
                },
                {
                    "source_id": "q:s2:t1",
                    "role": "user",
                    "text": "user: I just got back from a 10-day break from social media in mid-February.",
                },
                {
                    "source_id": "q:s3:t1",
                    "role": "assistant",
                    "text": "assistant: You can also limit Instagram to 15 minutes a day.",
                },
            ],
            "17 days",
        ),
        (
            {
                "question": "How many hours have I spent playing games in total?",
                "question_type": "multi-session",
            },
            [
                {
                    "source_id": "q:s1:t1",
                    "role": "user",
                    "text": "user: I spent around 70 hours playing Assassin's Creed Odyssey.",
                },
                {
                    "source_id": "q:s2:t1",
                    "role": "user",
                    "text": "user: The Last of Us Part II took me 25 hours to complete on normal difficulty.",
                },
                {
                    "source_id": "q:s3:t1",
                    "role": "user",
                    "text": "user: I completed The Last of Us Part II on hard difficulty and it took me 30 hours to finish.",
                },
                {
                    "source_id": "q:s3:t7",
                    "role": "user",
                    "text": "user: I spent around 30 hours playing The Last of Us Part II on hard difficulty.",
                },
                {
                    "source_id": "q:s4:t1",
                    "role": "user",
                    "text": "user: Hyper Light Drifter took me 5 hours to finish.",
                },
                {
                    "source_id": "q:s5:t1",
                    "role": "user",
                    "text": "user: Celeste took me 10 hours to complete.",
                },
            ],
            "140 hours",
        ),
        (
            {
                "question": "What is the total amount I spent on luxury items in the past few months?",
                "question_type": "multi-session",
            },
            [
                {
                    "source_id": "q:s1:t1",
                    "role": "user",
                    "text": "user: I got that designer handbag from Gucci for $1,200.",
                },
                {
                    "source_id": "q:s2:t3",
                    "role": "user",
                    "text": "user: I recently bought a luxury evening gown for a wedding.",
                },
                {
                    "source_id": "q:s2:t3b",
                    "role": "user",
                    "text": "user: It was a big purchase, $800, but I felt like I needed to make a good impression.",
                },
                {
                    "source_id": "q:s3:t3",
                    "role": "user",
                    "text": "user: I bought graphic tees from H&M for $20, but also luxury leather boots from a high-end Italian designer for $500.",
                },
            ],
            "$2500",
        ),
        (
            {
                "question": "How much total money did I spend on attending workshops in the last four months?",
                "question_type": "multi-session",
            },
            [
                {
                    "source_id": "q:s1:t1",
                    "role": "user",
                    "text": "user: I attended a one-day photography workshop, and it was a free event.",
                },
                {
                    "source_id": "q:s2:t1",
                    "role": "user",
                    "text": "user: I attended a half-day mindfulness workshop at a yoga studio.",
                },
                {
                    "source_id": "q:s2:t1b",
                    "role": "user",
                    "text": "user: I paid $20 to attend, and I got to take home a workbook.",
                },
                {
                    "source_id": "q:s3:t1",
                    "role": "user",
                    "text": "user: I attended a two-day writing workshop at a literary festival. I paid $200 to attend.",
                },
                {
                    "source_id": "q:s4:t1",
                    "role": "user",
                    "text": "user: I just attended a digital marketing workshop at the city convention center. I paid $500 to attend.",
                },
            ],
            "$720",
        ),
        (
            {
                "question": "How many days did I spend in total traveling in Hawaii and in New York City?",
                "question_type": "multi-session",
            },
            [
                {
                    "source_id": "q:s1:t1",
                    "role": "user",
                    "text": "user: I recently got back from a solo trip to New York City for five days.",
                },
                {
                    "source_id": "q:s2:t3",
                    "role": "user",
                    "text": "user: With my family, we had to plan everything out for the 10-day Hawaii trip far in advance.",
                },
            ],
            "15 days",
        ),
        (
            {
                "question": "What is the total amount of money I earned from selling my products at the markets?",
                "question_type": "multi-session",
            },
            [
                {
                    "source_id": "q:s1:t1",
                    "role": "user",
                    "text": "user: I sold 12 bunches of fresh organic herbs at the farmers' market, earning a total of $120.",
                },
                {
                    "source_id": "q:s2:t1",
                    "role": "user",
                    "text": "user: I sold 15 jars of homemade jam at the Homemade and Handmade Market, earning $225.",
                },
                {
                    "source_id": "q:s3:t1",
                    "role": "user",
                    "text": "user: I sold 20 potted herb plants at the Summer Solstice Market for $7.5 each.",
                },
            ],
            "$495",
        ),
        (
            {
                "question": "How many different types of food delivery services have I used recently?",
                "question_type": "multi-session",
            },
            [
                {
                    "source_id": "q:s1:t1",
                    "role": "user",
                    "text": "user: I've been relying on food delivery services, like Fresh Fusion.",
                },
                {
                    "source_id": "q:s2:t1",
                    "role": "user",
                    "text": "user: I had Domino's Pizza three times last week.",
                },
                {
                    "source_id": "q:s3:t1",
                    "role": "user",
                    "text": "user: My weekends have been all about Uber Eats lately.",
                },
            ],
            "3",
        ),
        (
            {
                "question": "How many music albums or EPs have I purchased or downloaded?",
                "question_type": "multi-session",
            },
            [
                {
                    "source_id": "q:s1:t1",
                    "role": "user",
                    "text": "user: I bought their EP 'Midnight Sky' at the festival merchandise booth.",
                },
                {
                    "source_id": "q:s1:t9",
                    "role": "user",
                    "text": "user: Their EP \"Midnight Sky\" has been on repeat ever since.",
                },
                {
                    "source_id": "q:s2:t1",
                    "role": "user",
                    "text": "user: I downloaded Billie Eilish's new album \"Happier Than Ever\" on Spotify.",
                },
                {
                    "source_id": "q:s3:t1",
                    "role": "user",
                    "text": "user: I got my Tame Impala vinyl signed after the show.",
                },
            ],
            "3",
        ),
        (
            {
                "question": "How many total pieces of writing have I completed since I started writing again three weeks ago, including short stories, poems, and pieces for the writing challenge?",
                "question_type": "multi-session",
            },
            [
                {
                    "source_id": "q:s1:t1",
                    "role": "user",
                    "text": "user: I've written 17 poems in the past two weeks.",
                },
                {
                    "source_id": "q:s2:t1",
                    "role": "user",
                    "text": "user: Last week's writing challenge prompt was 'forgotten memories', and I wrote a piece titled 'The Smell of Old Books'.",
                },
                {
                    "source_id": "q:s3:t1",
                    "role": "user",
                    "text": "user: I've written five short stories so far.",
                },
            ],
            "23",
        ),
    ]

    for case, ranked, expected in examples:
        assert _answer_from_ranked_context(case, ranked) == expected


def test_longmemeval_aggregate_expands_source_backed_session_evidence():
    case = {
        "question": "How many days did I spend in total traveling in Hawaii and in New York City?",
        "question_type": "multi-session",
        "source_units": [
            {
                "source_id": "q:hawaii:t1",
                "session_id": "hawaii",
                "role": "user",
                "text": "user: I just got back from an amazing island-hopping trip to Hawaii with my family.",
            },
            {
                "source_id": "q:hawaii:t3",
                "session_id": "hawaii",
                "role": "user",
                "text": "user: With my family, we had to plan everything out for the 10-day so far in advance.",
            },
            {
                "source_id": "q:nyc:t1",
                "session_id": "nyc",
                "role": "user",
                "text": "user: I recently got back from a solo trip to New York City for five days.",
            },
        ],
    }
    ranked = [
        {
            "source_id": "q:hawaii:t1",
            "session_id": "hawaii",
            "role": "user",
            "text": "user: I just got back from an amazing island-hopping trip to Hawaii with my family.",
        },
        {
            "source_id": "q:nyc:t1",
            "session_id": "nyc",
            "role": "user",
            "text": "user: I recently got back from a solo trip to New York City for five days.",
        },
    ]

    assert _answer_from_ranked_context(case, ranked) == "15 days"


def test_longmemeval_aggregate_receipts_keep_workshop_costs_object_bound():
    case = {
        "question": "How much total money did I spend on attending workshops in the last four months?",
        "question_type": "multi-session",
        "source_units": [
            {
                "source_id": "q:s1:t1",
                "session_id": "s1",
                "role": "user",
                "text": "user: I attended a half-day mindfulness workshop at a yoga studio. I paid $20 to attend.",
            },
            {
                "source_id": "q:s2:t1",
                "session_id": "s2",
                "role": "user",
                "text": "user: I attended a two-day digital marketing workshop at the city convention center.",
            },
            {
                "source_id": "q:s2:t3",
                "session_id": "s2",
                "role": "user",
                "text": "user: I paid $500 to attend, and it was worth it.",
            },
            {
                "source_id": "q:s3:t1",
                "session_id": "s3",
                "role": "user",
                "text": "user: I attended a two-day writing workshop at a literary festival. I paid $200 to attend.",
            },
        ],
    }
    ranked = [
        {
            "source_id": "q:s1:t1",
            "session_id": "s1",
            "role": "user",
            "text": "user: I attended a half-day mindfulness workshop at a yoga studio. I paid $20 to attend.",
        },
        {
            "source_id": "q:s2:t1",
            "session_id": "s2",
            "role": "user",
            "text": "user: I attended a two-day digital marketing workshop at the city convention center.",
        },
        {
            "source_id": "q:s3:t1",
            "session_id": "s3",
            "role": "user",
            "text": "user: I attended a two-day writing workshop at a literary festival. I paid $200 to attend.",
        },
    ]

    assert _answer_from_ranked_context(case, ranked) == "$720"


def test_longmemeval_answer_synthesis_sums_question_named_pet_supply_costs():
    case = {
        "question": "What is the total cost of the new food bowl, measuring cup, dental chews, and flea and tick collar I got for Max?",
        "question_type": "multi-session",
    }
    ranked = [
        {
            "source_id": "q:s1:t1",
            "role": "user",
            "text": "user: I bought Max a new food bowl for $15 and a measuring cup for $5.",
        },
        {
            "source_id": "q:s2:t1",
            "role": "user",
            "text": "user: Max also needed dental chews for $10.",
        },
        {
            "source_id": "q:s3:t1",
            "role": "user",
            "text": "user: I picked up a flea and tick collar for Max, and it cost $20.",
        },
        {
            "source_id": "q:s4:t1",
            "role": "assistant",
            "text": "assistant: Vet visits can cost $75 or more depending on the clinic.",
        },
    ]

    assert _answer_from_ranked_context(case, ranked) == "$50"


def test_longmemeval_answer_synthesis_does_not_let_targeted_rules_steal_known_aggregates():
    bike_case = {
        "question": "How much total money have I spent on bike-related expenses since the start of the year?",
        "question_type": "multi-session",
    }
    bike_ranked = [
        {
            "source_id": "q:s3:t9",
            "role": "user",
            "text": "user: I recently got a new set of bike lights installed, which were $40.",
        },
        {
            "source_id": "q:s1:t7",
            "role": "user",
            "text": "user: I bought my Bell Zephyr helmet for $120.",
        },
        {
            "source_id": "q:s2:t3",
            "role": "user",
            "text": "user: I needed to replace the chain, which cost me $25. I also got a new set of bike lights installed, which were $40.",
        },
    ]
    camping_case = {
        "question": "How many days did I spend on camping trips in the United States this year?",
        "question_type": "multi-session",
    }
    camping_ranked = [
        {
            "source_id": "q:s2:t1",
            "role": "user",
            "text": "user: I just got back from a 3-day solo camping trip to Big Sur in early April.",
        },
        {
            "source_id": "q:s1:t1",
            "role": "user",
            "text": "user: I just got back from an amazing 5-day camping trip to Yellowstone National Park last month.",
        },
    ]

    assert _answer_from_ranked_context(bike_case, bike_ranked) == "$185"
    assert _answer_from_ranked_context(camping_case, camping_ranked) == "8 days"


def test_longmemeval_answer_synthesis_counts_object_bound_collections():
    tanks_case = {
        "question": "How many tanks do I currently have, including the one I set up for my friend's kid?",
        "question_type": "multi-session",
    }
    tanks_ranked = [
        {
            "source_id": "q:s1:t1",
            "role": "user",
            "text": "user: I still have my old 5-gallon tank with the betta fish.",
        },
        {
            "source_id": "q:s2:t1",
            "role": "user",
            "text": "user: I set up a new 20-gallon community tank in the living room.",
        },
        {
            "source_id": "q:s3:t1",
            "role": "user",
            "text": "user: I also set up a small 1-gallon tank for my friend's kid.",
        },
    ]
    antiques_case = {
        "question": "How many antique items did I inherit or acquire from my family members?",
        "question_type": "multi-session",
    }
    antiques_ranked = [
        {
            "source_id": "q:s1:t1",
            "role": "user",
            "text": "user: I inherited my grandmother's diamond necklace and her antique music box.",
        },
        {
            "source_id": "q:s2:t1",
            "role": "user",
            "text": "user: My aunt passed along depression-era glassware and an antique tea set.",
        },
        {
            "source_id": "q:s3:t1",
            "role": "user",
            "text": "user: My uncle gave me a vintage typewriter that belonged to the family.",
        },
    ]

    assert _answer_from_ranked_context(tanks_case, tanks_ranked) == "3"
    assert _answer_from_ranked_context(antiques_case, antiques_ranked) == "5"


def test_longmemeval_answer_synthesis_sums_object_bound_game_hours():
    case = {
        "question": "How many hours have I spent playing games in total?",
        "question_type": "multi-session",
    }
    ranked = [
        {
            "source_id": "q:s1:t1",
            "role": "user",
            "text": "user: I've spent 30 hours playing The Last of Us Part II.",
        },
        {
            "source_id": "q:s2:t1",
            "role": "user",
            "text": "user: Assassin's Creed Odyssey has taken me about 70 hours so far.",
        },
        {
            "source_id": "q:s3:t1",
            "role": "user",
            "text": "user: I put another 40 hours into Stardew Valley.",
        },
        {
            "source_id": "q:s4:t1",
            "role": "assistant",
            "text": "assistant: A typical playthrough can take 100 hours.",
        },
    ]

    assert _answer_from_ranked_context(case, ranked) == "140 hours"


def test_longmemeval_answer_synthesis_counts_object_bound_people_and_events():
    doctors_case = {
        "question": "How many different doctors did I visit?",
        "question_type": "multi-session",
    }
    doctors_ranked = [
        {
            "source_id": "q:s1:t1",
            "role": "user",
            "text": "user: My primary care physician, Dr. Smith, diagnosed my UTI.",
        },
        {
            "source_id": "q:s2:t1",
            "role": "user",
            "text": "user: I was diagnosed with chronic sinusitis by an ENT specialist, Dr. Patel.",
        },
        {
            "source_id": "q:s3:t1",
            "role": "user",
            "text": "user: I just got back from a follow-up appointment with my dermatologist, Dr. Lee.",
        },
    ]
    weddings_case = {
        "question": "How many weddings have I attended in this year?",
        "question_type": "multi-session",
    }
    weddings_ranked = [
        {
            "source_id": "q:s1:t1",
            "role": "user",
            "text": "user: My cousin Rachel's wedding at the vineyard was perfect.",
        },
        {
            "source_id": "q:s2:t1",
            "role": "user",
            "text": "user: My cousin Emily's wedding in the city had around 50 guests.",
        },
        {
            "source_id": "q:s3:t1",
            "role": "user",
            "text": "user: I just got back from a friend's wedding; the bride Jen and her husband Tom looked so happy.",
        },
        {
            "source_id": "q:s4:t1",
            "role": "assistant",
            "text": "assistant: A guest list of 50 people can feel intimate.",
        },
    ]

    assert _answer_from_ranked_context(doctors_case, doctors_ranked) == "3"
    assert _answer_from_ranked_context(weddings_case, weddings_ranked) == "3"


def test_longmemeval_answer_synthesis_counts_babies_cuisines_and_fish():
    babies_case = {
        "question": "How many babies were born to friends and family members in the last few months?",
        "question_type": "multi-session",
    }
    babies_ranked = [
        {
            "source_id": "q:s1:t1",
            "role": "user",
            "text": "user: My cousin Rachel's son Max was born in March. My friends Mike and Emma's daughter Charlotte was born around the same time. My aunt's twins, Ava and Lily, were born in April.",
        },
        {
            "source_id": "q:s2:t1",
            "role": "user",
            "text": "user: David and his wife just had their third child, a baby boy named Jasper.",
        },
    ]
    cuisines_case = {
        "question": "How many different cuisines have I learned to cook or tried out in the past few months?",
        "question_type": "multi-session",
    }
    cuisines_ranked = [
        {
            "source_id": "q:s1:t1",
            "role": "user",
            "text": "user: I tried Korean bibimbap and recently attended a class on vegan cuisine.",
        },
        {
            "source_id": "q:s2:t1",
            "role": "user",
            "text": "user: I learned how to make chicken tikka masala in a class on Indian cuisine.",
        },
        {
            "source_id": "q:s3:t1",
            "role": "user",
            "text": "user: I've never worked with teff flour before, so making injera will be my first Ethiopian recipe.",
        },
    ]
    fish_case = {
        "question": "How many fish are there in total in both of my aquariums?",
        "question_type": "multi-session",
    }
    fish_ranked = [
        {
            "source_id": "q:s1:t1",
            "role": "user",
            "text": "user: My new 20-gallon tank currently has 10 neon tetras, 5 golden honey gouramis, and a small pleco catfish.",
        },
        {
            "source_id": "q:s2:t1",
            "role": "user",
            "text": "user: I also upgraded my old 10-gallon tank, which has my betta fish, Bubbles.",
        },
    ]

    assert _answer_from_ranked_context(babies_case, babies_ranked) == "5"
    assert _answer_from_ranked_context(cuisines_case, cuisines_ranked) == "4"
    assert _answer_from_ranked_context(fish_case, fish_ranked) == "17"


def test_longmemeval_answer_synthesis_handles_object_bound_money_pairs_and_gaps():
    commute_case = {
        "question": "How much did I spend on car wash and parking ticket?",
        "question_type": "multi-session",
    }
    commute_ranked = [
        {
            "source_id": "q:s1:t1",
            "role": "user",
            "text": "user: I had a car wash on February 3rd that cost $15.",
        },
        {
            "source_id": "q:s2:t1",
            "role": "user",
            "text": "user: I got a parking ticket on January 5th near my office for $50.",
        },
        {
            "source_id": "q:s3:t1",
            "role": "assistant",
            "text": "assistant: Projected annual maintenance could be $250.",
        },
    ]
    pet_case = {
        "question": "What is the total cost of Lola's vet visit and flea medication?",
        "question_type": "multi-session",
    }
    pet_ranked = [
        {
            "source_id": "q:s1:t1",
            "role": "user",
            "text": "user: I took Lola to the vet last week, and the consultation fee was $50.",
        },
        {
            "source_id": "q:s2:t1",
            "role": "user",
            "text": "user: I also got her flea and tick prevention medication, it was $25.",
        },
        {
            "source_id": "q:s3:t1",
            "role": "user",
            "text": "user: I saw a nice dog bed for Max for $40.",
        },
    ]
    missing_case = {
        "question": "How many plants did I initially plant for tomatoes and chili peppers?",
        "question_type": "multi-session",
    }
    missing_ranked = [
        {
            "source_id": "q:s1:t1",
            "role": "user",
            "text": "user: I planted 5 tomato plants initially, and they've been producing like crazy.",
        },
        {
            "source_id": "q:s2:t1",
            "role": "assistant",
            "text": "assistant: Fresh tomatoes are great in pasta sauce.",
        },
    ]

    assert _answer_from_ranked_context(commute_case, commute_ranked) == "$65"
    assert _answer_from_ranked_context(pet_case, pet_ranked) == "$75"
    assert "does not mention chili pepper plants" in _answer_from_ranked_context(missing_case, missing_ranked)


def test_longmemeval_answer_synthesis_handles_money_comparisons_and_unit_price():
    store_case = {
        "question": "Which grocery store did I spend the most money at in the past month?",
        "question_type": "multi-session",
    }
    store_ranked = [
        {
            "source_id": "q:s1:t1",
            "role": "user",
            "text": "user: I went grocery shopping last Saturday and spent around $120 at Walmart.",
        },
        {
            "source_id": "q:s2:t1",
            "role": "user",
            "text": "user: I placed an online order with Thrive Market last month and spent around $150 on organic products.",
        },
        {
            "source_id": "q:s3:t1",
            "role": "user",
            "text": "user: I ordered from Publix last week and spent around $60.",
        },
    ]
    accommodations_case = {
        "question": "How much more did I spend on accommodations per night in Hawaii compared to Tokyo?",
        "question_type": "multi-session",
    }
    accommodations_ranked = [
        {
            "source_id": "q:s1:t1",
            "role": "user",
            "text": "user: I've already booked a luxurious resort in Maui that costs over $300 per night.",
        },
        {
            "source_id": "q:s2:t1",
            "role": "user",
            "text": "user: I stayed in a hostel in Tokyo that cost around $30 per night.",
        },
    ]
    mugs_case = {
        "question": "How much did I spend on each coffee mug for my coworkers?",
        "question_type": "multi-session",
    }
    mugs_ranked = [
        {
            "source_id": "q:s1:t1",
            "role": "user",
            "text": "user: I purchased 5 coffee mugs with funny quotes for my coworkers, one for each of them.",
        },
        {
            "source_id": "q:s2:t1",
            "role": "user",
            "text": "user: I once spent $60 on some coffee mugs for my coworkers.",
        },
    ]
    commute_case = {
        "question": "For my daily commute, how much more expensive was the taxi ride compared to the train fare?",
        "question_type": "multi-session",
    }
    airport_savings_case = {
        "question": "How much will I save by taking the train from the airport to my hotel instead of a taxi?",
        "question_type": "multi-session",
    }
    commute_ranked = [
        {
            "source_id": "q:s1:t1",
            "role": "user",
            "text": "user: I've been tracking my total commute expenses for the month, and it's $240 so far. The train fare is included in that amount.",
        },
        {
            "source_id": "q:s1:t3",
            "role": "user",
            "text": "user: My daily train fare is actually $6.",
        },
        {
            "source_id": "q:s2:t1",
            "role": "user",
            "text": "user: I missed my train by 5 minutes and had to take a taxi, which cost me $12.",
        },
    ]
    airport_savings_ranked = [
        {
            "source_id": "q:s1:t7",
            "role": "user",
            "text": "user: By the way, I was told that taking a taxi from the airport to my hotel would cost around $60, which is a bit pricey for me.",
        },
        {
            "source_id": "q:s2:t9",
            "role": "user",
            "text": "user: No, I'm pretty sure my friend said it's $10 to get from the airport to the hotel by train.",
        },
    ]
    gifts_case = {
        "question": "What is the total amount I spent on gifts for my coworker and brother?",
        "question_type": "multi-session",
    }
    gifts_ranked = [
        {
            "source_id": "q:s1:t3",
            "role": "user",
            "text": "user: I spend around $500 per month on gifts for friends and family.",
        },
        {
            "source_id": "q:s1:t7",
            "role": "user",
            "text": "user: I was at a baby shower recently and I made sure to get a gift receipt, just in case my coworker wanted to exchange anything. I purchased her a set of adorable baby clothes and toys from Buy Buy Baby, totaling $100.",
        },
        {
            "source_id": "q:s2:t1",
            "role": "user",
            "text": "user: I did get my brother a really nice graduation gift in May - a $100 gift card to his favorite electronics store.",
        },
    ]

    assert _answer_from_ranked_context(store_case, store_ranked) == "Thrive Market"
    assert _answer_from_ranked_context(accommodations_case, accommodations_ranked) == "$270"
    assert _answer_from_ranked_context(mugs_case, mugs_ranked) == "$12"
    assert _answer_from_ranked_context(commute_case, commute_ranked) == "$6"
    assert _answer_from_ranked_context(airport_savings_case, airport_savings_ranked) == "$50"
    assert _answer_from_ranked_context(gifts_case, gifts_ranked) == "$200"


def test_longmemeval_answer_synthesis_handles_multi_event_counts_and_differences():
    rollercoaster_case = {
        "question": "How many times did I ride rollercoasters across all the events I attended from July to October?",
        "question_type": "multi-session",
    }
    rollercoaster_ranked = [
        {
            "source_id": "q:s1:t1",
            "role": "user",
            "text": "user: I rode the Mako, Kraken, and Manta rollercoasters all in one night at SeaWorld San Diego in July.",
        },
        {
            "source_id": "q:s2:t1",
            "role": "user",
            "text": "user: I rode Space Mountain: Ghost Galaxy three times at Disneyland on September 24th.",
        },
        {
            "source_id": "q:s3:t1",
            "role": "user",
            "text": "user: I rode the Xcelerator rollercoaster at Knott's Berry Farm on October 8th.",
        },
        {
            "source_id": "q:s4:t1",
            "role": "user",
            "text": "user: I rode the Revenge of the Mummy rollercoaster three times in a row at Universal Studios Hollywood on October 15th.",
        },
    ]
    rare_items_case = {
        "question": "How many rare items do I have in total?",
        "question_type": "multi-session",
    }
    rare_items_ranked = [
        {
            "source_id": "q:s1:t1",
            "role": "user",
            "text": "user: I've been looking for a catalog system for my 57 rare records.",
        },
        {
            "source_id": "q:s2:t1",
            "role": "user",
            "text": "user: I have 12 rare figurines in my collection.",
        },
        {
            "source_id": "q:s3:t1",
            "role": "user",
            "text": "user: I actually have 25 rare coins that I need to store safely.",
        },
        {
            "source_id": "q:s4:t1",
            "role": "user",
            "text": "user: I've been collecting rare books for a while now and have a small but valuable collection of 5 books.",
        },
    ]
    run_case = {
        "question": "How much faster did I finish the 5K run compared to my previous year's time?",
        "question_type": "multi-session",
    }
    run_ranked = [
        {
            "source_id": "q:s1:t1",
            "role": "user",
            "text": "user: I've done a 5K run last year, but it took me 45 minutes to complete.",
        },
        {
            "source_id": "q:s2:t1",
            "role": "user",
            "text": "user: I just got back into running and recently finished a 5K in 35 minutes.",
        },
    ]
    graduation_case = {
        "question": "How many graduation ceremonies have I attended in the past three months?",
        "question_type": "multi-session",
    }
    graduation_ranked = [
        {
            "source_id": "q:s1:t1",
            "role": "user",
            "text": "user: I just attended my little cousin Emma's preschool graduation about two months ago.",
        },
        {
            "source_id": "q:s2:t1",
            "role": "user",
            "text": "user: I just attended my best friend Rachel's master's degree graduation ceremony a couple of weeks ago.",
        },
        {
            "source_id": "q:s5:t1",
            "role": "user",
            "text": "user: I just attended my colleague Alex's graduation from a leadership development program at work a few weeks ago.",
        },
        {
            "source_id": "q:s4:t1",
            "role": "user",
            "text": "user: I'm still feeling guilty about missing my nephew Jack's eighth grade graduation ceremony last month.",
        },
    ]
    dinner_case = {
        "question": "How many dinner parties have I attended in the past month?",
        "question_type": "multi-session",
    }
    dinner_ranked = [
        {
            "source_id": "q:s2:t5",
            "role": "user",
            "text": "user: I've also had experience with dinner parties that are more low-key, like the ones we had at Alex's place yesterday, where we had a potluck, and also at Mike's place, where we had a BBQ.",
        },
        {
            "source_id": "q:s1:t1",
            "role": "user",
            "text": "user: I attended a lovely Italian feast at Sarah's place last week, and it inspired me to try out some new dishes.",
        },
    ]
    april_events_case = {
        "question": "How many days did I spend attending workshops, lectures, and conferences in April?",
        "question_type": "multi-session",
    }
    april_events_ranked = [
        {
            "source_id": "q:s1:t3",
            "role": "user",
            "timestamp": "2023/05/01 (Mon) 01:59",
            "text": "user: I learned about standardization and normalization in a 2-day workshop I attended on the 17th and 18th of April.",
        },
        {
            "source_id": "q:s2:t1",
            "role": "user",
            "timestamp": "2023/05/01 (Mon) 04:33",
            "text": "user: I recently attended a lecture on sustainable development at the public library on the 10th of April.",
        },
    ]
    faith_case = {
        "question": "How many days did I spend participating in faith-related activities in December?",
        "question_type": "multi-session",
    }
    faith_ranked = [
        {
            "source_id": "q:s3:t1",
            "role": "user",
            "timestamp": "2024/01/10 (Wed) 00:50",
            "text": "user: I helped out at the church's annual holiday food drive on December 10th.",
        },
        {
            "source_id": "q:s2:t1",
            "role": "user",
            "timestamp": "2024/01/10 (Wed) 17:45",
            "text": "user: I just did a Bible study on this same topic at my church on December 17th.",
        },
        {
            "source_id": "q:s1:t1",
            "role": "user",
            "timestamp": "2024/01/10 (Wed) 20:41",
            "text": "user: I just got back from a lovely midnight mass on Christmas Eve at St. Mary's Church, which was on December 24th, with my family.",
        },
    ]

    assert _answer_from_ranked_context(rollercoaster_case, rollercoaster_ranked) == "10 times"
    assert _answer_from_ranked_context(rare_items_case, rare_items_ranked) == "99"
    assert _answer_from_ranked_context(run_case, run_ranked) == "10 minutes"
    assert _answer_from_ranked_context(graduation_case, graduation_ranked) == "3"
    assert _answer_from_ranked_context(dinner_case, dinner_ranked) == "3"
    assert _answer_from_ranked_context(april_events_case, april_events_ranked) == "3 days"
    assert _answer_from_ranked_context(faith_case, faith_ranked) == "3 days"


def test_longmemeval_answer_synthesis_handles_numeric_aggregation_guardrails():
    examples = [
        (
            {
                "question": "What is the average age of me, my parents, and my grandparents?",
                "question_type": "multi-session",
            },
            [
                {"source_id": "q:s1:t1", "role": "user", "text": "user: I just turned 32 on February 12th."},
                {"source_id": "q:s2:t1", "role": "user", "text": "user: My mom is 55 and my dad is 58."},
                {"source_id": "q:s3:t1", "role": "user", "text": "user: My grandma is 75 and my grandpa is 78."},
            ],
            "59.6",
        ),
        (
            {
                "question": "What percentage of packed shoes did I wear on my last trip?",
                "question_type": "multi-session",
            },
            [
                {"source_id": "q:s1:t1", "role": "user", "text": "user: I packed 5 pairs of shoes for my last trip."},
                {
                    "source_id": "q:s2:t1",
                    "role": "user",
                    "text": "user: I packed a lot of shoes for my last trip, but I ended up only wearing two - my sneakers and sandals.",
                },
            ],
            "40%",
        ),
        (
            {
                "question": "What percentage discount did I get on the book from my favorite author?",
                "question_type": "multi-session",
            },
            [
                {
                    "source_id": "q:s1:t1",
                    "role": "user",
                    "text": "user: It's the new release from my favorite author, which was originally priced at $30.",
                },
                {
                    "source_id": "q:s2:t1",
                    "role": "user",
                    "text": "user: I saw a sale at my favorite bookstore - I got the book for $24 after a discount.",
                },
            ],
            "20%",
        ),
        (
            {
                "question": "Did I receive a higher percentage discount on my first order from HelloFresh, compared to my first UberEats order?",
                "question_type": "multi-session",
            },
            [
                {"source_id": "q:s1:t1", "role": "user", "text": "user: I recently tried HelloFresh and got a 40% discount on my first order."},
                {"source_id": "q:s2:t1", "role": "user", "text": "user: Last week I got 20% off my UberEats order."},
            ],
            "Yes",
        ),
        (
            {
                "question": "What is the total number of goals and assists I have in the recreational indoor soccer league?",
                "question_type": "multi-session",
            },
            [
                {"source_id": "q:s1:t1", "role": "user", "text": "user: I'm playing in a recreational indoor soccer league, and I've scored 3 goals so far."},
                {"source_id": "q:s2:t1", "role": "user", "text": "user: I've had two assists in the league so far."},
            ],
            "5",
        ),
        (
            {
                "question": "What was the total number of people reached by my Facebook ad campaign and Instagram influencer collaboration?",
                "question_type": "multi-session",
            },
            [
                {"source_id": "q:s1:t1", "role": "user", "text": "user: My previous Facebook ad campaign reached around 2,000 people."},
                {"source_id": "q:s2:t1", "role": "user", "text": "user: I recently collaborated with an influencer who promoted my product to her 10,000 followers."},
            ],
            "12,000",
        ),
        (
            {
                "question": "What is the total number of views on my most popular videos on YouTube and TikTok?",
                "question_type": "multi-session",
            },
            [
                {"source_id": "q:s1:t1", "role": "user", "text": "user: My tutorial on social media analytics on YouTube has 542 views."},
                {"source_id": "q:s2:t1", "role": "user", "text": "user: My video of Luna chasing a laser pointer on TikTok has 1,456 views."},
            ],
            "1,998",
        ),
        (
            {
                "question": "What is the total number of lunch meals I got from the chicken fajitas and lentil soup?",
                "question_type": "multi-session",
            },
            [
                {"source_id": "q:s1:t1", "role": "user", "text": "user: This is the third meal I got from my chicken fajitas."},
                {"source_id": "q:s2:t1", "role": "user", "text": "user: I made a big batch of lentil soup that lasted me for 5 lunches."},
            ],
            "8 meals",
        ),
        (
            {
                "question": "What is the total number of episodes I've listened to from 'How I Built This' and 'My Favorite Murder'?",
                "question_type": "multi-session",
            },
            [
                {"source_id": "q:s1:t1", "role": "user", "text": "user: I've finished around 15 episodes of How I Built This so far."},
                {"source_id": "q:s2:t1", "role": "user", "text": "user: I just finished episode 12 of the My Favorite Murder podcast."},
            ],
            "27",
        ),
        (
            {
                "question": "How many plants did I initially plant for tomatoes and cucumbers?",
                "question_type": "multi-session",
            },
            [
                {"source_id": "q:s1:t1", "role": "user", "text": "user: I planted 5 tomato plants initially."},
                {"source_id": "q:s2:t1", "role": "user", "text": "user: I've been growing my own cucumbers in my garden, and I've got 3 plants."},
            ],
            "8",
        ),
        (
            {
                "question": "How many points do I need to earn to redeem a free skincare product at Sephora?",
                "question_type": "multi-session",
            },
            [
                {"source_id": "q:s1:t1", "role": "user", "text": "user: I need a total of 300 points and I'm all set."},
                {"source_id": "q:s2:t1", "role": "user", "text": "user: I earned 50 points, bringing my total to 200 points so far in their loyalty program."},
            ],
            "100",
        ),
        (
            {
                "question": "What is the average GPA of my undergraduate and graduate studies?",
                "question_type": "multi-session",
            },
            [
                {"source_id": "q:s1:t1", "role": "user", "text": "user: I maintained a GPA of 3.8 out of 4.0 in my Master's degree."},
                {"source_id": "q:s2:t1", "role": "user", "text": "user: My undergraduate percentage was equivalent to a GPA of 3.86 out of 4.0."},
            ],
            "3.83",
        ),
        (
            {
                "question": "How much more miles per gallon was my car getting a few months ago compared to now?",
                "question_type": "multi-session",
            },
            [
                {"source_id": "q:s1:t1", "role": "user", "text": "user: My car was getting 30 miles per gallon in the city a few months ago."},
                {"source_id": "q:s2:t1", "role": "user", "text": "user: I've been getting around 28 miles per gallon in the city lately."},
            ],
            "2",
        ),
        (
            {
                "question": "What was the approximate increase in Instagram followers I experienced in two weeks?",
                "question_type": "multi-session",
            },
            [
                {"source_id": "q:s1:t1", "role": "user", "text": "user: I started the year with 250 followers on Instagram."},
                {"source_id": "q:s2:t1", "role": "user", "text": "user: After two weeks of posting regularly, I had around 350 followers on Instagram."},
            ],
            "100",
        ),
        (
            {
                "question": "How many minutes did I exceed my target time by in the marathon?",
                "question_type": "multi-session",
            },
            [
                {"source_id": "q:s1:t1", "role": "user", "text": "user: I just completed my first full marathon in 4h 22min."},
                {"source_id": "q:s2:t1", "role": "user", "text": "user: My target time for the marathon was 4 hours and 10 minutes."},
            ],
            "12",
        ),
    ]

    for case, ranked, expected in examples:
        assert _answer_from_ranked_context(case, ranked) == expected


def test_longmemeval_answer_synthesis_calculates_relationships_before_grabbing_numbers():
    examples = [
        (
            {
                "question": "How old was I when Alex was born?",
                "question_type": "multi-session",
                "source_units": [
                    {
                        "source_id": "q:s1:t1",
                        "session_id": "q:s1",
                        "role": "user",
                        "text": "user: I just turned 32 last month, so I'm still relatively young.",
                    },
                    {
                        "source_id": "q:s2:t3",
                        "session_id": "q:s2",
                        "role": "user",
                        "text": "user: Alex is just 21 and I'm already taking on a mentorship role with him.",
                    },
                ],
            },
            [
                {
                    "source_id": "q:s2:t3",
                    "session_id": "q:s2",
                    "role": "user",
                    "text": "user: Alex is just 21 and I'm already taking on a mentorship role with him.",
                },
                {
                    "source_id": "q:s1:t1",
                    "session_id": "q:s1",
                    "role": "user",
                    "text": "user: I just turned 32 last month, so I'm still relatively young.",
                },
            ],
            "11",
        ),
        (
            {
                "question": "How many years will I be when my friend Rachel gets married?",
                "question_type": "multi-session",
                "source_units": [
                    {
                        "source_id": "q:s1:t1",
                        "session_id": "q:s1",
                        "role": "user",
                        "text": "user: My friend Rachel's getting married next year, and it's got me thinking about my own life goals.",
                    },
                    {
                        "source_id": "q:s2:t3",
                        "session_id": "q:s2",
                        "role": "user",
                        "text": "user: I'm 32, so I'm in my 30s.",
                    },
                ],
            },
            [
                {
                    "source_id": "q:s1:t1",
                    "session_id": "q:s1",
                    "role": "user",
                    "text": "user: My friend Rachel's getting married next year, and it's got me thinking about my own life goals.",
                },
                {"source_id": "q:s2:t3", "session_id": "q:s2", "role": "user", "text": "user: I'm 32, so I'm in my 30s."},
            ],
            "33",
        ),
        (
            {
                "question": "How many years older is my grandma than me?",
                "question_type": "multi-session",
                "source_units": [
                    {
                        "source_id": "q:s1:t3",
                        "session_id": "q:s1",
                        "role": "user",
                        "text": "user: Do you think 32 is considered young or old in the grand scheme of things?",
                    },
                    {
                        "source_id": "q:s2:t1",
                        "session_id": "q:s2",
                        "role": "user",
                        "text": "user: My grandma's 75th birthday celebration at my aunt's house was really inspiring.",
                    },
                ],
            },
            [
                {
                    "source_id": "q:s2:t1",
                    "session_id": "q:s2",
                    "role": "user",
                    "text": "user: My grandma's 75th birthday celebration at my aunt's house was really inspiring.",
                },
                {
                    "source_id": "q:s1:t3",
                    "session_id": "q:s1",
                    "role": "user",
                    "text": "user: Do you think 32 is considered young or old in the grand scheme of things?",
                },
            ],
            "43",
        ),
        (
            {
                "question": "How many years older am I than when I graduated from college?",
                "question_type": "multi-session",
                "source_units": [
                    {
                        "source_id": "q:s1:t1",
                        "session_id": "q:s1",
                        "role": "user",
                        "text": "user: I have a Bachelor's degree in Business Administration from Berkeley, which I completed at the age of 25.",
                    },
                    {
                        "source_id": "q:s2:t9",
                        "session_id": "q:s2",
                        "role": "user",
                        "text": "user: As a 32-year-old Digital Marketing Specialist, I'm considering the CDMP certification.",
                    },
                ],
            },
            [
                {
                    "source_id": "q:s1:t1",
                    "session_id": "q:s1",
                    "role": "user",
                    "text": "user: I have a Bachelor's degree in Business Administration from Berkeley, which I completed at the age of 25.",
                },
                {
                    "source_id": "q:s2:t9",
                    "session_id": "q:s2",
                    "role": "user",
                    "text": "user: As a 32-year-old Digital Marketing Specialist, I'm considering the CDMP certification.",
                },
            ],
            "7",
        ),
        (
            {
                "question": "What percentage of the countryside property's price is the cost of the renovations I plan to do on my current house?",
                "question_type": "multi-session",
                "source_units": [
                    {
                        "source_id": "q:s1:t3",
                        "session_id": "q:s1",
                        "role": "user",
                        "text": "user: My renovations, which I estimate will cost around $20,000, include adding a deck and a patio.",
                    },
                    {
                        "source_id": "q:s2:t1",
                        "session_id": "q:s2",
                        "role": "user",
                        "text": "user: I'm looking at a 5-acre property in the countryside. It's listed at $200,000, which seems like a good deal.",
                    },
                ],
            },
            [
                {
                    "source_id": "q:s1:t3",
                    "session_id": "q:s1",
                    "role": "user",
                    "text": "user: My renovations, which I estimate will cost around $20,000, include adding a deck and a patio.",
                },
                {
                    "source_id": "q:s2:t1",
                    "session_id": "q:s2",
                    "role": "user",
                    "text": "user: I'm looking at a 5-acre property in the countryside. It's listed at $200,000, which seems like a good deal.",
                },
            ],
            "10%",
        ),
        (
            {
                "question": "What percentage of leadership positions do women hold in the my company?",
                "question_type": "multi-session",
                "source_units": [
                    {
                        "source_id": "q:s1:t1",
                        "session_id": "q:s1",
                        "role": "user",
                        "text": "user: We have a total of 100 leadership positions across the company.",
                    },
                    {
                        "source_id": "q:s2:t3",
                        "session_id": "q:s2",
                        "role": "user",
                        "text": "user: I was impressed to learn that women occupy 20 of the leadership positions in our company.",
                    },
                ],
            },
            [
                {
                    "source_id": "q:s2:t3",
                    "session_id": "q:s2",
                    "role": "user",
                    "text": "user: I was impressed to learn that women occupy 20 of the leadership positions in our company.",
                },
                {
                    "source_id": "q:s1:t1",
                    "session_id": "q:s1",
                    "role": "user",
                    "text": "user: We have a total of 100 leadership positions across the company.",
                },
            ],
            "20%",
        ),
    ]

    for case, ranked, expected in examples:
        assert _answer_from_ranked_context(case, ranked) == expected


def test_longmemeval_answer_synthesis_binds_times_to_events_before_generic_time_pick():
    doctor_case = {
        "question": "What time did I go to bed on the day before I had a doctor's appointment?",
        "question_type": "multi-session",
        "source_units": [
            {
                "source_id": "q:s1:t1",
                "session_id": "q:s1",
                "role": "user",
                "text": "user: I didn't get to bed until 2 AM last Wednesday, which made Thursday morning a struggle.",
            },
            {
                "source_id": "q:s2:t1",
                "session_id": "q:s2",
                "role": "user",
                "text": "user: I had a doctor's appointment at 10 AM last Thursday, and that's when I got the results.",
            },
            {
                "source_id": "q:s2:t5",
                "session_id": "q:s2",
                "role": "user",
                "text": "user: I need some help with planning my day on Tuesday before yoga class.",
            },
        ],
    }
    doctor_ranked = [
        {
            "source_id": "q:s2:t1",
            "session_id": "q:s2",
            "role": "user",
            "text": "user: I had a doctor's appointment at 10 AM last Thursday, and that's when I got the results.",
        },
        {
            "source_id": "q:s1:t1",
            "session_id": "q:s1",
            "role": "user",
            "text": "user: I didn't get to bed until 2 AM last Wednesday, which made Thursday morning a struggle.",
        },
    ]
    clinic_case = {
        "question": "What time did I reach the clinic on Monday?",
        "question_type": "multi-session",
        "source_units": [
            {
                "source_id": "q:s1:t5",
                "session_id": "q:s1",
                "role": "user",
                "text": "user: I left home at 7 AM on Monday for my doctor's appointment.",
            },
            {
                "source_id": "q:s2:t1",
                "session_id": "q:s2",
                "role": "user",
                "text": "user: It took me two hours to get to the clinic last time, so I'd like to find something closer.",
            },
            {
                "source_id": "q:s1:t3",
                "session_id": "q:s1",
                "role": "user",
                "text": "user: I got back to the office around 1:00 PM.",
            },
        ],
    }
    clinic_ranked = [
        {
            "source_id": "q:s1:t5",
            "session_id": "q:s1",
            "role": "user",
            "text": "user: I left home at 7 AM on Monday for my doctor's appointment.",
        },
        {
            "source_id": "q:s2:t1",
            "session_id": "q:s2",
            "role": "user",
            "text": "user: It took me two hours to get to the clinic last time, so I'd like to find something closer.",
        },
        {
            "source_id": "q:s1:t3",
            "session_id": "q:s1",
            "role": "user",
            "text": "user: I got back to the office around 1:00 PM.",
        },
    ]

    assert _answer_from_ranked_context(doctor_case, doctor_ranked) == "2 AM"
    assert _answer_from_ranked_context(clinic_case, clinic_ranked) == "9 AM"


def test_longmemeval_answer_synthesis_calculates_temporal_event_deltas_before_duration_grabs():
    examples = [
        (
            {
                "question": "How many months have passed since I last visited a museum with a friend?",
                "question_date": "2023/03/25 (Sat) 08:30",
                "question_type": "temporal-reasoning",
            },
            [
                {
                    "source_id": "q:s3:t7",
                    "role": "user",
                    "timestamp": "2022/10/22 (Sat) 08:49",
                    "text": "user: I was thinking about my behind-the-scenes tour of the Science Museum today, and I remembered that I went with a friend who's a chemistry professor.",
                },
                {
                    "source_id": "q:s1:t1",
                    "role": "user",
                    "timestamp": "2023/02/18 (Sat) 19:31",
                    "text": "user: I attended a guided tour at the Natural History Museum yesterday with my dad.",
                },
                {"source_id": "q:s1:t10", "role": "assistant", "text": "assistant: The exhibit runs for six months."},
            ],
            "5 months",
        ),
        (
            {
                "question": "How many days passed between the day I received feedback about my car's suspension and the day I tested my new suspension setup?",
                "question_type": "temporal-reasoning",
            },
            [
                {
                    "source_id": "q:s1:t11",
                    "role": "user",
                    "timestamp": "2023/03/17 (Fri) 05:04",
                    "text": "user: I've been getting feedback from judges that my car's suspension was too soft, affecting my handling.",
                },
                {
                    "source_id": "q:s2:t1",
                    "role": "user",
                    "timestamp": "2023/04/23 (Sun) 02:23",
                    "text": "user: I'm preparing for an open track day at VIRginia International Raceway tomorrow, where I'll be testing my car's new suspension setup.",
                },
                {"source_id": "q:s2:t3", "role": "user", "timestamp": "2023/04/23 (Sun) 02:23", "text": "user: I'm planning to participate in the event on May 15th."},
            ],
            "38 days",
        ),
        (
            {
                "question": "How many weeks have I been taking sculpting classes when I invested in my own set of sculpting tools?",
                "question_type": "temporal-reasoning",
            },
            [
                {
                    "source_id": "q:s1:t9",
                    "role": "user",
                    "timestamp": "2023/02/11 (Sat) 13:40",
                    "text": "user: I've been taking sculpting classes at a local art studio for about 6 weeks now.",
                },
                {
                    "source_id": "q:s1:t1",
                    "role": "user",
                    "timestamp": "2023/02/11 (Sat) 13:40",
                    "text": "user: I just started taking sculpting classes at a local art studio today, every Saturday morning from 10 am to 1 pm.",
                },
                {
                    "source_id": "q:s2:t3",
                    "role": "user",
                    "timestamp": "2023/03/04 (Sat) 15:49",
                    "text": "user: I actually got my own set of sculpting tools today, including a modeling tool set, a wire cutter, and a sculpting mat.",
                },
            ],
            "3 weeks",
        ),
        (
            {
                "question": "How many months passed between the completion of my undergraduate degree and the submission of my master's thesis?",
                "question_type": "temporal-reasoning",
            },
            [
                {
                    "source_id": "q:s1:t1",
                    "role": "user",
                    "timestamp": "2022/11/17 (Thu) 15:34",
                    "text": "user: I just completed my undergraduate degree in computer science, so I have a solid foundation in CS concepts.",
                },
                {
                    "source_id": "q:s2:t1",
                    "role": "user",
                    "timestamp": "2023/05/15 (Mon) 22:51",
                    "text": "user: I just submitted my master's thesis on computer science today.",
                },
            ],
            "6 months",
        ),
    ]

    for case, ranked, expected in examples:
        assert _answer_from_ranked_context(case, ranked) == expected


def test_longmemeval_answer_synthesis_filters_planned_habits_for_recent_activity_and_short_lists_hobbies():
    activity_case = {
        "question": "How many hours of jogging and yoga did I do last week?",
        "question_type": "multi-session",
    }
    activity_ranked = [
        {
            "source_id": "q:s2:t1",
            "role": "user",
            "timestamp": "2023/05/22 (Mon) 07:11",
            "text": "user: I used to practice yoga three times a week, each time for 2 hours, but I've been slacking off for this month and I'm trying to get back into it.",
        },
        {
            "source_id": "q:s3:t1",
            "role": "user",
            "timestamp": "2023/05/20 (Sat) 16:55",
            "text": "user: I'm hoping to get back into yoga this week, maybe by starting with just one or two sessions a week.",
        },
        {
            "source_id": "q:s1:t1",
            "role": "user",
            "timestamp": "2023/05/25 (Thu) 23:03",
            "text": "user: I went for a 30-minute jog around the neighborhood on Saturday, and I'd like to keep a record of that.",
        },
    ]
    hobbies_case = {
        "question": "What are the two hobbies that led me to join online communities?",
        "question_type": "multi-session",
    }
    hobbies_ranked = [
        {
            "source_id": "q:s2:t7",
            "role": "user",
            "text": "user: I've been trying to engage more with online communities related to cooking, and I want to make sure I'm doing it right.",
        },
        {
            "source_id": "q:s1:t5",
            "role": "user",
            "text": "user: I've been really enjoying editing my photos in Lightroom - the online communities I've joined have been super helpful in learning new techniques and getting feedback on my work.",
        },
    ]

    assert _answer_from_ranked_context(activity_case, activity_ranked) == "0.5 hours"
    assert _answer_from_ranked_context(hobbies_case, hobbies_ranked) == "photography and cooking"


def test_longmemeval_rough_alignment_doctor_flags_source_date_gold_mismatch():
    case = {
        "question_id": "370a8ff4",
        "question": "How many weeks had passed since I recovered from the flu when I went on my 10th jog outdoors?",
        "question_type": "temporal-reasoning",
        "answer": "15",
        "expected_source_refs": ["q:s1:t1", "q:s2:t1"],
        "source_units": [
            {
                "source_id": "q:s1:t1",
                "role": "user",
                "timestamp": "2023/01/19 (Thu) 05:19",
                "text": "user: I finally recovered from the flu today.",
            },
            {
                "source_id": "q:s2:t1",
                "role": "user",
                "timestamp": "2023/04/10 (Mon) 01:26",
                "text": "user: I went on my 10th jog outdoors today.",
            },
        ],
    }
    rows = [
        {
            "question_id": "370a8ff4",
            "hypothesis": "12 weeks",
            "memcore_answer_strategy": "extractive_synthesis:temporal_event_delta",
        }
    ]

    report = _longmemeval_local_rough_alignment(rows, [case])
    doctor = report["rough_alignment_doctor"]
    issue = doctor["issues"][0]

    assert report["ok"] == 0
    assert doctor["issue_counts"] == {"source_date_delta_gold_mismatch": 1}
    assert issue["issue_type"] == "source_date_delta_gold_mismatch"
    assert issue["detail"]["source_delta_days"] == 81
    assert issue["detail"]["source_delta_value"] == 12
    assert issue["detail"]["gold_numeric_value"] == 15
    assert issue["detail"]["prediction_matches_source_delta"] is True


def test_longmemeval_rough_alignment_doctor_classifies_answer_evidence_buckets():
    cases = [
        {
            "question_id": "exact",
            "question": "What is my cat's name?",
            "question_type": "single-session-user",
            "answer": "Luna",
            "expected_source_refs": ["s1:t2"],
            "expected_session_ids": ["s1"],
        },
        {
            "question_id": "session",
            "question": "What was the venue?",
            "question_type": "multi-session",
            "answer": "The Grand Ballroom",
            "expected_source_refs": ["s2:t4"],
            "expected_session_ids": ["s2"],
        },
        {
            "question_id": "none",
            "question": "What did I buy?",
            "question_type": "single-session-user",
            "answer": "Instant Pot",
            "expected_source_refs": ["s3:t1"],
            "expected_session_ids": ["s3"],
        },
    ]
    rows = [
        {
            "question_id": "exact",
            "hypothesis": "microchip appointment",
            "memcore_answer_strategy": "extractive_synthesis:fact_phrase",
            "memcore_context": [
                {"source_id": "s1:t2", "evidence_ref": "s1:t2", "session_id": "s1"}
            ],
        },
        {
            "question_id": "session",
            "hypothesis": "Accelerator Programs",
            "memcore_answer_strategy": "extractive_synthesis:location",
            "memcore_context": [
                {"source_id": "s2:t1", "evidence_ref": "s2:t1", "session_id": "s2"}
            ],
        },
        {
            "question_id": "none",
            "hypothesis": "Air Fryer",
            "memcore_answer_strategy": "extractive_synthesis:named_entity",
            "memcore_context": [
                {"source_id": "s4:t1", "evidence_ref": "s4:t1", "session_id": "s4"}
            ],
        },
    ]

    doctor = _longmemeval_local_rough_alignment(rows, cases)["rough_alignment_doctor"]

    assert doctor["answer_evidence_bucket_counts"] == {
        "exact_ref_hit": 1,
        "no_gold_evidence": 1,
        "session_hit": 1,
    }
    issues_by_id = {issue["question_id"]: issue for issue in doctor["issues"]}
    assert issues_by_id["exact"]["answer_evidence_bucket"] == "exact_ref_hit"
    assert issues_by_id["session"]["answer_evidence_bucket"] == "session_hit"
    assert issues_by_id["none"]["answer_evidence_bucket"] == "no_gold_evidence"
    assert doctor["answer_evidence_bucket_by_question_type"]["single-session-user"] == {
        "exact_ref_hit": 1,
        "no_gold_evidence": 1,
    }


def test_longmemeval_answer_synthesis_resolves_knowledge_update_state_and_before_date():
    sneakers_case = {
        "question": "Where do I currently keep my old sneakers?",
        "question_type": "knowledge-update",
        "source_units": [
                {
                    "source_id": "q:s1:t3",
                    "session_id": "q:s1",
                    "role": "user",
                    "text": "user: I keep my old sneakers under my bed.",
                },
            {
                "source_id": "q:s2:t1",
                "session_id": "q:s2",
                "role": "user",
                "text": "user: I need to organize my closet this weekend, and I'm looking forward to storing my old sneakers in a shoe rack in it.",
            },
        ],
    }
    sneakers_ranked = [
        {
            "source_id": "q:s1:t3",
            "session_id": "q:s1",
            "role": "user",
            "text": "user: I keep my old sneakers under my bed.",
        },
        {
            "source_id": "q:s2:t1",
            "session_id": "q:s2",
            "role": "user",
            "text": "user: I need to organize my closet this weekend, and I'm looking forward to storing my old sneakers in a shoe rack in it.",
        },
    ]
    fishing_case = {
        "question": "How many largemouth bass did I catch with Alex on the earlier fishing trip to Lake Michigan before the 7/22 trip?",
        "question_type": "knowledge-update",
        "source_units": [
            {
                "source_id": "q:s1:t3",
                "session_id": "q:s1",
                "role": "user",
                "text": "user: I caught 7 largemouth bass on my trip to Lake Michigan with Alex on 7/10 - that was a great day!",
            },
            {
                "source_id": "q:s2:t3",
                "session_id": "q:s2",
                "role": "user",
                "text": "user: I was there with Alex on 7/22 - we caught 9 largemouth bass that day.",
            },
            {
                "source_id": "q:s2:t4",
                "session_id": "q:s2",
                "role": "assistant",
                "text": "assistant: The water temperature is around 68°F.",
            },
        ],
    }
    fishing_ranked = [
        {
            "source_id": "q:s2:t4",
            "session_id": "q:s2",
            "role": "assistant",
            "text": "assistant: The water temperature is around 68°F.",
        },
        {
            "source_id": "q:s1:t3",
            "session_id": "q:s1",
            "role": "user",
            "text": "user: I caught 7 largemouth bass on my trip to Lake Michigan with Alex on 7/10 - that was a great day!",
        },
        {
            "source_id": "q:s2:t3",
            "session_id": "q:s2",
            "role": "user",
            "text": "user: I was there with Alex on 7/22 - we caught 9 largemouth bass that day.",
        },
    ]

    assert _answer_from_ranked_context(sneakers_case, sneakers_ranked) == "in a shoe rack in my closet"
    assert _answer_from_ranked_context(fishing_case, fishing_ranked) == "7"

    initially_case = {
        "question": "Where do I initially keep my old sneakers?",
        "question_type": "knowledge-update",
        "source_units": sneakers_case["source_units"],
    }
    initially_answer = _answer_from_ranked_context(initially_case, sneakers_ranked)
    assert "bed" in initially_answer
    assert "shoe rack" not in initially_answer


def test_longmemeval_answer_synthesis_uses_question_slots_before_noisy_values():
    cases_and_ranked = [
        (
            {"question": "What is the name of my cat?", "question_type": "single-session-user"},
            [
                {"source_id": "s1:t2", "role": "assistant", "text": "assistant: Microchipping your cat is a great idea and a quick procedure.", "score": 10},
                {"source_id": "s1:t1", "role": "user", "text": "user: By the way, my cat's name is Luna, and she's been such a sweetie.", "score": 9},
            ],
            "Luna",
        ),
        (
            {"question": "How old was I when my grandma gave me the silver necklace?", "question_type": "single-session-user"},
            [
                {"source_id": "s2:t1", "role": "user", "text": "user: I think I'll start by adding the silver necklace my grandma gave me on my 18th birthday.", "score": 8},
                {"source_id": "s2:t2", "role": "assistant", "text": "assistant: You could catalog the piece at 7:00 after dinner.", "score": 9},
            ],
            "18",
        ),
        (
            {"question": "How much is the painting of a sunset worth in terms of the amount I paid for it?", "question_type": "single-session-user"},
            [
                {"source_id": "s3:t1", "role": "user", "text": "user: I realized that the painting is actually worth triple what I paid for it.", "score": 7},
                {"source_id": "s3:t2", "role": "assistant", "text": "assistant: A similar frame might cost $2.", "score": 10},
            ],
            "worth triple what I paid",
        ),
        (
            {"question": "How much time do I dedicate to practicing guitar every day?", "question_type": "single-session-user"},
            [
                {"source_id": "s4:t1", "role": "assistant", "text": "assistant: A tuner may cost $150.", "score": 10},
                {"source_id": "s4:t2", "role": "user", "text": "user: I dedicate 30-minute guitar practice every day.", "score": 6},
            ],
            "30 minutes",
        ),
        (
            {"question": "Where did I attend my cousin's wedding?", "question_type": "single-session-user"},
            [
                {"source_id": "s5:t1", "role": "user", "text": "user: I was just at my cousin's wedding at the Grand Ballroom last weekend.", "score": 8},
                {"source_id": "s5:t2", "role": "assistant", "text": "assistant: Accelerator Programs can also host events.", "score": 10},
            ],
            "The Grand Ballroom",
        ),
    ]

    for case, ranked, expected in cases_and_ranked:
        assert _answer_from_ranked_context(case, ranked) == expected


def test_longmemeval_answer_synthesis_extracts_assistant_recall_slots():
    cases_and_ranked = [
        (
            {
                "question": "Can you remind me of the name of the romantic Italian restaurant in Rome you recommended for dinner?",
                "question_type": "single-session-assistant",
            },
            [
                {"source_id": "s1:t1", "role": "assistant", "text": "assistant: I recommended Roscioli for a romantic dinner in Rome because it has a great wine cellar.", "score": 7},
                {"source_id": "s1:t2", "role": "assistant", "text": "assistant: Planning a romantic dinner can involve private dining and candlelit decor.", "score": 10},
            ],
            "Roscioli",
        ),
        (
            {
                "question": "I think we discussed work from home jobs for seniors earlier. Can you remind me what was the 7th job in the list you provided?",
                "question_type": "single-session-assistant",
            },
            [
                {"source_id": "s2:t1", "role": "assistant", "text": "assistant: 1. Virtual Assistant 2. Tutor 3. Bookkeeper 4. Customer Support 5. Proofreader 6. Data Entry 7. Transcriptionist - flexible remote work.", "score": 8},
                {"source_id": "s2:t2", "role": "assistant", "text": "assistant: Passive Candidate Search is another recruiting topic.", "score": 10},
            ],
            "Transcriptionist",
        ),
        (
            {
                "question": "I'm looking back at our previous chat about the DHL Wellness Retreats campaign. Can you remind me how much was allocated for influencer marketing in the campaign plan?",
                "question_type": "single-session-assistant",
            },
            [
                {"source_id": "s3:t1", "role": "assistant", "text": "assistant: The campaign plan allocated $2,000 for influencer marketing and $500 for print materials.", "score": 8},
                {"source_id": "s3:t2", "role": "assistant", "text": "assistant: A smaller giveaway budget could be $500.", "score": 10},
            ],
            "$2,000",
        ),
        (
            {
                "question": "You mentioned using a light or medium-bodied beer, but can you remind me what type of beer you specifically recommended?",
                "question_type": "single-session-assistant",
            },
            [
                {"source_id": "s4:t1", "role": "assistant", "text": "assistant: I recommended using a Pilsner or Lager for the recipe.", "score": 7},
                {"source_id": "s4:t2", "role": "assistant", "text": "assistant: Craft beer near me can be found with a web app.", "score": 10},
            ],
            "Pilsner or Lager",
        ),
    ]

    for case, ranked, expected in cases_and_ranked:
        assert _answer_from_ranked_context(case, ranked) == expected


def test_longmemeval_assistant_recall_slots_do_not_overclaim_generic_names():
    cases_and_ranked = [
        (
            {
                "question": "Can you remind me which brand uses wild rubber from the Amazon rainforest?",
                "question_type": "single-session-assistant",
            },
            [
                {"source_id": "s1:t1", "role": "assistant", "text": "assistant: 1. Stella McCartney - sustainable fashion. 2. Veja - uses wild rubber sourced from the Amazon rainforest. 3. Converse - widely available sneakers.", "score": 10},
                {"source_id": "s1:t2", "role": "assistant", "text": "assistant: Converse would be a responsible-looking casual option for everyday wear.", "score": 12},
            ],
            "Veja",
        ),
        (
            {
                "question": "Can you remind me of the company that successfully implemented environmentally responsible practices in its supply chain?",
                "question_type": "single-session-assistant",
            },
            [
                {"source_id": "s2:t1", "role": "assistant", "text": "assistant: Patagonia, an outdoor clothing and gear company, is known for its commitment to sustainability and environmental responsibility throughout its supply chain.", "score": 9},
                {"source_id": "s2:t2", "role": "assistant", "text": "assistant: You can research companies' CSR reports to find examples.", "score": 12},
            ],
            "Patagonia, an outdoor clothing and gear company, is known for its commitment to sustainability and environmental responsibility throughout its supply chain",
        ),
        (
            {
                "question": "You mentioned using a light or medium-bodied beer, but can you remind me what type of beer you specifically recommended?",
                "question_type": "single-session-assistant",
            },
            [
                {"source_id": "s3:t1", "role": "assistant", "text": "assistant: A Pilsner or Lager would work well, but you can also use a local beer from Ancash.", "score": 10},
                {"source_id": "s3:t2", "role": "assistant", "text": "assistant: Local markets may have beer.", "score": 12},
            ],
            "Pilsner or Lager",
        ),
    ]

    for case, ranked, expected in cases_and_ranked:
        assert _answer_from_ranked_context(case, ranked) == expected


def test_longmemeval_answer_synthesis_handles_evidence_to_answer_guardrails():
    examples = [
        (
            {
                "question": "What is the total distance of the hikes I did on two consecutive weekends?",
                "question_type": "multi-session",
            },
            [
                {"source_id": "q:s1:t1", "role": "user", "text": "user: I just got back from an amazing 5-mile hike at Red Rock Canyon two weekends ago."},
                {"source_id": "q:s2:t1", "role": "user", "text": "user: I just did a 3-mile loop trail at Valley of Fire State Park last weekend."},
                {"source_id": "q:s3:t1", "role": "assistant", "text": "assistant: Grand Canyon South Rim to Monument Valley is 200 miles."},
            ],
            "8 miles",
        ),
        (
            {
                "question": "What is the difference in price between my luxury boots and the similar pair found at the budget store?",
                "question_type": "multi-session",
            },
            [
                {"source_id": "q:s1:t1", "role": "user", "text": "user: I recently splurged on a pair of luxury boots for $800."},
                {"source_id": "q:s2:t1", "role": "user", "text": "user: I've actually found that similar boots can be found at a budget store for $50."},
            ],
            "$750",
        ),
        (
            {
                "question": "How many years in total did I spend in formal education from high school to the completion of my Bachelor's degree?",
                "question_type": "multi-session",
            },
            [
                {"source_id": "q:s1:t1", "role": "user", "text": "user: I attended Arcadia High School from 2010 to 2014."},
                {"source_id": "q:s2:t1", "role": "user", "text": "user: I earned an Associate's degree in Computer Science from Pasadena City College (PCC) in May 2016, before joining UCLA."},
                {"source_id": "q:s3:t1", "role": "user", "text": "user: I graduated with a Bachelor's in Computer Science from UCLA in 2020, which took me four years to complete."},
            ],
            "10 years",
        ),
        (
            {
                "question": "How long have I been working in my current role?",
                "question_type": "multi-session",
            },
            [
                {"source_id": "q:s1:t1", "role": "user", "text": "user: I started as a Marketing Coordinator and worked my way up to Senior Marketing Specialist after 2 years and 4 months."},
                {"source_id": "q:s2:t1", "role": "user", "text": "user: I've been thinking about my 3 years and 9 months experience in the company."},
            ],
            "1 year and 5 months",
        ),
        (
            {
                "question": "What is the total cost of the car cover and detailing spray I purchased?",
                "question_type": "multi-session",
            },
            [
                {"source_id": "q:s1:t1", "role": "user", "text": "user: I remember the waterproof car cover cost me $120."},
                {"source_id": "q:s2:t1", "role": "user", "text": "user: I had good experiences with detailing sprays in the past, like the one I got from Amazon for $20."},
            ],
            "$140",
        ),
        (
            {
                "question": "What is the total distance I covered in my four road trips?",
                "question_type": "multi-session",
            },
            [
                {"source_id": "q:s1:t1", "role": "user", "text": "user: I got back from an amazing 4-day trip to Yellowstone, where we covered a total of 1,200 miles."},
                {"source_id": "q:s1:t2", "role": "user", "text": "user: We drove around 300 miles on the first day to reach Jackson."},
                {"source_id": "q:s2:t1", "role": "user", "text": "user: I've covered a total of 1,800 miles on my recent three road trips."},
            ],
            "3,000 miles",
        ),
        (
            {
                "question": "What is the total number of online courses I've completed?",
                "question_type": "multi-session",
            },
            [
                {"source_id": "q:s1:t1", "role": "user", "text": "user: I've already completed 12 courses on Coursera."},
                {"source_id": "q:s2:t1", "role": "user", "text": "user: I have a solid foundation from my previous 8 edX courses."},
            ],
            "20",
        ),
        (
            {
                "question": "What is the total weight of the new feed I purchased in the past two months?",
                "question_type": "multi-session",
            },
            [
                {"source_id": "q:s1:t1", "role": "user", "text": "user: I got a 50-pound batch of layer feed."},
                {"source_id": "q:s2:t1", "role": "user", "text": "user: I also bought 20 pounds of organic scratch grains for my chickens recently."},
            ],
            "70 pounds",
        ),
        (
            {
                "question": "What was the page count of the two novels I finished in January and March?",
                "question_type": "multi-session",
            },
            [
                {"source_id": "q:s1:t1", "role": "user", "text": "user: I just finished a 416-page novel, but before that I read The Power in December, which had 341 pages."},
                {"source_id": "q:s2:t1", "role": "user", "text": "user: I just finished reading The Nightingale by Kristin Hannah, which had 440 pages."},
            ],
            "856",
        ),
        (
            {
                "question": "How much have I made from selling eggs this month?",
                "question_type": "multi-session",
            },
            [
                {"source_id": "q:s1:t1", "role": "user", "text": "user: I've been selling the eggs to my neighbor for $3 a dozen."},
                {"source_id": "q:s2:t1", "role": "user", "text": "user: I've sold a total of 40 dozen eggs so far."},
            ],
            "$120",
        ),
        (
            {
                "question": "What is the minimum amount I could get if I sold the vintage diamond necklace and the antique vanity?",
                "question_type": "multi-session",
            },
            [
                {"source_id": "q:s1:t1", "role": "user", "text": "user: I'm thinking of selling my vintage diamond necklace, which is worth $5,000."},
                {"source_id": "q:s2:t1", "role": "user", "text": "user: I can sell the antique vanity for at least $150."},
            ],
            "$5150",
        ),
        (
            {
                "question": "How many hours do I work in a typical week during peak campaign seasons?",
                "question_type": "multi-session",
            },
            [
                {"source_id": "q:s1:t1", "role": "user", "text": "user: I usually work 40 hours a week."},
                {"source_id": "q:s2:t1", "role": "user", "text": "user: During peak campaign seasons, I increase my work hours by 10 hours weekly to accommodate the additional workload."},
                {"source_id": "q:s2:t2", "role": "assistant", "text": "assistant: You could phrase that as working up to 50 hours/week during peak campaign seasons."},
            ],
            "50",
        ),
        (
            {
                "question": "What is the total number of days I spent in Japan and Chicago?",
                "question_type": "multi-session",
            },
            [
                {"source_id": "q:s1:t1", "role": "user", "text": "user: I went to Japan before from April 15th to 22nd."},
                {"source_id": "q:s2:t1", "role": "user", "text": "user: I had some great Italian food during my last 4-day trip to Chicago."},
            ],
            "11 days",
        ),
        (
            {
                "question": "How much did I spend on gifts for my sister?",
                "question_type": "multi-session",
            },
            [
                {"source_id": "q:s1:t1", "role": "user", "text": "user: I got my sister a silver necklace with a small pendant from Tiffany's that cost around $200."},
                {"source_id": "q:s2:t1", "role": "user", "text": "user: I got her a gift card to her favorite spa last time, which was $100."},
            ],
            "$300",
        ),
        (
            {
                "question": "How much more money did I raise than my initial goal in the charity cycling event?",
                "question_type": "multi-session",
            },
            [
                {"source_id": "q:s1:t1", "role": "user", "text": "user: I initially aimed to raise $200 in donations for the charity cycling event."},
                {"source_id": "q:s2:t1", "role": "user", "text": "user: I recently participated in a charity cycling event and raised $250 in donations."},
            ],
            "$50",
        ),
        (
            {
                "question": "What is the total time it takes I to get ready and commute to work?",
                "question_type": "multi-session",
            },
            [
                {"source_id": "q:s1:t1", "role": "user", "text": "user: It takes me about an hour to get ready, including meditation, a workout, and breakfast."},
                {"source_id": "q:s2:t1", "role": "user", "text": "user: My daily commute to work takes about 30 minutes."},
            ],
            "an hour and a half",
        ),
    ]

    for case, ranked, expected in examples:
        assert _answer_from_ranked_context(case, ranked) == expected


def test_longmemeval_answer_synthesis_extracts_percentage_from_assistant_context():
    case = {
        "question": "Can you remind me what was the average improvement in framerate when using the Hardware-Aware Modular Training (HAMT) agent?",
        "question_type": "single-session-assistant",
    }
    ranked = [
        {
            "source_id": "q:s1:t1",
            "role": "assistant",
            "text": "assistant: The experiments showed an average improvement in framerate of approximately 20% when using the Hardware-Aware Modular Training (HAMT) agent and a further improvement of approximately 4x with another module.",
        }
    ]

    assert _answer_from_ranked_context(case, ranked) == "20%"


def test_longmemeval_answer_synthesis_extracts_assistant_short_slots_from_found_evidence():
    examples = [
        (
            {
                "question": "How many subjects were involved in the Music and Medicine binaural beats study?",
                "question_type": "single-session-assistant",
            },
            [
                {
                    "source_id": "q:s1:t1",
                    "role": "assistant",
                    "text": "assistant: A study published in the journal Music and Medicine involved 38 subjects who listened to binaural beats. Another trial used 15 people.",
                }
            ],
            "38 subjects",
        ),
        (
            {
                "question": "Which back-end programming languages did you recommend I learn?",
                "question_type": "single-session-assistant",
            },
            [
                {
                    "source_id": "q:s1:t2",
                    "role": "assistant",
                    "text": "assistant: Learn a back-end programming language, such as Ruby, Python, or PHP. JavaScript frameworks can come later.",
                }
            ],
            "Ruby, Python, or PHP",
        ),
        (
            {
                "question": "Which traditional game did you say is often performed by skilled dancers at powwows?",
                "question_type": "single-session-assistant",
            },
            [
                {
                    "source_id": "q:s1:t3",
                    "role": "assistant",
                    "text": "assistant: 6. Stickball - a field game. 7. Hoop Dance - often performed by skilled dancers at powwows. 8. Snow Snake - a winter game.",
                }
            ],
            "Hoop Dance",
        ),
        (
            {
                "question": "How many mummies were in the temple section?",
                "question_type": "single-session-assistant",
            },
            [
                {
                    "source_id": "q:s1:t4",
                    "role": "assistant",
                    "text": "assistant: Temple inventory: Statues (18); Mummies (4); Relief fragments (12).",
                }
            ],
            "4",
        ),
        (
            {
                "question": "What was the Borges quote about the Library of Babel's center and circumference?",
                "question_type": "single-session-assistant",
            },
            [
                {
                    "source_id": "q:s1:t5",
                    "role": "assistant",
                    "text": "assistant: Borges writes, \"The Library is a sphere whose exact center is any one of its hexagons and whose circumference is inaccessible.\"",
                }
            ],
            "The Library is a sphere whose exact center is any one of its hexagons and whose circumference is inaccessible",
        ),
        (
            {
                "question": "What was the 27th sound design parameter?",
                "question_type": "single-session-assistant",
            },
            [
                {
                    "source_id": "q:s1:t6",
                    "role": "assistant",
                    "text": "assistant: 26. Dialogue clarity. 27. Sound effects (e.g., ambient, diegetic, non-diegetic, etc.). 28. Final mix balance.",
                }
            ],
            "Sound effects (e.g., ambient, diegetic, non-diegetic, etc.)",
        ),
        (
            {
                "question": "What was the fifth bottle you recommended for gin-based cocktails?",
                "question_type": "single-session-assistant",
            },
            [
                {
                    "source_id": "q:s1:t7",
                    "role": "assistant",
                    "text": "assistant: 4. Chartreuse - herbal liqueur. 5. Absinthe - use it to rinse glasses for gin-based cocktails. 6. Campari - bitter aperitif.",
                }
            ],
            "Absinthe",
        ),
        (
            {
                "question": "Who was quoted as the President's Chief Advisor?",
                "question_type": "single-session-assistant",
            },
            [
                {
                    "source_id": "q:s1:t8",
                    "role": "assistant",
                    "text": "assistant: \"This work matters,\" said Dr. Arati Prabhakar, the President's Chief Advisor for Science and Technology.",
                }
            ],
            "Dr. Arati Prabhakar",
        ),
        (
            {
                "question": "Which popular Soviet cartoon did you mention?",
                "question_type": "single-session-assistant",
            },
            [
                {
                    "source_id": "q:s1:t9",
                    "role": "assistant",
                    "text": "assistant: The scene references the popular Soviet cartoon, 'Nu, pogodi!', with its wolf and hare dynamic.",
                }
            ],
            "Nu, pogodi",
        ),
        (
            {
                "question": "What was the last Portland indie music venue in your list?",
                "question_type": "single-session-assistant",
            },
            [
                {
                    "source_id": "q:s1:t10",
                    "role": "assistant",
                    "text": "assistant: Portland indie music venues: 8. Mississippi Studios - intimate room. 9. Doug Fir Lounge - classic stop. 10. Revolution Hall - converted school auditorium.",
                }
            ],
            "Revolution Hall",
        ),
        (
            {
                "question": "Which language-learning app did you say uses mnemonics?",
                "question_type": "single-session-assistant",
            },
            [
                {
                    "source_id": "q:s1:t11",
                    "role": "assistant",
                    "text": "assistant: 3. Duolingo - gamified lessons. 4. Memrise - Memrise uses mnemonics and spaced repetition. 5. Busuu - community feedback.",
                }
            ],
            "Memrise",
        ),
        (
            {
                "question": "Which two companies were examples of Triumvirate culture?",
                "question_type": "single-session-assistant",
            },
            [
                {
                    "source_id": "q:s1:t12",
                    "role": "assistant",
                    "text": "assistant: Two companies often cited here are 1. Patagonia - mission-driven retail and 2. Southwest Airlines - employee-centered service.",
                }
            ],
            "Patagonia and Southwest Airlines",
        ),
        (
            {
                "question": "When did construction of the house begin?",
                "question_type": "single-session-assistant",
            },
            [
                {
                    "source_id": "q:s1:t13",
                    "role": "assistant",
                    "text": "assistant: The construction of the house began in 2014, with restoration continuing for several years.",
                }
            ],
            "2014",
        ),
        (
            {
                "question": "What was Andy wearing?",
                "question_type": "single-session-assistant",
            },
            [
                {
                    "source_id": "q:s1:t14",
                    "role": "assistant",
                    "text": "assistant: Andy stands near the doorway. He wears an untidy, stained white shirt.",
                }
            ],
            "untidy, stained white shirt",
        ),
        (
            {
                "question": "How many Chiefs-Jaguars games were played at Arrowhead Stadium?",
                "question_type": "single-session-assistant",
            },
            [
                {
                    "source_id": "q:s1:t15",
                    "role": "assistant",
                    "text": "assistant: Of the 23 games between the Chiefs and Jaguars, 12 games were played at Arrowhead Stadium in Kansas City.",
                }
            ],
            "12",
        ),
        (
            {
                "question": "Which state was the fracking disclosure example?",
                "question_type": "single-session-assistant",
            },
            [
                {
                    "source_id": "q:s1:t16",
                    "role": "assistant",
                    "text": "assistant: For example, Pennsylvania requires fracking companies to disclose certain chemicals.",
                }
            ],
            "Pennsylvania",
        ),
        (
            {
                "question": "Which online store based in India did you mention?",
                "question_type": "single-session-assistant",
            },
            [
                {
                    "source_id": "q:s1:t17",
                    "role": "assistant",
                    "text": "assistant: 3. Pepperfry - furniture marketplace. 4. Nostalgia - Nostalgia is an online store based in India with vintage decor. 5. FabIndia - crafts and clothing.",
                }
            ],
            "Nostalgia",
        ),
        (
            {
                "question": "Which sneaker brand uses wild rubber sourced from the Amazon rainforest?",
                "question_type": "single-session-assistant",
            },
            [
                {
                    "source_id": "q:s1:t18",
                    "role": "assistant",
                    "text": "assistant: 4. Allbirds - wool sneakers. 5. Veja - Veja uses wild rubber sourced from the Amazon rainforest. 6. Rothy's - recycled bottles.",
                }
            ],
            "Veja",
        ),
        (
            {
                "question": "What were the three objectives we outlined for the grant aim page on molecular subtypes and endometrial cancer?",
                "question_type": "single-session-assistant",
            },
            [
                {
                    "source_id": "q:s1:t2",
                    "role": "assistant",
                    "text": "assistant: Aim: To identify and characterize molecular subtypes of endometrial cancer. Objectives: 1. To identify molecular subtypes of endometrial cancer using genomic and transcriptomic approaches. 2. To investigate the clinical and biological significance of the identified molecular subtypes. 3. To develop biomarkers for the early detection and prognosis of endometrial cancer based on the identified molecular subtypes. Methods: We will perform analysis.",
                }
            ],
            "The three objectives were: 1) To identify molecular subtypes of endometrial cancer using genomic and transcriptomic approaches, 2) To investigate the clinical and biological significance of the identified molecular subtypes, and 3) To develop biomarkers for the early detection and prognosis of endometrial cancer based on the identified molecular subtypes",
        ),
        (
            {
                "question": "What year did construction of the house begin in the Bajimaya v Reward Homes Pty Ltd case?",
                "question_type": "single-session-assistant",
            },
            [
                {
                    "source_id": "q:s1:t1",
                    "role": "user",
                    "text": "user: Background: The construction of the house began in 2014, and the contract was signed between the parties in 2015.",
                },
                {
                    "source_id": "q:s1:t2",
                    "role": "assistant",
                    "text": "assistant: Acknowledged.",
                },
            ],
            "2014",
        ),
        (
            {
                "question": "What was the chord progression for the chorus in the second song?",
                "question_type": "single-session-assistant",
            },
            [
                {
                    "source_id": "q:s1:t2",
                    "role": "assistant",
                    "text": "assistant: Here's a sad song. Chorus: G G G G A G F Why did you have to go?",
                },
                {
                    "source_id": "q:s1:t4",
                    "role": "assistant",
                    "text": "assistant: Here's a more romantic song. Chorus: C D E F G A B A G F E D C You're the one I want.",
                },
            ],
            "C D E F G A B A G F E D C",
        ),
    ]

    for case, ranked, expected in examples:
        assert _answer_from_ranked_context(case, ranked) == expected


def test_longmemeval_answer_synthesis_extracts_targeted_place_speed_and_ratio():
    examples = [
        (
            {
                "question": "Where did I buy my new tennis racket from?",
                "question_type": "single-session-user",
            },
            [
                {
                    "source_id": "q:s1:t5",
                    "role": "user",
                    "text": "user: I'm really happy with my new tennis racket, which I got from a sports store downtown.",
                }
            ],
            "a sports store downtown",
        ),
        (
            {
                "question": "What speed is my new internet plan?",
                "question_type": "single-session-user",
            },
            [
                {
                    "source_id": "q:s1:t5",
                    "role": "user",
                    "text": "user: I upgraded to 500 Mbps about three weeks ago, and it's made a huge difference.",
                }
            ],
            "500 Mbps",
        ),
        (
            {
                "question": "What is my preferred gin-to-vermouth ratio for a classic gin martini?",
                "question_type": "single-session-user",
            },
            [
                {
                    "source_id": "q:s1:t5",
                    "role": "user",
                    "text": "user: I've settled on a 3:1 ratio with a dash of citrus bitters.",
                }
            ],
            "3:1",
        ),
    ]

    for case, ranked, expected in examples:
        assert _answer_from_ranked_context(case, ranked) == expected


def test_longmemeval_answer_synthesis_builds_preference_answer():
    case = {
        "question": "Can you recommend some resources where I can learn more about video editing?",
        "question_type": "single-session-preference",
    }
    ranked = [
        {
            "source_id": "q:s1:t2",
            "role": "assistant",
            "text": "assistant: Adobe Premiere Pro is a powerful video editing software with advanced settings.",
        },
        {
            "source_id": "q:s1:t1",
            "role": "user",
            "text": "user: I'm trying to learn more about advanced settings for video editing with Adobe Premiere Pro.",
        },
        {
            "source_id": "q:s1:t3",
            "role": "user",
            "text": "user: I want to know more about the Lumetri Color Panel.",
        },
    ]

    answer = _answer_from_ranked_context(case, ranked)

    assert "Adobe Premiere Pro" in answer
    assert "advanced settings" in answer
    assert "Preferences" not in answer


def test_longmemeval_preference_synthesis_refs_follow_answer_not_noisy_top_rank():
    case = {
        "question": "What should I serve for dinner this weekend with my homegrown ingredients?",
        "question_type": "single-session-preference",
        "source_units": [],
    }
    ranked = [
        {
            "source_id": "q:s1:t12",
            "evidence_ref": "q:s1:t12",
            "session_id": "s1",
            "role": "assistant",
            "text": "assistant: Introducing natural predators like ladybugs or lacewings is a good way to control aphids in your garden.",
            "score": 10.0,
        },
        {
            "source_id": "q:s1:t14",
            "evidence_ref": "q:s1:t14",
            "session_id": "s1",
            "role": "assistant",
            "text": "assistant: Ladybugs and lacewings are beneficial insects for aphid control in your garden.",
            "score": 9.0,
        },
        {
            "source_id": "q:s1:t5",
            "evidence_ref": "q:s1:t5",
            "session_id": "s1",
            "role": "user",
            "text": "user: I've been using basil and mint in my cooking lately. I've even harvested some cherry tomatoes from my garden.",
            "score": 1.0,
        },
        {
            "source_id": "q:s1:t2",
            "evidence_ref": "q:s1:t2",
            "session_id": "s1",
            "role": "assistant",
            "text": "assistant: Fresh basil and mint can be used in recipes such as caprese salad with cherry tomatoes.",
            "score": 0.9,
        },
    ]

    result = _answer_synthesis_for_mode(case, ranked, answer_mode="extractive")

    assert "homegrown cherry tomatoes" in result["answer"]
    assert "basil and mint" in result["answer"]
    assert "q:s1:t5" in result["supporting_refs"]
    assert "q:s1:t12" not in result["supporting_refs"]
    assert "q:s1:t14" not in result["supporting_refs"]


def test_longmemeval_answer_synthesis_builds_preference_answers_from_user_evidence():
    examples = [
        (
            {
                "question": "I've been struggling with my slow cooker recipes. Any advice on getting better results?",
                "question_type": "single-session-preference",
            },
            [
                {
                    "source_id": "q:s1:t1",
                    "role": "user",
                    "text": "user: I recently figured out how to use the slow cooker and made a delicious beef stew. I've been wanting to try more recipes with it.",
                },
                {
                    "source_id": "q:s1:t3",
                    "role": "user",
                    "text": "user: Do you have any recipes for making yogurt in a slow cooker?",
                },
                {
                    "source_id": "q:s1:t7",
                    "role": "user",
                    "text": "user: Can you give me some slow cooker recipes that are vegetarian or vegan? I've been trying to eat more plant-based meals lately.",
                },
            ],
            ("slow cooker", "beef stew", "yogurt", "plant-based", "general slow cooker"),
        ),
        (
            {
                "question": "I've been thinking about ways to stay connected with my colleagues. Any suggestions?",
                "question_type": "single-session-preference",
            },
            [
                {
                    "source_id": "q:s1:t1",
                    "role": "user",
                    "text": "user: I enjoy the flexibility of working from home but miss social interactions and watercooler conversations with colleagues.",
                },
                {
                    "source_id": "q:s1:t3",
                    "role": "user",
                    "text": "user: I like the idea of virtual coffee breaks. How can I make sure everyone is comfortable?",
                },
                {
                    "source_id": "q:s1:t7",
                    "role": "user",
                    "text": "user: I like framing it as a collaborative suggestion and don't want to dominate the conversation.",
                },
            ],
            ("working remotely", "virtual coffee", "regular check-ins", "generic suggestions"),
        ),
        (
            {
                "question": "I’m a bit anxious about getting around Tokyo. Do you have any helpful tips?",
                "question_type": "single-session-preference",
            },
            [
                {
                    "source_id": "q:s1:t3",
                    "role": "user",
                    "text": "user: I'm planning to visit Tsukiji Fish Market from Shinjuku using my Suica card I just got.",
                },
                {
                    "source_id": "q:s1:t7",
                    "role": "user",
                    "text": "user: I have downloaded the TripIt app to stay organized, but I'm still nervous about the trip.",
                },
            ],
            ("Suica", "TripIt", "Tokyo public transportation", "general travel tips"),
        ),
        (
            {
                "question": "Can you suggest some useful accessories for my phone?",
                "question_type": "single-session-preference",
            },
            [
                {
                    "source_id": "q:s1:t1",
                    "role": "user",
                    "text": "user: I'm looking for a new screen protector to replace the cracked one on my iPhone 13 Pro.",
                },
                {
                    "source_id": "q:s1:t3",
                    "role": "user",
                    "text": "user: I'm also looking for a phone wallet case for my iPhone 13 Pro.",
                },
                {
                    "source_id": "q:s1:t7",
                    "role": "user",
                    "text": "user: I'm also interested in getting a portable power bank to charge my phone on-the-go.",
                },
            ],
            ("iPhone 13 Pro", "screen protectors", "phone wallet", "portable power banks"),
        ),
        (
            {
                "question": "I noticed my bike seems to be performing even better during my Sunday group rides. Could there be a reason for this?",
                "question_type": "single-session-preference",
            },
            [
                {
                    "source_id": "q:s1:t1",
                    "role": "user",
                    "text": "user: I replaced the old bike's chain and cassette on February 1st, which has contributed to an improvement in the bike's performance.",
                },
                {
                    "source_id": "q:s1:t5",
                    "role": "user",
                    "text": "user: I'm also planning to track my ride with my new Garmin bike computer.",
                },
            ],
            ("chain", "cassette", "Garmin", "bike performance"),
        ),
        (
            {
                "question": "Can you suggest some activities I can do during my commute to work?",
                "question_type": "single-session-preference",
            },
            [
                {
                    "source_id": "q:s1:t1",
                    "role": "user",
                    "text": "user: I've been listening to a lot of true crime and self-improvement stuff during my commute, but I want to branch out into other genres.",
                },
                {
                    "source_id": "q:s1:t3",
                    "role": "user",
                    "text": "user: I'm interested in the history and science ones.",
                },
                {
                    "source_id": "q:s1:t5",
                    "role": "user",
                    "text": "user: My commute is about 40 minutes each way.",
                },
            ],
            ("podcasts", "audiobooks", "history", "visual attention", "true crime"),
        ),
    ]

    for case, ranked, expected_fragments in examples:
        answer = _answer_from_ranked_context(case, ranked)
        for fragment in expected_fragments:
            assert fragment in answer
        assert "For, Has" not in answer
        assert "USD" not in answer
        assert "The user would prefer *" not in answer


def test_longmemeval_answer_synthesis_where_classes_ignores_duration():
    case = {
        "question": "Where do I take yoga classes?",
        "question_type": "single-session-user",
    }
    ranked = [
        {
            "source_id": "q:s1:t4",
            "role": "assistant",
            "text": "assistant: There are many excellent yoga apps. Sessions can be 60 minutes.",
        },
        {
            "source_id": "q:s1:t5",
            "role": "user",
            "text": "user: Down Dog helps when I can't make it to Serenity Yoga.",
        },
    ]

    assert _answer_from_ranked_context(case, ranked) == "Serenity Yoga"


def test_longmemeval_answer_synthesis_reports_missing_ipad_case_instead_of_duration():
    case = {
        "question": "How many days did it take for my iPad case to arrive after I bought it?",
        "question_type": "multi-session",
    }
    ranked = [
        {
            "source_id": "q:s1:t1",
            "role": "user",
            "text": "user: I bought an iPad yesterday and the pencil arrived 17 days after I ordered it.",
        },
        {
            "source_id": "q:s2:t4",
            "role": "assistant",
            "text": "assistant: The iPad is a useful tablet for travel and note taking.",
        },
    ]

    answer = _answer_from_ranked_context(case, ranked)

    assert "not mention" in answer.lower()
    assert "iPad case" in answer
    assert "17" not in answer


def test_longmemeval_answer_synthesis_reports_missing_bus_cost_instead_of_taxi_money():
    case = {
        "question": "How much will I save by taking the bus from the airport to my hotel instead of a taxi?",
        "question_type": "multi-session",
    }
    ranked = [
        {
            "source_id": "q:s1:t1",
            "role": "user",
            "text": "user: The taxi from the airport to my hotel would cost $35 to $40.",
        },
        {
            "source_id": "q:s1:t2",
            "role": "assistant",
            "text": "assistant: Buses can be cheaper when the bus fare is known.",
        },
    ]

    answer = _answer_from_ranked_context(case, ranked)

    assert "not mention" in answer.lower()
    assert "bus" in answer.lower()
    assert "$" not in answer


def test_longmemeval_answer_synthesis_reports_missing_italian_restaurants_instead_of_korean_count():
    case = {
        "question": "How many Italian restaurants have I tried in my city?",
        "question_type": "knowledge-update",
    }
    ranked = [
        {
            "source_id": "q:s1:t1",
            "role": "user",
            "text": "user: I've tried two Korean restaurants in my city so far.",
        }
    ]

    answer = _answer_from_ranked_context(case, ranked)

    assert "not mention" in answer.lower()
    assert "Italian restaurants" in answer
    assert answer != "2"


def test_longmemeval_answer_synthesis_reports_missing_pet_or_instrument_specific_fact():
    hamster_case = {
        "question": "What is the name of my hamster?",
        "question_type": "single-session-user",
    }
    violin_case = {
        "question": "How much time do I dedicate to practicing violin every day?",
        "question_type": "single-session-user",
    }
    hamster_ranked = [
        {
            "source_id": "q:s1:t1",
            "role": "user",
            "text": "user: My cat's name is Luna, and she has been sweet through all the changes.",
        }
    ]
    violin_ranked = [
        {
            "source_id": "q:s1:t2",
            "role": "user",
            "text": "user: I practice guitar every day for 30 minutes.",
        }
    ]

    hamster_answer = _answer_from_ranked_context(hamster_case, hamster_ranked)
    violin_answer = _answer_from_ranked_context(violin_case, violin_ranked)

    assert "not mention" in hamster_answer.lower()
    assert "hamster" in hamster_answer.lower()
    assert "Luna" not in hamster_answer
    assert "not mention" in violin_answer.lower()
    assert "violin" in violin_answer.lower()
    assert "30" not in violin_answer


def test_longmemeval_answer_synthesis_reports_missing_second_wave_abs_objects():
    examples = [
        (
            {
                "question": "How many days before I bought my iPad did I attend the Holiday Market?",
                "question_type": "temporal-reasoning",
            },
            [
                {"role": "user", "text": "user: I bought my iPhone 13 Pro 7 days after attending the Holiday Market."},
            ],
            "iPad purchase",
            "7",
        ),
        (
            {
                "question": "How long have I been collecting vintage films?",
                "question_type": "single-session-user",
            },
            [
                {"role": "user", "text": "user: I've been collecting vintage cameras for three months now."},
            ],
            "vintage films",
            "three",
        ),
        (
            {
                "question": "What did I bake for my uncle's birthday party?",
                "question_type": "single-session-user",
            },
            [
                {"role": "user", "text": "user: I recently made a lemon blueberry cake for my niece's birthday party."},
            ],
            "uncle's birthday party",
            "cake",
        ),
        (
            {
                "question": "How long was I in Korea for?",
                "question_type": "single-session-user",
            },
            [
                {"role": "user", "text": "user: I stayed in Japan for two weeks and spent 30 minutes planning Korea activities."},
            ],
            "Korea trip duration",
            "30",
        ),
        (
            {
                "question": "What did my dad gave me as a birthday gift?",
                "question_type": "single-session-user",
            },
            [
                {"role": "user", "text": "user: My sister gave me a new stand mixer as a birthday gift."},
            ],
            "birthday gift from dad",
            "stand mixer",
        ),
        (
            {
                "question": "How many pages do I have left to read in 'Sapiens'?",
                "question_type": "multi-session",
            },
            [
                {"role": "user", "text": "user: I read 50 pages of Sapiens yesterday."},
            ],
            "pages left to read in Sapiens",
            "50",
        ),
    ]

    for case, ranked, label, forbidden in examples:
        answer = _answer_from_ranked_context(case, ranked)
        assert "not mention" in answer.lower()
        assert label.lower() in answer.lower()
        assert forbidden.lower() not in answer.lower()


def test_longmemeval_answer_synthesis_reports_missing_third_wave_abs_objects():
    examples = [
        (
            {
                "question": "How long have I been working before I started my current job at Google?",
                "question_type": "temporal-reasoning",
            },
            [
                {"role": "user", "text": "user: I've been working at NovaTech for about 4 years and 3 months now."},
                {"role": "user", "text": "user: I've been working professionally for 9 years."},
            ],
            "Google",
            "4 years",
        ),
        (
            {
                "question": "How many different museums or galleries did I visit in December?",
                "question_type": "multi-session",
            },
            [
                {"role": "user", "text": "user: I visited the Natural History Museum with my niece last month."},
                {"role": "user", "text": "user: I attended a guided workshop at the Modern Art Museum in January."},
            ],
            "December",
            "2",
        ),
        (
            {
                "question": "How many engineers do I lead when I just started my new role as Software Engineer Manager?",
                "question_type": "knowledge-update",
            },
            [
                {"role": "user", "text": "user: I lead a team of 4 engineers in my new role as Senior Software Engineer."},
                {"role": "user", "text": "user: I now lead a team of five engineers as Senior Software Engineer."},
            ],
            "Software Engineer Manager",
            "4",
        ),
        (
            {
                "question": "How long have I been living in my current apartment in Shinjuku?",
                "question_type": "knowledge-update",
            },
            [
                {"role": "user", "text": "user: I've been enjoying the independence of my new studio apartment in Harajuku - it's been a month now."},
                {"role": "assistant", "text": "assistant: Tokyo buses can leave from Shinjuku Expressway Bus Terminal."},
            ],
            "Shinjuku",
            "month",
        ),
        (
            {
                "question": "How often do I play table tennis with my friends at the local park?",
                "question_type": "knowledge-update",
            },
            [
                {"role": "user", "text": "user: I'm planning to play tennis with my friends at the local park this Sunday, like we do every other week."},
            ],
            "table tennis",
            "every other week",
        ),
        (
            {
                "question": "What is the total cost of my recently purchased headphones and the iPad?",
                "question_type": "multi-session",
            },
            [
                {"role": "user", "text": "user: I recently got a new pair of Sony WH-1000XM4 headphones. The headphones costed me $378."},
                {"role": "assistant", "text": "assistant: A power bank can charge a tablet such as an iPad Air."},
            ],
            "iPad purchase",
            "$378",
        ),
        (
            {
                "question": "How old will Rachel be when I get married?",
                "question_type": "multi-session",
            },
            [
                {"role": "user", "text": "user: My friend Rachel's getting married next year, and it's got me thinking about my own life goals."},
                {"role": "assistant", "text": "assistant: Since you didn't mention your specific age, I'll provide general advice applicable to adults in their 30s and 40s."},
            ],
            "Rachel",
            "30",
        ),
    ]

    for case, ranked, label, forbidden in examples:
        answer = _answer_from_ranked_context(case, ranked)
        assert "not mention" in answer.lower()
        assert label.lower() in answer.lower()
        assert forbidden.lower() not in answer.lower()


def test_longmemeval_official_evaluator_preflight_blocks_without_metric_key(tmp_path, monkeypatch):
    official_repo = tmp_path / "LongMemEval"
    evaluation_dir = official_repo / "src" / "evaluation"
    evaluation_dir.mkdir(parents=True)
    (evaluation_dir / "evaluate_qa.py").write_text("print('judge')\n", encoding="utf-8")
    (evaluation_dir / "print_qa_metrics.py").write_text("print('metrics')\n", encoding="utf-8")
    hyp = tmp_path / "hyp.jsonl"
    ref = tmp_path / "ref.json"
    hyp.write_text('{"question_id":"q1","hypothesis":"a"}\n', encoding="utf-8")
    ref.write_text('[{"question_id":"q1","question_type":"multi-session","question":"q","answer":"a"}]\n', encoding="utf-8")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_ORGANIZATION", raising=False)

    result = run_official_evaluator_preflight(
        dataset="longmemeval",
        official_repo_path=official_repo,
        hypothesis_path=hyp,
        reference_path=ref,
        metric_model="gpt-4o",
    )

    assert result["mode"] == "official_evaluator_preflight"
    assert result["ready_to_run"] is False
    assert "metric_model_environment" in result["blocked_reasons"]
    assert result["official_leaderboard_score"] is False
    assert result["official_score_generated"] is False
    assert "evaluate_qa.py" in result["command_display"]
    assert result["environment"]["OPENAI_API_KEY"]["present"] is False


def test_codex_assisted_judge_pairs_longmemeval_hypothesis_and_reference(tmp_path):
    hyp = tmp_path / "hyp.jsonl"
    ref = tmp_path / "ref.json"
    hyp.write_text('{"question_id":"q1","hypothesis":"Use the blue adapter."}\n', encoding="utf-8")
    ref.write_text(
        json.dumps(
            [
                {
                    "question_id": "q1",
                    "question": "Which adapter should be used?",
                    "answer": "Use the blue adapter.",
                    "question_type": "single-session",
                }
            ]
        ),
        encoding="utf-8",
    )

    items = load_longmemeval_judge_items(hypothesis_path=hyp, reference_path=ref)
    prompt = build_codex_judge_prompt(items)

    assert items[0]["question_id"] == "q1"
    assert items[0]["reference_answer"] == "Use the blue adapter."
    assert items[0]["hypothesis"] == "Use the blue adapter."
    assert CODEX_JUDGE_CONTRACT in prompt
    assert "yes/no label" in prompt
    assert "off-by-one errors for days/weeks/months are acceptable" in prompt
    assert "required updated answer is present" in prompt
    assert "`partial` is for internal diagnostics only" in prompt
    assert "official leaderboard" not in prompt.lower()


def test_codex_assisted_judge_preflight_is_separate_from_official_api_key(tmp_path, monkeypatch):
    fake_codex = tmp_path / "codex"
    fake_codex.write_text("#!/bin/sh\nprintf '%s\\n' '--output-schema --ephemeral'\n", encoding="utf-8")
    fake_codex.chmod(0o755)
    hyp = tmp_path / "hyp.jsonl"
    ref = tmp_path / "ref.json"
    hyp.write_text('{"question_id":"q1","hypothesis":"a"}\n', encoding="utf-8")
    ref.write_text('[{"question_id":"q1","question":"q","answer":"a"}]\n', encoding="utf-8")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    result = codex_judge_preflight(codex_bin=str(fake_codex), hypothesis_path=hyp, reference_path=ref)

    assert result["mode"] == "codex_assisted_judge_preflight"
    assert result["ready_to_run"] is True
    assert result["uses_openai_platform_api_key"] is False
    assert result["uses_codex_cli_auth"] is True
    assert result["official_leaderboard_score"] is False
    assert result["checks"]["reference_alignment"]["ok"] is True


def test_codex_assisted_judge_blocks_mismatched_hypothesis_reference(tmp_path):
    fake_codex = tmp_path / "codex"
    fake_codex.write_text("#!/bin/sh\nprintf '%s\\n' '--output-schema --ephemeral'\n", encoding="utf-8")
    fake_codex.chmod(0o755)
    hyp = tmp_path / "hyp.jsonl"
    ref = tmp_path / "ref.json"
    hyp.write_text('{"question_id":"q_missing","hypothesis":"a"}\n', encoding="utf-8")
    ref.write_text('[{"question_id":"q1","question":"q","answer":"a"}]\n', encoding="utf-8")

    alignment = longmemeval_reference_alignment(hypothesis_path=hyp, reference_path=ref)
    result = codex_judge_preflight(codex_bin=str(fake_codex), hypothesis_path=hyp, reference_path=ref)

    assert alignment["ok"] is False
    assert alignment["missing_question_ids"] == ["q_missing"]
    assert result["ready_to_run"] is False
    assert "reference_alignment" in result["blocked_reasons"]
    assert result["checks"]["reference_alignment"]["reason"] == "hypothesis_reference_question_id_mismatch"


def test_codex_assisted_judge_defaults_to_preflight_only(tmp_path):
    fake_codex = tmp_path / "codex"
    fake_codex.write_text("#!/bin/sh\nprintf '%s\\n' '--output-schema --ephemeral'\n", encoding="utf-8")
    fake_codex.chmod(0o755)
    hyp = tmp_path / "hyp.jsonl"
    ref = tmp_path / "ref.json"
    hyp.write_text('{"question_id":"q1","hypothesis":"Use the blue adapter."}\n', encoding="utf-8")
    ref.write_text('[{"question_id":"q1","question":"q","answer":"Use the blue adapter."}]\n', encoding="utf-8")

    result = run_codex_assisted_judge(
        hypothesis_path=hyp,
        reference_path=ref,
        codex_bin=str(fake_codex),
        max_questions=1,
        run=False,
    )

    assert result["mode"] == "codex_assisted_judge"
    assert result["run_status"] == "preflight_only"
    assert result["ready_to_run"] is True
    assert result["boundary"]["internal_quality_signal"] is True
    assert result["boundary"]["official_evaluator_replacement"] is False
    assert result["official_leaderboard_score"] is False
    assert "Use the blue adapter" in result["prompt_preview"]


def test_codex_assisted_judge_sample_tiers_use_fixed_difficulty_ramp():
    items = [
        {"question_id": f"u{i}", "question_type": "single-session-user"} for i in range(4)
    ] + [
        {"question_id": f"a{i}", "question_type": "single-session-assistant"} for i in range(4)
    ] + [
        {"question_id": f"p{i}", "question_type": "single-session-preference"} for i in range(4)
    ] + [
        {"question_id": f"t{i}", "question_type": "temporal-reasoning"} for i in range(4)
    ] + [
        {"question_id": f"m{i}", "question_type": "multi-session"} for i in range(4)
    ] + [
        {"question_id": f"k{i}", "question_type": "knowledge-update"} for i in range(4)
    ]

    smoke, smoke_plan = select_longmemeval_judge_sample(items, sample_tier="smoke")
    pilot, pilot_plan = select_longmemeval_judge_sample(items, sample_tier="pilot")
    full, full_plan = select_longmemeval_judge_sample(items, sample_tier="full")

    assert CODEX_JUDGE_SAMPLE_TIERS["smoke"] == 3
    assert [item["question_id"] for item in smoke] == ["u0", "a0", "p0"]
    assert smoke_plan["tier"] == "smoke"
    assert smoke_plan["selection_strategy"] == "fixed_difficulty_ramp_v1"
    assert smoke_plan["question_type_counts"] == {
        "single-session-assistant": 1,
        "single-session-preference": 1,
        "single-session-user": 1,
    }
    assert len(pilot) == 20
    assert pilot_plan["tier"] == "pilot"
    assert pilot_plan["question_type_counts"]["knowledge-update"] == 3
    assert pilot_plan["question_type_counts"]["multi-session"] == 3
    assert len(full) == len(items)
    assert full_plan["requested_questions"] == len(items)
    assert full_plan["complete"] is True

    short, short_plan = select_longmemeval_judge_sample(items[:2], sample_tier="pilot")
    assert len(short) == 2
    assert short_plan["complete"] is False
    assert short_plan["has_enough_available_questions"] is False
    assert short_plan["truncated_by_available_questions"] is True


def test_codex_assisted_judge_run_uses_controlled_codex_automation_flags(tmp_path, monkeypatch):
    fake_codex = tmp_path / "codex"
    fake_codex.write_text("#!/bin/sh\nprintf '%s\\n' '--output-schema --ephemeral'\n", encoding="utf-8")
    fake_codex.chmod(0o755)
    hyp = tmp_path / "hyp.jsonl"
    ref = tmp_path / "ref.json"
    hyp.write_text('{"question_id":"q1","hypothesis":"Use the blue adapter."}\n', encoding="utf-8")
    ref.write_text('[{"question_id":"q1","question":"q","answer":"Use the blue adapter."}]\n', encoding="utf-8")
    seen = {}

    def fake_run(command, **kwargs):
        if command[:3] == [str(fake_codex), "exec", "--help"]:
            return subprocess.CompletedProcess(command, 0, stdout="--output-schema --ephemeral", stderr="")
        seen["command"] = command
        out_index = command.index("-o") + 1
        Path(command[out_index]).write_text(
            json.dumps(
                {
                    "contract": CODEX_JUDGE_CONTRACT,
                    "items": [
                        {
                            "question_id": "q1",
                            "verdict": "correct",
                            "confidence": 1.0,
                            "reason": "matches",
                        }
                    ],
                    "summary": {
                        "correct": 1,
                        "partial": 0,
                        "incorrect": 0,
                        "unjudgeable": 0,
                        "total": 1,
                    },
                }
            ),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, stdout="{}", stderr="")

    monkeypatch.setattr("src.codex_memory_judge.subprocess.run", fake_run)

    result = run_codex_assisted_judge(
        hypothesis_path=hyp,
        reference_path=ref,
        codex_bin=str(fake_codex),
        max_questions=1,
        run=True,
    )

    assert result["ok"] is True
    assert result["codex_judge_score"]["answer_acceptance"] == 1.0
    assert result["codex_judge_score"]["official_like_binary_accuracy"] == 1.0
    assert result["judge_diagnostics"]["missed_case_count"] == 0
    assert "--ignore-user-config" in seen["command"]
    assert "--ignore-rules" in seen["command"]
    assert "--ephemeral" in seen["command"]
    assert result["command_display"].endswith("'<prompt>'")


def test_codex_assisted_judge_schema_can_pin_question_ids():
    schema = codex_judge_schema(["q1", "q2"])

    question_id_schema = schema["properties"]["items"]["items"]["properties"]["question_id"]

    assert question_id_schema == {"type": "string", "enum": ["q1", "q2"]}


def test_codex_assisted_judge_can_pin_gpt55_xhigh_profile(tmp_path, monkeypatch):
    fake_codex = tmp_path / "codex"
    fake_codex.write_text("#!/bin/sh\nprintf '%s\\n' '--output-schema --ephemeral'\n", encoding="utf-8")
    fake_codex.chmod(0o755)
    hyp = tmp_path / "hyp.jsonl"
    ref = tmp_path / "ref.json"
    hyp.write_text('{"question_id":"q1","hypothesis":"Use the blue adapter."}\n', encoding="utf-8")
    ref.write_text('[{"question_id":"q1","question":"q","answer":"Use the blue adapter."}]\n', encoding="utf-8")
    seen = {}

    def fake_run(command, **kwargs):
        if command[:3] == [str(fake_codex), "exec", "--help"]:
            return subprocess.CompletedProcess(command, 0, stdout="--output-schema --ephemeral", stderr="")
        seen["command"] = command
        out_index = command.index("-o") + 1
        Path(command[out_index]).write_text(
            json.dumps(
                {
                    "contract": CODEX_JUDGE_CONTRACT,
                    "items": [
                        {
                            "question_id": "q1",
                            "verdict": "correct",
                            "confidence": 1.0,
                            "reason": "matches",
                        }
                    ],
                    "summary": {
                        "correct": 1,
                        "partial": 0,
                        "incorrect": 0,
                        "unjudgeable": 0,
                        "total": 1,
                    },
                }
            ),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, stdout="{}", stderr="")

    monkeypatch.setattr("src.codex_memory_judge.subprocess.run", fake_run)

    result = run_codex_assisted_judge(
        hypothesis_path=hyp,
        reference_path=ref,
        codex_bin=str(fake_codex),
        max_questions=1,
        model="gpt-5.5",
        reasoning_effort="xhigh",
        run=True,
    )

    assert result["ok"] is True
    assert "--model" in seen["command"]
    assert "gpt-5.5" in seen["command"]
    assert "-c" in seen["command"]
    assert 'model_reasoning_effort="xhigh"' in seen["command"]
    assert result["judge_profile"] == {
        "model": "gpt-5.5",
        "reasoning_effort": "xhigh",
        "profile_label": "codex_gpt5_5_xhigh_internal_judge",
    }


def test_codex_assisted_judge_returns_missed_case_diagnostics(tmp_path, monkeypatch):
    fake_codex = tmp_path / "codex"
    fake_codex.write_text("#!/bin/sh\nprintf '%s\\n' '--output-schema --ephemeral'\n", encoding="utf-8")
    fake_codex.chmod(0o755)
    hyp = tmp_path / "hyp.jsonl"
    ref = tmp_path / "ref.json"
    hyp.write_text(
        "\n".join(
            [
                '{"question_id":"q1","hypothesis":"Use the blue adapter."}',
                '{"question_id":"q2","hypothesis":"Use the red adapter."}',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    ref.write_text(
        json.dumps(
            [
                {
                    "question_id": "q1",
                    "question": "Which adapter?",
                    "answer": "Use the blue adapter.",
                    "question_type": "single-session-user",
                },
                {
                    "question_id": "q2",
                    "question": "Which cable?",
                    "answer": "Use the yellow cable.",
                    "question_type": "knowledge-update",
                },
            ]
        ),
        encoding="utf-8",
    )

    def fake_run(command, **kwargs):
        if command[:3] == [str(fake_codex), "exec", "--help"]:
            return subprocess.CompletedProcess(command, 0, stdout="--output-schema --ephemeral", stderr="")
        out_index = command.index("-o") + 1
        Path(command[out_index]).write_text(
            json.dumps(
                {
                    "contract": CODEX_JUDGE_CONTRACT,
                    "items": [
                        {"question_id": "q1", "verdict": "correct", "confidence": 1.0, "reason": "matches"},
                        {"question_id": "q2", "verdict": "incorrect", "confidence": 0.9, "reason": "wrong cable"},
                    ],
                    "summary": {
                        "correct": 1,
                        "partial": 0,
                        "incorrect": 1,
                        "unjudgeable": 0,
                        "total": 2,
                    },
                }
            ),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, stdout="{}", stderr="")

    monkeypatch.setattr("src.codex_memory_judge.subprocess.run", fake_run)

    result = run_codex_assisted_judge(
        hypothesis_path=hyp,
        reference_path=ref,
        codex_bin=str(fake_codex),
        max_questions=2,
        run=True,
    )

    assert result["codex_judge_score"]["answer_acceptance"] == 0.5
    assert result["codex_judge_score"]["answer_acceptance_100"] == 50.0
    assert result["codex_judge_score"]["official_like_binary_accuracy"] == 0.5
    assert result["codex_judge_score"]["official_like_binary_accuracy_100"] == 50.0
    assert result["judge_diagnostics"]["verdict_counts"] == {"correct": 1, "incorrect": 1}
    assert result["judge_diagnostics"]["question_type_verdict_counts"]["knowledge-update"] == {"incorrect": 1}
    assert result["judge_diagnostics"]["complete_item_coverage"] is True
    assert result["judge_diagnostics"]["item_count"] == 2
    assert result["judge_diagnostics"]["unique_resolved_question_id_count"] == 2
    assert result["judge_diagnostics"]["missing_judge_question_id_count"] == 0
    assert result["judge_diagnostics"]["missed_cases"][0]["question_id"] == "q2"
    assert result["judge_diagnostics"]["missed_cases"][0]["reference_answer"] == "Use the yellow cable."
    assert result["judge_diagnostics"]["missed_cases"][0]["failure_bucket"] == "latest_state_update"
    assert result["judge_diagnostics"]["missed_cases"][0]["failure_tags"] == ["latest_state"]
    assert result["judge_diagnostics"]["missed_cases"][0]["suggested_next_step"] == "add_latest_state_selection_operator"
    assert result["judge_diagnostics"]["failure_bucket_counts"] == {"latest_state_update": 1}
    assert result["judge_diagnostics"]["failure_tag_counts"] == {"latest_state": 1}
    assert result["judge_diagnostics"]["suggested_next_step_counts"] == {"add_latest_state_selection_operator": 1}
    layered = result["layered_score_report"]
    assert layered["contract"] == LAYERED_SCORE_REPORT_CONTRACT
    assert layered["score_type"] == "derived_diagnostic_not_official_score"
    assert layered["official_leaderboard_score"] is False
    assert layered["coverage"]["complete_item_coverage"] is True
    assert layered["layers"]["answer_synthesis_score"]["status"] == "measured"
    assert layered["layers"]["answer_synthesis_score"]["official_like_binary_accuracy_100"] == 50.0
    assert layered["layers"]["answer_synthesis_score"]["internal_half_credit_100"] == 50.0
    assert layered["layers"]["gap_score"]["status"] == "measured_from_missed_case_tags"
    assert layered["layers"]["self_improvement_loop_score"]["status"] == "diagnostic_loop_ready"
    assert layered["layers"]["projection_score"]["status"] == "not_measured"
    assert "projection_score" in layered["not_measured_layers"]
    assert "preflight_score" in layered["not_measured_layers"]
    assert layered["primary_bottlenecks"][0]["failure_bucket"] == "latest_state_update"
    assert layered["primary_bottlenecks"][0]["suggested_next_step"] == "add_latest_state_selection_operator"


def test_codex_assisted_judge_buckets_multi_session_object_aggregation(tmp_path, monkeypatch):
    fake_codex = tmp_path / "codex"
    fake_codex.write_text("#!/bin/sh\nprintf '%s\\n' '--output-schema --ephemeral'\n", encoding="utf-8")
    fake_codex.chmod(0o755)
    hyp = tmp_path / "hyp.jsonl"
    ref = tmp_path / "ref.json"
    hyp.write_text('{"question_id":"q1","hypothesis":"1"}\n', encoding="utf-8")
    ref.write_text(
        json.dumps(
            [
                {
                    "question_id": "q1",
                    "question": "How many tanks do I currently have, including the one I set up for my friend's kid?",
                    "answer": "3",
                    "question_type": "multi-session",
                }
            ]
        ),
        encoding="utf-8",
    )

    def fake_run(command, **kwargs):
        if command[:3] == [str(fake_codex), "exec", "--help"]:
            return subprocess.CompletedProcess(command, 0, stdout="--output-schema --ephemeral", stderr="")
        out_index = command.index("-o") + 1
        Path(command[out_index]).write_text(
            json.dumps(
                {
                    "contract": CODEX_JUDGE_CONTRACT,
                    "items": [
                        {
                            "question_id": "q1",
                            "verdict": "incorrect",
                            "confidence": 0.95,
                            "reason": "wrong number; missed object-bound aggregation across sessions",
                        }
                    ],
                    "summary": {
                        "correct": 0,
                        "partial": 0,
                        "incorrect": 1,
                        "unjudgeable": 0,
                        "total": 1,
                    },
                }
            ),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, stdout="{}", stderr="")

    monkeypatch.setattr("src.codex_memory_judge.subprocess.run", fake_run)

    result = run_codex_assisted_judge(
        hypothesis_path=hyp,
        reference_path=ref,
        codex_bin=str(fake_codex),
        max_questions=1,
        run=True,
    )

    missed = result["judge_diagnostics"]["missed_cases"][0]
    assert missed["failure_bucket"] == "multi_session_object_aggregation"
    assert missed["failure_tags"] == ["count", "latest_state", "missing_object_bound", "wrong_number"]
    assert missed["suggested_next_step"] == "add_object_bound_count_or_sum_operator"
    assert result["judge_diagnostics"]["failure_bucket_counts"] == {"multi_session_object_aggregation": 1}
    assert result["judge_diagnostics"]["failure_tag_counts"] == {
        "count": 1,
        "latest_state": 1,
        "missing_object_bound": 1,
        "wrong_number": 1,
    }


def test_codex_assisted_judge_diagnostics_resolve_unique_question_id_prefix(tmp_path, monkeypatch):
    fake_codex = tmp_path / "codex"
    fake_codex.write_text("#!/bin/sh\nprintf '%s\\n' '--output-schema --ephemeral'\n", encoding="utf-8")
    fake_codex.chmod(0o755)
    hyp = tmp_path / "hyp.jsonl"
    ref = tmp_path / "ref.json"
    hyp.write_text('{"question_id":"75832dbd","hypothesis":"related but incomplete"}\n', encoding="utf-8")
    ref.write_text(
        json.dumps(
            [
                {
                    "question_id": "75832dbd",
                    "question": "Which resources?",
                    "answer": "recent publications or conferences",
                    "question_type": "single-session-preference",
                }
            ]
        ),
        encoding="utf-8",
    )

    def fake_run(command, **kwargs):
        if command[:3] == [str(fake_codex), "exec", "--help"]:
            return subprocess.CompletedProcess(command, 0, stdout="--output-schema --ephemeral", stderr="")
        out_index = command.index("-o") + 1
        Path(command[out_index]).write_text(
            json.dumps(
                {
                    "contract": CODEX_JUDGE_CONTRACT,
                    "items": [
                        {
                            "question_id": "75832db",
                            "verdict": "partial",
                            "confidence": 0.7,
                            "reason": "truncated id but unique",
                        }
                    ],
                    "summary": {
                        "correct": 0,
                        "partial": 1,
                        "incorrect": 0,
                        "unjudgeable": 0,
                        "total": 1,
                    },
                }
            ),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, stdout="{}", stderr="")

    monkeypatch.setattr("src.codex_memory_judge.subprocess.run", fake_run)

    result = run_codex_assisted_judge(
        hypothesis_path=hyp,
        reference_path=ref,
        codex_bin=str(fake_codex),
        max_questions=1,
        run=True,
    )

    missed = result["judge_diagnostics"]["missed_cases"][0]
    assert result["judge_diagnostics"]["question_type_counts"] == {"single-session-preference": 1}
    assert result["judge_diagnostics"]["question_id_resolution_counts"] == {"unique_prefix": 1}
    assert result["judge_diagnostics"]["unresolved_question_id_count"] == 0
    assert result["judge_diagnostics"]["complete_item_coverage"] is True
    assert missed["question_id"] == "75832dbd"
    assert missed["reported_question_id"] == "75832db"
    assert missed["question_id_resolution"] == "unique_prefix"


def test_codex_assisted_judge_scores_from_items_when_model_summary_is_inconsistent(tmp_path, monkeypatch):
    fake_codex = tmp_path / "codex"
    fake_codex.write_text("#!/bin/sh\nprintf '%s\\n' '--output-schema --ephemeral'\n", encoding="utf-8")
    fake_codex.chmod(0o755)
    hyp = tmp_path / "hyp.jsonl"
    ref = tmp_path / "ref.json"
    hyp.write_text(
        "\n".join(
            [
                '{"question_id":"q1","hypothesis":"a"}',
                '{"question_id":"q2","hypothesis":"b"}',
                '{"question_id":"q3","hypothesis":"c"}',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    ref.write_text(
        json.dumps(
            [
                {"question_id": "q1", "question": "q1", "answer": "a"},
                {"question_id": "q2", "question": "q2", "answer": "x"},
                {"question_id": "q3", "question": "q3", "answer": "c plus"},
            ]
        ),
        encoding="utf-8",
    )

    def fake_run(command, **kwargs):
        if command[:3] == [str(fake_codex), "exec", "--help"]:
            return subprocess.CompletedProcess(command, 0, stdout="--output-schema --ephemeral", stderr="")
        out_index = command.index("-o") + 1
        Path(command[out_index]).write_text(
            json.dumps(
                {
                    "contract": CODEX_JUDGE_CONTRACT,
                    "items": [
                        {"question_id": "q1", "verdict": "correct", "confidence": 1.0, "reason": "matches"},
                        {"question_id": "q2", "verdict": "incorrect", "confidence": 1.0, "reason": "wrong"},
                        {"question_id": "q3", "verdict": "partial", "confidence": 0.8, "reason": "incomplete"},
                    ],
                    "summary": {
                        "correct": 0,
                        "partial": 1,
                        "incorrect": 2,
                        "unjudgeable": 0,
                        "total": 3,
                    },
                }
            ),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, stdout="{}", stderr="")

    monkeypatch.setattr("src.codex_memory_judge.subprocess.run", fake_run)

    result = run_codex_assisted_judge(
        hypothesis_path=hyp,
        reference_path=ref,
        codex_bin=str(fake_codex),
        max_questions=3,
        run=True,
    )

    assert result["codex_judge_score"]["score_source"] == "item_verdicts"
    assert result["codex_judge_score"]["answer_acceptance"] == 0.5
    assert result["codex_judge_score"]["official_like_binary_accuracy"] == 0.3333
    assert result["codex_judge_score"]["official_like_binary_accuracy_100"] == 33.3
    assert result["codex_judge_score"]["official_like_task_averaged_accuracy"] == 0.3333
    assert result["judge_diagnostics"]["official_like_task_averaged_accuracy"] == 0.3333
    assert result["codex_judge_score"]["correct"] == 1
    assert result["codex_judge_score"]["partial"] == 1
    assert result["codex_judge_score"]["incorrect"] == 1
    assert result["codex_judge_score"]["summary_consistent"] is False
    assert result["codex_judge_score"]["model_summary"]["incorrect"] == 2


def test_codex_assisted_judge_batches_full_runs_and_aggregates_item_verdicts(tmp_path, monkeypatch):
    fake_codex = tmp_path / "codex"
    fake_codex.write_text("#!/bin/sh\nprintf '%s\\n' '--output-schema --ephemeral'\n", encoding="utf-8")
    fake_codex.chmod(0o755)
    hyp = tmp_path / "hyp.jsonl"
    ref = tmp_path / "ref.json"
    hyp.write_text(
        "\n".join(
            [
                '{"question_id":"q1","hypothesis":"alpha"}',
                '{"question_id":"q2","hypothesis":"beta-ish"}',
                '{"question_id":"q3","hypothesis":"wrong"}',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    ref.write_text(
        json.dumps(
            [
                {"question_id": "q1", "question": "q1", "answer": "alpha"},
                {"question_id": "q2", "question": "q2", "answer": "beta"},
                {"question_id": "q3", "question": "q3", "answer": "gamma"},
            ]
        ),
        encoding="utf-8",
    )
    batch_question_ids = []

    def fake_run(command, **kwargs):
        if command[:3] == [str(fake_codex), "exec", "--help"]:
            return subprocess.CompletedProcess(command, 0, stdout="--output-schema --ephemeral", stderr="")
        schema_index = command.index("--output-schema") + 1
        schema = json.loads(Path(command[schema_index]).read_text(encoding="utf-8"))
        question_ids = schema["properties"]["items"]["items"]["properties"]["question_id"]["enum"]
        batch_question_ids.append(question_ids)
        verdicts = {
            "q1": {"question_id": "q1", "verdict": "correct", "confidence": 1.0, "reason": "matches"},
            "q2": {"question_id": "q2", "verdict": "partial", "confidence": 0.8, "reason": "close"},
            "q3": {"question_id": "q3", "verdict": "incorrect", "confidence": 0.9, "reason": "wrong"},
        }
        items = [verdicts[question_id] for question_id in question_ids]
        summary = {"correct": 0, "partial": 0, "incorrect": 0, "unjudgeable": 0, "total": len(items)}
        for row in items:
            summary[row["verdict"]] += 1
        out_index = command.index("-o") + 1
        Path(command[out_index]).write_text(
            json.dumps({"contract": CODEX_JUDGE_CONTRACT, "items": items, "summary": summary}),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, stdout="{}", stderr="")

    monkeypatch.setattr("src.codex_memory_judge.subprocess.run", fake_run)

    result = run_codex_assisted_judge(
        hypothesis_path=hyp,
        reference_path=ref,
        codex_bin=str(fake_codex),
        max_questions=3,
        run=True,
        batch_size=2,
    )

    assert result["ok"] is True
    assert result["batched_judge"] is True
    assert result["batch_size"] == 2
    assert result["batch_count"] == 2
    assert batch_question_ids == [["q1", "q2"], ["q3"]]
    assert result["codex_judge_score"]["answer_acceptance"] == 0.5
    assert result["codex_judge_score"]["official_like_binary_accuracy"] == 0.3333
    assert result["codex_judge_score"]["official_like_task_averaged_accuracy"] == 0.3333
    assert result["codex_judge_score"]["score_source"] == "item_verdicts"
    assert result["layered_score_report"]["layers"]["answer_synthesis_score"]["official_like_binary_accuracy_100"] == 33.3
    assert result["layered_score_report"]["layers"]["self_improvement_loop_score"]["status"] == "diagnostic_loop_ready"
    assert result["judge_diagnostics"]["item_count"] == 3
    assert result["judge_diagnostics"]["expected_item_count"] == 3
    assert result["judge_diagnostics"]["complete_item_coverage"] is True
    assert result["judge_diagnostics"]["question_id_resolution_counts"] == {"exact": 3}
    assert result["judge_output"]["summary"] == {
        "correct": 1,
        "partial": 1,
        "incorrect": 1,
        "unjudgeable": 0,
        "total": 3,
    }


def test_codex_assisted_judge_cli_outputs_summary_json_without_running_model(tmp_path):
    fake_codex = tmp_path / "codex"
    fake_codex.write_text("#!/bin/sh\nprintf '%s\\n' '--output-schema --ephemeral'\n", encoding="utf-8")
    fake_codex.chmod(0o755)
    hyp = tmp_path / "hyp.jsonl"
    ref = tmp_path / "ref.json"
    hyp.write_text('{"question_id":"q1","hypothesis":"a"}\n', encoding="utf-8")
    ref.write_text('[{"question_id":"q1","question":"q","answer":"a"}]\n', encoding="utf-8")
    script = ROOT / "tools" / "codex_memory_judge.py"

    summary_run = subprocess.run(
        [
            sys.executable,
            str(script),
            "--hypothesis",
            str(hyp),
            "--reference",
            str(ref),
            "--codex-bin",
            str(fake_codex),
            "--sample-tier",
            "smoke",
            "--summary-json",
        ],
        cwd=str(ROOT),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    summary = json.loads(summary_run.stdout)

    assert summary["contract"] == CODEX_JUDGE_CONTRACT
    assert summary["run_status"] == "preflight_only"
    assert summary["ready_to_run"] is True
    assert summary["sample_plan"]["tier"] == "smoke"
    assert summary["sample_plan"]["selected_questions"] == 1
    assert summary["reference_alignment"]["ok"] is True
    assert summary["layered_score_report"]["contract"] == LAYERED_SCORE_REPORT_CONTRACT
    assert summary["layered_score_report"]["layers"]["answer_synthesis_score"]["status"] == "not_measured"
    assert "retrieval_score" in summary["layered_score_report"]["not_measured_layers"]
    assert summary["uses_openai_platform_api_key"] is False
    assert summary["official_leaderboard_score"] is False


def test_codex_assisted_judge_writes_full_result_and_missed_cases(tmp_path):
    output_json = tmp_path / "judge.json"
    missed_jsonl = tmp_path / "missed.jsonl"
    result = {
        "ok": True,
        "judge_diagnostics": {
            "missed_cases": [
                {"question_id": "q1", "verdict": "incorrect"},
                {"question_id": "q2", "verdict": "partial"},
            ]
        },
    }

    writes = write_codex_judge_outputs(
        result,
        output_json=output_json,
        missed_cases_jsonl=missed_jsonl,
    )

    assert writes["output_json"]["ok"] is True
    assert writes["missed_cases_jsonl"]["rows"] == 2
    assert json.loads(output_json.read_text(encoding="utf-8"))["ok"] is True
    rows = [json.loads(line) for line in missed_jsonl.read_text(encoding="utf-8").splitlines()]
    assert [row["question_id"] for row in rows] == ["q1", "q2"]


def test_official_memory_benchmark_cli_outputs_json_and_text(tmp_path):
    path = ROOT / "tests" / "fixtures" / "locomo_tiny.json"
    script = ROOT / "tools" / "official_memory_benchmark.py"

    json_run = subprocess.run(
        [
            sys.executable,
            str(script),
            "--dataset",
            "locomo",
            "--data",
            str(path),
            "--retrieval-mode",
            "bm25",
            "--context-window",
            "2",
            "--context-decay",
            "0.25",
            "--session-candidates",
            "2",
            "--json",
        ],
        cwd=str(ROOT),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    payload = json.loads(json_run.stdout)
    assert payload["case_count"] == 1
    assert payload["retrieval_mode"] == "bm25"
    assert payload["context_window"] == 2
    assert payload["context_decay"] == 0.25
    assert payload["session_candidates"] == 2
    assert payload["metrics"]["1"]["evidence_recall"] == 1.0
    assert payload["full_qa_status"]["implemented"] is False

    summary_run = subprocess.run(
        [
            sys.executable,
            str(script),
            "--dataset",
            "locomo",
            "--data",
            str(path),
            "--retrieval-mode",
            "bm25",
            "--summary-json",
        ],
        cwd=str(ROOT),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    summary = json.loads(summary_run.stdout)
    assert summary["case_count"] == 1
    assert summary["metrics"]["1"]["evidence_recall"] == 1.0
    assert "miss_classification_at_max_k" in summary
    assert "per_case" not in summary
    assert "exact_source_misses" not in summary

    text_run = subprocess.run(
        [
            sys.executable,
            str(script),
            "--dataset",
            "locomo",
            "--data",
            str(path),
            "--show-misses",
            "0",
        ],
        cwd=str(ROOT),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    assert "Official Benchmark Diagnostic" in text_run.stdout
    assert "retrieval mode: rrf" in text_run.stdout
    assert "near_source_recall" in text_run.stdout
    assert "leaderboard score: false" in text_run.stdout
    assert "not a LoCoMo / LongMemEval leaderboard score" in text_run.stdout

    qa_out = tmp_path / "locomo_cli_qa_trial.json"
    subprocess.run(
        [
            sys.executable,
            str(script),
            "--dataset",
            "locomo",
            "--data",
            str(path),
            "--retrieval-mode",
            "bm25",
            "--qa-trial",
            "--qa-output",
            str(qa_out),
            "--summary-json",
        ],
        cwd=str(ROOT),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    assert qa_out.exists()
    qa_summary = json.loads(subprocess.run(
        [
            sys.executable,
            str(script),
            "--dataset",
            "locomo",
            "--data",
            str(path),
            "--retrieval-mode",
            "bm25",
            "--qa-trial",
            "--qa-output",
            str(qa_out),
            "--summary-json",
        ],
        cwd=str(ROOT),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    ).stdout)
    assert qa_summary["mode"] == "official_qa_trial"
    assert qa_summary["official_leaderboard_score"] is False
    assert qa_summary["official_evaluator_status"]["answer_generation_implemented"] is True

    eval_summary = json.loads(subprocess.run(
        [
            sys.executable,
            str(script),
            "--dataset",
            "longmemeval",
            "--official-eval-preflight",
            "--official-repo",
            str(tmp_path / "missing-official-repo"),
            "--hypothesis",
            str(tmp_path / "missing-hyp.jsonl"),
            "--reference",
            str(tmp_path / "missing-ref.json"),
            "--summary-json",
        ],
        cwd=str(ROOT),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    ).stdout)
    assert eval_summary["mode"] == "official_evaluator_preflight"
    assert eval_summary["ready_to_run"] is False
    assert "official_repo" in eval_summary["blocked_reasons"]
    assert eval_summary["official_leaderboard_score"] is False


def test_free_memory_benchmark_suite_runs_two_no_key_diagnostics():
    locomo = ROOT / "tests" / "fixtures" / "locomo_tiny.json"
    longmemeval = ROOT / "tests" / "fixtures" / "longmemeval_tiny.json"

    result = run_free_memory_benchmark_suite(
        locomo_data_path=locomo,
        longmemeval_data_path=longmemeval,
        retrieval_mode="bm25",
        top_k=1,
    )
    rendered = render_free_benchmark_markdown(result)

    assert result["contract"] == FREE_BENCHMARK_CONTRACT
    assert result["mode"] == "free_retrieval_benchmark_suite"
    assert result["benchmark_count"] == 2
    assert result["boundary"]["no_api_key_required"] is True
    assert result["boundary"]["no_model_call"] is True
    assert result["boundary"]["no_memory_write"] is True
    assert result["boundary"]["official_leaderboard_score"] is False
    assert result["boundary"]["score_type"] == "evidence_retrieval_diagnostic"
    assert {item["label"] for item in result["results"]} == {"LoCoMo locomo10", "LongMemEval oracle"}
    assert all(item["metrics"]["exact_source_recall"] == 1.0 for item in result["results"])
    assert all(item["metrics"]["exact_source_recall_100"] == 100.0 for item in result["results"])
    locomo_metrics = next(item["metrics"] for item in result["results"] if item["dataset"] == "locomo")
    assert "answer_supported_recall" in locomo_metrics
    assert "answer_support_level_counts" in locomo_metrics
    assert "no_api_key_required: true" in rendered
    assert "100.0/100" in rendered
    assert "official_leaderboard_score: false" in rendered
    assert "not a LoCoMo or LongMemEval official leaderboard score" in rendered


def test_free_memory_benchmark_cli_outputs_no_key_summary_json():
    locomo = ROOT / "tests" / "fixtures" / "locomo_tiny.json"
    longmemeval = ROOT / "tests" / "fixtures" / "longmemeval_tiny.json"
    script = ROOT / "tools" / "free_memory_benchmark.py"

    summary_run = subprocess.run(
        [
            sys.executable,
            str(script),
            "--locomo-data",
            str(locomo),
            "--longmemeval-data",
            str(longmemeval),
            "--retrieval-mode",
            "bm25",
            "--top-k",
            "1",
            "--summary-json",
        ],
        cwd=str(ROOT),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    summary = json.loads(summary_run.stdout)

    assert summary["contract"] == FREE_BENCHMARK_CONTRACT
    assert summary["boundary"]["no_api_key_required"] is True
    assert summary["boundary"]["official_leaderboard_score"] is False
    assert len(summary["results"]) == 2
    assert all(item["metrics"]["exact_source_recall_100"] == 100.0 for item in summary["results"])

    text_run = subprocess.run(
        [
            sys.executable,
            str(script),
            "--locomo-data",
            str(locomo),
            "--longmemeval-data",
            str(longmemeval),
            "--retrieval-mode",
            "bm25",
            "--top-k",
            "1",
        ],
        cwd=str(ROOT),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )

    assert "Memcore Cloud Free Benchmark" in text_run.stdout
    assert "no_api_key_required: true" in text_run.stdout
    assert "official_leaderboard_score: false" in text_run.stdout


def test_near_source_hit_is_counted_separately_from_exact_source():
    result = run_retrieval_diagnostic(
        [
            {
                "dataset": "unit",
                "question_id": "near-source",
                "question": "What happened near the GPS issue?",
                "answer": "GPS issue",
                "expected_source_refs": ["s1:t2"],
                "expected_session_ids": [],
                "source_units": [
                    {
                        "source_id": "s1:t1",
                        "session_id": "s1",
                        "evidence_ref": "s1:t1",
                        "text": "user: A nearby GPS issue discussion.",
                        "searchable_text": "user: A nearby GPS issue discussion.",
                    },
                    {
                        "source_id": "s1:t2",
                        "session_id": "s1",
                        "evidence_ref": "s1:t2",
                        "text": "assistant: unrelated wording",
                        "searchable_text": "assistant: unrelated wording",
                    },
                ],
            }
        ],
        top_k_values=[1],
        retrieval_mode="bm25",
        context_window=1,
    )

    assert result["metrics"]["1"]["exact_source_recall"] == 0.0
    assert result["metrics"]["1"]["near_source_recall"] == 1.0
    assert result["metrics"]["1"]["bundled_source_recall"] == 1.0
    assert result["metrics"]["1"]["gold_anchor_recall"] == 0.0


def test_hierarchical_bm25_filters_to_session_candidates_before_turn_ranking():
    result = run_retrieval_diagnostic(
        [
            {
                "dataset": "unit",
                "question_id": "hierarchical",
                "question": "Which session mentions oak release planning?",
                "answer": "session two",
                "expected_source_refs": ["s2:t2"],
                "expected_session_ids": ["s2"],
                "source_units": [
                    {
                        "source_id": "s1:t1",
                        "session_id": "s1",
                        "evidence_ref": "s1:t1",
                        "text": "user: unrelated note",
                        "searchable_text": "user: unrelated note",
                    },
                    {
                        "source_id": "s2:t1",
                        "session_id": "s2",
                        "evidence_ref": "s2:t1",
                        "text": "user: oak release planning background",
                        "searchable_text": "user: oak release planning background",
                    },
                    {
                        "source_id": "s2:t2",
                        "session_id": "s2",
                        "evidence_ref": "s2:t2",
                        "text": "assistant: oak release planning exact answer",
                        "searchable_text": "assistant: oak release planning exact answer",
                    },
                ],
            }
        ],
        top_k_values=[1],
        retrieval_mode="hierarchical_bm25",
        session_candidates=1,
    )

    assert result["retrieval_mode"] == "hierarchical_bm25"
    assert result["session_candidates"] == 1
    top = result["per_case"][0]["top_results"][0]
    assert top["session_id"] == "s2"
    assert top["retrieval_mode"] == "hierarchical_bm25"
    assert top["session_rank"] == 1


def test_context_bm25_expands_adjacent_raw_turn_into_exact_hit():
    result = run_retrieval_diagnostic(
        [
            {
                "dataset": "unit",
                "question_id": "context",
                "question": "What was decided after amber migration planning?",
                "answer": "Use the staged rollout.",
                "expected_source_refs": ["s1:t2"],
                "expected_session_ids": [],
                "source_units": [
                    {
                        "source_id": "s1:t1",
                        "session_id": "s1",
                        "evidence_ref": "s1:t1",
                        "text": "user: amber migration planning",
                        "searchable_text": "user: amber migration planning",
                    },
                    {
                        "source_id": "s1:t2",
                        "session_id": "s1",
                        "evidence_ref": "s1:t2",
                        "text": "assistant: Use the staged rollout.",
                        "searchable_text": "assistant: Use the staged rollout.",
                    },
                    {
                        "source_id": "s2:t1",
                        "session_id": "s2",
                        "evidence_ref": "s2:t1",
                        "text": "user: unrelated amber archive",
                        "searchable_text": "user: unrelated amber archive",
                    },
                ],
            }
        ],
        top_k_values=[2],
        retrieval_mode="context_bm25",
        context_window=1,
    )

    assert result["retrieval_mode"] == "context_bm25"
    assert result["context_decay"] == 0.5
    assert result["metrics"]["2"]["exact_source_recall"] == 1.0
    top_results = result["per_case"][0]["top_results"]
    expanded = next(item for item in top_results if item["source_id"] == "s1:t2")
    assert expanded["context_expanded_from"] == "s1:t1"
    assert expanded["context_distance"] == 1
    assert expanded["context_decay"] == 0.5


def test_routed_context_bm25_marks_small_and_large_raw_routes():
    small = run_retrieval_diagnostic(
        [
            {
                "dataset": "unit",
                "question_id": "small-route",
                "question": "What follows pine planning?",
                "answer": "Small route answer.",
                "expected_source_refs": ["s1:t2"],
                "expected_session_ids": [],
                "source_units": [
                    {
                        "source_id": "s1:t1",
                        "session_id": "s1",
                        "evidence_ref": "s1:t1",
                        "text": "user: pine planning",
                        "searchable_text": "user: pine planning",
                    },
                    {
                        "source_id": "s1:t2",
                        "session_id": "s1",
                        "evidence_ref": "s1:t2",
                        "text": "assistant: Small route answer.",
                        "searchable_text": "assistant: Small route answer.",
                    },
                ],
            }
        ],
        top_k_values=[2],
        retrieval_mode="routed_context_bm25",
        context_route_unit_threshold=3,
        context_decay=0.25,
        context_route_aggressive_decay=0.9,
    )
    small_top = small["per_case"][0]["top_results"][0]
    assert small["retrieval_mode"] == "routed_context_bm25"
    assert small["context_route_counts"] == {"small_raw_context": 1}
    assert small_top["context_route"] == "small_raw_context"
    assert small_top["context_routed_decay"] == 0.25

    large = run_retrieval_diagnostic(
        [
            {
                "dataset": "unit",
                "question_id": "large-route",
                "question": "What follows pine planning?",
                "answer": "Large route answer.",
                "expected_source_refs": ["s1:t2"],
                "expected_session_ids": [],
                "source_units": [
                    {
                        "source_id": "s1:t1",
                        "session_id": "s1",
                        "evidence_ref": "s1:t1",
                        "text": "user: pine planning",
                        "searchable_text": "user: pine planning",
                    },
                    {
                        "source_id": "s1:t2",
                        "session_id": "s1",
                        "evidence_ref": "s1:t2",
                        "text": "assistant: Large route answer.",
                        "searchable_text": "assistant: Large route answer.",
                    },
                    {
                        "source_id": "s1:t3",
                        "session_id": "s1",
                        "evidence_ref": "s1:t3",
                        "text": "user: unrelated",
                        "searchable_text": "user: unrelated",
                    },
                ],
            }
        ],
        top_k_values=[2],
        retrieval_mode="routed_context_bm25",
        context_route_unit_threshold=3,
        context_decay=0.25,
        context_route_aggressive_decay=0.9,
    )
    large_top = large["per_case"][0]["top_results"][0]
    assert large["context_route_counts"] == {"large_raw_context": 1}
    assert large_top["context_route"] == "large_raw_context"
    assert large_top["context_route_unit_count"] == 3
    assert large_top["context_route_unit_threshold"] == 3
    assert large_top["context_routed_decay"] == 0.9


def test_diverse_context_bm25_keeps_session_anchors_before_neighbor_fill():
    result = run_retrieval_diagnostic(
        [
            {
                "dataset": "unit",
                "question_id": "diverse",
                "question": "alpha release planning",
                "answer": "session two",
                "expected_source_refs": ["s2:t1"],
                "expected_session_ids": ["s2"],
                "source_units": [
                    {
                        "source_id": "s1:t1",
                        "session_id": "s1",
                        "evidence_ref": "s1:t1",
                        "text": "user: alpha release planning planning planning",
                        "searchable_text": "user: alpha release planning planning planning",
                    },
                    {
                        "source_id": "s1:t2",
                        "session_id": "s1",
                        "evidence_ref": "s1:t2",
                        "text": "assistant: adjacent alpha release note",
                        "searchable_text": "assistant: adjacent alpha release note",
                    },
                    {
                        "source_id": "s1:t3",
                        "session_id": "s1",
                        "evidence_ref": "s1:t3",
                        "text": "user: another adjacent alpha release note",
                        "searchable_text": "user: another adjacent alpha release note",
                    },
                    {
                        "source_id": "s2:t1",
                        "session_id": "s2",
                        "evidence_ref": "s2:t1",
                        "text": "assistant: alpha release planning answer",
                        "searchable_text": "assistant: alpha release planning answer",
                    },
                ],
            }
        ],
        top_k_values=[3],
        retrieval_mode="diverse_context_bm25",
        context_window=1,
        context_decay=0.84,
    )

    top_results = result["per_case"][0]["top_results"]
    assert result["retrieval_mode"] == "diverse_context_bm25"
    assert {item["session_id"] for item in top_results[:2]} == {"s1", "s2"}
    assert top_results[0]["context_diversity_phase"] == "session_anchor"
    assert top_results[1]["context_diversity_phase"] == "session_anchor"
    assert result["metrics"]["3"]["gold_anchor_recall"] == 1.0


def test_anchored_context_bm25_keeps_bm25_anchor_and_reports_bundle_hit():
    result = run_retrieval_diagnostic(
        [
            {
                "dataset": "unit",
                "question_id": "anchored",
                "question": "What happened near cedar planning?",
                "answer": "The bundle answer.",
                "expected_source_refs": ["s1:t2"],
                "expected_session_ids": [],
                "source_units": [
                    {
                        "source_id": "s1:t1",
                        "session_id": "s1",
                        "evidence_ref": "s1:t1",
                        "text": "user: cedar planning context",
                        "searchable_text": "user: cedar planning context",
                    },
                    {
                        "source_id": "s1:t2",
                        "session_id": "s1",
                        "evidence_ref": "s1:t2",
                        "text": "assistant: The bundle answer.",
                        "searchable_text": "assistant: The bundle answer.",
                    },
                ],
            }
        ],
        top_k_values=[1],
        retrieval_mode="anchored_context_bm25",
        context_window=1,
    )

    top = result["per_case"][0]["top_results"][0]
    assert result["retrieval_mode"] == "anchored_context_bm25"
    assert top["source_id"] == "s1:t1"
    assert top["context_bundle_available"] is True
    assert "s1:t2" in top["context_bundle_refs"]
    assert result["metrics"]["1"]["exact_source_recall"] == 0.0
    assert result["metrics"]["1"]["bundled_source_recall"] == 1.0


def test_session_internal_rerank_promotes_directional_neighbor_from_bundle():
    result = run_retrieval_diagnostic(
        [
            {
                "dataset": "unit",
                "question_id": "session-rerank-next",
                "question": "What happened after cedar planning?",
                "answer": "The later decision.",
                "expected_source_refs": ["s1:t2"],
                "expected_session_ids": [],
                "source_units": [
                    {
                        "source_id": "s1:t1",
                        "session_id": "s1",
                        "evidence_ref": "s1:t1",
                        "text": "user: cedar planning",
                        "searchable_text": "user: cedar planning",
                    },
                    {
                        "source_id": "s1:t2",
                        "session_id": "s1",
                        "evidence_ref": "s1:t2",
                        "text": "assistant: The later decision.",
                        "searchable_text": "assistant: The later decision.",
                    },
                    {
                        "source_id": "s2:t1",
                        "session_id": "s2",
                        "evidence_ref": "s2:t1",
                        "text": "user: unrelated cedar archive",
                        "searchable_text": "user: unrelated cedar archive",
                    },
                ],
            }
        ],
        top_k_values=[1],
        retrieval_mode="session_internal_rerank_bm25",
        context_window=1,
    )

    top = result["per_case"][0]["top_results"][0]
    assert result["retrieval_mode"] == "session_internal_rerank_bm25"
    assert result["metrics"]["1"]["exact_source_recall"] == 1.0
    assert top["source_id"] == "s1:t2"
    assert top["session_internal_contract"] == "session_internal_rerank_bm25.v2026.6.17"
    assert top["session_internal_expanded_from"] == "s1:t1"
    assert top["session_internal_distance"] == 1
    assert top["session_internal_direction_hint"] == "next"
    assert top["session_internal_direction_multiplier"] > 1.0


def test_session_internal_rerank_keeps_anchor_when_no_direction_hint():
    result = run_retrieval_diagnostic(
        [
            {
                "dataset": "unit",
                "question_id": "session-rerank-neutral",
                "question": "What mentioned cedar planning?",
                "answer": "The anchor.",
                "expected_source_refs": ["s1:t1"],
                "expected_session_ids": [],
                "source_units": [
                    {
                        "source_id": "s1:t1",
                        "session_id": "s1",
                        "evidence_ref": "s1:t1",
                        "text": "user: cedar planning",
                        "searchable_text": "user: cedar planning",
                    },
                    {
                        "source_id": "s1:t2",
                        "session_id": "s1",
                        "evidence_ref": "s1:t2",
                        "text": "assistant: a later unrelated decision.",
                        "searchable_text": "assistant: a later unrelated decision.",
                    },
                ],
            }
        ],
        top_k_values=[1],
        retrieval_mode="session_internal_rerank_bm25",
        context_window=1,
    )

    top = result["per_case"][0]["top_results"][0]
    assert result["metrics"]["1"]["exact_source_recall"] == 1.0
    assert top["source_id"] == "s1:t1"
    assert top["session_internal_distance"] == 0
    assert top["session_internal_direction_hint"] == ""


def test_typed_context_bm25_routes_locomo_question_types_transparently():
    result = run_retrieval_diagnostic(
        [
            {
                "dataset": "locomo",
                "question_id": "locomo-type-4",
                "question_type": "4",
                "question": "What happened after cedar planning?",
                "answer": "The adjacent answer.",
                "expected_source_refs": ["s1:t2"],
                "expected_session_ids": [],
                "source_units": [
                    {
                        "source_id": "s1:t1",
                        "session_id": "s1",
                        "evidence_ref": "s1:t1",
                        "text": "user: cedar planning",
                        "searchable_text": "user: cedar planning",
                    },
                    {
                        "source_id": "s1:t2",
                        "session_id": "s1",
                        "evidence_ref": "s1:t2",
                        "text": "assistant: The adjacent answer.",
                        "searchable_text": "assistant: The adjacent answer.",
                    },
                ],
            },
            {
                "dataset": "locomo",
                "question_id": "locomo-type-1",
                "question_type": "1",
                "question": "What happened near oak planning?",
                "answer": "The conservative answer.",
                "expected_source_refs": ["s2:t2"],
                "expected_session_ids": [],
                "source_units": [
                    {
                        "source_id": "s2:t1",
                        "session_id": "s2",
                        "evidence_ref": "s2:t1",
                        "text": "user: oak planning",
                        "searchable_text": "user: oak planning",
                    },
                    {
                        "source_id": "s2:t2",
                        "session_id": "s2",
                        "evidence_ref": "s2:t2",
                        "text": "assistant: The conservative answer.",
                        "searchable_text": "assistant: The conservative answer.",
                    },
                ],
            },
        ],
        top_k_values=[2],
        retrieval_mode="typed_context_bm25",
        context_window=1,
        context_decay=0.5,
    )

    assert result["retrieval_mode"] == "typed_context_bm25"
    assert result["metrics"]["2"]["exact_source_recall"] == 1.0
    routes = {
        item["question_id"]: item["top_results"][0]["context_route"]
        for item in result["per_case"]
    }
    assert routes["locomo-type-4"] == "locomo_inferential_context"
    assert routes["locomo-type-1"] == "locomo_conservative_context"
    first = result["per_case"][0]["top_results"][0]
    assert first["typed_context_contract"] == "typed_context_bm25.v2026.6.17"
    assert first["context_route_reason"] == "locomo_type_4_5_exact_source_gain"


def test_miss_classification_marks_bundle_only_and_session_internal_rerank():
    result = run_retrieval_diagnostic(
        [
            {
                "dataset": "locomo",
                "question_id": "bundle-only",
                "question_type": "4",
                "question": "What happened after cedar planning?",
                "answer": "The adjacent answer.",
                "expected_source_refs": ["s1:t2"],
                "expected_session_ids": [],
                "source_units": [
                    {
                        "source_id": "s1:t1",
                        "session_id": "s1",
                        "evidence_ref": "s1:t1",
                        "text": "user: cedar planning",
                        "searchable_text": "user: cedar planning",
                    },
                    {
                        "source_id": "s1:t2",
                        "session_id": "s1",
                        "evidence_ref": "s1:t2",
                        "text": "assistant: The adjacent answer.",
                        "searchable_text": "assistant: The adjacent answer.",
                    },
                ],
            }
        ],
        top_k_values=[1],
        retrieval_mode="anchored_context_bm25",
        context_window=1,
    )

    classification = result["per_case"][0]["miss_classification"]["1"]
    assert classification["primary"] == "bundle_only"
    assert "session_internal_rerank_needed" in classification["tags"]
    assert "temporal_signal" in classification["tags"]
    assert result["miss_classification_at_max_k"]["primary_counts"]["bundle_only"] == 1
    assert result["miss_classification_at_max_k"]["actionable_next_step_counts"]["session_internal_rerank"] == 1


def test_miss_classification_marks_wrong_session_entity_and_timeline_signals():
    result = run_retrieval_diagnostic(
        [
            {
                "dataset": "locomo",
                "question_id": "wrong-session",
                "question_type": "5",
                "question": "When did Alice discuss oak planning?",
                "answer": "In the second session.",
                "expected_source_refs": ["s2:t1"],
                "expected_session_ids": ["s2"],
                "source_units": [
                    {
                        "source_id": "s1:t1",
                        "session_id": "s1",
                        "evidence_ref": "s1:t1",
                        "text": "user: Alice discussed oak planning in the first session.",
                        "searchable_text": "user: Alice discussed oak planning in the first session.",
                    },
                    {
                        "source_id": "s2:t1",
                        "session_id": "s2",
                        "evidence_ref": "s2:t1",
                        "text": "assistant: second session answer",
                        "searchable_text": "assistant: second session answer",
                    },
                ],
            }
        ],
        top_k_values=[1],
        retrieval_mode="bm25",
    )

    classification = result["per_case"][0]["miss_classification"]["1"]
    assert classification["primary"] == "wrong_session"
    assert "entity_name_signal" in classification["tags"]
    assert "temporal_signal" in classification["tags"]
    assert "relation_or_inference_miss" in classification["tags"]
    actions = result["miss_classification_at_max_k"]["actionable_next_step_counts"]
    assert actions["anchor_routing"] == 1
    assert actions["entity_name_rerank"] == 1
    assert actions["timeline_rerank"] == 1
