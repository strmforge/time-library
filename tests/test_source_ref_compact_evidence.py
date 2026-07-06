import json
from pathlib import Path

from src.source_ref_compact_evidence import (
    SOURCE_REF_COMPACT_EVIDENCE_CONTRACT,
    build_compact_evidence_from_source_surface,
    build_source_ref_compact_evidence_probe,
)


def test_source_ref_compact_evidence_reads_bounded_raw_for_model_only(tmp_path, monkeypatch):
    raw_dir = tmp_path / "raw" / "probe_logs"
    raw_dir.mkdir(parents=True)
    raw_file = raw_dir / "delivery.jsonl"
    raw_file.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "id": "m1",
                        "type": "response_item",
                        "payload": {
                            "type": "user_message",
                            "message": "发布完成了吗？",
                        },
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "id": "m2",
                        "type": "response_item",
                        "payload": {
                            "type": "agent_message",
                            "message": "本地候选和测试完成；远端发布回执没有找到。",
                        },
                    },
                    ensure_ascii=False,
                ),
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    item = build_compact_evidence_from_source_surface(
        {
            "library_id": "ZX-ANCHOR",
            "library_shelf": "xingce",
            "source_system": "codex",
            "source_path": "raw/probe_logs/delivery.jsonl",
            "msg_ids": ["m2"],
        },
        excerpt_chars=240,
    )

    assert item["contract"] == SOURCE_REF_COMPACT_EVIDENCE_CONTRACT
    assert item["read_only"] is True
    assert item["write_performed"] is False
    assert item["raw_write_performed"] is False
    assert item["platform_write_performed"] is False
    assert item["model_call_performed"] is False
    assert item["answer_bearing"] == "supporting_context"
    assert "远端发布回执没有找到" in item["text"]
    assert item["raw_excerpt_available_for_internal_model_context"] is True
    assert item["raw_excerpt_exposed"] is False
    assert item["raw_excerpt_exposed_by_default"] is False
    assert item["compact_evidence_for_model_only"] is True
    assert item["raw_authority_policy"] == "raw_source_text_is_highest_authority"
    assert item["summary_policy"] == "summaries_are_navigation_not_source_replacement"
    assert item["summary_may_replace_raw"] is False
    assert "summaries_are_navigation_not_source_replacement" in item["limitations"]
    assert "raw_excerpt" not in item


def test_source_ref_compact_evidence_missing_file_remains_candidate_only(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    item = build_compact_evidence_from_source_surface(
        {
            "library_id": "ZX-MISSING",
            "source_system": "codex",
            "source_path": "raw/probe_logs/missing.jsonl",
        }
    )

    assert item["answer_bearing"] == "candidate_only"
    assert item["raw_evidence_status"] == "missing_source_path"
    assert item["raw_expand_available"] is True
    assert item["raw_excerpt_exposed"] is False
    assert item["summary_policy"] == "summaries_are_navigation_not_source_replacement"
    assert item["summary_may_replace_raw"] is False


def test_source_ref_compact_evidence_probe_summarizes_backtrace_hits(tmp_path, monkeypatch):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    (raw_dir / "session.jsonl").write_text(
        json.dumps({"id": "m1", "type": "human", "content": "记住：search 归本机，think 归模型。"}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    probe = build_source_ref_compact_evidence_probe(
        [
            {
                "library_id": "ZX-1",
                "source_system": "codex",
                "source_path": "raw/session.jsonl",
                "msg_ids": ["m1"],
            }
        ]
    )

    assert probe["contract"] == SOURCE_REF_COMPACT_EVIDENCE_CONTRACT
    assert probe["read_only"] is True
    assert probe["raw_excerpt_exposed"] is False
    assert probe["items_count"] == 1
    assert probe["answer_bearing_items_count"] == 1
    assert probe["raw_backtrace_hits_count"] == 1


def test_source_ref_compact_evidence_source_path_without_anchor_keeps_summary(tmp_path, monkeypatch):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    (raw_dir / "session.jsonl").write_text(
        json.dumps({"type": "human", "content": "无关尾部内容不应该覆盖摘要。"}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    item = build_compact_evidence_from_source_surface(
        {
            "library_id": "ZX-SUMMARY",
            "source_system": "codex",
            "source_path": "raw/session.jsonl",
            "summary": "windows123 provider bucket 修复为 token provider。",
        }
    )

    assert item["answer_bearing"] == "supporting_context"
    assert item["text"] == "windows123 provider bucket 修复为 token provider。"
    assert item["raw_evidence_status"] == "source_anchor_without_precise_msg_or_offset"
    assert item["raw_excerpt_available_for_internal_model_context"] is False


def test_source_ref_compact_evidence_query_slice_keeps_answer_bearing_tail(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    long_summary = (
        "Handoff Summary " + "当前验证摘要没有最终结论。" * 80
        + " 真实结论：windows123 provider bucket custom 对齐 token 后，"
        "codex exec 返回 OK，EXIT=0。"
    )

    item = build_compact_evidence_from_source_surface(
        {
            "library_id": "ZX-LONG",
            "source_system": "codex",
            "summary": long_summary,
        },
        excerpt_chars=180,
        query="windows123 provider bucket custom 对齐 token 后 codex exec OK 的验证结果是什么？",
    )

    assert "windows123 provider bucket custom" in item["text"]
    assert "返回 OK" in item["text"]
    assert "Handoff Summary" not in item["text"]


def test_source_ref_compact_evidence_reads_by_byte_offsets_without_msg_id(tmp_path, monkeypatch):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    first = json.dumps({"id": "m1", "type": "human", "content": "无关内容"}, ensure_ascii=False) + "\n"
    target = json.dumps({"id": "m2", "type": "human", "content": "windows123 bucket 证据来自 byte offset。"}, ensure_ascii=False) + "\n"
    raw_path = raw_dir / "session.jsonl"
    raw_path.write_text(first + target, encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    item = build_compact_evidence_from_source_surface(
        {
            "library_id": "ZX-OFFSET",
            "source_system": "codex",
            "source_path": "raw/session.jsonl",
            "byte_offsets": {"start": len(first.encode("utf-8")), "end": len((first + target).encode("utf-8"))},
        }
    )

    assert item["answer_bearing"] == "supporting_context"
    assert "windows123 bucket" in item["text"]
    assert item["raw_evidence_status"] == "raw_offset"
    assert item["raw_excerpt_available_for_internal_model_context"] is True


def test_source_ref_compact_evidence_query_slices_long_offset_excerpt(tmp_path, monkeypatch):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    first = json.dumps({"id": "m1", "type": "human", "content": "无关内容"}, ensure_ascii=False) + "\n"
    target_text = (
        "Handoff Summary "
        + "当前摘要没有最终验证结果。" * 100
        + " 真实结论：windows123 provider bucket custom 对齐 token 后，"
        "codex exec 返回 OK，EXIT=0。"
    )
    target = json.dumps({"id": "m2", "type": "human", "content": target_text}, ensure_ascii=False) + "\n"
    raw_path = raw_dir / "session.jsonl"
    raw_path.write_text(first + target, encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    item = build_compact_evidence_from_source_surface(
        {
            "library_id": "ZX-OFFSET-LONG",
            "source_system": "codex",
            "source_path": "raw/session.jsonl",
            "byte_offsets": {
                "start": len(first.encode("utf-8")),
                "end": len((first + target).encode("utf-8")),
            },
        },
        excerpt_chars=220,
        query="windows123 provider bucket custom 对齐 token 后 codex exec OK 的验证结果是什么？",
    )

    assert item["answer_bearing"] == "supporting_context"
    assert item["raw_evidence_status"] == "raw_offset"
    assert "windows123 provider bucket custom" in item["text"]
    assert "返回 OK" in item["text"]
    assert "EXIT=0" in item["text"]
    assert "Handoff Summary" not in item["text"]


def test_source_ref_compact_evidence_reads_runtime_memcore_memory_root(tmp_path, monkeypatch):
    memcore_root = tmp_path / "installed-memcore"
    raw_dir = memcore_root / "memory" / "node" / "codex"
    raw_dir.mkdir(parents=True)
    raw_file = raw_dir / "session.jsonl"
    raw_file.write_text(
        json.dumps({"id": "runtime-m1", "type": "human", "content": "运行态安装根 memory 下的 raw 可只读回源。"}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    outside = tmp_path / "outside.jsonl"
    outside.write_text(json.dumps({"type": "human", "content": "不该被读取"}, ensure_ascii=False) + "\n", encoding="utf-8")
    other = tmp_path / "other"
    other.mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(other)

    allowed = build_compact_evidence_from_source_surface(
        {
            "library_id": "ZX-RUNTIME",
            "source_system": "codex",
            "source_path": str(raw_file),
            "msg_ids": ["runtime-m1"],
        },
        memcore_root=str(memcore_root),
    )
    denied = build_compact_evidence_from_source_surface(
        {
            "library_id": "ZX-OUTSIDE",
            "source_system": "codex",
            "source_path": str(outside),
        },
        memcore_root=str(memcore_root),
    )

    assert allowed["answer_bearing"] == "supporting_context"
    assert "运行态安装根 memory" in allowed["text"]
    assert allowed["raw_excerpt_exposed"] is False
    assert denied["answer_bearing"] == "candidate_only"
    assert denied["raw_evidence_status"] == "missing_source_path"
