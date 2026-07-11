import json
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
