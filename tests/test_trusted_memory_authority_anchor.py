from __future__ import annotations

import hashlib
from pathlib import Path

from src.trusted_memory_authority_anchor import (
    TRUSTED_MEMORY_AUTHORITY_ANCHOR_CONTRACT,
    TRUSTED_MEMORY_AUTHORITY_ANCHORS,
    has_trusted_memory_authority_anchor,
    trusted_memory_authority_anchor_items,
    trusted_memory_authority_anchor_query,
)


def test_trusted_memory_authority_anchor_query_is_narrow():
    assert trusted_memory_authority_anchor_query("Trusted Memory 的 recall_only 边界是什么？") is True
    assert trusted_memory_authority_anchor_query("为什么说投影不脱敏？") is True
    assert trusted_memory_authority_anchor_query("今天跑 pytest 哪个文件？") is False


def test_trusted_memory_authority_anchor_items_are_read_only_source_refs(tmp_path):
    authority_file = tmp_path / "memory_authority_policy.py"
    authority_file.write_text(
        "memory_authority_policy: recall_only can read scoped memory. 投影不脱敏。",
        encoding="utf-8",
    )
    anchors = (
        {
            "library_id": "ZX-AUTH-TEST",
            "library_shelf": "errata",
            "source_path": str(authority_file),
            "summary": "fallback summary should not be used when file exists",
            "terms": ("memory_authority_policy", "recall_only", "投影不脱敏"),
        },
    )

    items = trusted_memory_authority_anchor_items(
        query="Trusted Memory recall_only",
        source_system="codex",
        computer_name="local",
        canonical_window_id="window-a",
        session_id="session-a",
        project_id="project-a",
        project_root="/repo",
        workstream_id="work-a",
        task_id="task-a",
        excerpt_chars=120,
        limit=5,
        anchors=anchors,
        created_at="2026-07-01T00:00:00Z",
    )

    assert len(items) == 1
    item = items[0]
    assert item["type"] == "trusted_memory_authority_anchor"
    assert item["library_id"] == "ZX-AUTH-TEST"
    assert item["library_shelf"] == "errata"
    assert item["source_path"] == str(authority_file)
    assert item["raw_excerpt"] == "memory_authority_policy: recall_only can read scoped memory. 投影不脱敏。"
    assert item["raw_evidence_status"] == "raw_authority_file"
    assert item["evidence_hash"] == hashlib.sha256(item["raw_excerpt"].encode("utf-8")).hexdigest()
    assert item["should_inject"] is False
    assert item["zhiyi_experience_used_as_raw"] is False
    assert item["trusted_memory_authority_anchor"] is True
    assert item["required_terms"] == ["memory_authority_policy", "recall_only", "投影不脱敏"]
    assert item["matched_by"] == ["trusted_memory_authority_anchor"]
    assert item["library_index_projection_contract"] == TRUSTED_MEMORY_AUTHORITY_ANCHOR_CONTRACT
    assert item["library_index_projection_policy"] == "project_boundary_source_anchor_only"


def test_trusted_memory_authority_anchor_items_fallback_when_source_missing(tmp_path):
    missing = tmp_path / "missing.md"
    anchors = (
        {
            "library_id": "ZX-AUTH-MISSING",
            "source_path": str(missing),
            "summary": "fallback boundary summary with recall_only",
            "terms": ("recall_only",),
        },
    )

    items = trusted_memory_authority_anchor_items(
        query="recall_only",
        source_system="",
        computer_name="",
        canonical_window_id="",
        session_id="",
        project_id="",
        project_root="",
        workstream_id="",
        task_id="",
        excerpt_chars=20,
        limit=1,
        anchors=anchors,
    )

    assert items[0]["source_system"] == "project_boundary"
    assert items[0]["raw_excerpt"] == "fallback boundary su"
    assert items[0]["raw_evidence_status"] == "authority_anchor_missing_source_file"
    assert items[0]["native_session_key"] == "trusted-memory-authority"


def test_has_trusted_memory_authority_anchor_requires_all_boundary_terms():
    complete = [
        {
            "summary": "memory_authority_policy recall_only 投影不脱敏",
            "required_terms": [
                "299_2026-06-21_TrustedMemory授权模型纠偏",
                "scope_and_queries_required",
            ],
        }
    ]
    incomplete = [
        {
            "summary": "memory_authority_policy recall_only",
            "required_terms": ["scope_and_queries_required"],
        }
    ]

    assert has_trusted_memory_authority_anchor(complete) is True
    assert has_trusted_memory_authority_anchor(incomplete) is False


def test_default_authority_anchors_stay_repo_owned():
    repo_root = Path(__file__).resolve().parents[1]

    assert TRUSTED_MEMORY_AUTHORITY_ANCHORS
    for anchor in TRUSTED_MEMORY_AUTHORITY_ANCHORS:
        source_path = Path(str(anchor["source_path"]))
        assert source_path.is_absolute()
        assert source_path.resolve().is_relative_to(repo_root.resolve())
        assert anchor["library_id"].startswith("ZX-AUTH-")
        assert anchor["terms"]


def test_trusted_memory_authority_anchor_limit_and_annotation(tmp_path):
    anchors = (
        {
            "library_id": "ZX-AUTH-ONE",
            "source_path": str(tmp_path / "one.md"),
            "summary": "memory_authority_policy recall_only",
            "terms": ("memory_authority_policy",),
        },
        {
            "library_id": "ZX-AUTH-TWO",
            "source_path": str(tmp_path / "two.md"),
            "summary": "投影不脱敏",
            "terms": ("投影不脱敏",),
        },
    )

    items = trusted_memory_authority_anchor_items(
        query="memory_authority_policy",
        source_system="codex",
        computer_name="",
        canonical_window_id="",
        session_id="",
        project_id="",
        project_root="",
        workstream_id="",
        task_id="",
        excerpt_chars=120,
        limit=1,
        anchors=anchors,
        annotate_item=lambda item: {**item, "annotated": True},
    )

    assert [item["library_id"] for item in items] == ["ZX-AUTH-ONE"]
    assert items[0]["annotated"] is True
