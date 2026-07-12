import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def test_raw_archive_layout_prefers_computer_source_native_format_order():
    from raw_archive_layout import layout_descriptor, preferred_raw_archive_path

    descriptor = layout_descriptor(
        computer_name="mac-mini",
        source_system="opencode",
        native_format="opencode_session_jsonl",
        native_scope="project-a",
        session_id="session-001",
    )
    path = preferred_raw_archive_path(
        "memory",
        computer_name="mac-mini",
        source_system="opencode",
        native_format="opencode_session_jsonl",
        native_scope="project-a",
        session_id="session-001",
    )

    assert descriptor["contract"] == "raw_archive_layout.v1"
    assert descriptor["read_only"] is True
    assert descriptor["effective_from_version"] == "2026.6.1"
    assert descriptor["new_install_default_layout"] == "computer_first"
    assert descriptor["new_raw_writes_must_use_preferred_layout"] is True
    assert descriptor["preferred_segment_order"] == [
        "computer_name",
        "source_system",
        "native_artifact_format",
    ]
    assert descriptor["primary_partition_key"] == "computer_name"
    assert descriptor["secondary_partition_key"] == "source_system"
    assert "central node" in descriptor["central_node_mode_rationale"]
    assert descriptor["legacy_layout_status"] == "read_compatibility_only"
    assert descriptor["legacy_layout_allowed_for_new_writes"] is False
    assert descriptor["legacy_migration_required_before_read"] is False
    assert str(path) == "memory/mac-mini/opencode/opencode_session_jsonl/project-a/session-001.jsonl"


def test_raw_archive_layout_sanitizes_segments_without_changing_order():
    from raw_archive_layout import preferred_raw_archive_path

    path = preferred_raw_archive_path(
        "memory",
        computer_name="Mac Mini / Desk",
        source_system="Claude Desktop",
        native_format="IndexedDB LevelDB",
        native_scope="Official Login",
        session_id="session/with spaces",
    )

    assert path.parts[:4] == (
        "memory",
        "Mac-Mini-Desk",
        "Claude-Desktop",
        "IndexedDB-LevelDB",
    )


def test_raw_archive_layout_reuses_unique_computer_partition_alias(tmp_path):
    from raw_archive_layout import existing_or_preferred_raw_archive_path, preferred_raw_archive_path

    memory = tmp_path / "memory"
    preferred = preferred_raw_archive_path(
        memory,
        computer_name="renamed-host",
        source_system="codex",
        native_format="codex_session_jsonl",
        native_scope="project-a",
        session_id="session-001",
    )
    existing = memory / "local" / "codex" / "codex_session_jsonl" / "project-a" / "session-001.jsonl"
    existing.parent.mkdir(parents=True)
    existing.write_text("{}\n", encoding="utf-8")

    assert existing_or_preferred_raw_archive_path(memory, preferred) == existing


def test_raw_archive_layout_does_not_guess_between_multiple_computer_partitions(tmp_path):
    from raw_archive_layout import existing_or_preferred_raw_archive_path, preferred_raw_archive_path

    memory = tmp_path / "memory"
    preferred = preferred_raw_archive_path(
        memory,
        computer_name="renamed-host",
        source_system="codex",
        native_format="codex_session_jsonl",
        native_scope="project-a",
        session_id="session-001",
    )
    for computer in ("old-host-a", "old-host-b"):
        existing = memory / computer / "codex" / "codex_session_jsonl" / "project-a" / "session-001.jsonl"
        existing.parent.mkdir(parents=True)
        existing.write_text("{}\n", encoding="utf-8")

    assert existing_or_preferred_raw_archive_path(memory, preferred) == preferred


def test_raw_archive_layout_audit_counts_current_and_legacy_paths(tmp_path):
    from raw_archive_layout import audit_raw_archive_layout

    memory = tmp_path / "memory"
    current = memory / "mac-mini" / "codex" / "codex_session_jsonl" / "project-a" / "s1.jsonl"
    legacy = memory / "codex" / "mac-mini" / "project-a" / "s2.jsonl"
    current.parent.mkdir(parents=True)
    legacy.parent.mkdir(parents=True)
    current.write_text("{}\n", encoding="utf-8")
    legacy.write_text("{}\n", encoding="utf-8")

    audit = audit_raw_archive_layout(memory)

    assert audit["contract"] == "raw_archive_layout_audit.v1"
    assert audit["read_only"] is True
    assert audit["new_raw_writes_must_use_preferred_layout"] is True
    assert audit["legacy_layout_allowed_for_new_writes"] is False
    assert audit["totals"]["computer_first_files"] == 1
    assert audit["totals"]["legacy_source_first_files"] == 1
    assert audit["legacy_present"] is True
    assert audit["by_computer"]["mac-mini"] == 2
    assert audit["by_source_system"]["codex"] == 2
    assert audit["by_native_artifact_format"]["codex_session_jsonl"] == 1
