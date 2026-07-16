from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
from typing import Dict, List, Optional

import pytest

from src import time_library_delivery_runtime as runtime
from tools import rq1_card_adoption_baseline as rq1


UTC = timezone.utc
T0 = datetime(2026, 7, 13, 14, 0, tzinfo=UTC)
LABEL_CUTOFF = datetime(2026, 7, 15, tzinfo=UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _card_record(tmp_path: Path, library_id: str, source_system: str = "codex") -> dict:
    support = tmp_path / (library_id + ".json")
    support.write_text("{}", encoding="utf-8")
    source = tmp_path / (library_id + ".jsonl")
    source.write_text('{"messages":[{"content":"hello"}]}\n', encoding="utf-8")
    old = (T0 - timedelta(hours=1)).timestamp()
    support.touch()
    source.touch()
    import os

    os.utime(support, (old, old))
    os.utime(source, (old, old))
    excerpt = "hello"
    return {
        "candidate_type": "zhiyi_preference_card",
        "library_shelf": "zhiyi",
        "lifecycle_status": "active",
        "candidate_id": library_id,
        "source_mode": "evidence_bound_model_distill",
        "created_at": _iso(T0 - timedelta(hours=2)),
        "updated_at": _iso(T0 - timedelta(hours=1)),
        "summary": "hello summary",
        "verbatim_excerpt": excerpt,
        "verbatim_sha256": rq1.sha256_bytes(excerpt.encode("utf-8")),
        "source_refs": {
            "source_system": source_system,
            "source_path": str(source),
            "msg_ids": ["msg_001"],
            "captured_at": _iso(T0 - timedelta(hours=1)),
            "candidate_path": str(support),
            "verbatim_sha256": rq1.sha256_bytes(excerpt.encode("utf-8")),
        },
    }


def _event(
    retrieval_id: str,
    stage: str,
    observed_at: datetime,
    refs: List[Dict],
    previous: str = "",
    *,
    used_refs: Optional[List[Dict]] = None,
) -> dict:
    event_id = "event-%s-%s" % (retrieval_id, stage)
    event = {
        "delivery_event_id": event_id,
        "retrieval_id": retrieval_id,
        "platform": "codex",
        "delivery_audience": "agent",
        "delivery_form": "context",
        "delivery_stage": stage,
        "observed_at": _iso(observed_at),
        "recorded_at": _iso(observed_at),
        "evidence_ref": "evidence-%s" % event_id,
        "source_refs": refs,
        "selection_observation": {
            "decision": "emit",
            "policy_ref": "test-policy",
        },
    }
    if previous:
        event["previous_event_id"] = previous
    if stage in {"delivered", "used"}:
        event["delivery_observation"] = {
            "kind": "platform_model_request",
            "observed": True,
            "evidence_ref": "delivery-%s" % event_id,
            "source_refs": refs,
            "request_id": "request-%s" % event_id,
            "evidence_authority": "host_self_report",
            "independent_model_delivery_proven": False,
            "platform_delivery_proof_kind": "host_attested_append_only_chain",
        }
    if stage == "used":
        event["adoption_evidence"] = {
            "kind": "response_source_refs",
            "observed": True,
            "evidence_ref": "adoption-%s" % event_id,
            "evidence_authority": "host_self_report",
            "independent_model_delivery_proven": False,
            "platform_delivery_proof_kind": "host_attested_append_only_chain",
        }
        event["used_source_refs"] = used_refs if used_refs is not None else refs
    return event


def _db_with_events(
    tmp_path: Path,
    events: List[Dict],
    decisions: Optional[List[Dict]] = None,
) -> Path:
    db = tmp_path / "delivery-events.sqlite3"
    connection = sqlite3.connect(db)
    runtime._ensure_schema(connection)
    for event in events:
        connection.execute(
            """
            INSERT INTO delivery_events(
                event_id,retrieval_id,platform,stage,observed_at,recorded_at,
                previous_event_id,evidence_ref,event_json,inserted_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?)
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
                rq1.canonical_json(event),
                event["recorded_at"],
            ),
        )
    for decision in decisions or []:
        payload = {
            "retrieval_id": decision["retrieval_id"],
            "decision": decision["decision"],
        }
        connection.execute(
            """
            INSERT INTO delivery_decisions(
                decision_id,retrieval_id,platform,decision,observed_at,reasons_json,decision_json
            ) VALUES (?,?,?,?,?,?,?)
            """,
            (
                "decision-" + decision["retrieval_id"],
                decision["retrieval_id"],
                "codex",
                decision["decision"],
                decision["observed_at"],
                "[]",
                rq1.canonical_json(payload),
            ),
        )
    connection.commit()
    connection.close()
    return db


def _chain(
    retrieval_id: str,
    refs: List[Dict],
    *,
    used_refs: Optional[List[Dict]] = None,
) -> List[Dict]:
    events = []
    previous = ""
    for index, stage in enumerate(("stored", "retrieved", "selected", "delivered", "used")):
        event = _event(
            retrieval_id,
            stage,
            T0 + timedelta(minutes=index + 1),
            refs,
            previous,
            used_refs=used_refs,
        )
        events.append(event)
        previous = event["delivery_event_id"]
    return events


def test_future_evaluation_label_mutation_keeps_markers_model_and_scores_fixed():
    markers = [
        {
            "card_key": "card-%03d" % index,
            "features": {name: float((index + offset) % 3) for offset, name in enumerate(rq1.FEATURE_NAMES)},
        }
        for index in range(80)
    ]
    labels = [
        {
            "card_key": marker["card_key"],
            "label": index % 2,
            "label_observed_at": _iso(T0 + timedelta(minutes=index + 1)),
            "label_source": "test",
            "features": marker["features"],
        }
        for index, marker in enumerate(markers)
    ]
    train, evaluation = rq1._temporal_split(labels)
    assert train and evaluation
    model = rq1.fit_l2_logistic(train)
    scores = [rq1.score_with_model(row, model) for row in evaluation]
    mutated = [dict(row) for row in evaluation]
    mutated[0]["label"] = 1 - mutated[0]["label"]
    assert model == rq1.fit_l2_logistic(train)
    assert scores == [rq1.score_with_model(row, model) for row in mutated]
    assert [row["label"] for row in evaluation] != [row["label"] for row in mutated]


def test_snapshot_freezes_card_marker_against_future_file_mutation(tmp_path, monkeypatch):
    record = _card_record(tmp_path, "ZX-ZHIYI-ONE")
    monkeypatch.setattr(rq1, "load_file_backed_library_candidate_records", lambda **_: [record])
    monkeypatch.setattr(rq1, "_raw_evidence", lambda _refs: (1, ["hello"]))
    snapshot = rq1.build_card_snapshot(tmp_path, T0)
    before = rq1.canonical_json(snapshot)
    Path(record["source_refs"]["candidate_path"]).write_text("future card state", encoding="utf-8")
    after = rq1.canonical_json(snapshot)
    assert before == after
    rq1.validate_card_snapshot(snapshot)


def test_snapshot_rehash_cannot_replace_bound_tool_sha(tmp_path, monkeypatch):
    record = _card_record(tmp_path, "ZX-ZHIYI-BOUND")
    monkeypatch.setattr(
        rq1, "load_file_backed_library_candidate_records", lambda **_: [record]
    )
    monkeypatch.setattr(rq1, "_raw_evidence", lambda _refs: (1, ["hello"]))
    snapshot = rq1.build_card_snapshot(tmp_path, T0)
    snapshot["rq1_tool_sha256"] = "0" * 64
    snapshot.pop("canonical_payload_sha256")
    snapshot["canonical_payload_sha256"] = rq1.sha256_json(snapshot)
    with pytest.raises(rq1.RQ1Error, match="card_snapshot_tool_sha256_mismatch"):
        rq1.validate_card_snapshot(snapshot)


def test_duplicate_card_library_id_fails_closed(tmp_path, monkeypatch):
    first = _card_record(tmp_path, "ZX-ZHIYI-DUP")
    second = dict(first)
    second["source_refs"] = dict(first["source_refs"])
    second["source_refs"]["candidate_path"] = first["source_refs"]["candidate_path"]
    monkeypatch.setattr(rq1, "load_file_backed_library_candidate_records", lambda **_: [first, second])
    monkeypatch.setattr(rq1, "_raw_evidence", lambda _refs: (1, ["hello"]))
    with pytest.raises(rq1.RQ1Error, match="duplicate_card_library_id"):
        rq1.collect_card_markers(tmp_path, T0)


def test_future_source_ref_fails_closed(tmp_path, monkeypatch):
    record = _card_record(tmp_path, "ZX-ZHIYI-FUTURE")
    record["source_refs"]["captured_at"] = _iso(T0 + timedelta(seconds=1))
    monkeypatch.setattr(rq1, "load_file_backed_library_candidate_records", lambda **_: [record])
    monkeypatch.setattr(rq1, "_raw_evidence", lambda _refs: (1, ["hello"]))
    with pytest.raises(rq1.RQ1Error, match="source_observed_after_marker_cutoff"):
        rq1.collect_card_markers(tmp_path, T0)


def test_nonempty_fake_verbatim_does_not_pass_roundtrip(tmp_path, monkeypatch):
    record = _card_record(tmp_path, "ZX-ZHIYI-FAKE")
    record["verbatim_excerpt"] = "fabricated but nonempty"
    record["verbatim_sha256"] = rq1.sha256_bytes(
        record["verbatim_excerpt"].encode("utf-8")
    )
    monkeypatch.setattr(
        rq1, "load_file_backed_library_candidate_records", lambda **_: [record]
    )
    rows, _diagnostics = rq1.collect_card_markers(tmp_path, T0)
    assert rows[0]["features"]["verbatim_present"] == 1.0
    assert rows[0]["features"]["provenance_roundtrip_exact"] == 0.0
    assert rows[0]["features"]["verbatim_not_distill_masquerade"] == 0.0


def test_explicitly_superseded_card_is_excluded_even_if_loader_returns_it(
    tmp_path, monkeypatch
):
    record = _card_record(tmp_path, "ZX-ZHIYI-OLD")
    record["lifecycle_status"] = "superseded"
    monkeypatch.setattr(
        rq1, "load_file_backed_library_candidate_records", lambda **_: [record]
    )
    rows, diagnostics = rq1.collect_card_markers(tmp_path, T0)
    assert rows == []
    assert diagnostics["explicitly_inactive_card_excluded_count"] == 1


def test_card_join_requires_library_id_and_source_system(tmp_path):
    refs = [{"library_id": "ZX-ZHIYI-A", "source_system": "codex"}]
    events = _chain("r1", refs)
    db = _db_with_events(
        tmp_path,
        events,
        [{"retrieval_id": "r1", "decision": "emit", "observed_at": _iso(T0 + timedelta(minutes=1))}],
    )
    evidence = rq1.read_card_adoption_evidence(
        db,
        marker_cutoff=T0,
        label_cutoff=LABEL_CUTOFF,
        marker_identities={"ZX-ZHIYI-A": ["codex"]},
    )
    assert evidence["delivered_card_library_id_matched_count"] == 1
    assert evidence["delivered_card_library_id_match_rate"] == 1.0
    mismatched = rq1.read_card_adoption_evidence(
        db,
        marker_cutoff=T0,
        label_cutoff=LABEL_CUTOFF,
        marker_identities={"ZX-ZHIYI-A": ["claude_code_cli"]},
    )
    assert mismatched["delivered_card_library_id_matched_count"] == 0
    assert mismatched["delivered_card_library_id_source_system_mismatch_count"] == 1


def test_used_source_refs_only_label_used_card(tmp_path, monkeypatch):
    a = {"library_id": "ZX-ZHIYI-A", "source_system": "codex"}
    b = {"library_id": "ZX-ZHIYI-B", "source_system": "codex"}
    events = _chain("r-used", [a, b], used_refs=[a])
    db = _db_with_events(
        tmp_path,
        events,
        [{"retrieval_id": "r-used", "decision": "emit", "observed_at": _iso(T0 + timedelta(minutes=1))}],
    )
    monkeypatch.setattr(rq1, "validate_delivery_chain", lambda _events: {"errors": [], "validated_prefix_event_count": len(_events)})
    evidence = rq1.read_card_adoption_evidence(
        db,
        marker_cutoff=T0,
        label_cutoff=LABEL_CUTOFF,
        marker_identities={"ZX-ZHIYI-A": ["codex"], "ZX-ZHIYI-B": ["codex"]},
    )
    assert [(row["library_id"], row["label"]) for row in evidence["labels"]] == [
        ("ZX-ZHIYI-A", 0),
        ("ZX-ZHIYI-B", 1),
    ]
    assert evidence["used_is_host_attested"] is True


def test_selected_without_delivered_is_not_a_negative_label(tmp_path, monkeypatch):
    refs = [{"library_id": "ZX-ZHIYI-A", "source_system": "codex"}]
    events = [_event("r-selected", "stored", T0 + timedelta(minutes=1), refs)]
    events.append(_event("r-selected", "retrieved", T0 + timedelta(minutes=2), refs, events[-1]["delivery_event_id"]))
    events.append(_event("r-selected", "selected", T0 + timedelta(minutes=3), refs, events[-1]["delivery_event_id"]))
    db = _db_with_events(
        tmp_path,
        events,
        [{"retrieval_id": "r-selected", "decision": "emit", "observed_at": _iso(T0 + timedelta(minutes=1))}],
    )
    monkeypatch.setattr(rq1, "validate_delivery_chain", lambda _events: {"errors": [], "validated_prefix_event_count": len(_events)})
    evidence = rq1.read_card_adoption_evidence(
        db,
        marker_cutoff=T0,
        label_cutoff=LABEL_CUTOFF,
        marker_identities={"ZX-ZHIYI-A": ["codex"]},
    )
    assert evidence["labels"] == []


def test_invalid_used_tail_cannot_turn_delivered_prefix_into_bad_card(
    tmp_path, monkeypatch
):
    refs = [{"library_id": "ZX-ZHIYI-A", "source_system": "codex"}]
    events = _chain("r-invalid-tail", refs)
    db = _db_with_events(
        tmp_path,
        events,
        [
            {
                "retrieval_id": "r-invalid-tail",
                "decision": "emit",
                "observed_at": _iso(T0 + timedelta(minutes=1)),
            }
        ],
    )
    monkeypatch.setattr(
        rq1,
        "validate_delivery_chain",
        lambda _events: {
            "errors": ["event_4:used_source_refs_invalid"],
            "validated_prefix_event_count": 4,
        },
    )
    evidence = rq1.read_card_adoption_evidence(
        db,
        marker_cutoff=T0,
        label_cutoff=LABEL_CUTOFF,
        marker_identities={"ZX-ZHIYI-A": ["codex"]},
    )
    assert evidence["labels"] == []
    assert evidence["invalid_retrieval_chain_count"] == 1
    assert evidence["invalid_chain_event_count_excluded"] == len(events)


def test_sparse_evaluation_never_fits_auc():
    rows = [
        {"card_key": "a", "features": {name: 0.0 for name in rq1.FEATURE_NAMES}},
        {"card_key": "b", "features": {name: 1.0 for name in rq1.FEATURE_NAMES}},
    ]
    labels = [
        {"card_key": "a", "label": 0, "label_observed_at": _iso(T0 + timedelta(hours=1)), "features": rows[0]["features"]}
    ]
    result = rq1.evaluate_proxy(rows, labels, join_matched_count=1)
    assert result["decision"] == rq1.DECISION_SPARSE
    assert result["model_fitted"] is False
    assert result["roc_auc"] is None
    assert result["precision_at_k"] is None


def test_report_declares_rescope_and_no_production_unlock(tmp_path, monkeypatch):
    record = _card_record(tmp_path, "ZX-ZHIYI-A")
    monkeypatch.setattr(rq1, "load_file_backed_library_candidate_records", lambda **_: [record])
    monkeypatch.setattr(rq1, "_raw_evidence", lambda _refs: (1, ["hello"]))
    snapshot = rq1.build_card_snapshot(tmp_path, T0)
    db = _db_with_events(tmp_path, [])
    report = rq1.build_report(
        runtime_root=tmp_path,
        delivery_db=db,
        card_snapshot=snapshot,
        label_cutoff=LABEL_CUTOFF,
    )
    assert report["score_is_adoption_proxy_not_semantic_accuracy"] is True
    assert report["rescopes_r2_quality_to_card_adoption_layer"] is True
    assert report["raw_extraction_remains_unmeasured_upstream"] is True
    assert report["production_unlock"] is False


def test_report_write_is_0600_and_refuses_runtime_output(tmp_path):
    report = {"contract": rq1.CONTRACT, "decision": rq1.DECISION_SPARSE}
    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir()
    with pytest.raises(rq1.RQ1Error, match="report_output_must_not_be_inside_runtime_root"):
        rq1.write_report(runtime_root / "report.json", report, runtime_root=runtime_root)
    output = tmp_path / "output" / "report.json"
    rq1.write_report(output, report, runtime_root=runtime_root)
    assert oct(output.stat().st_mode & 0o777) == "0o600"
    assert output.read_text(encoding="utf-8") == rq1.canonical_json(report) + "\n"


def test_snapshot_write_is_atomic_0600_and_no_overwrite(tmp_path):
    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir()
    output = tmp_path / "snapshot.json"
    payload = {"contract": rq1.SNAPSHOT_CONTRACT}
    rq1.write_private_json(output, payload, runtime_root=runtime_root)
    assert oct(output.stat().st_mode & 0o777) == "0o600"
    with pytest.raises(rq1.RQ1Error, match="private_output_already_exists"):
        rq1.write_private_json(output, payload, runtime_root=runtime_root)


def test_tool_has_no_network_or_model_client_imports():
    source = Path(rq1.__file__).read_text(encoding="utf-8")
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
    assert "PRAGMA query_only = ON" in source
    assert '"model_call_performed": False' in source
