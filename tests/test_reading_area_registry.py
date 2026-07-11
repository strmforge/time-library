import hashlib
import json
from pathlib import Path

from src import reading_area_registry as registry
from src import window_binding_registry


def test_borrowing_card_preserves_window_project_id_as_technical_anchor_only(tmp_path):
    path = tmp_path / "reading_area_registry.json"
    result = registry.ensure_borrowing_card(
        source_system="codex",
        consumer="codex",
        canonical_window_id="codex-window-1",
        session_id="codex-session-1",
        binding={
            "canonical_window_id": "codex-window-1",
            "session_id": "codex-session-1",
            "metadata": {"project_id": "fixture-window-7f60287b"},
        },
        path=path,
    )

    assert result["ok"] is True
    card = result["card"]
    assert card["project_identity_source"] == "agent_self_report_not_technical_project_id"
    assert card["technical_anchors"]["project_id"] == "fixture-window-7f60287b"
    assert card["declared_project_ids"] == []
    assert card["reading_area_content_write_performed"] is False


def test_borrowing_card_can_be_issued_from_current_window_binding_without_project_inference(tmp_path):
    window_path = tmp_path / "window_binding_registry.json"
    reading_path = tmp_path / "reading_area_registry.json"
    window_binding_registry.register_current_window(
        source_system="codex",
        consumer="codex",
        canonical_window_id="codex-window-2",
        session_id="codex-session-2",
        metadata={"project_id": "fixture-window-7f60287b"},
        path=window_path,
    )

    result = registry.ensure_borrowing_card_for_current_window(
        source_system="codex",
        consumer="codex",
        window_registry_path=window_path,
        reading_area_registry_path=reading_path,
    )

    assert result["ok"] is True
    assert result["window_binding_applied"] is True
    assert result["window_binding_key"] == "codex"
    card = result["card"]
    assert card["canonical_window_id"] == "codex-window-2"
    assert card["technical_anchors"]["project_id"] == "fixture-window-7f60287b"
    assert card["declared_project_ids"] == []
    assert card["project_identity_source"] == "agent_self_report_not_technical_project_id"


def test_self_report_membership_creates_reading_area_project_and_series(tmp_path):
    path = tmp_path / "reading_area_registry.json"
    card = registry.ensure_borrowing_card(
        source_system="opus",
        canonical_window_id="opus-window",
        session_id="opus-session",
        path=path,
    )["card"]

    result = registry.declare_membership(
        card_id=card["card_id"],
        reading_area="Time Library阅读区",
        projects=["Time Library"],
        series=["Shared Reading Series"],
        path=path,
    )

    assert result["ok"] is True
    saved = registry.load_registry(path)
    saved_card = saved["borrowing_cards"][card["card_id"]]
    assert result["reading_area_id"] in saved_card["declared_reading_area_ids"]
    assert result["project_ids"][0] in saved_card["declared_project_ids"]
    assert result["series_ids"][0] in saved_card["declared_series_ids"]
    assert saved["projects"][result["project_ids"][0]]["name"] == "time-library"
    assert saved["series"][result["series_ids"][0]]["name"] == "Shared Reading Series"
    assert saved["_meta"]["project_id_technical_anchor_not_overwritten"] is True


def test_membership_can_store_declared_roles(tmp_path):
    path = tmp_path / "reading_area_registry.json"
    card = registry.ensure_borrowing_card(
        source_system="codex",
        canonical_window_id="roles-window",
        session_id="roles-session",
        path=path,
    )["card"]

    result = registry.declare_membership(
        card_id=card["card_id"],
        reading_area="Time Library阅读区",
        projects=["Time Library"],
        roles=["施工", "一签"],
        path=path,
    )

    assert result["ok"] is True
    assert result["declared_roles"] == ["一签", "施工"]
    saved_card = registry.load_registry(path)["borrowing_cards"][card["card_id"]]
    assert saved_card["declared_roles"] == ["一签", "施工"]


def test_rename_preserves_alias_and_updates_cards(tmp_path):
    path = tmp_path / "reading_area_registry.json"
    card = registry.ensure_borrowing_card(
        source_system="codex",
        canonical_window_id="window-a",
        path=path,
    )["card"]
    joined = registry.declare_membership(
        card_id=card["card_id"],
        reading_area="Time Library阅读区",
        projects=["Original Project"],
        series=["Shared Reading Series"],
        path=path,
    )

    renamed = registry.rename_scope(
        "project",
        joined["project_ids"][0],
        "Time Library",
        declared_by_card_id=card["card_id"],
        path=path,
    )

    assert renamed["ok"] is True
    assert registry.resolve_scope_id("project", "Time Library", path=path) == renamed["new_id"]
    assert registry.resolve_scope_id("project", "Original Project", path=path) == renamed["new_id"]
    saved_card = registry.load_registry(path)["borrowing_cards"][card["card_id"]]
    assert renamed["new_id"] in saved_card["declared_project_ids"]
    assert joined["project_ids"][0] not in saved_card["declared_project_ids"]


def test_merge_scope_aliases_duplicate_projects(tmp_path):
    path = tmp_path / "reading_area_registry.json"
    card = registry.ensure_borrowing_card(
        source_system="mimo",
        canonical_window_id="window-m",
        path=path,
    )["card"]
    first = registry.declare_membership(card_id=card["card_id"], projects=["Time Library"], path=path)
    second = registry.declare_membership(card_id=card["card_id"], projects=["Legacy Time Library"], path=path)

    merged = registry.merge_scope("project", second["project_ids"][0], first["project_ids"][0], path=path)

    assert merged["ok"] is True
    assert registry.resolve_scope_id("project", "Legacy Time Library", path=path) == first["project_ids"][0]
    saved = registry.load_registry(path)
    assert len(saved["merges"]["project"]) == 1
    assert second["project_ids"][0] not in saved["projects"]


def test_known_time_library_aliases_register_one_canonical_project(tmp_path):
    path = tmp_path / "reading_area_registry.json"
    card = registry.ensure_borrowing_card(
        source_system="codex",
        canonical_window_id="known-alias-window",
        path=path,
    )["card"]

    project_ids = []
    for project_name in registry.TIME_LIBRARY_PROJECT_ALIASES:
        membership = registry.declare_membership(
            card_id=card["card_id"],
            projects=[project_name],
            path=path,
        )
        project_ids.extend(membership["project_ids"])

    assert set(project_ids) == {registry.TIME_LIBRARY_CANONICAL_PROJECT_ID}
    saved = registry.load_registry(path)
    assert list(saved["projects"]) == [registry.TIME_LIBRARY_CANONICAL_PROJECT_ID]
    assert saved["projects"][registry.TIME_LIBRARY_CANONICAL_PROJECT_ID]["name"] == "time-library"
    for alias in registry.TIME_LIBRARY_PROJECT_ALIASES:
        assert registry.resolve_scope_id("project", alias, path=path) == registry.TIME_LIBRARY_CANONICAL_PROJECT_ID


def test_rename_to_known_alias_merges_instead_of_creating_ghost(tmp_path):
    path = tmp_path / "reading_area_registry.json"
    card = registry.ensure_borrowing_card(
        source_system="opus",
        canonical_window_id="alias-rename-window",
        path=path,
    )["card"]
    canonical = registry.declare_membership(card_id=card["card_id"], projects=["time-library"], path=path)
    legacy = registry.declare_membership(card_id=card["card_id"], projects=["旧时间库"], path=path)

    renamed = registry.rename_scope("project", legacy["project_ids"][0], "时间图书馆", path=path)

    assert renamed["ok"] is True
    assert renamed["to_id"] == canonical["project_ids"][0]
    saved = registry.load_registry(path)
    assert list(saved["projects"]) == [registry.TIME_LIBRARY_CANONICAL_PROJECT_ID]
    assert registry.resolve_scope_id("project", "旧时间库", path=path) == registry.TIME_LIBRARY_CANONICAL_PROJECT_ID


def test_merge_rewrites_all_scope_bearing_records_without_changing_evidence(tmp_path):
    path = tmp_path / "reading_area_registry.json"
    canonical_id = registry.TIME_LIBRARY_CANONICAL_PROJECT_ID
    ghost_id = "project:legacy-library:0000000001"
    saved = registry.load_registry(path)
    saved["projects"] = {
        canonical_id: {"id": canonical_id, "name": "time-library", "aliases": ["time-library"]},
        ghost_id: {"id": ghost_id, "name": "Legacy Library", "aliases": ["Legacy Library"]},
    }
    saved["aliases"]["project"] = {
        "time-library": canonical_id,
        canonical_id: canonical_id,
        "Legacy Library": ghost_id,
        ghost_id: ghost_id,
    }
    source_ref = {"source_path": "/source/evidence.txt", "verbatim_sha256": "sha-preserved"}
    saved["borrowing_cards"] = {"card:1": {"declared_project_ids": [ghost_id]}}
    saved["borrowing_records"] = [{"record_id": "borrow:1", "project_id": ghost_id, "declared_project_ids": [ghost_id]}]
    saved["whiteboard_records"] = [{"record_id": "WB-1", "declared_project_ids": [ghost_id], "source_ref": source_ref}]
    saved["project_history_records"] = [{
        "record_id": "PH-1",
        "project_id": ghost_id,
        "declared_project_ids": [ghost_id],
        "source_ref": source_ref,
        "verbatim_sha256": "sha-preserved",
    }]
    saved["project_nominations"] = [{"nomination_id": "PN-1", "declared_project_ids": [ghost_id]}]
    registry.save_registry(saved, path)

    result = registry.merge_scope("project", ghost_id, canonical_id, path=path)

    assert result["rewritten_references"] == {
        "borrowing_cards": 1,
        "borrowing_records": 1,
        "whiteboard_records": 1,
        "project_history_records": 1,
        "project_nominations": 1,
    }
    after = registry.load_registry(path)
    for records in (
        after["borrowing_cards"].values(),
        after["borrowing_records"],
        after["whiteboard_records"],
        after["project_history_records"],
        after["project_nominations"],
    ):
        for record in records:
            assert ghost_id not in record.get("declared_project_ids", [])
            assert record.get("project_id", "") != ghost_id
    assert after["whiteboard_records"][0]["source_ref"] == source_ref
    assert after["project_history_records"][0]["source_ref"] == source_ref
    assert after["project_history_records"][0]["verbatim_sha256"] == "sha-preserved"


def test_archive_scope_redirects_history_without_semantic_alias(tmp_path):
    path = tmp_path / "reading_area_registry.json"
    canonical_id = registry.TIME_LIBRARY_CANONICAL_PROJECT_ID
    work_id = "project:retired-work-item:0000000002"
    saved = registry.load_registry(path)
    saved["projects"] = {
        canonical_id: {"id": canonical_id, "name": "time-library", "aliases": ["time-library"]},
        work_id: {"id": work_id, "name": "Retired Work Item", "aliases": ["Retired Work Item"]},
    }
    saved["aliases"]["project"] = {
        "time-library": canonical_id,
        canonical_id: canonical_id,
        "Retired Work Item": work_id,
        work_id: work_id,
    }
    saved["project_history_records"] = [{
        "record_id": "PH-HISTORY-1",
        "project_id": work_id,
        "declared_project_ids": [work_id],
        "source_ref": {"source_path": "/durable/evidence.txt"},
        "verbatim_sha256": "sha-preserved",
    }]
    registry.save_registry(saved, path)

    archived = registry.archive_scope(
        "project",
        work_id,
        canonical_id,
        reason="work item belongs in project history",
        path=path,
    )
    second = registry.archive_scope("project", "Retired Work Item", canonical_id, path=path)

    assert archived["ok"] is True
    assert second["already_archived"] is True
    after = registry.load_registry(path)
    assert work_id not in after["projects"]
    assert "Retired Work Item" not in after["aliases"]["project"]
    assert after["projects"][canonical_id]["aliases"] == ["time-library"]
    assert after["project_history_records"][0]["record_id"] == "PH-HISTORY-1"
    assert after["project_history_records"][0]["project_id"] == canonical_id
    assert after["project_history_records"][0]["source_ref"] == {"source_path": "/durable/evidence.txt"}
    assert after["project_history_records"][0]["verbatim_sha256"] == "sha-preserved"


def test_record_borrowing_tracks_library_ids_and_source_refs_without_content_write(tmp_path):
    path = tmp_path / "reading_area_registry.json"
    card = registry.ensure_borrowing_card(
        source_system="codex",
        canonical_window_id="window-borrow",
        path=path,
    )["card"]
    source_ref = {
        "source_system": "codex",
        "source_path": "raw/session.jsonl",
        "byte_offsets": {"start": 10, "end": 80},
    }

    result = registry.record_borrowing(
        card_id=card["card_id"],
        request_id="req-1",
        library_ids=["ZX-XINGCE-1", "ZX-ZHIYI-2"],
        source_refs=[source_ref],
        path=path,
    )

    assert result["ok"] is True
    receipt = result["borrowing_record"]
    assert receipt["used_library_ids"] == ["ZX-XINGCE-1", "ZX-ZHIYI-2"]
    assert receipt["used_source_refs"] == [source_ref]
    assert receipt["read_only"] is True
    assert receipt["write_performed"] is False
    assert receipt["reading_area_content_write_performed"] is False
    saved = registry.load_registry(path)
    assert saved["borrowing_records"][0]["contract"] == registry.BORROWING_RECORD_CONTRACT
    assert saved["borrowing_cards"][card["card_id"]]["borrowed_library_ids"] == ["ZX-XINGCE-1", "ZX-ZHIYI-2"]


def test_record_borrowing_inherits_declared_reading_area_scope_from_card(tmp_path):
    path = tmp_path / "reading_area_registry.json"
    card = registry.ensure_borrowing_card(
        source_system="opus",
        canonical_window_id="window-scope-borrow",
        path=path,
    )["card"]
    membership = registry.declare_membership(
        card_id=card["card_id"],
        reading_area="Time Library阅读区",
        projects=["Time Library"],
        series=["Shared Reading Series"],
        path=path,
    )

    result = registry.record_borrowing(
        card_id=card["card_id"],
        request_id="req-scope",
        library_ids=["ZX-RAW-1"],
        path=path,
    )

    assert result["ok"] is True
    receipt = result["borrowing_record"]
    assert receipt["reading_area_id"] == ""
    assert receipt["project_id"] == ""
    assert receipt["series_id"] == ""
    assert receipt["declared_reading_area_ids"] == [membership["reading_area_id"]]
    assert receipt["declared_project_ids"] == membership["project_ids"]
    assert receipt["declared_series_ids"] == membership["series_ids"]
    assert receipt["declared_scope_identity_source"] == "borrowing_card_agent_self_report_not_technical_project_id"
    assert receipt["technical_project_id_used_as_declared_identity"] is False
    assert receipt["read_only"] is True
    assert receipt["reading_area_content_write_performed"] is False


def test_record_borrowing_does_not_use_technical_project_id_as_scope(tmp_path):
    path = tmp_path / "reading_area_registry.json"
    card = registry.ensure_borrowing_card(
        source_system="codex",
        canonical_window_id="window-technical-anchor",
        binding={"metadata": {"project_id": "fixture-window-7f60287b"}},
        path=path,
    )["card"]

    result = registry.record_borrowing(
        card_id=card["card_id"],
        request_id="req-technical-anchor",
        library_ids=["ZX-RAW-2"],
        path=path,
    )

    receipt = result["borrowing_record"]
    assert card["technical_anchors"]["project_id"] == "fixture-window-7f60287b"
    assert receipt["project_id"] == ""
    assert receipt["declared_project_ids"] == []
    assert receipt["technical_project_id_used_as_declared_identity"] is False


def test_record_borrowing_preserves_explicit_scope_args_separately_from_declared_lists(tmp_path):
    path = tmp_path / "reading_area_registry.json"
    card = registry.ensure_borrowing_card(
        source_system="codex",
        canonical_window_id="window-explicit-scope",
        path=path,
    )["card"]
    membership = registry.declare_membership(
        card_id=card["card_id"],
        projects=["Time Library"],
        path=path,
    )

    result = registry.record_borrowing(
        card_id=card["card_id"],
        request_id="req-explicit-scope",
        library_ids=["ZX-RAW-3"],
        reading_area_id="explicit-area",
        project_id="explicit-project",
        series_id="explicit-series",
        path=path,
    )

    receipt = result["borrowing_record"]
    assert receipt["reading_area_id"] == "explicit-area"
    assert receipt["project_id"] == "explicit-project"
    assert receipt["series_id"] == "explicit-series"
    assert receipt["declared_project_ids"] == membership["project_ids"]
    assert receipt["technical_project_id_used_as_declared_identity"] is False


def test_registry_summary_counts_borrowing_records_by_declared_scope(tmp_path):
    path = tmp_path / "reading_area_registry.json"
    card = registry.ensure_borrowing_card(
        source_system="opus",
        canonical_window_id="window-summary-scope",
        path=path,
    )["card"]
    membership = registry.declare_membership(
        card_id=card["card_id"],
        reading_area="Time Library阅读区",
        projects=["Time Library"],
        series=["Shared Reading Series"],
        path=path,
    )
    registry.record_borrowing(card_id=card["card_id"], library_ids=["ZX-RAW-1"], request_id="r1", path=path)
    registry.record_borrowing(card_id=card["card_id"], library_ids=["ZX-ZHIYI-1"], request_id="r2", path=path)

    summary = registry.summarize_registry(path)

    assert summary["borrowing_record_count"] == 2
    assert summary["borrowing_records_with_declared_scope_count"] == 2
    assert summary["borrowing_record_scope_counts"]["reading_area"] == {membership["reading_area_id"]: 2}
    assert "project" not in summary["borrowing_record_scope_counts"]
    assert summary["project_scope_borrowing_record_count"] == 2
    assert summary["project_scope_breakdown_policy"] == "aggregate_only_no_project_id_keyed_summary"
    assert summary["borrowing_record_scope_counts"]["series"] == {membership["series_ids"][0]: 2}
    assert summary["write_performed"] is False
    assert summary["reading_area_content_write_performed"] is False


def test_registry_file_shape_is_json_and_reading_area_is_not_sixth_shelf(tmp_path):
    path = tmp_path / "reading_area_registry.json"
    registry.ensure_borrowing_card(
        source_system="codex",
        canonical_window_id="window-json",
        path=path,
    )
    data = json.loads(Path(path).read_text(encoding="utf-8"))

    assert data["_meta"]["contract"] == registry.READING_AREA_REGISTRY_CONTRACT
    assert data["_meta"]["not_a_sixth_shelf"] is True
    assert data["_meta"]["projection_revision"] >= 1
    summary = registry.summarize_registry(path)
    assert summary["not_a_sixth_shelf"] is True
    assert summary["project_identity_source"] == "agent_self_report_not_project_id"


def test_whiteboard_record_is_append_only_and_role_snapshot_is_persisted(tmp_path):
    path = tmp_path / "reading_area_registry.json"
    card = registry.ensure_borrowing_card(
        source_system="codex",
        consumer="codex",
        canonical_window_id="wb-window",
        session_id="wb-session",
        path=path,
    )["card"]
    membership = registry.declare_membership(
        card_id=card["card_id"],
        reading_area="Time Library阅读区",
        projects=["Time Library"],
        series=["Shared Reading Series"],
        roles=["施工"],
        path=path,
    )

    written = registry.write_whiteboard_record(
        borrowing_card_id=card["card_id"],
        record_type="claim_task",
        task_id="whiteboard-alpha",
        task_name="whiteboard block A",
        summary="甲块施工开始，先补底座与角色字段。",
        next_owner="二签",
        request_id="wb-req-1",
        library_ids=["ZX-ZHIYI-1"],
        path=path,
    )

    assert written["ok"] is True
    assert written["whiteboard_registry_write_performed"] is True
    record = written["record"]
    assert record["record_id"].startswith("WB-")
    assert record["record_type"] == "claim_task"
    assert record["status"] == "active"
    assert record["role"] == "施工"
    assert record["declared_project_ids"] == membership["project_ids"]
    assert record["declared_series_ids"] == membership["series_ids"]
    assert record["source_ref"] == {"library_id": "ZX-ZHIYI-1"}

    duplicated = registry.write_whiteboard_record(
        borrowing_card_id=card["card_id"],
        record_type="claim_task",
        task_id="whiteboard-alpha",
        summary="重复调用不应写第二条。",
        request_id="wb-req-1",
        path=path,
    )
    assert duplicated["already_recorded"] is True
    saved = registry.load_registry(path)
    assert len(saved["whiteboard_records"]) == 1


def test_whiteboard_list_uses_declared_scope_and_visible_statuses(tmp_path):
    path = tmp_path / "reading_area_registry.json"
    card = registry.ensure_borrowing_card(
        source_system="opus",
        consumer="opus",
        canonical_window_id="wb-opus-window",
        session_id="wb-opus-session",
        path=path,
    )["card"]
    registry.declare_membership(
        card_id=card["card_id"],
        reading_area="Time Library阅读区",
        projects=["Time Library"],
        series=["Shared Reading Series"],
        roles=["二签"],
        path=path,
    )
    active = registry.write_whiteboard_record(
        borrowing_card_id=card["card_id"],
        record_type="handoff",
        task_id="whiteboard-beta",
        summary="等二签接棒核白板注入。",
        status="handoff",
        role="二签",
        next_owner="二签",
        request_id="wb-req-2",
        path=path,
    )["record"]
    registry.write_whiteboard_record(
        borrowing_card_id=card["card_id"],
        record_type="checkpoint",
        task_id="whiteboard-gamma",
        summary="历史节点不该进默认在飞列表。",
        status="completed",
        role="二签",
        request_id="wb-req-3",
        path=path,
    )

    listed = registry.list_whiteboard_records(
        borrowing_card_id=card["card_id"],
        path=path,
    )

    assert listed["ok"] is True
    assert listed["record_count"] == 1
    assert listed["records"][0]["record_id"] == active["record_id"]
    assert listed["records"][0]["display_line"].startswith("在飞：二签/opus")


def test_project_history_record_is_append_only_evidence_bound_and_not_sixth_shelf(tmp_path):
    path = tmp_path / "reading_area_registry.json"
    source_path = tmp_path / "raw" / "session.jsonl"
    text = "  用户裁定：白板历史从蒸馏中补，进入项目页 history。\n"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text(text, encoding="utf-8")
    card = registry.ensure_borrowing_card(
        source_system="codex",
        consumer="codex",
        canonical_window_id="history-window",
        session_id="history-session",
        path=path,
    )["card"]
    membership = registry.declare_membership(
        card_id=card["card_id"],
        reading_area="Time Library阅读区",
        projects=["Time Library"],
        series=["Shared Reading Series"],
        roles=["施工"],
        path=path,
    )

    written = registry.write_project_history_record(
        borrowing_card_id=card["card_id"],
        history_type="decision",
        title="白板历史从蒸馏中补",
        summary="老项目进入白板后从现在记录，历史由蒸馏回填到项目页。",
        source_refs=[{
            "source_system": "codex",
            "source_path": str(source_path),
            "source_author": "user",
            "byte_offsets": {"start": 0, "end": len(text.encode("utf-8"))},
            "verbatim_excerpt": text,
        }],
        request_id="history-req-1",
        path=path,
    )

    assert written["ok"] is True
    record = written["record"]
    assert record["record_id"].startswith("PH-")
    assert record["contract"] == registry.PROJECT_HISTORY_RECORD_CONTRACT
    assert record["declared_project_ids"] == membership["project_ids"]
    assert record["verbatim_excerpt"] == text
    assert record["source_ref"]["verbatim_excerpt"] == text
    assert record["verbatim_sha256"] == hashlib.sha256(text.encode("utf-8")).hexdigest()
    assert record["source_ref"]["verbatim_sha256"] == record["verbatim_sha256"]
    assert record["not_a_sixth_shelf"] is True

    listed = registry.list_project_history_records(project_ids=membership["project_ids"], path=path)
    assert listed["record_count"] == 1
    assert listed["records"][0]["display_line"].startswith("历史：decision")
    assert registry.summarize_registry(path)["project_history_record_count"] == 1


def test_project_history_temp_source_ref_is_materialized_to_durable_archive(tmp_path):
    path = tmp_path / "reading_area_registry.json"
    temp_root = tmp_path / "var" / "folders" / "session"
    source_path = temp_root / "history-source.txt"
    text = "  用户裁定：项目史证据源不能长期指向临时目录。\n"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text(text, encoding="utf-8")
    card = registry.ensure_borrowing_card(
        source_system="codex",
        consumer="codex",
        canonical_window_id="history-temp-window",
        session_id="history-temp-session",
        path=path,
    )["card"]
    registry.declare_membership(
        card_id=card["card_id"],
        projects=["Time Library"],
        series=["Shared Reading Series"],
        path=path,
    )

    written = registry.write_project_history_record(
        borrowing_card_id=card["card_id"],
        history_type="decision",
        title="项目史证据源必须持久化",
        summary="项目史记录写入时遇到临时 source_ref，要物化到持久 evidence archive。",
        source_refs=[{
            "source_system": "codex",
            "source_path": str(source_path),
            "source_author": "user",
            "byte_offsets": {"start": 0, "end": len(text.encode("utf-8"))},
            "verbatim_excerpt": text,
        }],
        request_id="history-temp-req-1",
        path=path,
    )

    assert written["ok"] is True
    record = written["record"]
    archived_ref = record["source_ref"]
    assert archived_ref["source_path"] != str(source_path)
    assert str(temp_root) not in archived_ref["source_path"]
    assert "/output/project_history_evidence/slices/" in archived_ref["source_path"]
    assert archived_ref["byte_offsets"] == {"start": 0, "end": len(text.encode("utf-8"))}
    assert archived_ref["source_persistence"] == "durable_project_history_evidence_archive"
    assert archived_ref["original_source_ref"]["source_path"] == str(source_path)
    archived_path = Path(archived_ref["source_path"])
    assert archived_path.is_file()
    assert archived_path.read_text(encoding="utf-8") == text
    assert archived_ref["verbatim_sha256"] == hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_materialize_existing_project_history_temp_source_refs_preserves_record_id(tmp_path):
    path = tmp_path / "reading_area_registry.json"
    temp_root = tmp_path / "var" / "folders" / "old-history"
    source_path = temp_root / "history-source.txt"
    text = "  【想象者拍板】旧项目史记录要迁走临时 source_ref。\n"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text(text, encoding="utf-8")
    raw = text.encode("utf-8")
    path.write_text(json.dumps({
        "_meta": {"projection_revision": 1},
        "borrowing_cards": {},
        "reading_areas": {},
        "projects": {},
        "series": {},
        "aliases": {"reading_area": {}, "project": {}, "series": {}},
        "merges": {"reading_area": [], "project": [], "series": []},
        "borrowing_records": [],
        "whiteboard_records": [],
        "project_nominations": [],
        "project_history_records": [{
            "contract": registry.PROJECT_HISTORY_RECORD_CONTRACT,
            "record_id": "PH-OLDTEMP",
            "record_type": "project_history",
            "history_type": "decision",
            "status": "active",
            "title": "旧项目史记录迁移",
            "summary": "旧项目史记录不能继续指向临时目录。",
            "declared_project_ids": ["project:Time Library:1"],
            "declared_series_ids": ["series:Shared Reading Series:1"],
            "project_id": "project:Time Library:1",
            "source_ref": {
                "source_system": "codex",
                "source_path": str(source_path),
                "source_author": "user",
                "byte_offsets": {"start": 0, "end": len(raw)},
                "verbatim_excerpt": text,
                "verbatim_sha256": hashlib.sha256(raw).hexdigest(),
            },
            "evidence_refs": [],
            "verbatim_excerpt": text,
            "verbatim_sha256": hashlib.sha256(raw).hexdigest(),
        }],
    }, ensure_ascii=False), encoding="utf-8")

    result = registry.materialize_project_history_temporary_source_refs(path)

    assert result["ok"] is True
    assert result["materialized_record_ids"] == ["PH-OLDTEMP"]
    saved = registry.load_registry(path)
    record = saved["project_history_records"][0]
    assert record["record_id"] == "PH-OLDTEMP"
    assert record["source_ref"]["source_path"] != str(source_path)
    assert record["source_ref"]["original_source_ref"]["source_path"] == str(source_path)
    assert Path(record["source_ref"]["source_path"]).read_bytes() == raw


def test_project_nomination_requires_claim_before_declared_membership(tmp_path):
    path = tmp_path / "reading_area_registry.json"
    card = registry.ensure_borrowing_card(
        source_system="opus",
        consumer="opus",
        canonical_window_id="nomination-window",
        session_id="nomination-session",
        path=path,
    )["card"]
    nomination = registry.create_project_nomination(
        source_system="opus",
        canonical_window_id="old-window",
        session_id="old-session",
        source_path="/tmp/old-session.jsonl",
        nominated_project="Time Library",
        nominated_series="Shared Reading Series",
        reason="标题和关键词相似，仅作提名。",
        confidence=0.62,
        request_id="nom-1",
        path=path,
    )

    assert nomination["ok"] is True
    saved_card = registry.load_registry(path)["borrowing_cards"][card["card_id"]]
    assert saved_card["declared_project_ids"] == []
    listed = registry.list_project_nominations(path=path)
    assert listed["nomination_count"] == 1
    assert listed["nominations"][0]["status"] == "pending"

    claimed = registry.claim_project_nomination(
        nomination_id=nomination["nomination_id"],
        borrowing_card_id=card["card_id"],
        reading_area="Time Library阅读区",
        roles=["二签"],
        path=path,
    )

    assert claimed["ok"] is True
    assert claimed["declared_membership_written"] is True
    claimed_card = registry.load_registry(path)["borrowing_cards"][card["card_id"]]
    assert claimed["membership_receipt"]["project_ids"][0] in claimed_card["declared_project_ids"]
    assert registry.list_project_nominations(statuses=["claimed"], path=path)["nomination_count"] == 1


def test_reject_project_nomination_is_visible_without_membership_write(tmp_path):
    path = tmp_path / "reading_area_registry.json"
    nomination = registry.create_project_nomination(
        source_system="codex",
        session_id="reject-session",
        nominated_project="另一个项目",
        reason="仅路径相似。",
        path=path,
    )

    rejected = registry.reject_project_nomination(
        nomination_id=nomination["nomination_id"],
        reason="不是同一个项目。",
        path=path,
    )

    assert rejected["ok"] is True
    assert rejected["declared_membership_written"] is False
    listed = registry.list_project_nominations(statuses=["rejected"], path=path)
    assert listed["nomination_count"] == 1
    assert listed["nominations"][0]["reject_reason"] == "不是同一个项目。"
