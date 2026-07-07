import json

from src import reading_area_registry as registry
from src.reading_area_projection import (
    PROJECT_DIGEST_PROJECTION_CONTRACT,
    PROJECT_HISTORY_PROJECTION_CONTRACT,
    READING_AREA_PROJECTION_CONTRACT,
    WHITEBOARD_PROJECTION_CONTRACT,
    build_project_digest_projection,
    build_reading_area_catalog_projection,
)


def _record(
    library_id,
    shelf,
    title,
    source_system,
    *,
    declared_project_ids=None,
    declared_series_ids=None,
    technical_project_id="window-technical-project",
):
    return {
        "_type": f"{shelf}_memory",
        "library_id": library_id,
        "library_shelf": shelf,
        "title": title,
        "summary": f"{title} summary body must not be pushed",
        "detail": "正文 detail must stay pull-only",
        "verbatim_excerpt": "verbatim body must stay pull-only",
        "source_system": source_system,
        "project_id": technical_project_id,
        "declared_project_ids": declared_project_ids or [],
        "declared_series_ids": declared_series_ids or [],
        "source_refs": {
            "source_system": source_system,
            "source_path": f"raw/{library_id}.jsonl",
            "byte_offsets": {"start": 10, "end": 40},
        },
        "lifecycle_status": "active",
    }


def test_reading_area_projection_keeps_five_shelf_sections_and_project_page():
    records = [
        _record("ZX-ZHIYI-1", "zhiyi", "用户偏好短答", "opus", declared_project_ids=["time-library"], declared_series_ids=["private_architecture"]),
        _record("ZX-XINGCE-1", "xingce", "发布前跑完整测试", "codex", declared_project_ids=["time-library"], declared_series_ids=["private_architecture"]),
        _record("ZX-TOOL-1", "toolbook", "9851 是 gateway 端口", "mimo", declared_project_ids=["time-library"], declared_series_ids=["private_architecture"]),
        _record("ZX-RAW-1", "raw", "项目 raw 摘要入口", "codex", declared_project_ids=["time-library"], declared_series_ids=["private_architecture"]),
        _record("ZX-ERRATA-1", "errata", "旧说法已废弃", "opus", declared_project_ids=["time-library"], declared_series_ids=["private_architecture"]),
    ]

    result = build_reading_area_catalog_projection(
        records,
        reading_area_id="time-library-room",
        project_ids=["time-library"],
        series_ids=["private_architecture"],
    )

    assert result["contract"] == READING_AREA_PROJECTION_CONTRACT
    assert result["read_only"] is True
    assert result["write_performed"] is False
    assert result["startup_injection_modified"] is False
    assert result["not_a_sixth_shelf"] is True
    assert set(result["shelf_sections"]) == {"zhiyi", "xingce", "toolbook", "raw", "errata"}
    assert result["shelf_sections"]["zhiyi"]["entry_count"] == 1
    assert result["shelf_sections"]["xingce"]["entry_count"] == 1
    assert result["shelf_sections"]["toolbook"]["entry_count"] == 1
    assert result["shelf_sections"]["raw"]["entry_count"] == 1
    assert result["shelf_sections"]["errata"]["entry_count"] == 1
    assert result["project_page_count"] == 1
    assert result["project_pages"][0]["project_id"] == "time-library"
    assert result["project_pages"][0]["lane_summary_policy"] == "visible_lanes_only_no_body"
    assert result["whiteboard"]["contract"] == WHITEBOARD_PROJECTION_CONTRACT
    lane_summaries = {lane["agent"]: lane for lane in result["project_pages"][0]["visible_lane_summaries"]}
    assert lane_summaries["codex"]["shelf_counts"] == {"xingce": 1, "raw": 1}
    assert "ZX-XINGCE-1" in lane_summaries["codex"]["library_ids"]
    assert "ZX-XINGCE-1" in result["project_pages"][0]["visible_library_id_pull_handles"]
    assert result["project_pages"][0]["omitted_library_id_pull_handles_count"] == 0
    assert result["contains_body_markers"] is False
    assert "正文" not in result["toc_text"]
    assert "verbatim" not in result["toc_text"]


def test_projection_includes_whiteboard_lines_without_becoming_sixth_shelf(tmp_path):
    registry_path = tmp_path / "reading_area_registry.json"
    card = registry.ensure_borrowing_card(
        source_system="codex",
        consumer="codex",
        canonical_window_id="wb-projection-window",
        session_id="wb-projection-session",
        path=registry_path,
    )["card"]
    membership = registry.declare_membership(
        card_id=card["card_id"],
        reading_area="Time Library阅读区",
        projects=["time-library"],
        series=["private_architecture"],
        roles=["施工"],
        path=registry_path,
    )
    first = registry.write_whiteboard_record(
        borrowing_card_id=card["card_id"],
        record_type="claim_task",
        task_id="wb-projection-a",
        task_name="whiteboard block A",
        summary="甲块施工中，准备把交接记录推到开局注入。",
        next_owner="二签",
        request_id="wb-projection-1",
        path=registry_path,
    )["record"]
    registry.write_whiteboard_record(
        borrowing_card_id=card["card_id"],
        record_type="checkpoint",
        task_id="wb-projection-b",
        summary="已完成的历史节点不进默认白板段。",
        status="completed",
        request_id="wb-projection-2",
        path=registry_path,
    )
    records = [
        _record("ZX-ZHIYI-1", "zhiyi", "用户偏好短答", "opus", declared_project_ids=[membership["project_ids"][0]], declared_series_ids=[membership["series_ids"][0]]),
        _record("ZX-XINGCE-1", "xingce", "发布前跑完整测试", "codex", declared_project_ids=[membership["project_ids"][0]], declared_series_ids=[membership["series_ids"][0]]),
    ]

    result = build_reading_area_catalog_projection(
        records,
        reading_area_id=membership["reading_area_id"],
        reading_area_registry_path=str(registry_path),
        project_ids=[membership["project_ids"][0]],
        series_ids=[membership["series_ids"][0]],
    )

    assert result["whiteboard"]["contract"] == WHITEBOARD_PROJECTION_CONTRACT
    assert result["whiteboard"]["record_count"] == 1
    assert result["whiteboard"]["visible_record_ids"] == [first["record_id"]]
    assert result["whiteboard"]["lines"][0].startswith("在飞：施工/codex whiteboard block A")
    assert result["whiteboard"]["char_count"] <= 450
    assert result["shelf_sections"]["zhiyi"]["entry_count"] == 1
    assert result["shelf_sections"]["xingce"]["entry_count"] == 1
    assert "whiteboard" not in result["shelf_sections"]


def test_projection_discovers_project_pages_from_whiteboard_records_when_catalog_has_no_project_records(tmp_path):
    registry_path = tmp_path / "reading_area_registry.json"
    card = registry.ensure_borrowing_card(
        source_system="codex",
        consumer="codex",
        canonical_window_id="wb-only-window",
        session_id="wb-only-session",
        path=registry_path,
    )["card"]
    membership = registry.declare_membership(
        card_id=card["card_id"],
        reading_area="Time Library阅读区",
        projects=["Time Library"],
        series=["Shared Reading Series"],
        roles=["施工"],
        path=registry_path,
    )
    record = registry.write_whiteboard_record(
        borrowing_card_id=card["card_id"],
        record_type="handoff",
        task_id="wb-only-task",
        task_name="whiteboard block A收尾",
        summary="甲块施工完成，交接二签做裸窗复验。",
        next_owner="二签",
        request_id="wb-only-1",
        path=registry_path,
    )["record"]

    result = build_reading_area_catalog_projection(
        [],
        reading_area_registry_path=str(registry_path),
    )

    assert result["project_page_count"] == 1
    assert result["project_pages"][0]["project_id"] == membership["project_ids"][0]
    assert result["whiteboard"]["visible_record_ids"] == [record["record_id"]]
    assert result["whiteboard"]["lines"][0].startswith("在飞：施工/codex whiteboard block A收尾")


def test_projection_discovers_whiteboard_projects_from_loaded_registry(tmp_path, monkeypatch):
    registry_path = tmp_path / "reading_area_registry.json"
    card = registry.ensure_borrowing_card(
        source_system="codex",
        consumer="codex",
        canonical_window_id="wb-loaded-window",
        session_id="wb-loaded-session",
        path=registry_path,
    )["card"]
    membership = registry.declare_membership(
        card_id=card["card_id"],
        reading_area="Time Library阅读区",
        projects=["Time Library"],
        series=["Shared Reading Series"],
        roles=["施工"],
        path=registry_path,
    )
    record = registry.write_whiteboard_record(
        borrowing_card_id=card["card_id"],
        record_type="handoff",
        task_id="wb-loaded-task",
        task_name="whiteboard block A收尾",
        summary="甲块施工完成，交接二签做裸窗复验。",
        next_owner="二签",
        request_id="wb-loaded-1",
        path=registry_path,
    )["record"]

    monkeypatch.setenv("MEMCORE_READING_AREA_REGISTRY", str(registry_path))

    result = build_reading_area_catalog_projection([])

    assert result["project_page_count"] == 1
    assert result["project_pages"][0]["project_id"] == membership["project_ids"][0]
    assert result["project_pages"][0]["whiteboard"]["visible_record_ids"] == [record["record_id"]]


def test_projection_includes_project_history_without_adding_sixth_shelf(tmp_path):
    registry_path = tmp_path / "reading_area_registry.json"
    raw_path = tmp_path / "raw" / "history.jsonl"
    text = "用户裁定：历史从蒸馏中补，项目页显示 history。"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_text(text, encoding="utf-8")
    card = registry.ensure_borrowing_card(
        source_system="codex",
        consumer="codex",
        canonical_window_id="history-projection-window",
        session_id="history-projection-session",
        path=registry_path,
    )["card"]
    membership = registry.declare_membership(
        card_id=card["card_id"],
        reading_area="Time Library阅读区",
        projects=["Time Library"],
        series=["Shared Reading Series"],
        roles=["施工"],
        path=registry_path,
    )
    history = registry.write_project_history_record(
        borrowing_card_id=card["card_id"],
        history_type="decision",
        title="历史从蒸馏中补",
        summary="白板在飞从现在开始，历史由蒸馏补到项目页 history。",
        source_refs=[{
            "source_system": "codex",
            "source_path": str(raw_path),
            "source_author": "user",
            "byte_offsets": {"start": 0, "end": len(text.encode("utf-8"))},
            "verbatim_excerpt": text,
        }],
        request_id="history-projection-1",
        path=registry_path,
    )["record"]

    result = build_reading_area_catalog_projection(
        [],
        reading_area_registry_path=str(registry_path),
        project_ids=membership["project_ids"],
        series_ids=membership["series_ids"],
    )

    assert "project_history" not in result["shelf_sections"]
    assert result["history"]["contract"] == PROJECT_HISTORY_PROJECTION_CONTRACT
    assert result["history"]["visible_record_ids"] == [history["record_id"]]
    assert result["project_pages"][0]["history"]["visible_record_ids"] == [history["record_id"]]
    assert result["contains_body_markers"] is False


def test_project_digest_groups_by_agent_lanes_without_raw_body():
    records = [
        _record("ZX-XINGCE-1", "xingce", "发布前跑完整测试", "codex", declared_project_ids=["time-library"]),
        _record("ZX-ZHIYI-1", "zhiyi", "用户偏好短答", "opus", declared_project_ids=["time-library"]),
        _record("ZX-TOOL-1", "toolbook", "9851 是 gateway 端口", "codex", declared_project_ids=["time-library"]),
    ]

    result = build_project_digest_projection(records, project_id="time-library")

    assert result["contract"] == PROJECT_DIGEST_PROJECTION_CONTRACT
    assert result["read_only"] is True
    assert result["summary_only"] is True
    assert result["contains_body_markers"] is False
    assert result["lane_count"] == 2
    lanes = {lane["agent"]: lane for lane in result["lanes"]}
    assert lanes["codex"]["item_count"] == 2
    assert lanes["opus"]["item_count"] == 1
    assert "ZX-XINGCE-1" in result["library_id_pull_handles"]
    assert "detail" not in result["digest_text"]
    assert "verbatim" not in result["digest_text"]


def test_project_digest_normalizes_claude_code_aliases_into_opus_lane():
    records = [
        _record("ZX-ZHIYI-1", "zhiyi", "中文命名偏好", "claude_code_cli", declared_project_ids=["time-library"]),
        _record("ZX-RAW-1", "raw", "Opus 原始会话", "opus", declared_project_ids=["time-library"]),
        _record("ZX-XINGCE-1", "xingce", "Claude Code 工作经验", "claude_code", declared_project_ids=["time-library"]),
    ]

    result = build_project_digest_projection(records, project_id="time-library")

    assert result["lane_count"] == 1
    lane = result["lanes"][0]
    assert lane["agent"] == "opus"
    assert lane["item_count"] == 3
    assert lane["shelf_counts"]["zhiyi"] == 1
    assert lane["shelf_counts"]["xingce"] == 1
    assert lane["shelf_counts"]["raw"] == 1


def test_project_digest_pull_handles_include_items_beyond_visible_headlines():
    records = [
        _record(f"ZX-XINGCE-{idx}", "xingce", f"行策 {idx}", "codex", declared_project_ids=["time-library"])
        for idx in range(6)
    ]
    records.append(
        _record("ZX-RAW-96A5378C52", "raw", "Codex raw lane", "codex", declared_project_ids=["time-library"])
    )

    result = build_project_digest_projection(records, project_id="time-library", per_agent_limit=5)
    lane = result["lanes"][0]

    assert "ZX-RAW-96A5378C52" not in lane["library_ids"]
    assert "ZX-RAW-96A5378C52" in result["library_id_pull_handles"]
    assert lane["shelf_counts"]["raw"] == 1


def test_reading_area_raw_counts_handles_and_catalog_stay_consistent():
    records = [
        _record(f"ZX-XINGCE-{idx}", "xingce", f"行策 {idx}", "codex", declared_project_ids=["time-library"])
        for idx in range(6)
    ]
    raw_records = [
        _record("ZX-RAW-32C3BFF741", "raw", "Opus raw lane", "opus", declared_project_ids=["time-library"]),
        _record("ZX-RAW-96A5378C52", "raw", "Codex raw lane", "codex", declared_project_ids=["time-library"]),
        _record("ZX-RAW-9CF3546482", "raw", "MiMo raw lane", "mimo", declared_project_ids=["time-library"]),
    ]
    result = build_reading_area_catalog_projection(records + raw_records, project_ids=["time-library"], target_tokens=1200)
    page = result["project_pages"][0]

    catalog_raw_ids = {entry["library_id"] for entry in result["shelf_sections"]["raw"]["entries"]}
    page_raw_handles = {item for item in page["library_id_pull_handles"] if item.startswith("ZX-RAW-")}
    lane_raw_count = sum(
        int(lane.get("shelf_counts", {}).get("raw") or 0)
        for lane in build_project_digest_projection(records + raw_records, project_id="time-library")["lanes"]
    )

    assert result["shelf_sections"]["raw"]["entry_count"] == 3
    assert lane_raw_count == 3
    assert catalog_raw_ids == {"ZX-RAW-32C3BFF741", "ZX-RAW-96A5378C52", "ZX-RAW-9CF3546482"}
    assert page_raw_handles == catalog_raw_ids


def test_project_digest_text_is_bounded_by_target_tokens_without_body():
    records = [
        _record(
            f"ZX-RAW-{idx}",
            "raw",
            f"很长的项目摘要标题 {idx} " + "需要保持轻目录只给编号 " * 12,
            f"agent-{idx}",
            declared_project_ids=["time-library"],
        )
        for idx in range(12)
    ]

    result = build_project_digest_projection(records, project_id="time-library", target_tokens=40)

    assert result["lane_count"] == 12
    assert result["visible_lane_count"] < result["lane_count"]
    assert result["truncated"] is True
    assert result["omitted_lane_count"] > 0
    assert result["token_count"] <= 40
    assert result["over_budget"] is False
    assert result["contains_body_markers"] is False
    assert "正文" not in result["digest_text"]
    assert "verbatim" not in result["digest_text"]


def test_project_page_lane_summaries_follow_visible_lane_budget_without_body():
    records = [
        _record(
            f"ZX-RAW-{idx}",
            "raw",
            f"很长的项目摘要标题 {idx} " + "只保留目录编号 " * 10,
            f"agent-{idx}",
            declared_project_ids=["time-library"],
        )
        for idx in range(40)
    ]

    result = build_reading_area_catalog_projection(records, project_ids=["time-library"], target_tokens=80)
    page = result["project_pages"][0]

    assert page["visible_lane_count"] < page["lane_count"]
    assert len(page["visible_lane_summaries"]) == page["visible_lane_count"]
    assert page["lane_summary_policy"] == "visible_lanes_only_no_body"
    visible_ids = set(page["visible_library_id_pull_handles"])
    all_ids = set(page["library_id_pull_handles"])
    assert visible_ids <= all_ids
    assert page["omitted_library_id_pull_handles_count"] == len(all_ids - visible_ids)
    assert page["omitted_library_id_pull_handles_count"] > 0
    assert all("detail" not in str(lane).lower() for lane in page["visible_lane_summaries"])
    assert all("verbatim" not in str(lane).lower() for lane in page["visible_lane_summaries"])


def test_project_digest_direct_call_does_not_use_technical_project_id():
    records = [
        _record(
            "ZX-XINGCE-1",
            "xingce",
            "技术 project_id 不能当声明项目",
            "codex",
            declared_project_ids=[],
            technical_project_id="time-library",
        ),
    ]

    result = build_project_digest_projection(records, project_id="time-library")

    assert result["lane_count"] == 0
    assert result["library_id_pull_handles"] == []


def test_scope_uses_declared_project_not_technical_project_id():
    records = [
        _record(
            "ZX-XINGCE-1",
            "xingce",
            "应在声明项目下出现",
            "codex",
            declared_project_ids=["time-library"],
            technical_project_id="fixture-window-7f60287b",
        ),
        _record(
            "ZX-XINGCE-2",
            "xingce",
            "只有技术 project_id 不该被纳入",
            "codex",
            declared_project_ids=[],
            technical_project_id="time-library",
        ),
    ]

    result = build_reading_area_catalog_projection(records, project_ids=["time-library"])

    assert result["record_count"] == 1
    assert "应在声明项目下出现" in result["toc_text"]
    assert "只有技术 project_id 不该被纳入" not in result["toc_text"]
    assert result["scope_policy"] == "declared_project_or_series_only_no_technical_project_id_inference"


def test_unscoped_projection_can_show_machine_catalog_without_inference_claim():
    records = [
        _record("ZX-XINGCE-1", "xingce", "无声明时仍可做全机目录样本", "codex", declared_project_ids=[]),
    ]

    result = build_reading_area_catalog_projection(records)

    assert result["record_count"] == 1
    assert result["catalog_entry_count"] == 1
    assert result["project_page_count"] == 0
    assert result["scope_policy"] == "declared_project_or_series_only_no_technical_project_id_inference"


def test_clean_zhiyi_preference_card_can_enter_catalog_projection():
    records = [
        {
            "_type": "preference_memory",
            "type": "preference_memory",
            "library_shelf": "zhiyi",
            "library_id": "ZX-ZHIYI-PREF-1",
            "title": "回答先给结论再给证据",
            "summary": "用户喜欢回答先给结论，再给关键证据。",
            "detail": "正文 detail 不应进入书单。",
            "preference_statement": "用户喜欢回答先给结论，再给关键证据。",
            "when_to_use": "回答复杂问题时",
            "verbatim_excerpt": "我喜欢你回答时先给结论，再给关键证据。",
            "declared_project_ids": ["time-library"],
            "declared_series_ids": ["private_architecture"],
            "source_refs": {
                "source_system": "codex",
                "source_path": "raw/pref.jsonl",
                "byte_offsets": {"start": 1, "end": 40},
            },
            "lifecycle_status": "active",
        }
    ]

    result = build_reading_area_catalog_projection(records, project_ids=["time-library"])

    assert result["shelf_sections"]["zhiyi"]["entry_count"] == 1
    entry = result["shelf_sections"]["zhiyi"]["entries"][0]
    assert entry["library_id"] == "ZX-ZHIYI-PREF-1"
    assert entry["title"] == "回答先给结论再给证据"
    assert "正文 detail" not in result["toc_text"]
    assert result["contains_body_markers"] is False
