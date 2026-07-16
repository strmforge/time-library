import hashlib
import importlib
import json
import os
from pathlib import Path

from src.raw_archive_monotonic import append_jsonl_records, append_source_file


def test_source_truncation_never_shrinks_primary_raw(tmp_path):
    source = tmp_path / "source.jsonl"
    archive = tmp_path / "memory" / "session.jsonl"
    original = b'{"id":"one"}\n{"id":"two"}\n'
    source.write_bytes(original)

    first = append_source_file(source, archive)
    source.write_bytes(b'{"id":"one"}\n')
    second = append_source_file(source, archive)

    assert first["write_performed"] is True
    assert second["status"] == "source_regression_raw_retained"
    assert second["source_regression"] is True
    assert second["write_performed"] is False
    assert second["raw_shrink_performed"] is False
    assert archive.read_bytes() == original


def test_source_growth_appends_only_the_new_tail(tmp_path):
    source = tmp_path / "source.jsonl"
    archive = tmp_path / "memory" / "session.jsonl"
    first_payload = b'{"id":"one"}\n'
    final_payload = first_payload + b'{"id":"two"}\n'
    source.write_bytes(first_payload)
    append_source_file(source, archive)
    source.write_bytes(final_payload)

    result = append_source_file(source, archive)

    assert result["status"] == "appended"
    assert result["bytes_appended"] == len(final_payload) - len(first_payload)
    assert archive.read_bytes() == final_payload


def test_source_prefix_rewrite_is_reported_without_archive_mutation(tmp_path):
    source = tmp_path / "source.jsonl"
    archive = tmp_path / "memory" / "session.jsonl"
    original = b'{"id":"one","text":"original"}\n'
    source.write_bytes(original)
    append_source_file(source, archive)
    source.write_bytes(b'{"id":"one","text":"rewritten"}\n')

    result = append_source_file(source, archive)

    assert result["status"] == "source_divergence_raw_retained"
    assert result["source_divergence"] is True
    assert result["write_performed"] is False
    assert archive.read_bytes() == original


def test_source_deletion_keeps_archive_and_records_regression(tmp_path):
    source = tmp_path / "source.jsonl"
    archive = tmp_path / "memory" / "session.jsonl"
    original = b'{"id":"one"}\n{"id":"two"}\n'
    source.write_bytes(original)
    append_source_file(source, archive)

    source.unlink()
    result = append_source_file(source, archive)

    assert result["status"] == "source_regression_raw_retained"
    assert result["source_missing"] is True
    assert result["source_regression"] is True
    assert result["write_performed"] is False
    assert result["raw_shrink_performed"] is False
    assert result["retained_bytes"] == len(original)
    assert archive.read_bytes() == original


def test_inode_rotation_keeps_old_segment_and_starts_new_segment(tmp_path):
    source = tmp_path / "source.jsonl"
    replacement = tmp_path / "replacement.jsonl"
    archive = tmp_path / "memory" / "session.jsonl"
    original = b'{"id":"one"}\n'
    rotated = b'{"id":"rotated"}\n'
    source.write_bytes(original)
    first_inode = source.stat().st_ino
    first = append_source_file(source, archive, source_inode=first_inode)
    Path(str(archive) + ".meta.json").write_text(
        json.dumps({"source_inode": first_inode}), encoding="utf-8"
    )

    replacement.write_bytes(rotated)
    os.replace(replacement, source)
    second_inode = source.stat().st_ino
    assert second_inode != first_inode

    second = append_source_file(source, archive, source_inode=second_inode)
    segment = Path(second["archive_path"])

    assert first["archive_path"] == str(archive)
    assert second["status"] == "created"
    assert segment.name == "session.seg1.jsonl"
    assert archive.read_bytes() == original
    assert segment.read_bytes() == rotated
    assert Path(str(archive) + ".meta.json").read_text(encoding="utf-8")


def test_local_files_ingest_keeps_raw_history_after_source_delete_and_replacement(tmp_path, monkeypatch):
    connector = importlib.import_module("src.connectors.local_files_connector")
    input_dir = tmp_path / "input"
    raw_dir = tmp_path / "raw"
    index_file = raw_dir / ".source_index.jsonl"
    checkpoint_file = raw_dir / ".checkpoint.json"
    source = input_dir / "notes.txt"
    monkeypatch.setattr(connector, "INPUT_DIR", input_dir)
    monkeypatch.setattr(connector, "RAW_DIR", raw_dir)
    monkeypatch.setattr(connector, "INDEX_FILE", index_file)
    monkeypatch.setattr(connector, "CHECKPOINT_FILE", checkpoint_file)

    source.parent.mkdir(parents=True)
    source.write_text("first source version\n", encoding="utf-8")
    first = connector.ingest(dry_run=False)
    raw_file = raw_dir / f"{hashlib.md5(str(source).encode()).hexdigest()}.jsonl"
    before = raw_file.read_bytes()
    assert first["total_ingested"] == 1

    source.write_text("replacement source version\n", encoding="utf-8")
    second = connector.ingest(dry_run=False)
    after_replacement = raw_file.read_bytes()
    assert second["total_updated"] == 1
    assert len(after_replacement) > len(before)

    source.unlink()
    third = connector.ingest(dry_run=False)
    assert third["total_discovered"] == 0
    assert raw_file.read_bytes() == after_replacement


def test_jsonl_record_source_regression_keeps_existing_records(tmp_path):
    archive = tmp_path / "memory" / "session.jsonl"
    full = [{"id": "one", "text": "first"}, {"id": "two", "text": "second"}]
    first = append_jsonl_records(archive, full)
    before = archive.read_bytes()

    second = append_jsonl_records(archive, full[:1])

    assert first["appended_record_count"] == 2
    assert second["status"] == "source_regression_raw_retained"
    assert second["source_missing_record_count"] == 1
    assert second["write_performed"] is False
    assert archive.read_bytes() == before
    assert [json.loads(line)["id"] for line in archive.read_text().splitlines()] == ["one", "two"]
