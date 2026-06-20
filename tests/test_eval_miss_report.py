import json
from pathlib import Path

import src.eval_miss_report as eval_miss_report
from src.eval_miss_report import (
    build_eval_miss_report,
    build_evidence_pack_candidate_report,
    build_evidence_object_state_report,
    build_multi_evidence_aggregation_report,
    build_pack_gate_model_calibration_report,
    build_pack_gate_model_feature_report,
    build_pack_gate_model_probe_report,
    build_pack_gate_runtime_candidate_report,
    build_pack_aware_answer_support_report,
    build_pack_trigger_gate_report,
    render_eval_miss_report_markdown,
)


def test_eval_miss_report_infers_run_and_reports_candidate_recovery(tmp_path, monkeypatch):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "summary.json").write_text(
        json.dumps(
            {
                "benchmark_result": {
                    "results": [
                        {
                            "dataset": "locomo",
                            "split": "locomo10",
                            "case_count": 2,
                            "top_k": 3,
                        }
                    ]
                },
                "host_label": "r730xd",
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "run-ledger.json").write_text(
        json.dumps({"retrieval_mode": "fused_library_index_bm25", "run_id": "run-1"}),
        encoding="utf-8",
    )

    def fake_diagnostic(**kwargs):
        assert kwargs["dataset"] == "locomo"
        assert kwargs["retrieval_mode"] == "fused_library_index_bm25"
        assert kwargs["max_questions"] == 2
        assert kwargs["top_k_values"] == [3, 5]
        return {
            "split": "locomo10",
            "data_path": "/tmp/locomo10.json",
            "case_count": 2,
            "source_unit_count": 12,
            "metrics": {
                "3": {
                    "exact_source_recall": 0.5,
                    "bundled_source_recall": 0.5,
                    "session_recall": 0.5,
                    "gold_anchor_recall": 0.5,
                },
                "5": {
                    "exact_source_recall": 1.0,
                    "bundled_source_recall": 1.0,
                    "session_recall": 1.0,
                    "gold_anchor_recall": 1.0,
                },
            },
            "per_case": [
                {
                    "question_id": "q1",
                    "question_type": "1",
                    "question": "What color did Caroline choose?",
                    "answer": "blue",
                    "expected_source_refs": ["D1:1"],
                    "expected_session_ids": ["D1"],
                    "hits": {
                        "3": {"exact_source_hit": False, "gold_anchor_hit": False},
                        "5": {"exact_source_hit": True, "gold_anchor_hit": True},
                    },
                    "miss_classification": {
                        "3": {"primary": "wrong_session", "tags": ["anchor_routing_needed"]},
                        "5": {"primary": "exact_hit", "tags": []},
                    },
                    "top_results": [
                        {"evidence_ref": "D2:1", "session_id": "D2", "score": 1.0, "text": "wrong"}
                    ],
                },
                {
                    "question_id": "q2",
                    "question_type": "2",
                    "question": "Who helped?",
                    "answer": "Melanie",
                    "expected_source_refs": ["D1:2"],
                    "expected_session_ids": ["D1"],
                    "hits": {
                        "3": {"exact_source_hit": True, "gold_anchor_hit": True},
                        "5": {"exact_source_hit": True, "gold_anchor_hit": True},
                    },
                    "miss_classification": {
                        "3": {"primary": "exact_hit", "tags": []},
                        "5": {"primary": "exact_hit", "tags": []},
                    },
                    "top_results": [
                        {"evidence_ref": "D1:2", "session_id": "D1", "score": 2.0, "text": "right"}
                    ],
                },
            ],
        }

    monkeypatch.setattr(eval_miss_report, "run_official_memory_diagnostic", fake_diagnostic)
    monkeypatch.setattr(
        eval_miss_report,
        "load_cases",
        lambda **kwargs: [
                {
                    "question_id": "q1",
                    "question_type": "1",
                    "question": "What color did Caroline choose?",
                    "expected_source_refs": ["D1:1"],
                    "expected_session_ids": ["D1"],
                    "source_units": [
                        {"source_id": "s1", "session_id": "D1", "evidence_ref": "D1:1", "text": "Caroline chose the blue color."},
                    {"source_id": "s2", "session_id": "D2", "evidence_ref": "D2:1", "text": "Wrong session."},
                ],
                "library_index_units": [],
            }
        ],
    )

    report = build_eval_miss_report(
        run_dir=run_dir,
        compare_top_k_values=[3, 5],
    )

    assert report["contract"] == "eval_miss_report.v2026.6.19"
    assert report["dataset"] == "locomo"
    assert report["source_run"]["run_id"] == "run-1"
    assert report["boundary"]["no_model_call"] is True
    assert report["boundary"]["no_memory_write"] is True
    assert report["focus_miss_classification"]["primary_counts"]["wrong_session"] == 1
    assert report["candidate_pool_recovery"]["exact_source_misses_recovered_by_larger_k"] == {"top5": 1}
    entity_report = report["entity_subject_session"]
    assert entity_report["contract"] == "entity_subject_session_report.v2026.6.19"
    assert entity_report["boundary"]["ranking_unchanged"] is True
    assert entity_report["signal_counts"]["wrong_session_subject_route_suspect"] == 1
    assert entity_report["label_counts"]["top_missing_expected_object"] == 1
    assert entity_report["evidence_label_counts"]["top_evidence_missing_expected_object"] == 1
    example = entity_report["examples"]["top_missing_expected_object"][0]
    assert example["proper_phrases"] == ["caroline"]
    assert example["expected_subject_hits"] == ["caroline"]
    assert "color" in example["object_tokens"]
    assert "caroline" not in example["object_tokens"]
    assert example["expected_evidence_object_hits"] == ["color"]
    assert example["top_evidence_object_hits"] == []

    markdown = render_eval_miss_report_markdown(report)
    assert "Memcore Eval Miss Report" in markdown
    assert "official_leaderboard_score: false" in markdown
    assert "Entity / Subject Session Diagnostic" in markdown


def test_evidence_object_state_report_uses_fake_model_without_changing_ranking():
    cases = [
        {
            "question_id": "q1",
            "question_type": "temporal",
            "question": "When did Caroline go to the support group?",
            "answer": "yesterday",
            "expected_source_refs": ["D1:3"],
            "expected_session_ids": ["D1"],
            "source_units": [
                {
                    "source_id": "conv:D1:3",
                    "session_id": "D1",
                    "evidence_ref": "D1:3",
                    "role": "Caroline",
                    "timestamp": "2023-05-08",
                    "text": "Caroline: I went to a support group yesterday.",
                    "source_refs": {"source_system": "test", "msg_ids": ["D1:3"]},
                },
                {
                    "source_id": "conv:D2:4",
                    "session_id": "D2",
                    "evidence_ref": "D2:4",
                    "role": "Caroline",
                    "timestamp": "2023-05-09",
                    "text": "Caroline: The book club meets on Fridays.",
                    "source_refs": {"source_system": "test", "msg_ids": ["D2:4"]},
                },
            ],
        }
    ]
    per_case = [
        {
            "question_id": "q1",
            "question_type": "temporal",
            "question": "When did Caroline go to the support group?",
            "answer": "yesterday",
            "expected_source_refs": ["D1:3"],
            "expected_session_ids": ["D1"],
            "hits": {"3": {"exact_source_hit": False, "gold_anchor_hit": False}},
            "miss_classification": {"3": {"primary": "wrong_session", "tags": ["anchor_routing_needed"]}},
            "top_results": [
                {
                    "source_id": "conv:D2:4",
                    "session_id": "D2",
                    "evidence_ref": "D2:4",
                    "score": 2.0,
                    "text": "Caroline: The book club meets on Fridays.",
                }
            ],
        }
    ]

    def fake_client(messages, config):
        payload = json.loads(messages[1]["content"])
        assert payload["gold_evidence"][0]["evidence_ref"] == "D1:3"
        assert payload["top_evidence"][0]["evidence_ref"] == "D2:4"
        return {
            "content": json.dumps(
                {
                    "object_topic": "Caroline activity",
                    "state_fact": "Gold evidence is about the support group; top evidence is about book club.",
                    "action_relation": "different activity",
                    "time_hint": "historical",
                    "support_verdict": "different_fact",
                    "confidence": 0.82,
                    "gold_supporting_refs": ["D1:3"],
                    "top_supporting_refs": ["D2:4"],
                    "mismatch_reason": "top evidence discusses a different activity",
                    "unknown_reason": "",
                }
            )
        }

    report = build_evidence_object_state_report(
        cases,
        per_case,
        focus_top_k=3,
        max_model_cases=10,
        execute_model=True,
        model_config={"provider": "test", "model": "fake", "base_url": "", "api_key_env": ""},
        model_client=fake_client,
    )

    assert report["contract"] == "evidence_object_state_report.v2026.6.19"
    assert report["boundary"]["diagnostic_only"] is True
    assert report["boundary"]["ranking_unchanged"] is True
    assert report["boundary"]["no_memory_write"] is True
    assert report["model_call_count"] == 1
    assert report["verdict_counts"] == {"different_fact": 1}
    row = report["rows"][0]
    assert row["gold_refs"] == ["D1:3"]
    assert row["top_refs"] == ["D2:4"]
    assert row["diagnostic"]["support_verdict"] == "different_fact"
    assert row["diagnostic"]["gold_supporting_refs"] == ["D1:3"]
    assert row["diagnostic"]["top_supporting_refs"] == ["D2:4"]


def test_eval_miss_report_can_include_evidence_object_state_dry_run(tmp_path, monkeypatch):
    def fake_diagnostic(**kwargs):
        return {
            "split": "locomo10",
            "data_path": "/tmp/locomo10.json",
            "case_count": 1,
            "source_unit_count": 2,
            "metrics": {
                "3": {
                    "exact_source_recall": 0.0,
                    "bundled_source_recall": 0.0,
                    "session_recall": 0.0,
                    "gold_anchor_recall": 0.0,
                }
            },
            "per_case": [
                {
                    "question_id": "q1",
                    "question_type": "temporal",
                    "question": "When did Caroline go to the support group?",
                    "answer": "yesterday",
                    "expected_source_refs": ["D1:3"],
                    "expected_session_ids": ["D1"],
                    "hits": {"3": {"exact_source_hit": False, "gold_anchor_hit": False}},
                    "miss_classification": {"3": {"primary": "wrong_session", "tags": ["anchor_routing_needed"]}},
                    "top_results": [
                        {
                            "source_id": "conv:D2:4",
                            "session_id": "D2",
                            "evidence_ref": "D2:4",
                            "score": 2.0,
                            "text": "Caroline: The book club meets on Fridays.",
                        }
                    ],
                }
            ],
        }

    cases = [
        {
            "question_id": "q1",
            "question_type": "temporal",
            "question": "When did Caroline go to the support group?",
            "answer": "yesterday",
            "expected_source_refs": ["D1:3"],
            "expected_session_ids": ["D1"],
            "source_units": [
                {"source_id": "conv:D1:3", "session_id": "D1", "evidence_ref": "D1:3", "text": "Caroline went to a support group yesterday."},
                {"source_id": "conv:D2:4", "session_id": "D2", "evidence_ref": "D2:4", "text": "Caroline joined a book club."},
            ],
            "library_index_units": [],
        }
    ]
    monkeypatch.setattr(eval_miss_report, "run_official_memory_diagnostic", fake_diagnostic)
    monkeypatch.setattr(eval_miss_report, "load_cases", lambda **kwargs: cases)

    report = build_eval_miss_report(
        dataset="locomo",
        data_path=tmp_path / "unused.json",
        compare_top_k_values=[3],
        include_evidence_object_state=True,
        evidence_object_state_max_cases=1,
    )

    assert report["boundary"]["no_model_call"] is True
    assert "evidence_object_state" in report
    assert report["evidence_object_state"]["verdict_counts"] == {"dry_run": 1}
    markdown = render_eval_miss_report_markdown(report)
    assert "Evidence Object / State Diagnostic" in markdown
    assert "model_call_performed: false" in markdown


def test_multi_evidence_aggregation_report_finds_same_session_near_turns():
    cases = [
        {
            "question_id": "q1",
            "question_type": "list",
            "question": "What activities has Melanie done with her family?",
            "answer": "painting and camping",
            "expected_source_refs": ["D1:2", "D1:4"],
            "expected_session_ids": ["D1"],
            "source_units": [
                {"source_id": "conv:D1:1", "session_id": "D1", "evidence_ref": "D1:1", "text": "Melanie talked about family plans."},
                {"source_id": "conv:D1:2", "session_id": "D1", "evidence_ref": "D1:2", "text": "Melanie painted with her kids."},
                {"source_id": "conv:D1:3", "session_id": "D1", "evidence_ref": "D1:3", "text": "Melanie packed snacks."},
                {"source_id": "conv:D1:4", "session_id": "D1", "evidence_ref": "D1:4", "text": "Melanie camped with her family."},
            ],
        }
    ]
    per_case = [
        {
            "question_id": "q1",
            "question_type": "list",
            "question": "What activities has Melanie done with her family?",
            "answer": "painting and camping",
            "expected_source_refs": ["D1:2", "D1:4"],
            "expected_session_ids": ["D1"],
            "hits": {"3": {"exact_source_hit": False, "gold_anchor_hit": True}},
            "miss_classification": {"3": {"primary": "right_session_wrong_turn", "tags": ["session_internal_rerank_needed"]}},
            "top_results": [
                {
                    "source_id": "conv:D1:3",
                    "session_id": "D1",
                    "evidence_ref": "D1:3",
                    "context_window": 1,
                    "context_bundle_refs": [],
                    "score": 2.0,
                    "text": "Melanie packed snacks.",
                }
            ],
        }
    ]

    report = build_multi_evidence_aggregation_report(cases, per_case, focus_top_k=3)

    assert report["contract"] == "multi_evidence_aggregation_report.v2026.6.19"
    assert report["boundary"]["no_model_call"] is True
    assert report["boundary"]["no_memory_write"] is True
    assert report["label_counts"] == {"all_gold_in_neighbor_pack": 1}
    row = report["rows"][0]
    assert row["neighbor_overlap"] == ["D1:2", "D1:4"]
    assert row["turn_distance"]["near_turn_distance_le_2"] is True
    assert "list_or_set" in row["question_signals"]


def test_multi_evidence_aggregation_report_marks_missing_gold_for_count_question():
    cases = [
        {
            "question_id": "q2",
            "question_type": "count",
            "question": "How many times has Melanie gone to the beach in 2023?",
            "answer": "2",
            "expected_source_refs": ["D6:16", "D10:8"],
            "expected_session_ids": ["D6", "D10"],
            "source_units": [
                {"source_id": "conv:D6:16", "session_id": "D6", "evidence_ref": "D6:16", "text": "Beach visit one."},
                {"source_id": "conv:D10:8", "session_id": "D10", "evidence_ref": "D10:8", "text": "Beach visit two."},
                {"source_id": "conv:D4:1", "session_id": "D4", "evidence_ref": "D4:1", "text": "Camping talk."},
            ],
        }
    ]
    per_case = [
        {
            "question_id": "q2",
            "question_type": "count",
            "question": "How many times has Melanie gone to the beach in 2023?",
            "answer": "2",
            "expected_source_refs": ["D6:16", "D10:8"],
            "expected_session_ids": ["D6", "D10"],
            "hits": {"3": {"exact_source_hit": False, "gold_anchor_hit": False}},
            "miss_classification": {"3": {"primary": "bundle_only", "tags": ["session_internal_rerank_needed"]}},
            "top_results": [
                {"source_id": "conv:D4:1", "session_id": "D4", "evidence_ref": "D4:1", "context_window": 1, "text": "Camping talk."}
            ],
        }
    ]

    report = build_multi_evidence_aggregation_report(cases, per_case, focus_top_k=3)

    assert report["label_counts"] == {"aggregation_candidate_missing_gold": 1}
    row = report["rows"][0]
    assert row["neighbor_overlap"] == []
    assert "count" in row["question_signals"]
    assert report["signal_counts"]["multi_gold_ref"] == 1


def test_evidence_pack_candidate_report_recovers_neighbor_gold_refs():
    cases = [
        {
            "question_id": "q1",
            "question_type": "list",
            "question": "What activities has Melanie done with her family?",
            "answer": "painting and camping",
            "expected_source_refs": ["D1:2", "D1:4"],
            "expected_session_ids": ["D1"],
            "source_units": [
                {"source_id": "conv:D1:1", "session_id": "D1", "evidence_ref": "D1:1", "text": "Melanie talked about family plans."},
                {"source_id": "conv:D1:2", "session_id": "D1", "evidence_ref": "D1:2", "text": "Melanie painted with her kids."},
                {"source_id": "conv:D1:3", "session_id": "D1", "evidence_ref": "D1:3", "text": "Melanie packed snacks."},
                {"source_id": "conv:D1:4", "session_id": "D1", "evidence_ref": "D1:4", "text": "Melanie camped with her family."},
            ],
        }
    ]
    per_case = [
        {
            "question_id": "q1",
            "question_type": "list",
            "question": "What activities has Melanie done with her family?",
            "answer": "painting and camping",
            "expected_source_refs": ["D1:2", "D1:4"],
            "expected_session_ids": ["D1"],
            "hits": {"3": {"exact_source_hit": False, "gold_anchor_hit": True}},
            "miss_classification": {"3": {"primary": "right_session_wrong_turn", "tags": []}},
            "top_results": [
                {"source_id": "conv:D1:3", "session_id": "D1", "evidence_ref": "D1:3", "context_window": 1, "text": "Melanie packed snacks."}
            ],
        }
    ]

    report = build_evidence_pack_candidate_report(cases, per_case, focus_top_k=3, pack_window=1)

    assert report["contract"] == "evidence_pack_candidate_report.v2026.6.19"
    assert report["boundary"]["no_model_call"] is True
    assert report["label_counts"] == {"pack_full_gold": 1}
    assert report["metrics"]["top_any_gold_recall"] == 0.0
    assert report["metrics"]["pack_any_gold_recall"] == 1.0
    assert report["metrics"]["pack_full_gold_recall"] == 1.0
    row = report["rows"][0]
    assert row["pack_overlap"] == ["D1:2", "D1:4"]
    assert row["pack_refs"] == ["D1:2", "D1:3", "D1:4"]


def test_evidence_pack_candidate_report_marks_pack_missing_gold():
    cases = [
        {
            "question_id": "q2",
            "question_type": "fact",
            "question": "What did Caroline research?",
            "answer": "adoption agencies",
            "expected_source_refs": ["D2:8"],
            "expected_session_ids": ["D2"],
            "source_units": [
                {"source_id": "conv:D2:8", "session_id": "D2", "evidence_ref": "D2:8", "text": "Caroline researched adoption agencies."},
                {"source_id": "conv:D8:1", "session_id": "D8", "evidence_ref": "D8:1", "text": "Unrelated topic."},
            ],
        }
    ]
    per_case = [
        {
            "question_id": "q2",
            "question_type": "fact",
            "question": "What did Caroline research?",
            "answer": "adoption agencies",
            "expected_source_refs": ["D2:8"],
            "expected_session_ids": ["D2"],
            "hits": {"3": {"exact_source_hit": False, "gold_anchor_hit": False}},
            "miss_classification": {"3": {"primary": "wrong_session", "tags": ["anchor_routing_needed"]}},
            "top_results": [
                {"source_id": "conv:D8:1", "session_id": "D8", "evidence_ref": "D8:1", "context_window": 2, "text": "Unrelated topic."}
            ],
        }
    ]

    report = build_evidence_pack_candidate_report(cases, per_case, focus_top_k=3, pack_window=2)

    assert report["label_counts"] == {"pack_missing_gold": 1}
    row = report["rows"][0]
    assert row["pack_missing_refs"] == ["D2:8"]
    assert row["pack_overlap"] == []


def test_pack_aware_answer_support_report_marks_pack_improvement():
    cases = [
        {
            "question_id": "q1",
            "question_type": "list",
            "question": "What activities has Melanie done with her family?",
            "answer": "painting and camping",
            "expected_source_refs": ["D1:2", "D1:4"],
            "expected_session_ids": ["D1"],
            "source_units": [
                {"source_id": "conv:D1:1", "session_id": "D1", "evidence_ref": "D1:1", "text": "Melanie talked about family plans."},
                {"source_id": "conv:D1:2", "session_id": "D1", "evidence_ref": "D1:2", "text": "Melanie mentioned painting with her kids."},
                {"source_id": "conv:D1:3", "session_id": "D1", "evidence_ref": "D1:3", "text": "Melanie packed snacks."},
                {"source_id": "conv:D1:4", "session_id": "D1", "evidence_ref": "D1:4", "text": "Melanie also mentioned camping with her family."},
            ],
        }
    ]
    per_case = [
        {
            "question_id": "q1",
            "question_type": "list",
            "question": "What activities has Melanie done with her family?",
            "answer": "painting and camping",
            "expected_source_refs": ["D1:2", "D1:4"],
            "expected_session_ids": ["D1"],
            "hits": {"3": {"exact_source_hit": False, "gold_anchor_hit": True}},
            "miss_classification": {"3": {"primary": "right_session_wrong_turn", "tags": []}},
            "top_results": [
                {"source_id": "conv:D1:3", "session_id": "D1", "evidence_ref": "D1:3", "context_window": 1, "text": "Melanie packed snacks."}
            ],
        }
    ]

    report = build_pack_aware_answer_support_report(cases, per_case, focus_top_k=3, pack_window=1)

    assert report["contract"] == "pack_aware_answer_support_report.v2026.6.19"
    assert report["boundary"]["no_model_call"] is True
    assert report["boundary"]["no_memory_write"] is True
    assert report["boundary"]["ranking_unchanged"] is True
    assert report["support_delta_counts"] == {"pack_improved": 1}
    assert report["metrics"]["top_supported_rate"] == 0.0
    assert report["metrics"]["pack_supported_rate"] == 1.0
    assert report["metrics"]["pack_improved_rate"] == 1.0
    row = report["rows"][0]
    assert row["top_support_label"] == "none"
    assert row["pack_support_label"] == "answer_token_overlap_in_pack"
    assert row["incremental_refs"] == ["D1:2", "D1:4"]
    assert row["pack_size"] == 3


def test_pack_aware_answer_support_report_can_show_gold_without_answer_gain():
    cases = [
        {
            "question_id": "q2",
            "question_type": "fact",
            "question": "What did Caroline research?",
            "answer": "adoption agencies",
            "expected_source_refs": ["D2:8"],
            "expected_session_ids": ["D2"],
            "source_units": [
                {"source_id": "conv:D2:7", "session_id": "D2", "evidence_ref": "D2:7", "text": "Caroline opened several browser tabs."},
                {"source_id": "conv:D2:8", "session_id": "D2", "evidence_ref": "D2:8", "text": "Caroline said the research topic was private."},
                {"source_id": "conv:D2:9", "session_id": "D2", "evidence_ref": "D2:9", "text": "She closed the laptop afterward."},
            ],
        }
    ]
    per_case = [
        {
            "question_id": "q2",
            "question_type": "fact",
            "question": "What did Caroline research?",
            "answer": "adoption agencies",
            "expected_source_refs": ["D2:8"],
            "expected_session_ids": ["D2"],
            "hits": {"3": {"exact_source_hit": False, "gold_anchor_hit": True}},
            "miss_classification": {"3": {"primary": "right_session_wrong_turn", "tags": []}},
            "top_results": [
                {"source_id": "conv:D2:7", "session_id": "D2", "evidence_ref": "D2:7", "context_window": 1, "text": "Caroline opened several browser tabs."}
            ],
        }
    ]

    report = build_pack_aware_answer_support_report(cases, per_case, focus_top_k=3, pack_window=1)

    assert report["support_delta_counts"] == {"pack_no_gain": 1}
    assert report["metrics"]["pack_supported_count"] == 0
    row = report["rows"][0]
    assert row["pack_overlap"] == ["D2:8"]
    assert row["pack_support_label"] == "none"
    assert row["support_delta"] == "pack_no_gain"


def test_pack_trigger_gate_report_captures_observed_pack_improvement():
    cases = [
        {
            "question_id": "q1",
            "question_type": "list",
            "question": "What activities has Melanie done with her family?",
            "answer": "painting and camping",
            "expected_source_refs": ["D1:2", "D1:4"],
            "expected_session_ids": ["D1"],
            "source_units": [
                {"source_id": "conv:D1:1", "session_id": "D1", "evidence_ref": "D1:1", "text": "Melanie talked about family plans."},
                {"source_id": "conv:D1:2", "session_id": "D1", "evidence_ref": "D1:2", "text": "Melanie mentioned painting with her kids."},
                {"source_id": "conv:D1:3", "session_id": "D1", "evidence_ref": "D1:3", "text": "Melanie packed snacks."},
                {"source_id": "conv:D1:4", "session_id": "D1", "evidence_ref": "D1:4", "text": "Melanie also mentioned camping with her family."},
            ],
        }
    ]
    per_case = [
        {
            "question_id": "q1",
            "question_type": "list",
            "question": "What activities has Melanie done with her family?",
            "answer": "painting and camping",
            "expected_source_refs": ["D1:2", "D1:4"],
            "expected_session_ids": ["D1"],
            "hits": {"3": {"exact_source_hit": False, "gold_anchor_hit": True}},
            "miss_classification": {"3": {"primary": "right_session_wrong_turn", "tags": []}},
            "top_results": [
                {"source_id": "conv:D1:3", "session_id": "D1", "evidence_ref": "D1:3", "context_window": 1, "text": "Melanie packed snacks."}
            ],
        }
    ]

    report = build_pack_trigger_gate_report(cases, per_case, focus_top_k=3, pack_window=1)

    assert report["contract"] == "pack_trigger_gate_report.v2026.6.19"
    assert report["boundary"]["runtime_policy"] is False
    assert report["boundary"]["uses_expected_answer_for_diagnostic"] is True
    assert report["trigger_counts"] == {"trigger": 1}
    assert report["metrics"]["pack_improved_capture_rate"] == 1.0
    row = report["rows"][0]
    assert row["would_trigger"] is True
    assert row["trigger_reasons"] == ["pack_improved_target_primary"]
    assert row["expected_gain_bucket"] == "observed_pack_improved"


def test_pack_trigger_gate_report_skips_no_gain_high_cost():
    cases = [
        {
            "question_id": "q2",
            "question_type": "fact",
            "question": "What has Melanie painted?",
            "answer": "a sunrise",
            "expected_source_refs": ["D2:8"],
            "expected_session_ids": ["D2"],
            "source_units": [
                {"source_id": "conv:D2:1", "session_id": "D2", "evidence_ref": "D2:1", "text": "Melanie talked about art."},
                {"source_id": "conv:D2:2", "session_id": "D2", "evidence_ref": "D2:2", "text": "She prepared brushes."},
                {"source_id": "conv:D2:3", "session_id": "D2", "evidence_ref": "D2:3", "text": "She cleaned the studio."},
                {"source_id": "conv:D2:4", "session_id": "D2", "evidence_ref": "D2:4", "text": "She bought a frame."},
                {"source_id": "conv:D2:5", "session_id": "D2", "evidence_ref": "D2:5", "text": "She moved an easel."},
                {"source_id": "conv:D2:6", "session_id": "D2", "evidence_ref": "D2:6", "text": "She invited Caroline."},
                {"source_id": "conv:D2:7", "session_id": "D2", "evidence_ref": "D2:7", "text": "They discussed weekend plans."},
                {"source_id": "conv:D2:8", "session_id": "D2", "evidence_ref": "D2:8", "text": "The artwork subject was left unnamed."},
                {"source_id": "conv:D2:9", "session_id": "D2", "evidence_ref": "D2:9", "text": "They had tea afterward."},
                {"source_id": "conv:D2:10", "session_id": "D2", "evidence_ref": "D2:10", "text": "The room was quiet."},
                {"source_id": "conv:D2:11", "session_id": "D2", "evidence_ref": "D2:11", "text": "They went home."},
                {"source_id": "conv:D2:12", "session_id": "D2", "evidence_ref": "D2:12", "text": "No one named the artwork subject."},
                {"source_id": "conv:D2:13", "session_id": "D2", "evidence_ref": "D2:13", "text": "Caroline changed the subject."},
                {"source_id": "conv:D2:14", "session_id": "D2", "evidence_ref": "D2:14", "text": "The conversation ended."},
                {"source_id": "conv:D2:15", "session_id": "D2", "evidence_ref": "D2:15", "text": "Melanie packed her bag."},
            ],
        }
    ]
    per_case = [
        {
            "question_id": "q2",
            "question_type": "fact",
            "question": "What has Melanie painted?",
            "answer": "a sunrise",
            "expected_source_refs": ["D2:8"],
            "expected_session_ids": ["D2"],
            "hits": {"3": {"exact_source_hit": False, "gold_anchor_hit": True}},
            "miss_classification": {"3": {"primary": "bundle_only", "tags": []}},
            "top_results": [
                {"source_id": "conv:D2:8", "session_id": "D2", "evidence_ref": "D2:8", "context_window": 7, "text": "The artwork subject was left unnamed."}
            ],
        }
    ]

    report = build_pack_trigger_gate_report(cases, per_case, focus_top_k=3, pack_window=7)

    assert report["trigger_counts"] == {"skip": 1}
    assert report["metrics"]["no_gain_high_cost_skip_rate"] == 1.0
    row = report["rows"][0]
    assert row["would_trigger"] is False
    assert "pack_no_answer_gain" in row["would_skip_reason"]
    assert "high_cost_without_support" in row["would_skip_reason"]


def test_pack_gate_model_probe_report_dry_run_keeps_model_off():
    cases = [
        {
            "question_id": "q1",
            "question_type": "list",
            "question": "What activities has Melanie done with her family?",
            "answer": "painting and camping",
            "expected_source_refs": ["D1:2", "D1:4"],
            "expected_session_ids": ["D1"],
            "source_units": [
                {"source_id": "conv:D1:1", "session_id": "D1", "evidence_ref": "D1:1", "text": "Melanie talked about family plans."},
                {"source_id": "conv:D1:2", "session_id": "D1", "evidence_ref": "D1:2", "text": "Melanie mentioned painting with her kids."},
                {"source_id": "conv:D1:3", "session_id": "D1", "evidence_ref": "D1:3", "text": "Melanie packed snacks."},
                {"source_id": "conv:D1:4", "session_id": "D1", "evidence_ref": "D1:4", "text": "Melanie also mentioned camping with her family."},
            ],
        }
    ]
    per_case = [
        {
            "question_id": "q1",
            "question_type": "list",
            "question": "What activities has Melanie done with her family?",
            "answer": "painting and camping",
            "expected_source_refs": ["D1:2", "D1:4"],
            "expected_session_ids": ["D1"],
            "hits": {"3": {"exact_source_hit": False, "gold_anchor_hit": True}},
            "miss_classification": {"3": {"primary": "right_session_wrong_turn", "tags": []}},
            "top_results": [
                {"source_id": "conv:D1:3", "session_id": "D1", "evidence_ref": "D1:3", "context_window": 1, "text": "Melanie packed snacks."}
            ],
        }
    ]

    report = build_pack_gate_model_probe_report(cases, per_case, focus_top_k=3, pack_window=1, max_model_cases=1)

    assert report["contract"] == "pack_gate_model_probe_report.v2026.6.19"
    assert report["boundary"]["model_call_performed"] is False
    assert report["boundary"]["runtime_policy"] is False
    assert report["boundary"]["expected_answer_as_draft_only"] is True
    assert report["model_call_count"] == 0
    assert report["verdict_counts"] == {"dry_run": 1}
    row = report["rows"][0]
    assert row["top_model"]["verdict"] == "dry_run"
    assert row["pack_model"]["verdict"] == "dry_run"


def test_pack_gate_model_probe_report_fake_model_marks_pack_improved():
    cases = [
        {
            "question_id": "q1",
            "question_type": "list",
            "question": "What activities has Melanie done with her family?",
            "answer": "painting and camping",
            "expected_source_refs": ["D1:2", "D1:4"],
            "expected_session_ids": ["D1"],
            "source_units": [
                {"source_id": "conv:D1:1", "session_id": "D1", "evidence_ref": "D1:1", "text": "Melanie talked about family plans."},
                {"source_id": "conv:D1:2", "session_id": "D1", "evidence_ref": "D1:2", "text": "Melanie mentioned painting with her kids."},
                {"source_id": "conv:D1:3", "session_id": "D1", "evidence_ref": "D1:3", "text": "Melanie packed snacks."},
                {"source_id": "conv:D1:4", "session_id": "D1", "evidence_ref": "D1:4", "text": "Melanie also mentioned camping with her family."},
            ],
        }
    ]
    per_case = [
        {
            "question_id": "q1",
            "question_type": "list",
            "question": "What activities has Melanie done with her family?",
            "answer": "painting and camping",
            "expected_source_refs": ["D1:2", "D1:4"],
            "expected_session_ids": ["D1"],
            "hits": {"3": {"exact_source_hit": False, "gold_anchor_hit": True}},
            "miss_classification": {"3": {"primary": "right_session_wrong_turn", "tags": []}},
            "top_results": [
                {"source_id": "conv:D1:3", "session_id": "D1", "evidence_ref": "D1:3", "context_window": 1, "text": "Melanie packed snacks."}
            ],
        }
    ]

    def fake_client(messages, config):
        payload = json.loads(messages[1]["content"])
        refs = {item["evidence_ref"] for item in payload["evidence"]}
        if {"D1:2", "D1:4"} <= refs:
            return {
                "content": json.dumps(
                    {
                        "answer": "painting and camping",
                        "verdict": "answered",
                        "confidence": 0.9,
                        "supporting_refs": ["D1:2", "D1:4"],
                        "unknown_reason": "",
                    }
                )
            }
        return {
            "content": json.dumps(
                {
                    "answer": "UNKNOWN",
                    "verdict": "unknown",
                    "confidence": 0.0,
                    "supporting_refs": [],
                    "unknown_reason": "top evidence only mentions snacks",
                }
            )
        }

    report = build_pack_gate_model_probe_report(
        cases,
        per_case,
        focus_top_k=3,
        pack_window=1,
        max_model_cases=1,
        execute_model=True,
        model_config={"provider": "test", "model": "fake", "base_url": "", "api_key_env": ""},
        model_client=fake_client,
    )

    assert report["model_call_count"] == 2
    assert report["verdict_counts"] == {"pack_model_improved": 1}
    row = report["rows"][0]
    assert row["model_verdict"] == "pack_model_improved"
    assert row["top_model"]["verdict"] == "unknown"
    assert row["pack_model"]["verdict"] == "answered"
    assert row["pack_model"]["supporting_refs"] == ["D1:2", "D1:4"]


def test_pack_gate_model_calibration_report_dry_run_matrix():
    cases = [
        {
            "question_id": "q1",
            "question_type": "list",
            "question": "What activities has Melanie done with her family?",
            "answer": "painting and camping",
            "expected_source_refs": ["D1:2", "D1:4"],
            "expected_session_ids": ["D1"],
            "source_units": [
                {"source_id": "conv:D1:1", "session_id": "D1", "evidence_ref": "D1:1", "text": "Melanie talked about family plans."},
                {"source_id": "conv:D1:2", "session_id": "D1", "evidence_ref": "D1:2", "text": "Melanie mentioned painting with her kids."},
                {"source_id": "conv:D1:3", "session_id": "D1", "evidence_ref": "D1:3", "text": "Melanie packed snacks."},
                {"source_id": "conv:D1:4", "session_id": "D1", "evidence_ref": "D1:4", "text": "Melanie also mentioned camping with her family."},
            ],
        }
    ]
    per_case = [
        {
            "question_id": "q1",
            "question_type": "list",
            "question": "What activities has Melanie done with her family?",
            "answer": "painting and camping",
            "expected_source_refs": ["D1:2", "D1:4"],
            "expected_session_ids": ["D1"],
            "hits": {"3": {"exact_source_hit": False, "gold_anchor_hit": True}},
            "miss_classification": {"3": {"primary": "right_session_wrong_turn", "tags": []}},
            "top_results": [
                {"source_id": "conv:D1:3", "session_id": "D1", "evidence_ref": "D1:3", "context_window": 1, "text": "Melanie packed snacks."}
            ],
        }
    ]

    report = build_pack_gate_model_calibration_report(cases, per_case, focus_top_k=3, pack_window=1, max_model_cases=1)

    assert report["contract"] == "pack_gate_model_calibration_report.v2026.6.19"
    assert report["boundary"]["model_call_performed"] is False
    assert report["boundary"]["runtime_policy"] is False
    assert report["confusion_matrix"] == {"heuristic_trigger": {"dry_run": 1}}
    assert report["metrics"]["dry_run_total"] == 1


def test_pack_gate_model_calibration_report_fake_model_confusion_matrix():
    cases = [
        {
            "question_id": "q1",
            "question_type": "list",
            "question": "What activities has Melanie done with her family?",
            "answer": "painting and camping",
            "expected_source_refs": ["D1:2", "D1:4"],
            "expected_session_ids": ["D1"],
            "source_units": [
                {"source_id": "conv:D1:1", "session_id": "D1", "evidence_ref": "D1:1", "text": "Melanie talked about family plans."},
                {"source_id": "conv:D1:2", "session_id": "D1", "evidence_ref": "D1:2", "text": "Melanie mentioned painting with her kids."},
                {"source_id": "conv:D1:3", "session_id": "D1", "evidence_ref": "D1:3", "text": "Melanie packed snacks."},
                {"source_id": "conv:D1:4", "session_id": "D1", "evidence_ref": "D1:4", "text": "Melanie also mentioned camping with her family."},
            ],
        }
    ]
    per_case = [
        {
            "question_id": "q1",
            "question_type": "list",
            "question": "What activities has Melanie done with her family?",
            "answer": "painting and camping",
            "expected_source_refs": ["D1:2", "D1:4"],
            "expected_session_ids": ["D1"],
            "hits": {"3": {"exact_source_hit": False, "gold_anchor_hit": True}},
            "miss_classification": {"3": {"primary": "right_session_wrong_turn", "tags": []}},
            "top_results": [
                {"source_id": "conv:D1:3", "session_id": "D1", "evidence_ref": "D1:3", "context_window": 1, "text": "Melanie packed snacks."}
            ],
        }
    ]

    def fake_client(messages, config):
        payload = json.loads(messages[1]["content"])
        refs = {item["evidence_ref"] for item in payload["evidence"]}
        if {"D1:2", "D1:4"} <= refs:
            return {
                "content": json.dumps(
                    {
                        "answer": "painting and camping",
                        "verdict": "answered",
                        "confidence": 0.9,
                        "supporting_refs": ["D1:2", "D1:4"],
                        "unknown_reason": "",
                    }
                )
            }
        return {
            "content": json.dumps(
                {
                    "answer": "UNKNOWN",
                    "verdict": "unknown",
                    "confidence": 0.0,
                    "supporting_refs": [],
                    "unknown_reason": "top evidence only mentions snacks",
                }
            )
        }

    report = build_pack_gate_model_calibration_report(
        cases,
        per_case,
        focus_top_k=3,
        pack_window=1,
        max_model_cases=1,
        execute_model=True,
        model_config={"provider": "test", "model": "fake", "base_url": "", "api_key_env": ""},
        model_client=fake_client,
    )

    assert report["confusion_matrix"] == {"heuristic_trigger": {"model_pack_improved": 1}}
    assert report["metrics"]["trigger_precision_for_model_pack_improved"] == 1.0
    assert report["metrics"]["trigger_recall_for_model_pack_improved"] == 1.0
    assert report["metrics"]["avg_pack_supporting_ref_density"] == 0.6667
    assert report["probe_model_call_count"] == 2


def test_pack_gate_model_feature_report_dry_run_boundaries():
    cases = [
        {
            "question_id": "q1",
            "question_type": "list",
            "question": "What activities has Melanie done with her family?",
            "answer": "painting and camping",
            "expected_source_refs": ["D1:2", "D1:4"],
            "expected_session_ids": ["D1"],
            "source_units": [
                {"source_id": "conv:D1:1", "session_id": "D1", "evidence_ref": "D1:1", "text": "Melanie talked about family plans."},
                {"source_id": "conv:D1:2", "session_id": "D1", "evidence_ref": "D1:2", "text": "Melanie mentioned painting with her kids."},
                {"source_id": "conv:D1:3", "session_id": "D1", "evidence_ref": "D1:3", "text": "Melanie packed snacks."},
                {"source_id": "conv:D1:4", "session_id": "D1", "evidence_ref": "D1:4", "text": "Melanie also mentioned camping with her family."},
            ],
        }
    ]
    per_case = [
        {
            "question_id": "q1",
            "question_type": "list",
            "question": "What activities has Melanie done with her family?",
            "answer": "painting and camping",
            "expected_source_refs": ["D1:2", "D1:4"],
            "expected_session_ids": ["D1"],
            "hits": {"3": {"exact_source_hit": False, "gold_anchor_hit": True}},
            "miss_classification": {"3": {"primary": "right_session_wrong_turn", "tags": []}},
            "top_results": [
                {"source_id": "conv:D1:3", "session_id": "D1", "evidence_ref": "D1:3", "context_window": 1, "text": "Melanie packed snacks."}
            ],
        }
    ]

    report = build_pack_gate_model_feature_report(cases, per_case, focus_top_k=3, pack_window=1, max_model_cases=1)

    assert report["contract"] == "pack_gate_model_feature_report.v2026.6.19"
    assert report["boundary"]["model_call_performed"] is False
    assert report["boundary"]["runtime_policy"] is False
    assert report["boundary"]["daily_entry_integrated"] is False
    assert report["boundary"]["contains_gold_diagnostic_features"] is True
    assert report["rows"][0]["model_class"] == "dry_run"
    assert report["by_feature"]["answer_state_pair"][0]["bucket"] == "top_dry_run__pack_dry_run"


def test_pack_gate_model_feature_report_fake_model_buckets_pack_improved():
    cases = [
        {
            "question_id": "q1",
            "question_type": "list",
            "question": "What activities has Melanie done with her family?",
            "answer": "painting and camping",
            "expected_source_refs": ["D1:2", "D1:4"],
            "expected_session_ids": ["D1"],
            "source_units": [
                {"source_id": "conv:D1:1", "session_id": "D1", "evidence_ref": "D1:1", "text": "Melanie talked about family plans."},
                {"source_id": "conv:D1:2", "session_id": "D1", "evidence_ref": "D1:2", "text": "Melanie mentioned painting with her kids."},
                {"source_id": "conv:D1:3", "session_id": "D1", "evidence_ref": "D1:3", "text": "Melanie packed snacks."},
                {"source_id": "conv:D1:4", "session_id": "D1", "evidence_ref": "D1:4", "text": "Melanie also mentioned camping with her family."},
            ],
        }
    ]
    per_case = [
        {
            "question_id": "q1",
            "question_type": "list",
            "question": "What activities has Melanie done with her family?",
            "answer": "painting and camping",
            "expected_source_refs": ["D1:2", "D1:4"],
            "expected_session_ids": ["D1"],
            "hits": {"3": {"exact_source_hit": False, "gold_anchor_hit": True}},
            "miss_classification": {"3": {"primary": "right_session_wrong_turn", "tags": []}},
            "top_results": [
                {"source_id": "conv:D1:3", "session_id": "D1", "evidence_ref": "D1:3", "context_window": 1, "text": "Melanie packed snacks."}
            ],
        }
    ]

    def fake_client(messages, config):
        payload = json.loads(messages[1]["content"])
        refs = {item["evidence_ref"] for item in payload["evidence"]}
        if {"D1:2", "D1:4"} <= refs:
            return {
                "content": json.dumps(
                    {
                        "answer": "painting and camping",
                        "verdict": "answered",
                        "confidence": 0.9,
                        "supporting_refs": ["D1:2", "D1:4"],
                        "unknown_reason": "",
                    }
                )
            }
        return {
            "content": json.dumps(
                {
                    "answer": "UNKNOWN",
                    "verdict": "unknown",
                    "confidence": 0.0,
                    "supporting_refs": [],
                    "unknown_reason": "top evidence only mentions snacks",
                }
            )
        }

    report = build_pack_gate_model_feature_report(
        cases,
        per_case,
        focus_top_k=3,
        pack_window=1,
        max_model_cases=1,
        execute_model=True,
        model_config={"provider": "test", "model": "fake", "base_url": "", "api_key_env": ""},
        model_client=fake_client,
    )

    assert report["rows"][0]["model_class"] == "model_pack_improved"
    assert report["rows"][0]["features"]["answer_state_pair"] == "top_not_answered__pack_answered"
    assert report["rows"][0]["features"]["pack_supporting_ref_density_bucket"] == "density_high"
    assert {
        "bucket": "answer_state_pair:top_not_answered__pack_answered",
        "total": 1,
        "model_counts": {"model_pack_improved": 1},
        "model_pack_improved_rate": 1.0,
    } in report["candidate_positive_signals"]
    assert report["probe_model_call_count"] == 2


def test_pack_gate_runtime_candidate_report_dry_run_is_report_only():
    cases = [
        {
            "question_id": "q1",
            "question_type": "list",
            "question": "What activities has Melanie done with her family?",
            "answer": "painting and camping",
            "expected_source_refs": ["D1:2", "D1:4"],
            "expected_session_ids": ["D1"],
            "source_units": [
                {"source_id": "conv:D1:1", "session_id": "D1", "evidence_ref": "D1:1", "text": "Melanie talked about family plans."},
                {"source_id": "conv:D1:2", "session_id": "D1", "evidence_ref": "D1:2", "text": "Melanie mentioned painting with her kids."},
                {"source_id": "conv:D1:3", "session_id": "D1", "evidence_ref": "D1:3", "text": "Melanie packed snacks."},
                {"source_id": "conv:D1:4", "session_id": "D1", "evidence_ref": "D1:4", "text": "Melanie also mentioned camping with her family."},
            ],
        }
    ]
    per_case = [
        {
            "question_id": "q1",
            "question_type": "list",
            "question": "What activities has Melanie done with her family?",
            "answer": "painting and camping",
            "expected_source_refs": ["D1:2", "D1:4"],
            "expected_session_ids": ["D1"],
            "hits": {"3": {"exact_source_hit": False, "gold_anchor_hit": True}},
            "miss_classification": {"3": {"primary": "right_session_wrong_turn", "tags": []}},
            "top_results": [
                {"source_id": "conv:D1:3", "session_id": "D1", "evidence_ref": "D1:3", "context_window": 1, "text": "Melanie packed snacks."}
            ],
        }
    ]

    report = build_pack_gate_runtime_candidate_report(cases, per_case, focus_top_k=3, pack_window=1, max_model_cases=1)

    assert report["contract"] == "pack_gate_runtime_candidate_report.v2026.6.19"
    assert report["boundary"]["runtime_policy"] is False
    assert report["boundary"]["runtime_candidate_report_only"] is True
    assert report["boundary"]["uses_gold_expected_answer"] is False
    assert report["decision_counts"] == {"observe_only": 1}
    assert report["rows"][0]["features"]["answer_state_pair"] == "top_dry_run__pack_dry_run"


def test_pack_gate_runtime_candidate_report_fake_model_triggers_pack_improved():
    cases = [
        {
            "question_id": "q1",
            "question_type": "list",
            "question": "What activities has Melanie done with her family?",
            "answer": "painting and camping",
            "expected_source_refs": ["D1:2", "D1:4"],
            "expected_session_ids": ["D1"],
            "source_units": [
                {"source_id": "conv:D1:1", "session_id": "D1", "evidence_ref": "D1:1", "text": "Melanie talked about family plans."},
                {"source_id": "conv:D1:2", "session_id": "D1", "evidence_ref": "D1:2", "text": "Melanie mentioned painting with her kids."},
                {"source_id": "conv:D1:3", "session_id": "D1", "evidence_ref": "D1:3", "text": "Melanie packed snacks."},
                {"source_id": "conv:D1:4", "session_id": "D1", "evidence_ref": "D1:4", "text": "Melanie also mentioned camping with her family."},
            ],
        }
    ]
    per_case = [
        {
            "question_id": "q1",
            "question_type": "list",
            "question": "What activities has Melanie done with her family?",
            "answer": "painting and camping",
            "expected_source_refs": ["D1:2", "D1:4"],
            "expected_session_ids": ["D1"],
            "hits": {"3": {"exact_source_hit": False, "gold_anchor_hit": True}},
            "miss_classification": {"3": {"primary": "right_session_wrong_turn", "tags": []}},
            "top_results": [
                {"source_id": "conv:D1:3", "session_id": "D1", "evidence_ref": "D1:3", "context_window": 1, "text": "Melanie packed snacks."}
            ],
        }
    ]

    def fake_client(messages, config):
        payload = json.loads(messages[1]["content"])
        refs = {item["evidence_ref"] for item in payload["evidence"]}
        if {"D1:2", "D1:4"} <= refs:
            return {
                "content": json.dumps(
                    {
                        "answer": "painting and camping",
                        "verdict": "answered",
                        "confidence": 0.9,
                        "supporting_refs": ["D1:2", "D1:4"],
                        "unknown_reason": "",
                    }
                )
            }
        return {
            "content": json.dumps(
                {
                    "answer": "UNKNOWN",
                    "verdict": "unknown",
                    "confidence": 0.0,
                    "supporting_refs": [],
                    "unknown_reason": "top evidence only mentions snacks",
                }
            )
        }

    report = build_pack_gate_runtime_candidate_report(
        cases,
        per_case,
        focus_top_k=3,
        pack_window=1,
        max_model_cases=1,
        execute_model=True,
        model_config={"provider": "test", "model": "fake", "base_url": "", "api_key_env": ""},
        model_client=fake_client,
    )

    assert report["decision_counts"] == {"trigger_candidate": 1}
    assert report["model_by_decision"] == {"trigger_candidate": {"model_pack_improved": 1}}
    assert report["metrics"]["trigger_candidate_precision"] == 1.0
    assert report["rows"][0]["reasons"] == ["density_positive", "top_not_answered_pack_answered"]
    assert report["boundary"]["runtime_policy"] is False
