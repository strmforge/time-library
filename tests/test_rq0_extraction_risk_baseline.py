import ast
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
from pathlib import Path
import sqlite3

import pytest

from src import state_memory_extraction_candidate as candidate_rules
from src.time_library_delivery_spine import (
    HOST_ATTESTED_PLATFORM_DELIVERY_PROOF_KIND,
    HOST_SELF_REPORT_EVIDENCE_AUTHORITY,
)
from tools import rq0_extraction_risk_baseline as rq0


UTC = timezone.utc


def _iso(value):
    return (
        value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
    )


def _features(risk=0.0, *, size=1.0):
    values = {name: 0.0 for name in rq0.FEATURE_NAMES}
    values.update(
        {
            "marker_build_succeeded": 1.0,
            "span_exactness": 1.0 - risk,
            "source_ref_resolvable": 1.0 - risk,
            "roundtrip_byte_exact": 1.0 - risk,
            "unknown_honesty": 1.0 - risk,
            "overconfidence_rate": risk,
            "atom_redundancy": risk,
            "ambiguity_flag_rate": risk,
            "empty_extraction_on_stateful": risk,
            "log_record_bytes": size,
            "log_atom_count": size / 2.0,
        }
    )
    return values


def _marker(index, *, library_id=None, native_id=None, identity_group=None, risk=0.0):
    return {
        "record_key": "record-%03d" % index,
        "library_id": library_id or "library-%03d" % index,
        "native_id": native_id or "native-%03d" % index,
        "identity_group": identity_group or "group-%03d" % index,
        "kind": "case",
        "features": _features(risk, size=1.0 + index / 1000.0),
    }


def _label(marker, label, observed_at):
    return {
        "record_key": marker["record_key"],
        "identity_group": marker["identity_group"],
        "label": label,
        "label_observed_at": _iso(observed_at),
        "label_source": "synthetic_proxy",
        "features": dict(marker["features"]),
    }


def _source_ref(library_id):
    return {"source_system": "test_host", "library_id": library_id}


def _event(stage, retrieval_id, index, observed_at, refs, *, used_refs=None):
    event = {
        "delivery_event_id": "%s-%s-%d" % (retrieval_id, stage, index),
        "retrieval_id": retrieval_id,
        "platform": "test_host",
        "delivery_audience": "agent",
        "delivery_form": "context",
        "delivery_stage": stage,
        "observed_at": _iso(observed_at),
        "recorded_at": _iso(observed_at),
        "evidence_ref": "evidence-%s-%d" % (stage, index),
        "source_refs": deepcopy(refs),
    }
    if index:
        previous_stage = ("stored", "retrieved", "selected", "delivered", "used")[
            index - 1
        ]
        event["previous_event_id"] = "%s-%s-%d" % (
            retrieval_id,
            previous_stage,
            index - 1,
        )
    if stage == "selected":
        event["selection_observation"] = {
            "decision": "emit",
            "policy_ref": "test-policy",
        }
    if stage in {"delivered", "used"}:
        event["delivery_observation"] = {
            "kind": "platform_model_request",
            "observed": True,
            "evidence_ref": "request-evidence",
            "request_id": "request-1",
            "source_refs": deepcopy(refs),
            "evidence_authority": HOST_SELF_REPORT_EVIDENCE_AUTHORITY,
            "independent_model_delivery_proven": False,
            "platform_delivery_proof_kind": HOST_ATTESTED_PLATFORM_DELIVERY_PROOF_KIND,
        }
    if stage == "used":
        event["used_source_refs"] = deepcopy(
            used_refs if used_refs is not None else refs
        )
        event["adoption_evidence"] = {
            "kind": "response_source_refs",
            "observed": True,
            "evidence_ref": "adoption-evidence",
            "evidence_authority": HOST_SELF_REPORT_EVIDENCE_AUTHORITY,
            "independent_model_delivery_proven": False,
            "platform_delivery_proof_kind": HOST_ATTESTED_PLATFORM_DELIVERY_PROOF_KIND,
        }
    return event


def _create_delivery_db(path):
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE delivery_events (
            event_id TEXT PRIMARY KEY,
            retrieval_id TEXT NOT NULL,
            platform TEXT NOT NULL,
            stage TEXT NOT NULL,
            observed_at TEXT NOT NULL,
            recorded_at TEXT NOT NULL,
            previous_event_id TEXT NOT NULL DEFAULT '',
            evidence_ref TEXT NOT NULL,
            event_json TEXT NOT NULL,
            inserted_at TEXT NOT NULL
        );
        CREATE TABLE delivery_challenges (
            challenge_id TEXT PRIMARY KEY,
            retrieval_id TEXT NOT NULL UNIQUE,
            platform TEXT NOT NULL,
            selected_event_id TEXT NOT NULL,
            unknown_event_id TEXT NOT NULL,
            challenge_hash TEXT NOT NULL,
            source_refs_json TEXT NOT NULL,
            issued_at TEXT NOT NULL,
            expires_at TEXT NOT NULL
        );
        CREATE TABLE delivery_security_events (
            security_event_id TEXT PRIMARY KEY,
            challenge_id TEXT NOT NULL DEFAULT '',
            platform TEXT NOT NULL DEFAULT '',
            reason TEXT NOT NULL,
            observed_at TEXT NOT NULL,
            evidence_ref TEXT NOT NULL
        );
        """
    )
    connection.commit()
    return connection


def _insert_event(connection, event):
    connection.execute(
        """
        INSERT INTO delivery_events (
            event_id, retrieval_id, platform, stage, observed_at, recorded_at,
            previous_event_id, evidence_ref, event_json, inserted_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event["delivery_event_id"],
            event["retrieval_id"],
            event["platform"],
            event["delivery_stage"],
            event["observed_at"],
            event["recorded_at"],
            event.get("previous_event_id", ""),
            event["evidence_ref"],
            rq0.canonical_json(event),
            event["recorded_at"],
        ),
    )


def _insert_chain(
    connection,
    retrieval_id,
    start,
    refs,
    stages,
    *,
    used_refs=None,
    step_microseconds=1,
):
    events = []
    for index, stage in enumerate(stages):
        event = _event(
            stage,
            retrieval_id,
            index,
            start + timedelta(microseconds=index * step_microseconds),
            refs,
            used_refs=used_refs,
        )
        _insert_event(connection, event)
        events.append(event)
    return events


def test_future_evaluation_label_mutation_keeps_markers_model_and_scores_fixed():
    t0 = datetime(2026, 7, 14, tzinfo=UTC)
    markers = [_marker(index, risk=float(index % 2)) for index in range(200)]
    labels = [
        _label(marker, index % 2, t0 + timedelta(seconds=index + 1))
        for index, marker in enumerate(markers)
    ]
    marker_digest = rq0.sha256_json(
        [
            {"record_key": row["record_key"], "features": row["features"]}
            for row in markers
        ]
    )
    train, evaluation = rq0._temporal_split(labels)
    model = rq0.fit_l2_logistic(train)
    scores = [rq0.score_with_model(row, model) for row in evaluation]
    auc = rq0.roc_auc([row["label"] for row in evaluation], scores)

    mutated_evaluation = deepcopy(evaluation)
    mutated_evaluation[0]["label"] = 1 - mutated_evaluation[0]["label"]
    assert marker_digest == rq0.sha256_json(
        [
            {"record_key": row["record_key"], "features": row["features"]}
            for row in markers
        ]
    )
    assert model == rq0.fit_l2_logistic(train)
    assert scores == [rq0.score_with_model(row, model) for row in mutated_evaluation]
    assert auc != rq0.roc_auc([row["label"] for row in mutated_evaluation], scores)

    mutated_train = deepcopy(train)
    mutated_train[0]["label"] = 1 - mutated_train[0]["label"]
    assert rq0.fit_l2_logistic(mutated_train) != model


def test_marker_rejects_source_observed_after_t0():
    t0 = datetime(2026, 7, 14, 11, 45, 11, tzinfo=UTC)
    record = {
        "exp_id": "future-source",
        "summary": "The source timestamp is in the future.",
        "extracted_at": _iso(t0),
        "source_refs": [
            {
                "source_system": "test",
                "source_path": "/private/source.jsonl",
                "captured_at": _iso(t0 + timedelta(microseconds=1)),
            }
        ],
    }

    with pytest.raises(rq0.RQ0Error, match="source_observed_after_t0"):
        rq0._plan_for_record("case", 1, record, t0=t0)


def test_delivery_window_chain_validation_used_subset_and_challenge_noise(tmp_path):
    db_path = tmp_path / "delivery.sqlite3"
    connection = _create_delivery_db(db_path)
    t0 = datetime(2026, 7, 14, 11, 45, 11, tzinfo=UTC)

    _insert_chain(
        connection,
        "at-t0",
        t0,
        [_source_ref("library-at-t0")],
        ("stored", "retrieved", "selected"),
        step_microseconds=0,
    )
    selected = _insert_chain(
        connection,
        "selected-after",
        t0 + timedelta(microseconds=1),
        [_source_ref("library-selected")],
        ("stored", "retrieved", "selected"),
    )
    refs = [_source_ref("library-used"), _source_ref("library-selected-only")]
    used = _insert_chain(
        connection,
        "used-subset",
        t0 + timedelta(microseconds=10),
        refs,
        ("stored", "retrieved", "selected", "delivered", "used"),
        used_refs=[refs[0]],
    )
    unlinked_tail = _event(
        "used",
        "unlinked-tail",
        4,
        t0 + timedelta(microseconds=20),
        [_source_ref("library-unlinked")],
    )
    _insert_event(connection, unlinked_tail)

    challenge_time = t0 + timedelta(microseconds=12)
    connection.execute(
        "INSERT INTO delivery_challenges VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "challenge-used",
            "used-subset",
            "test_host",
            used[2]["delivery_event_id"],
            "unknown-event",
            "hash",
            "[]",
            _iso(challenge_time),
            _iso(challenge_time + timedelta(minutes=15)),
        ),
    )
    connection.execute(
        "INSERT INTO delivery_security_events VALUES (?, ?, ?, ?, ?, ?)",
        (
            "security-used",
            "challenge-used",
            "test_host",
            "challenge_mismatch",
            _iso(challenge_time),
            "security-evidence",
        ),
    )
    connection.commit()
    connection.close()

    before = (
        hashlib.sha256(db_path.read_bytes()).hexdigest(),
        db_path.stat().st_mtime_ns,
    )
    evidence = rq0.read_delivery_evidence(
        db_path,
        t0=t0,
        label_cutoff=t0 + timedelta(microseconds=30),
    )
    after = (
        hashlib.sha256(db_path.read_bytes()).hexdigest(),
        db_path.stat().st_mtime_ns,
    )

    assert before == after
    assert not Path(str(db_path) + "-wal").exists()
    assert not Path(str(db_path) + "-shm").exists()
    assert "library-at-t0" not in evidence["by_library"]
    assert evidence["by_library"]["library-selected"]["selected"] == [
        selected[2]["observed_at"]
    ]
    assert evidence["by_library"]["library-used"]["used"] == [used[4]["observed_at"]]
    assert "used" not in evidence["by_library"]["library-selected-only"]
    assert "library-unlinked" not in evidence["by_library"]
    assert evidence["invalid_retrieval_chain_count"] == 1
    assert evidence["challenge_rejection_labeled_bad_count"] == 0
    assert evidence["challenge_rejection_then_same_retrieval_used_count"] == 1
    assert evidence["query_only"] is True


def test_natural_labels_are_unique_and_leave_unexposed_collision_and_conflict_unlabeled():
    a = _marker(1, library_id="library-a", native_id="native-a")
    b = _marker(2, library_id="library-b", native_id="native-b")
    collision_1 = _marker(3, library_id="library-collision", native_id="native-c1")
    collision_2 = _marker(4, library_id="library-collision", native_id="native-c2")
    conflict = _marker(5, library_id="library-conflict", native_id="native-conflict")
    correction = _marker(
        6, library_id="library-correction", native_id="native-correction"
    )
    duplicate_1 = _marker(
        7,
        library_id="library-duplicate-1",
        native_id="native-duplicate-1",
        identity_group="shared-group",
    )
    duplicate_2 = _marker(
        8,
        library_id="library-duplicate-2",
        native_id="native-duplicate-2",
        identity_group="shared-group",
    )
    marker_rows = [
        a,
        b,
        collision_1,
        collision_2,
        conflict,
        correction,
        duplicate_1,
        duplicate_2,
    ]
    delivery = {
        "by_library": {
            "library-a": {
                "selected": ["2026-07-15T00:00:01.000000Z"],
                "used": ["2026-07-15T00:00:02.000000Z"],
            },
            "library-collision": {"selected": ["2026-07-15T00:00:03.000000Z"]},
            "library-conflict": {"selected": ["2026-07-15T00:00:04.000000Z"]},
            "library-duplicate-1": {"selected": ["2026-07-15T00:00:05.000000Z"]},
        }
    }
    relations = {
        "corrective_targets": [
            ("native-conflict", "2026-07-15T00:00:06.000000Z"),
            ("native-correction", "2026-07-15T00:00:07.000000Z"),
        ],
        "ambiguous_targets": [("native-b", "2026-07-15T00:00:08.000000Z")],
    }

    labels, diagnostics = rq0.build_natural_labels(marker_rows, delivery, relations)

    assert [(row["record_key"], row["label"]) for row in labels] == [
        (a["record_key"], 0),
        (correction["record_key"], 1),
    ]
    assert b["record_key"] not in {row["record_key"] for row in labels}
    assert diagnostics["unselected_records_labeled_bad"] == 0
    assert diagnostics["challenge_rejections_labeled_bad"] == 0
    assert diagnostics["mapping_collision_target_count"] == 1
    assert diagnostics["duplicate_identity_group_target_count"] == 1
    assert diagnostics["ambiguous_conflicting_proxy_count"] == 1
    assert diagnostics["effective_independent_labeled_record_count"] == 2


def test_post_cutoff_relations_exclude_backfilled_old_facts_and_keep_supersede_ambiguous(
    tmp_path, monkeypatch
):
    runtime = tmp_path / "runtime"
    path = runtime / "case.jsonl"
    path.parent.mkdir(parents=True)
    prefix = b'{"prefix":true}\n'
    t0 = datetime(2026, 7, 14, 11, 45, 11, tzinfo=UTC)

    def record(exp_id, captured_at, **relations):
        return {
            "exp_id": exp_id,
            "summary": "state",
            "extracted_at": _iso(t0 + timedelta(hours=1)),
            "source_refs": [
                {
                    "source_system": "test",
                    "source_path": "/private/source.jsonl",
                    "captured_at": captured_at,
                }
            ],
            **relations,
        }

    tail = [
        record("backfill", _iso(t0), correction_of="native-old"),
        record(
            "correction",
            _iso(t0 + timedelta(seconds=1)),
            correction_of="native-corrected",
        ),
        record(
            "world-change",
            _iso(t0 + timedelta(seconds=2)),
            supersedes="native-old-state",
        ),
    ]
    path.write_bytes(
        prefix + b"".join((rq0.canonical_json(item) + "\n").encode() for item in tail)
    )
    monkeypatch.setattr(rq0.r2_audit, "RECORD_PATHS", {"case": "case.jsonl"})
    result = rq0.read_post_cutoff_relations(
        runtime,
        {"files": [{"kind": "case", "cutoff_bytes": len(prefix)}]},
        t0=t0,
        label_cutoff=t0 + timedelta(hours=2),
    )

    assert [target for target, _time in result["corrective_targets"]] == [
        "native-corrected"
    ]
    assert [target for target, _time in result["ambiguous_targets"]] == [
        "native-old-state"
    ]
    assert result["backfilled_old_fact_records_excluded"] == 1


def test_sparse_signal_is_a_legal_negative_result_without_auc():
    t0 = datetime(2026, 7, 14, tzinfo=UTC)
    markers = [_marker(index) for index in range(200)]
    labels = [
        _label(markers[index], 0, t0 + timedelta(seconds=index + 1))
        for index in range(4)
    ]

    result = rq0.evaluate_proxy(markers, labels)

    assert result["decision"] == rq0.REPORT_DECISION_SPARSE
    assert result["model_fitted"] is False
    assert result["roc_auc"] is None
    assert result["precision_at_k"] is None
    assert "class_support_below_minimum" in result["sparse_reasons"]


def test_sufficient_temporal_two_class_signal_fits_deterministically():
    t0 = datetime(2026, 7, 14, tzinfo=UTC)
    markers = [_marker(index, risk=float(index % 2)) for index in range(200)]
    labels = [
        _label(marker, index % 2, t0 + timedelta(seconds=index + 1))
        for index, marker in enumerate(markers)
    ]

    first = rq0.evaluate_proxy(markers, labels)
    second = rq0.evaluate_proxy(markers, labels)

    assert first == second
    assert first["decision"] == rq0.REPORT_DECISION_CALIBRATED
    assert first["model_fitted"] is True
    assert first["roc_auc"] == 1.0
    assert first["precision_at_k"]["value"] == 1.0
    assert first["evaluation"]["count"] >= 10


def test_build_report_is_byte_deterministic_and_keeps_proxy_boundaries(
    tmp_path, monkeypatch
):
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    cutoff_path = tmp_path / "cutoff.json"
    cutoff = {
        "captured_at": "2026-07-14T11:45:11Z",
        "cutoff_identity_sha256": "c" * 64,
        "files": [{"kind": "case", "newline_count": 2}],
    }
    cutoff_path.write_text(rq0.canonical_json(cutoff), encoding="utf-8")
    prereg_path = tmp_path / "prereg.json"
    prereg_path.write_text(
        rq0.canonical_json(
            {
                "rules_frozen": True,
                "cutoff_file_sha256": rq0.file_sha256(cutoff_path),
                "cutoff_identity_sha256": cutoff["cutoff_identity_sha256"],
                "extractor_sha256": rq0.file_sha256(Path(candidate_rules.__file__)),
                "source_commit": "a" * 40,
                "extractor_contract": candidate_rules.HYBRID_EXTRACTION_CONTRACT,
            }
        ),
        encoding="utf-8",
    )
    markers = [_marker(1, library_id="library-a"), _marker(2, library_id="library-b")]
    delivery = {
        "quick_check": "ok",
        "query_only": True,
        "by_library": {"library-a": {"selected": ["2026-07-15T00:00:00.000000Z"]}},
        "event_count_in_label_window": 1,
        "stage_counts": {"selected": 1},
        "distinct_library_ids": 1,
        "telemetry_present_at_or_before_t0": True,
        "validated_retrieval_chain_count": 1,
        "invalid_retrieval_chain_count": 0,
        "invalid_chain_event_count_excluded": 0,
        "challenge_rejection_count": 0,
        "challenge_rejection_labeled_bad_count": 0,
        "challenge_rejection_then_same_retrieval_used_count": 0,
        "challenge_rejection_unmatched_challenge_count": 0,
        "sanitized_evidence_sha256": "d" * 64,
    }
    relations = {
        "tail_records_observed": 0,
        "backfilled_old_fact_records_excluded": 0,
        "relation_time_unusable_records_excluded": 0,
        "corrective_targets": [],
        "ambiguous_targets": [],
        "corrective_target_count": 0,
        "ambiguous_target_count": 0,
        "sanitized_relations_sha256": "e" * 64,
    }
    monkeypatch.setattr(rq0.r2_audit, "validate_cutoff", lambda _cutoff: None)
    monkeypatch.setattr(
        rq0, "collect_marker_rows", lambda _root, _cutoff: (markers, {})
    )
    monkeypatch.setattr(
        rq0, "read_delivery_evidence", lambda *_args, **_kwargs: delivery
    )
    monkeypatch.setattr(
        rq0, "read_post_cutoff_relations", lambda *_args, **_kwargs: relations
    )

    kwargs = {
        "runtime_root": runtime,
        "cutoff_path": cutoff_path,
        "prereg_path": prereg_path,
        "delivery_db": tmp_path / "unused.sqlite3",
        "label_cutoff": datetime(2026, 7, 15, tzinfo=UTC),
    }
    first = rq0.build_report(**kwargs)
    second = rq0.build_report(**kwargs)

    assert rq0.canonical_json(first) == rq0.canonical_json(second)
    assert first["decision"] == rq0.REPORT_DECISION_SPARSE
    assert first["score_is_risk_proxy_not_semantic_accuracy"] is True
    assert first["candidate_semantic_accuracy"] == "not_measured"
    assert first["production_unlock"] is False
    assert first["quality_status"] == "not_measured"
    assert first["production_decision"] == "NO_GO_PRODUCTION_SHADOW"
    assert first["runtime_write_performed"] is False
    assert first["global_zero_write_proven"] is False
    assert first["natural_labels"]["coverage_rate"] == 0.5
    assert first["natural_labels"]["eligible_negative_supported"] is False
    assert first["gate_b_no_future_leakage"]["marker_source_refs_not_after_t0"] is True
    assert (
        first["gate_b_no_future_leakage"]["future_label_mutation_score_invariance"]
        is True
    )
    assert "private/source" not in rq0.canonical_json(first)


def test_report_write_is_0600_and_refuses_runtime_output(tmp_path):
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    report = {"contract": rq0.CONTRACT, "decision": rq0.REPORT_DECISION_SPARSE}

    with pytest.raises(
        rq0.RQ0Error, match="report_output_must_not_be_inside_runtime_root"
    ):
        rq0.write_report(runtime / "report.json", report, runtime_root=runtime)

    output = tmp_path / "output" / "report.json"
    rq0.write_report(output, report, runtime_root=runtime)
    assert output.read_text(encoding="utf-8") == rq0.canonical_json(report) + "\n"
    assert oct(output.stat().st_mode & 0o777) == "0o600"


def test_tool_has_no_network_or_model_client_imports():
    source = Path(rq0.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".")[0])

    assert not imported_roots.intersection(
        {"httpx", "requests", "urllib", "subprocess", "socket", "openai", "anthropic"}
    )
    assert "?mode=ro" in source
    assert "PRAGMA query_only = ON" in source
    assert '"model_call_performed": False' in source
