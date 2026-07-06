import importlib
import json
import hashlib
import os
import re
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _make_xingce_record(candidate_id, title, work_scenario, source_path, applicable_scope=""):
    return {
        "_type": "xingce_work_experience_candidate",
        "exp_id": candidate_id,
        "library_shelf": "xingce",
        "title": title,
        "summary": f"行策工作经验：{title}",
        "detail": f"详情：{title}",
        "work_scenario": work_scenario,
        "action_strategy": f"策略：{work_scenario}",
        "applicable_scope": applicable_scope or work_scenario,
        "acceptance_checks": ["验证通过"],
        "avoid_conditions": ["避免错误"],
        "source_refs": {
            "source_system": "codex",
            "computer_name": "local",
            "canonical_window_id": "test-window",
            "session_id": f"session-{candidate_id}",
            "source_path": source_path,
            "artifact_type": "codex_session_jsonl",
        },
        "_xingce": {
            "candidate_id": candidate_id,
            "lifecycle_status": "candidate",
        },
        "lifecycle_status": "candidate",
    }


def _make_installed_xingce_record(candidate_id, title, source_path, byte_start=0, byte_end=200):
    """Mimics the shape of a real installed xingce candidate after _xingce_candidate_to_memory.

    source_refs is a dict (from evidence_refs[0]) but evidence_refs is preserved on record.
    applicable_scope is set to window_id fallback (the bug scenario).
    """
    window_id = f"ssh-192-168-50-148-{candidate_id[-6:]}"
    return {
        "_type": "xingce_work_experience_candidate",
        "exp_id": candidate_id,
        "library_shelf": "xingce",
        "title": title,
        "summary": f"行策工作经验：{title}。状态=active usable；证据=2；source_refs=2。evidence-bound，write_boundary false。",
        "detail": f"observed: {title}\nrecommended: 先检查再操作",
        "work_scenario": title,
        "action_strategy": ["先检查再操作", "验证通过后提交"],
        "applicable_scope": f"{window_id} openclaw local",
        "acceptance_checks": ["验证通过"],
        "avoid_conditions": ["避免错误"],
        "evidence_refs": [
            {
                "source_path": source_path,
                "canonical_window_id": window_id,
                "byte_offsets": {"start": byte_start, "end": byte_end},
            },
            {
                "source_path": source_path.replace(".jsonl", "-extra.jsonl"),
                "canonical_window_id": window_id,
            },
        ],
        "source_refs": {
            "source_system": "openclaw",
            "computer_name": "local",
            "canonical_window_id": window_id,
            "source_path": source_path,
            "candidate_path": f"/tmp/candidates/{candidate_id}.json",
        },
        "_xingce": {
            "candidate_id": candidate_id,
            "lifecycle_status": "candidate",
            "action_status": "auto_adopted_evidence_bound",
        },
        "lifecycle_status": "candidate",
    }


def _make_installed_list_source_refs_record(candidate_id, title, source_paths):
    """Mimics raw installed candidate where source_refs is still a list (pre-_xingce_candidate_to_memory)."""
    window_id = f"ssh-192-168-50-148-{candidate_id[-6:]}"
    return {
        "_type": "xingce_work_experience_candidate",
        "exp_id": candidate_id,
        "library_shelf": "xingce",
        "title": title,
        "summary": f"行策工作经验：{title}",
        "detail": f"详情：{title}",
        "work_scenario": title,
        "action_strategy": "先检查再操作",
        "applicable_scope": f"{window_id} openclaw local",
        "acceptance_checks": ["验证通过"],
        "evidence_refs": [
            {
                "source_path": p,
                "canonical_window_id": window_id,
                "byte_offsets": {"start": i * 100, "end": (i + 1) * 100},
            }
            for i, p in enumerate(source_paths)
        ],
        "source_refs": source_paths,
        "_xingce": {
            "candidate_id": candidate_id,
            "lifecycle_status": "candidate",
        },
        "lifecycle_status": "candidate",
    }


def _make_zhiyi_record(exp_id, summary, source_path):
    return {
        "_type": "case_memory",
        "exp_id": exp_id,
        "library_shelf": "zhiyi",
        "title": summary[:30],
        "summary": summary,
        "detail": summary,
        "source_refs": {
            "source_system": "codex",
            "source_path": source_path,
            "canonical_window_id": "test-window",
        },
        "lifecycle_status": "active",
    }


def _make_quarantined_record(candidate_id, title, source_path):
    return {
        "_type": "xingce_work_experience_candidate",
        "exp_id": candidate_id,
        "library_shelf": "xingce",
        "title": title,
        "summary": f"隔离记录：{title}",
        "work_scenario": title,
        "source_refs": {
            "source_system": "codex",
            "source_path": source_path,
        },
        "_xingce": {"candidate_id": candidate_id},
        "lifecycle_status": "candidate",
    }


def _make_errata_record(exp_id, summary, source_path):
    return {
        "_type": "case_memory",
        "exp_id": exp_id,
        "library_shelf": "errata",
        "title": summary[:30],
        "summary": summary,
        "source_refs": {
            "source_system": "codex",
            "source_path": source_path,
        },
        "lifecycle_status": "deprecated",
    }


def _sample_records():
    records = []
    for i in range(10):
        records.append(_make_xingce_record(
            f"candidate-{i:03d}",
            f"行策经验标题{i}",
            f"场景：平台配置问题{i}",
            f"raw/sessions/session-{i:03d}.jsonl",
            f"适用范围：Hermes 平台配置",
        ))
    records.append(_make_zhiyi_record(
        "zhiyi-pref-001",
        "用户偏好：公开文案不要出现内部工具依赖",
        "raw/probe_logs/wording-pref.jsonl",
    ))
    records.append(_make_zhiyi_record(
        "zhiyi-pref-002",
        "用户偏好：代码提交前先跑 lint",
        "raw/probe_logs/lint-pref.jsonl",
    ))
    return records


def _installed_sample_records():
    """7 installed-shape records mimicking real candidate files."""
    titles = [
        "发布前应执行完整测试",
        "Hermes profile config 先查 profile 再改配置",
        "Claude MCP 连接失败时先检查 provider bucket",
        "公开文案不要出现内部工具依赖",
        "代码提交前先跑 lint 和 typecheck",
        "Windows 远程机器 SSH 配置用 repo-local config",
        "忆凡尘施工区路径用京造物理卷名",
    ]
    records = []
    for i, title in enumerate(titles):
        records.append(_make_installed_xingce_record(
            f"ZX-XINGCE-{i:04d}A2F93C",
            title,
            f"raw/sessions/installed-{i:03d}.jsonl",
            byte_start=i * 200,
            byte_end=(i + 1) * 200,
        ))
    return records


# ─── Catalog Push Tests ──────────────────────────────────────────────────


def test_catalog_push_generates_entries_from_records():
    compaction = importlib.import_module("src.context_delivery_compaction")
    records = _sample_records()

    result = compaction.build_library_catalog_push(records, target_tokens=1200)

    assert result["ok"] is True
    assert result["contract"] == "zhixing_catalog_push.v1"
    assert result["read_only"] is True
    assert result["write_performed"] is False
    assert result["entry_count"] >= 7
    assert result["token_count"] > 0
    assert result["token_count"] <= 1200
    assert result["over_budget"] is False
    assert len(result["catalog"]) == result["entry_count"]
    assert result["catalog_text"]
    assert result["index_projection_contract"] == "zhixing_library_index_projection.v1"
    assert result["projection_layer"] == "L0_library_index_projection"
    assert result["library_index_projection"]["not_a_new_memory_layer"] is True
    assert result["library_index_projection"]["record_count"] == len(records)


def test_catalog_push_entry_has_three_piece_set():
    compaction = importlib.import_module("src.context_delivery_compaction")
    records = _sample_records()

    result = compaction.build_library_catalog_push(records, target_tokens=1200)

    for entry in result["catalog"]:
        assert entry["library_id"], "entry must have library_id"
        assert entry["when_to_use"], "entry must have when_to_use"
        assert entry["shelf"], "entry must have shelf"
        assert entry["source_ref"], f"entry {entry['library_id']} must have source_ref"


def test_catalog_push_token_budget_respected():
    compaction = importlib.import_module("src.context_delivery_compaction")
    records = _sample_records()

    result = compaction.build_library_catalog_push(records, target_tokens=800)

    assert result["ok"] is True
    assert result["token_count"] <= 800


def test_catalog_push_trim_preserves_one_handle_per_non_empty_shelf():
    compaction = importlib.import_module("src.context_delivery_compaction")
    records = []
    for i in range(18):
        records.append(_make_zhiyi_record(
            f"zhiyi-pref-{i:03d}",
            f"用户偏好：普通人产品问题要翻译成生活后果{i}",
            f"raw/zhiyi/session-{i:03d}.jsonl",
        ))
    for i in range(18):
        records.append(_make_xingce_record(
            f"candidate-{i:03d}",
            f"行策经验标题{i}",
            f"场景：平台配置问题{i}",
            f"raw/xingce/session-{i:03d}.jsonl",
            f"适用范围：平台配置{i}",
        ))
    records.append({
        "_type": "raw_memory_index",
        "exp_id": "raw-opus-001",
        "library_shelf": "raw",
        "title": "Opus raw lane",
        "summary": "raw lane index",
        "source_refs": {"source_path": "raw/opus.jsonl", "byte_offsets": {"start": 0, "end": 4096}},
        "lifecycle_status": "active",
    })
    records.append({
        "_type": "toolbook_candidate",
        "exp_id": "toolbook-one",
        "library_shelf": "toolbook",
        "title": "macOS 用 Windows App 连接远程桌面",
        "summary": "macOS 用 Windows App 连接远程桌面",
        "observed_behavior": "macOS 用 Windows App 连接远程桌面",
        "source_refs": {"source_path": "raw/toolbook.jsonl", "byte_offsets": {"start": 0, "end": 80}},
        "lifecycle_status": "candidate",
    })
    records.append(_make_errata_record(
        "errata-one",
        "勘误：旧卡锚点误署 user",
        "raw/errata.jsonl",
    ))

    result = compaction.build_library_catalog_push(records, target_tokens=800)

    assert result["ok"] is True
    shelves = {entry["shelf"] for entry in result["catalog"]}
    assert {"zhiyi", "xingce", "raw", "toolbook", "errata"}.issubset(shelves)
    assert result["omitted_shelves"] == []
    for shelf in ("raw", "toolbook", "errata"):
        entry = next(item for item in result["catalog"] if item["shelf"] == shelf)
        assert entry["source_ref"], f"{shelf} handle must remain borrowable"


def test_catalog_push_filters_quarantined_records():
    compaction = importlib.import_module("src.context_delivery_compaction")
    records = _sample_records()
    records.append(_make_quarantined_record(
        "quarantined-001",
        "隔离的旧记录",
        "output/xingce_work_experience/quarantined/old-record.jsonl",
    ))

    result = compaction.build_library_catalog_push(records, target_tokens=1200)

    assert result["ok"] is True
    library_ids = [e["library_id"] for e in result["catalog"]]
    assert not any("quarantined" in lid for lid in library_ids)


def test_catalog_push_includes_errata_records():
    compaction = importlib.import_module("src.context_delivery_compaction")
    records = _sample_records()
    records.append(_make_errata_record(
        "errata-001",
        "已废弃的旧经验",
        "raw/probe_logs/errata-record.jsonl",
    ))

    result = compaction.build_library_catalog_push(records, target_tokens=1200)

    assert result["ok"] is True
    assert any(entry["shelf"] == "errata" for entry in result["catalog"])


def test_catalog_push_filters_superseded_non_errata_records():
    compaction = importlib.import_module("src.context_delivery_compaction")
    records = _sample_records()
    superseded = _make_zhiyi_record(
        "zhiyi-old-001",
        "旧知意卡，已换锚",
        "raw/probe_logs/old-zhiyi.jsonl",
    )
    superseded["lifecycle_status"] = "superseded"
    records.append(superseded)

    result = compaction.build_library_catalog_push(records, target_tokens=1200)

    assert result["ok"] is True
    assert all(entry["library_id"] != "ZX-ZHIYI-OLD-001" for entry in result["catalog"])
    assert not any(entry["title"] == "旧知意卡，已换锚" for entry in result["catalog"])


def test_catalog_push_deduplicates_library_ids():
    compaction = importlib.import_module("src.context_delivery_compaction")
    records = _sample_records()
    dup = _make_xingce_record(
        "candidate-000",
        "重复标题",
        "重复场景",
        "raw/sessions/dup.jsonl",
    )
    records.append(dup)

    result = compaction.build_library_catalog_push(records, target_tokens=1200)

    assert result["ok"] is True
    ids = [e["library_id"] for e in result["catalog"]]
    assert len(ids) == len(set(ids))


def test_catalog_push_xingce_shelf_sorted_first():
    compaction = importlib.import_module("src.context_delivery_compaction")
    records = _sample_records()

    result = compaction.build_library_catalog_push(records, target_tokens=1200)

    assert result["ok"] is True
    first_non_xingce = None
    for entry in result["catalog"]:
        if entry["shelf"] != "xingce":
            first_non_xingce = entry
            break
    if first_non_xingce:
        xingce_count = sum(1 for e in result["catalog"] if e["shelf"] == "xingce")
        assert xingce_count > 0


def test_catalog_push_empty_records_returns_error():
    compaction = importlib.import_module("src.context_delivery_compaction")

    result = compaction.build_library_catalog_push([], target_tokens=1200)
    assert result["ok"] is False
    assert result["error"] == "no_records"

    result2 = compaction.build_library_catalog_push(None, target_tokens=1200)
    assert result2["ok"] is False


# ─── Installed-Shape Catalog Push Tests ──────────────────────────────────


def test_catalog_push_installed_shape_has_headline_in_text():
    compaction = importlib.import_module("src.context_delivery_compaction")
    records = _installed_sample_records()

    result = compaction.build_library_catalog_push(records, target_tokens=2000)

    assert result["ok"] is True
    text = result["catalog_text"]
    for entry in result["catalog"]:
        title = entry["title"]
        assert title, f"entry {entry['library_id']} must have title"
        assert title in text, f"title '{title}' must appear in catalog_text"
    assert "when_to_use:" in text
    assert "source:" in text


def test_catalog_push_installed_shape_source_ref_nonempty():
    compaction = importlib.import_module("src.context_delivery_compaction")
    records = _installed_sample_records()

    result = compaction.build_library_catalog_push(records, target_tokens=2000)

    assert result["ok"] is True
    for entry in result["catalog"]:
        assert entry["source_ref"], \
            f"entry {entry['library_id']} source_ref must be non-empty, got ''"
        ref = entry["source_ref"]
        assert ".jsonl" in ref or ":" in ref, \
            f"source_ref should contain basename or byte offset: {ref}"


def test_catalog_push_installed_shape_when_to_use_not_window_id():
    compaction = importlib.import_module("src.context_delivery_compaction")
    records = _installed_sample_records()

    result = compaction.build_library_catalog_push(records, target_tokens=2000)

    assert result["ok"] is True
    for entry in result["catalog"]:
        wtu = entry["when_to_use"]
        assert "ssh-" not in wtu, f"when_to_use must not contain window id: {wtu}"
        assert "openclaw local" not in wtu.lower(), f"when_to_use must not be window id fallback: {wtu}"
        assert "canonical_window" not in wtu.lower(), f"when_to_use must not be window id: {wtu}"


def test_catalog_push_installed_shape_full_three_piece_set():
    compaction = importlib.import_module("src.context_delivery_compaction")
    records = _installed_sample_records()

    result = compaction.build_library_catalog_push(records, target_tokens=2000)

    assert result["ok"] is True
    assert result["entry_count"] == 7
    text = result["catalog_text"]
    for entry in result["catalog"]:
        assert entry["library_id"], "library_id required"
        assert entry["title"], f"title required for {entry['library_id']}"
        assert entry["when_to_use"], f"when_to_use required for {entry['library_id']}"
        assert entry["source_ref"], f"source_ref required for {entry['library_id']}"
        assert entry["when_to_use"] in text
        assert entry["title"] in text
    assert result["index_projection_contract"] == "zhixing_library_index_projection.v1"
    assert result["projection_layer"] == "L0_library_index_projection"


def test_catalog_push_list_source_refs_extracts_from_evidence():
    compaction = importlib.import_module("src.context_delivery_compaction")
    records = [
        _make_installed_list_source_refs_record(
            "ZX-XINGCE-LIST-001",
            "测试 list source_refs 提取",
            [
                "raw/sessions/session-abc123.jsonl",
                "raw/sessions/session-def456.jsonl",
            ],
        ),
    ]

    result = compaction.build_library_catalog_push(records, target_tokens=1200)

    assert result["ok"] is True
    entry = result["catalog"][0]
    assert entry["source_ref"], "source_ref must be non-empty for list source_refs"
    assert "session-abc123.jsonl" in entry["source_ref"] or "abc123" in entry["source_ref"]


def test_catalog_push_evidence_refs_byte_offsets_in_source_ref():
    compaction = importlib.import_module("src.context_delivery_compaction")
    record = _make_installed_xingce_record(
        "ZX-XINGCE-BYTE-001",
        "byte offset 测试",
        "raw/sessions/byte-test.jsonl",
        byte_start=350,
        byte_end=780,
    )

    result = compaction.build_library_catalog_push([record], target_tokens=1200)

    assert result["ok"] is True
    entry = result["catalog"][0]
    assert "byte-test.jsonl" in entry["source_ref"]
    assert "350" in entry["source_ref"]
    assert "780" in entry["source_ref"]


# ─── Catalog Compaction Tests ────────────────────────────────────────────


def test_catalog_compaction_wraps_catalog():
    compaction = importlib.import_module("src.context_delivery_compaction")
    records = _sample_records()

    catalog = compaction.build_library_catalog_push(records, target_tokens=1200)
    result = compaction.build_catalog_compaction(catalog, target_tokens=1200)

    assert result["ok"] is True
    assert result["contract"] == "zhixing_context_delivery_compaction.v1"
    assert result["dry_run"] is True
    assert result["write_performed"] is False
    candidate = result["candidate"]
    assert candidate["content_profile"]["content_type"] == "catalog_index"
    assert candidate["preservation_policy"]["raw_authority_preserved"] is True


def test_catalog_compaction_rejects_invalid_input():
    compaction = importlib.import_module("src.context_delivery_compaction")

    result = compaction.build_catalog_compaction({"ok": False}, target_tokens=1200)
    assert result["ok"] is False
    assert result["error"] == "invalid_catalog_input"

    result2 = compaction.build_catalog_compaction({}, target_tokens=1200)
    assert result2["ok"] is False


# ─── Catalog Inject Prompt Tests ────────────────────────────────────────


def test_catalog_inject_prompt_generates_system_prompt():
    compaction = importlib.import_module("src.context_delivery_compaction")
    records = _sample_records()

    catalog = compaction.build_library_catalog_push(records, target_tokens=1200)
    result = compaction.build_catalog_inject_prompt(catalog)

    assert result["ok"] is True
    assert result["should_inject"] is True
    assert result["contract"] == "zhixing_catalog_push.v1"
    assert result["read_only"] is True
    assert result["write_performed"] is False
    assert "library_id" in result["system_prompt"]
    assert "when_to_use" in result["system_prompt"]
    assert result["entry_count"] >= 7
    assert result["token_count"] > 0


def test_catalog_inject_prompt_uses_time_library_public_name():
    compaction = importlib.import_module("src.context_delivery_compaction")
    records = _sample_records()

    catalog = compaction.build_library_catalog_push(records, target_tokens=1200)
    result = compaction.build_catalog_inject_prompt(catalog)

    prompt = result["system_prompt"]
    assert "Time Library / 忆凡尘" in prompt
    assert "本机忆凡尘图书馆" not in prompt
    assert "知意" not in prompt


def test_catalog_inject_prompt_has_headline_format():
    compaction = importlib.import_module("src.context_delivery_compaction")
    records = _installed_sample_records()

    catalog = compaction.build_library_catalog_push(records, target_tokens=2000)
    result = compaction.build_catalog_inject_prompt(catalog)

    assert result["ok"] is True
    prompt = result["system_prompt"]
    assert "when_to_use:" in prompt
    assert "| source:" in prompt
    for entry in catalog["catalog"]:
        assert entry["title"] in prompt, f"headline '{entry['title']}' must appear in inject prompt"


def test_catalog_inject_prompt_rejects_empty_catalog():
    compaction = importlib.import_module("src.context_delivery_compaction")

    result = compaction.build_catalog_inject_prompt({"ok": True, "catalog": []})
    assert result["ok"] is False
    assert result["should_inject"] is False

    result2 = compaction.build_catalog_inject_prompt({"ok": False})
    assert result2["ok"] is False


# ─── End-to-End Push Path (p4_inject) ────────────────────────────────────


def test_build_catalog_inject_end_to_end():
    p4 = importlib.import_module("src.p4_inject")
    records = _sample_records()

    result = p4.build_catalog_inject(records, target_tokens=1200)

    assert result["ok"] is True
    assert result["should_inject"] is True
    assert result["system_prompt"]
    assert result["catalog_entry_count"] >= 7
    assert result["catalog_token_count"] > 0
    assert result["catalog_token_count"] <= 1200
    assert result["inject_token_count"] > 0
    assert result["target_tokens"] == 1200
    assert result["catalog_contract"] == "zhixing_catalog_push.v1"


def test_build_catalog_inject_installed_shape_end_to_end():
    p4 = importlib.import_module("src.p4_inject")
    records = _installed_sample_records()

    result = p4.build_catalog_inject(records, target_tokens=2000)

    assert result["ok"] is True
    assert result["should_inject"] is True
    assert result["catalog_entry_count"] == 7
    prompt = result["system_prompt"]
    assert "发布前应执行完整测试" in prompt
    assert "when_to_use:" in prompt


def test_build_catalog_inject_handles_empty_records():
    p4 = importlib.import_module("src.p4_inject")

    result = p4.build_catalog_inject([], target_tokens=1200)

    assert result["ok"] is False
    assert result["should_inject"] is False


def test_p4_provider_catalog_inject_from_candidates_temp_root():
    """P4 runtime endpoint helper builds startup catalog without window binding."""
    p4_provider = importlib.import_module("src.p4_provider")
    zhixing = importlib.import_module("src.zhixing_library")
    candidate_id = "xingce-test-provider-catalog-001"

    with tempfile.TemporaryDirectory() as tmp:
        candidates_dir = os.path.join(tmp, "output", "xingce_work_experience", "candidates")
        actions_dir = os.path.join(tmp, "output", "xingce_work_experience", "actions")
        os.makedirs(candidates_dir)
        os.makedirs(actions_dir)

        candidate = {
            "candidate_id": candidate_id,
            "candidate_type": "xingce_work_experience",
            "lifecycle_status": "candidate",
            "title": "发布前应执行完整测试",
            "work_scenario": "发布前收口",
            "summary": "正文不应进入 catalog",
            "detail": "这是正文 detail，不应进入 catalog 书单",
            "observed_facts": ["正文事实不应进入 catalog"],
            "recommended_procedure": ["正文步骤不应进入 catalog"],
            "verification_steps": ["全量测试通过"],
            "evidence_refs": [
                {
                    "source_path": "raw/sessions/test-provider.jsonl",
                    "canonical_window_id": "test-window",
                    "byte_offsets": {"start": 10, "end": 80},
                }
            ],
            "source_refs": ["raw/sessions/test-provider.jsonl"],
        }
        with open(os.path.join(candidates_dir, f"{candidate_id}-candidate.json"), "w", encoding="utf-8") as f:
            json.dump(candidate, f, ensure_ascii=False)

        with open(os.path.join(actions_dir, "2026-07-01-action.jsonl"), "w", encoding="utf-8") as f:
            json.dump({
                "candidate_id": candidate_id,
                "action_status": "auto_adopted_evidence_bound",
                "action_id": "action-001",
            }, f, ensure_ascii=False)
            f.write("\n")

        result = p4_provider.build_catalog_inject_from_candidates(target_tokens=1200, xingce_root=tmp)

        assert result["ok"] is True
        assert result["should_inject"] is True
        assert result["no_window_binding_required"] is True
        assert result["catalog_entry_count"] == 1
        assert result["catalog_token_count"] <= 1200
        assert result["contains_body_markers"] is False
        assert "Time Library / 忆凡尘" in result["system_prompt"]
        assert "发布前应执行完整测试" in result["catalog_text"]
        assert "这是正文 detail" not in result["catalog_text"]
        assert "正文步骤" not in result["catalog_text"]
        assert result["catalog"][0]["library_id"].startswith("ZX-XINGCE-")
        assert result["catalog"][0]["source_ref"] == "test-provider.jsonl:10-80"

        card = zhixing.fetch_library_card_by_id_from_candidates(
            result["catalog"][0]["library_id"],
            xingce_root=tmp,
        )
        assert card
        assert card["library_id"] == result["catalog"][0]["library_id"]


def test_p4_provider_catalog_card_from_candidates_temp_root():
    """P4 runtime pull helper lets a bare consumer borrow a true card by library_id."""
    p4_provider = importlib.import_module("src.p4_provider")
    zhixing = importlib.import_module("src.zhixing_library")
    candidate_id = "xingce-test-provider-card-001"

    with tempfile.TemporaryDirectory() as tmp:
        candidates_dir = os.path.join(tmp, "output", "xingce_work_experience", "candidates")
        actions_dir = os.path.join(tmp, "output", "xingce_work_experience", "actions")
        raw_dir = os.path.join(tmp, "raw", "sessions")
        os.makedirs(candidates_dir)
        os.makedirs(actions_dir)
        os.makedirs(raw_dir)
        raw_path = os.path.join(raw_dir, "card-provider.jsonl")
        raw_prefix = "prefix:"
        raw_excerpt = "明白，那 Windows 线我改成只测 VM 的纯官方环境。"
        with open(raw_path, "w", encoding="utf-8") as f:
            f.write(raw_prefix + raw_excerpt + ":suffix")
        start = len(raw_prefix.encode("utf-8"))
        end = start + len(raw_excerpt.encode("utf-8"))

        candidate = {
            "candidate_id": candidate_id,
            "candidate_type": "xingce_work_experience",
            "lifecycle_status": "candidate",
            "title": "隔离测试环境用纯净 VM",
            "work_scenario": "宿主机测试被污染",
            "summary": "蒸馏摘要不应冒充逐字证据",
            "detail": "蒸馏详情不应冒充逐字证据",
            "verbatim_excerpt": raw_excerpt,
            "verbatim_sha256": hashlib.sha256(raw_excerpt.encode("utf-8")).hexdigest(),
            "evidence_refs": [
                {
                    "source_path": raw_path,
                    "canonical_window_id": "test-window",
                    "byte_offsets": {"start": start, "end": end},
                    "verbatim_sha256": hashlib.sha256(raw_excerpt.encode("utf-8")).hexdigest(),
                }
            ],
            "source_refs": [raw_path],
        }
        with open(os.path.join(candidates_dir, f"{candidate_id}-candidate.json"), "w", encoding="utf-8") as f:
            json.dump(candidate, f, ensure_ascii=False)
        with open(os.path.join(actions_dir, "2026-07-01-action.jsonl"), "w", encoding="utf-8") as f:
            json.dump({
                "candidate_id": candidate_id,
                "action_status": "auto_adopted_evidence_bound",
                "action_id": "action-001",
            }, f, ensure_ascii=False)
            f.write("\n")

        memory = p4_provider.load_catalog_candidate_records(xingce_root=tmp)[0]
        library_id = zhixing.library_id_for(memory)
        result = p4_provider.fetch_catalog_card_by_library_id(library_id, xingce_root=tmp)

        assert result["ok"] is True
        assert result["read_only"] is True
        assert result["write_performed"] is False
        assert result["no_window_binding_required"] is True
        assert result["library_id"] == library_id
        assert result["card"]["library_id"] == library_id
        assert result["source_refs"].get("source_path") == raw_path
        assert result["verbatim_excerpt"] == raw_excerpt
        assert result["card"]["verbatim_excerpt"] == raw_excerpt
        assert result["card"]["verbatim_sha256"] == hashlib.sha256(raw_excerpt.encode("utf-8")).hexdigest()
        assert "蒸馏摘要" not in result["verbatim_excerpt"]
        assert "蒸馏详情" not in result["verbatim_excerpt"]
        assert result["raw_source_excerpt_status"] == "ok"
        assert result["raw_source_excerpt"] == raw_excerpt
        assert result["raw_source_excerpt_ref"]["byte_offsets"] == {"start": start, "end": end}


def test_p4_provider_catalog_loads_zhiyi_preference_candidates_temp_root():
    """Zhiyi accepted candidates enter the same naked startup catalog and can be borrowed."""
    p4_provider = importlib.import_module("src.p4_provider")
    zhixing = importlib.import_module("src.zhixing_library")
    candidate_id = "zhiyi-distill-owner-accepted-001"

    with tempfile.TemporaryDirectory() as tmp:
        candidates_dir = os.path.join(tmp, "output", "zhiyi_preference_cards", "candidates")
        raw_dir = os.path.join(tmp, "raw", "sessions")
        os.makedirs(candidates_dir)
        os.makedirs(raw_dir)
        raw_path = os.path.join(raw_dir, "zhiyi-card.jsonl")
        prefix = "prefix:"
        raw_excerpt = "我把这个新的模式取名为阅读区和raw一样不能修改只读，多窗口进入为多人阅读区"
        with open(raw_path, "w", encoding="utf-8") as f:
            f.write(prefix + raw_excerpt + ":suffix")
        start = len(prefix.encode("utf-8"))
        end = start + len(raw_excerpt.encode("utf-8"))

        candidate = {
            "candidate_id": candidate_id,
            "candidate_type": "zhiyi_preference_card",
            "library_shelf": "zhiyi",
            "type": "preference_memory",
            "source_mode": "evidence_bound_model_distill",
            "lifecycle_status": "active",
            "title": "阅读区模式保持只读",
            "summary": "新的阅读区模式应与raw模式相同，保持只读不可修改，多窗口进入时为多人阅读区",
            "preference_statement": "新的阅读区模式应与raw模式相同，保持只读不可修改，多窗口进入时为多人阅读区",
            "when_to_use": "设计阅读区或多人共读区时",
            "verbatim_excerpt": raw_excerpt,
            "source_author": "user",
            "source_role": "user",
            "source_refs": {
                "source_path": raw_path,
                "source_role": "user",
                "byte_offsets": {"start": start, "end": end},
            },
            "evidence_refs": [
                {
                    "source_path": raw_path,
                    "source_role": "user",
                    "byte_offsets": {"start": start, "end": end},
                }
            ],
        }
        with open(os.path.join(candidates_dir, f"{candidate_id}.json"), "w", encoding="utf-8") as f:
            json.dump(candidate, f, ensure_ascii=False)

        records = p4_provider.load_catalog_candidate_records(xingce_root=tmp)
        assert len(records) == 1
        attached = zhixing.attach_library_card(records[0])
        library_id = attached["library_id"]
        assert library_id.startswith("ZX-ZHIYI-")

        result = p4_provider.build_catalog_inject_from_candidates(target_tokens=1200, xingce_root=tmp)
        assert result["ok"] is True
        assert result["catalog_entry_count"] == 1
        assert result["catalog"][0]["shelf"] == "zhiyi"
        assert result["catalog"][0]["library_id"] == library_id
        assert result["catalog"][0]["when_to_use"] == "设计阅读区或多人共读区时"
        assert result["catalog"][0]["source_ref"] == f"zhiyi-card.jsonl:{start}-{end}"
        assert "阅读区模式保持只读" in result["catalog_text"]
        assert raw_excerpt not in result["catalog_text"]

        pulled = p4_provider.fetch_catalog_card_by_library_id(library_id, xingce_root=tmp)
        assert pulled["ok"] is True
        assert pulled["card"]["library_id"] == library_id
        assert pulled["card"]["shelf"] == "zhiyi"
        assert pulled["raw_source_excerpt_status"] == "ok"
        assert pulled["raw_source_excerpt"] == raw_excerpt


def test_p4_provider_catalog_omits_superseded_zhiyi_candidates_temp_root():
    p4_provider = importlib.import_module("src.p4_provider")
    zhixing = importlib.import_module("src.zhixing_library")

    with tempfile.TemporaryDirectory() as tmp:
        candidates_dir = os.path.join(tmp, "output", "zhiyi_preference_cards", "candidates")
        raw_dir = os.path.join(tmp, "raw", "sessions")
        os.makedirs(candidates_dir)
        os.makedirs(raw_dir)
        raw_path = os.path.join(raw_dir, "zhiyi-card.jsonl")
        raw_excerpt = "一致不等于印证"
        with open(raw_path, "w", encoding="utf-8") as f:
            f.write(raw_excerpt)
        for candidate_id, lifecycle_status in (
            ("zhiyi-active", "active"),
            ("zhiyi-superseded", "superseded"),
        ):
            candidate = {
                "candidate_id": candidate_id,
                "candidate_type": "zhiyi_preference_card",
                "library_shelf": "zhiyi",
                "type": "preference_memory",
                "source_mode": "evidence_bound_model_distill",
                "lifecycle_status": lifecycle_status,
                "title": candidate_id,
                "summary": candidate_id,
                "preference_statement": candidate_id,
                "verbatim_excerpt": raw_excerpt,
                "source_author": "user",
                "source_role": "user",
                "source_refs": {
                    "source_path": raw_path,
                    "source_role": "user",
                    "byte_offsets": {"start": 0, "end": len(raw_excerpt.encode("utf-8"))},
                },
            }
            with open(os.path.join(candidates_dir, f"{candidate_id}.json"), "w", encoding="utf-8") as f:
                json.dump(candidate, f, ensure_ascii=False)

        records = p4_provider.load_catalog_candidate_records(xingce_root=tmp)

        assert [record["candidate_id"] for record in records] == ["zhiyi-active"]
        all_records = zhixing.load_file_backed_library_candidate_records(xingce_root=tmp, include_inactive=True)
        superseded_id = zhixing.library_id_for(next(record for record in all_records if record["candidate_id"] == "zhiyi-superseded"))
        pulled = p4_provider.fetch_catalog_card_by_library_id(superseded_id, xingce_root=tmp)
        assert pulled["ok"] is True
        assert pulled["card"]["status"] == "superseded"


def test_catalog_card_omits_invalid_toolbook_candidates_temp_root():
    p4_provider = importlib.import_module("src.p4_provider")
    zhixing = importlib.import_module("src.zhixing_library")

    with tempfile.TemporaryDirectory() as tmp:
        candidates_dir = os.path.join(tmp, "output", "toolbook_platform_facts", "candidates")
        raw_dir = os.path.join(tmp, "raw", "sessions")
        os.makedirs(candidates_dir)
        os.makedirs(raw_dir)
        raw_path = os.path.join(raw_dir, "toolbook.jsonl")
        raw_excerpt = "box-shadow: 0 4px 24px rgba(59, 130, 246, 0.08);"
        with open(raw_path, "w", encoding="utf-8") as f:
            f.write(raw_excerpt)
        candidate = {
            "candidate_id": "toolbook-invalid-css",
            "candidate_type": "toolbook_candidate",
            "library_shelf": "toolbook",
            "type": "toolbook_candidate",
            "source_mode": "evidence_bound_p2_extract",
            "lifecycle_status": "invalid",
            "title": "box-shadow: 0 4px 24px rgba(59, 130, 246, 0.08)",
            "summary": raw_excerpt,
            "verbatim_excerpt": raw_excerpt,
            "source_author": "assistant",
            "source_role": "assistant",
            "source_refs": {
                "source_path": raw_path,
                "source_role": "assistant",
                "byte_offsets": {"start": 0, "end": len(raw_excerpt.encode("utf-8"))},
            },
        }
        with open(os.path.join(candidates_dir, "toolbook-invalid-css.json"), "w", encoding="utf-8") as f:
            json.dump(candidate, f, ensure_ascii=False)

        library_id = zhixing.library_id_for(dict(candidate, _type="toolbook_candidate", exp_id="toolbook-invalid-css"))

        assert p4_provider.load_catalog_candidate_records(xingce_root=tmp) == []
        pulled = p4_provider.fetch_catalog_card_by_library_id(library_id, xingce_root=tmp)
        assert pulled["ok"] is False
        assert pulled["error"] == "library_card_not_found"


def test_catalog_card_refuses_source_excerpt_outside_allowed_roots():
    """library_id pull must not turn source_refs into arbitrary local file reads."""
    p4_provider = importlib.import_module("src.p4_provider")
    zhixing = importlib.import_module("src.zhixing_library")
    candidate_id = "zhiyi-distill-owner-blocked-source"

    with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside:
        candidates_dir = os.path.join(tmp, "output", "zhiyi_preference_cards", "candidates")
        os.makedirs(candidates_dir)
        blocked_path = os.path.join(outside, "secret.txt")
        secret = "secret should not leak"
        with open(blocked_path, "w", encoding="utf-8") as f:
            f.write(secret)
        candidate = {
            "candidate_id": candidate_id,
            "candidate_type": "zhiyi_preference_card",
            "library_shelf": "zhiyi",
            "type": "preference_memory",
            "source_mode": "evidence_bound_model_distill",
            "lifecycle_status": "active",
            "title": "blocked source path",
            "summary": "blocked source path",
            "preference_statement": "blocked source path",
            "when_to_use": "path safety regression",
            "verbatim_excerpt": secret,
            "source_author": "user",
            "source_role": "user",
            "source_refs": {
                "source_path": blocked_path,
                "source_role": "user",
                "byte_offsets": {"start": 0, "end": len(secret)},
            },
        }
        with open(os.path.join(candidates_dir, f"{candidate_id}.json"), "w", encoding="utf-8") as f:
            json.dump(candidate, f, ensure_ascii=False)

        records = p4_provider.load_catalog_candidate_records(xingce_root=tmp)
        library_id = zhixing.attach_library_card(records[0])["library_id"]
        pulled = p4_provider.fetch_catalog_card_by_library_id(library_id, xingce_root=tmp)

        assert pulled["ok"] is True
        assert pulled["raw_source_excerpt_status"] == "source_path_not_allowed"
        assert pulled["raw_source_excerpt"] == ""


def test_p4_provider_reading_area_catalog_requires_declared_membership():
    """Technical project_id alone must not create a reading-area project page."""
    p4_provider = importlib.import_module("src.p4_provider")
    candidate_id = "xingce-reading-area-001"

    with tempfile.TemporaryDirectory() as tmp:
        candidates_dir = os.path.join(tmp, "output", "xingce_work_experience", "candidates")
        actions_dir = os.path.join(tmp, "output", "xingce_work_experience", "actions")
        raw_dir = os.path.join(tmp, "raw", "sessions", "ssh-192-168-50-148-7f60287b")
        os.makedirs(candidates_dir)
        os.makedirs(actions_dir)
        os.makedirs(raw_dir)
        raw_path = os.path.join(raw_dir, "session.jsonl")
        with open(raw_path, "w", encoding="utf-8") as f:
            f.write("发布前应执行完整测试")
        candidate = {
            "candidate_id": candidate_id,
            "candidate_type": "xingce_work_experience",
            "lifecycle_status": "candidate",
            "title": "发布前应执行完整测试",
            "work_scenario": "发布前验证",
            "summary": "发布前验证摘要",
            "detail": "正文不应进目录",
            "evidence_refs": [
                {
                    "source_path": raw_path,
                    "canonical_window_id": "ssh-192-168-50-148-7f60287b",
                    "byte_offsets": {"start": 0, "end": 30},
                }
            ],
            "source_refs": [raw_path],
            # This is deliberately a technical anchor, not declared identity.
            "project_id": "time-library",
        }
        with open(os.path.join(candidates_dir, f"{candidate_id}-candidate.json"), "w", encoding="utf-8") as f:
            json.dump(candidate, f, ensure_ascii=False)
        with open(os.path.join(actions_dir, "2026-07-01-action.jsonl"), "w", encoding="utf-8") as f:
            json.dump({
                "candidate_id": candidate_id,
                "action_status": "auto_adopted_evidence_bound",
                "action_id": "action-001",
            }, f, ensure_ascii=False)
            f.write("\n")

        result = p4_provider.build_reading_area_catalog_from_candidates(
            xingce_root=tmp,
            project_ids=["time-library"],
        )

        assert result["ok"] is True
        assert result["record_count"] == 0
        assert result["project_page_count"] == 1
        assert result["project_pages"][0]["lane_count"] == 0
        assert result["technical_project_id_used_as_declared_identity"] is False


def test_p4_provider_reading_area_catalog_uses_borrowing_card_declaration():
    """A declared borrowing card can scope matching window records into a project page."""
    p4_provider = importlib.import_module("src.p4_provider")
    window_registry = importlib.import_module("src.window_binding_registry")
    candidate_id = "xingce-reading-area-002"

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        xingce_root = tmp_path / "memcore"
        candidates_dir = xingce_root / "output" / "xingce_work_experience" / "candidates"
        actions_dir = xingce_root / "output" / "xingce_work_experience" / "actions"
        raw_dir = xingce_root / "raw" / "sessions" / "ssh-192-168-50-148-7f60287b"
        candidates_dir.mkdir(parents=True)
        actions_dir.mkdir(parents=True)
        raw_dir.mkdir(parents=True)
        raw_path = raw_dir / "session.jsonl"
        raw_path.write_text("发布前应执行完整测试", encoding="utf-8")
        candidate = {
            "candidate_id": candidate_id,
            "candidate_type": "xingce_work_experience",
            "lifecycle_status": "candidate",
            "title": "发布前应执行完整测试",
            "work_scenario": "发布前验证",
            "summary": "发布前验证摘要",
            "detail": "正文不应进目录",
            "evidence_refs": [
                {
                    "source_path": str(raw_path),
                    "canonical_window_id": "ssh-192-168-50-148-7f60287b",
                    "byte_offsets": {"start": 0, "end": 30},
                }
            ],
            "source_refs": [str(raw_path)],
        }
        (candidates_dir / f"{candidate_id}-candidate.json").write_text(json.dumps(candidate, ensure_ascii=False), encoding="utf-8")
        with (actions_dir / "2026-07-01-action.jsonl").open("w", encoding="utf-8") as f:
            json.dump({
                "candidate_id": candidate_id,
                "action_status": "auto_adopted_evidence_bound",
                "action_id": "action-001",
            }, f, ensure_ascii=False)
            f.write("\n")

        window_path = tmp_path / "window_binding_registry.json"
        reading_path = tmp_path / "reading_area_registry.json"
        window_registry.register_current_window(
            source_system="codex",
            consumer="codex",
            canonical_window_id="019e44e4-d1dc-7362-9e1d-6c6feab5e53d",
            session_id="019e44e4-d1dc-7362-9e1d-6c6feab5e53d",
            metadata={
                "project_id": "ssh-192-168-50-148-7f60287b",
                "project_root": "/Users/example/Documents/Codex/2026-05-20/ssh-192-168-50-148",
            },
            path=window_path,
        )

        membership = p4_provider.declare_reading_area_membership_for_current_window(
            "codex",
            consumer="codex",
            reading_area="忆凡尘阅读区",
            projects=["time-library"],
            series=["honghuang"],
            window_registry_path=str(window_path),
            reading_area_registry_path=str(reading_path),
        )
        result = p4_provider.build_reading_area_catalog_from_candidates(
            xingce_root=str(xingce_root),
            reading_area_registry_path=str(reading_path),
            project_ids=["time-library"],
            series_ids=["honghuang"],
        )

        assert membership["ok"] is True
        assert membership["technical_project_id_used_as_declared_identity"] is False
        assert result["ok"] is True
        assert result["record_count"] == 1
        assert result["project_page_count"] == 1
        assert result["project_pages"][0]["lane_count"] == 1
        assert result["contains_body_markers"] is False
        assert result["technical_project_id_used_as_declared_identity"] is False
        assert result["borrowing_scope_meta"]["matched_record_count"] == 1


def test_p4_provider_reading_area_catalog_can_include_declared_raw_session_lane():
    """Raw shallow index can light a second agent lane without distillation."""
    p4_provider = importlib.import_module("src.p4_provider")
    window_registry = importlib.import_module("src.window_binding_registry")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        xingce_root = tmp_path / "memcore"
        candidates_dir = xingce_root / "output" / "xingce_work_experience" / "candidates"
        actions_dir = xingce_root / "output" / "xingce_work_experience" / "actions"
        raw_dir = xingce_root / "raw" / "sessions" / "codex-window"
        candidates_dir.mkdir(parents=True)
        actions_dir.mkdir(parents=True)
        raw_dir.mkdir(parents=True)
        raw_path = raw_dir / "session.jsonl"
        raw_path.write_text("发布前应执行完整测试", encoding="utf-8")
        candidate_id = "xingce-reading-area-with-raw"
        candidate = {
            "candidate_id": candidate_id,
            "candidate_type": "xingce_work_experience",
            "lifecycle_status": "candidate",
            "title": "发布前应执行完整测试",
            "summary": "发布前验证摘要",
            "evidence_refs": [
                {
                    "source_path": str(raw_path),
                    "canonical_window_id": "codex-window",
                    "byte_offsets": {"start": 0, "end": 30},
                }
            ],
            "source_refs": [str(raw_path)],
        }
        (candidates_dir / f"{candidate_id}-candidate.json").write_text(json.dumps(candidate, ensure_ascii=False), encoding="utf-8")
        with (actions_dir / "2026-07-01-action.jsonl").open("w", encoding="utf-8") as f:
            json.dump({"candidate_id": candidate_id, "action_status": "auto_adopted_evidence_bound"}, f, ensure_ascii=False)
            f.write("\n")

        records_db = tmp_path / "records.db"
        con = sqlite3.connect(records_db)
        con.execute(
            """
            create table canonical_sessions (
                record_id text primary key, source_system text not null,
                session_id text, raw_artifact_id text, canonical_window_id text,
                project_id text, project_root text, thread_name text,
                source_path text, raw_path text, source_mtime text, raw_mtime text,
                source_size_bytes integer, raw_size_bytes integer,
                source_line_count integer, raw_line_count integer,
                indexed_message_count integer, indexed_chunk_count integer,
                raw_indexed_message_count integer, raw_offset_coverage_count integer,
                bad_json_line_count integer, oversized_line_count integer,
                index_status text, updated_at text, payload_json text
            )
            """
        )
        con.execute(
            """
            create table canonical_messages (
                message_id text primary key, record_id text not null,
                source_system text not null, session_id text, canonical_window_id text,
                project_id text, project_root text, source_path text, raw_path text,
                role text, native_type text, native_id text, timestamp text,
                line_no integer, raw_line_no integer, source_offset_start integer,
                source_offset_end integer, raw_offset_start integer, raw_offset_end integer,
                content_chars integer, content_hash text, line_hash text,
                content_preview text, raw_available integer, updated_at text,
                payload_json text
            )
            """
        )
        claude_source = tmp_path / "claude" / "opus-session.jsonl"
        title_text = "我把这个新的模式取名为阅读区和raw一样不能修改只读，多窗口进入为多人阅读区"
        prefix = "prefix:"
        claude_source.parent.mkdir(parents=True)
        claude_source.write_text(prefix + title_text + ":suffix\n", encoding="utf-8")
        start = len(prefix.encode("utf-8"))
        end = start + len(title_text.encode("utf-8"))
        con.execute(
            """
            insert into canonical_sessions values (
                ?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?
            )
            """,
            (
                "record-opus",
                "claude_code_cli",
                "opus-session",
                "opus-session",
                "opus-session",
                "technical-project",
                "/tmp/project",
                "Opus reading area design",
                str(claude_source),
                str(tmp_path / "missing-raw.jsonl"),
                "2026-07-01T00:00:00Z",
                "",
                claude_source.stat().st_size,
                0,
                1,
                0,
                1,
                1,
                0,
                0,
                0,
                0,
                "raw_missing",
                "2026-07-01T00:00:00Z",
                "{}",
            ),
        )
        payload = {"source_line": {"role": "user", "content": title_text, "offset_start": start, "offset_end": end}}
        con.execute(
            """
            insert into canonical_messages values (
                ?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?
            )
            """,
            (
                "msg-opus",
                "record-opus",
                "claude_code_cli",
                "opus-session",
                "opus-session",
                "technical-project",
                "/tmp/project",
                str(claude_source),
                str(tmp_path / "missing-raw.jsonl"),
                "user",
                "user",
                "msg-opus",
                "2026-07-01T00:00:00Z",
                1,
                0,
                start,
                end,
                None,
                None,
                len(title_text),
                "hash",
                "linehash",
                title_text,
                0,
                "2026-07-01T00:00:00Z",
                json.dumps(payload, ensure_ascii=False),
            ),
        )
        con.commit()
        con.close()

        window_path = tmp_path / "window_binding_registry.json"
        reading_path = tmp_path / "reading_area_registry.json"
        window_registry.register_current_window(
            source_system="codex",
            consumer="codex",
            canonical_window_id="codex-window",
            session_id="codex-window",
            metadata={"project_id": "technical-codex"},
            path=window_path,
        )
        codex_membership = p4_provider.declare_reading_area_membership_for_current_window(
            "codex",
            consumer="codex",
            reading_area="忆凡尘阅读区",
            projects=["time-library"],
            series=["honghuang"],
            window_registry_path=str(window_path),
            reading_area_registry_path=str(reading_path),
        )
        opus_card = importlib.import_module("src.reading_area_registry").ensure_borrowing_card(
            source_system="claude_code_cli",
            consumer="opus",
            canonical_window_id="opus-session",
            session_id="opus-session",
            path=reading_path,
        )["card"]
        opus_membership = importlib.import_module("src.reading_area_registry").declare_membership(
            card_id=opus_card["card_id"],
            reading_area="忆凡尘阅读区",
            projects=["time-library"],
            series=["honghuang"],
            path=reading_path,
        )

        result = p4_provider.build_reading_area_catalog_from_candidates(
            xingce_root=str(xingce_root),
            reading_area_registry_path=str(reading_path),
            records_db_path=str(records_db),
            include_raw_index=True,
            project_ids=codex_membership["project_ids"],
            series_ids=opus_membership["series_ids"],
        )

        assert result["ok"] is True
        assert result["raw_index"]["record_count"] == 1
        assert result["raw_index"]["title_model_used"] is False
        assert result["shelf_sections"]["raw"]["entry_count"] == 1
        assert result["project_page_count"] == 1
        page = result["project_pages"][0]
        assert page["lane_count"] == 2
        assert "opus" in page["digest"]
        assert "Opus reading area design" in page["digest"]
        assert result["contains_body_markers"] is False
        assert result["technical_project_id_used_as_declared_identity"] is False
        raw_library_id = result["shelf_sections"]["raw"]["entries"][0]["library_id"]
        pulled = p4_provider.fetch_catalog_card_by_library_id(
            raw_library_id,
            xingce_root=str(xingce_root),
            reading_area_registry_path=str(reading_path),
            records_db_path=str(records_db),
            include_raw_index=True,
            project_ids=codex_membership["project_ids"],
            series_ids=opus_membership["series_ids"],
        )
        assert pulled["ok"] is True
        assert pulled["card"]["shelf"] == "raw"
        assert pulled["raw_source_excerpt_status"] == "ok"
        assert title_text in pulled["raw_source_excerpt"]
        assert pulled["raw_index"]["title_model_used"] is False


def test_catalog_inject_includes_declared_raw_session_lane_by_default():
    """Startup catalog push should carry the read-only raw lane, not only xingce."""
    p4_provider = importlib.import_module("src.p4_provider")
    window_registry = importlib.import_module("src.window_binding_registry")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        xingce_root = tmp_path / "memcore"
        candidates_dir = xingce_root / "output" / "xingce_work_experience" / "candidates"
        actions_dir = xingce_root / "output" / "xingce_work_experience" / "actions"
        raw_dir = xingce_root / "raw" / "sessions" / "codex-window"
        candidates_dir.mkdir(parents=True)
        actions_dir.mkdir(parents=True)
        raw_dir.mkdir(parents=True)
        raw_path = raw_dir / "session.jsonl"
        raw_path.write_text("发布前应执行完整测试", encoding="utf-8")
        candidate_id = "xingce-startup-with-raw"
        candidate = {
            "candidate_id": candidate_id,
            "candidate_type": "xingce_work_experience",
            "lifecycle_status": "candidate",
            "title": "发布前应执行完整测试",
            "summary": "发布前验证摘要",
            "evidence_refs": [
                {
                    "source_path": str(raw_path),
                    "canonical_window_id": "codex-window",
                    "byte_offsets": {"start": 0, "end": 30},
                }
            ],
            "source_refs": [str(raw_path)],
        }
        (candidates_dir / f"{candidate_id}-candidate.json").write_text(json.dumps(candidate, ensure_ascii=False), encoding="utf-8")
        with (actions_dir / "2026-07-01-action.jsonl").open("w", encoding="utf-8") as f:
            json.dump({"candidate_id": candidate_id, "action_status": "auto_adopted_evidence_bound"}, f, ensure_ascii=False)
            f.write("\n")

        records_db = tmp_path / "records.db"
        con = sqlite3.connect(records_db)
        con.execute(
            """
            create table canonical_sessions (
                record_id text primary key, source_system text not null,
                session_id text, raw_artifact_id text, canonical_window_id text,
                project_id text, project_root text, thread_name text,
                source_path text, raw_path text, source_mtime text, raw_mtime text,
                source_size_bytes integer, raw_size_bytes integer,
                source_line_count integer, raw_line_count integer,
                indexed_message_count integer, indexed_chunk_count integer,
                raw_indexed_message_count integer, raw_offset_coverage_count integer,
                bad_json_line_count integer, oversized_line_count integer,
                index_status text, updated_at text, payload_json text
            )
            """
        )
        con.execute(
            """
            create table canonical_messages (
                message_id text primary key, record_id text not null,
                source_system text not null, session_id text, canonical_window_id text,
                project_id text, project_root text, source_path text, raw_path text,
                role text, native_type text, native_id text, timestamp text,
                line_no integer, raw_line_no integer, source_offset_start integer,
                source_offset_end integer, raw_offset_start integer, raw_offset_end integer,
                content_chars integer, content_hash text, line_hash text,
                content_preview text, raw_available integer, updated_at text,
                payload_json text
            )
            """
        )
        claude_source = tmp_path / "claude" / "opus-session.jsonl"
        title_text = "阅读区只给目录和编号，正文按需借阅"
        prefix = "prefix:"
        claude_source.parent.mkdir(parents=True)
        claude_source.write_text(prefix + title_text + ":suffix\n", encoding="utf-8")
        start = len(prefix.encode("utf-8"))
        end = start + len(title_text.encode("utf-8"))
        con.execute(
            "insert into canonical_sessions values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "record-opus",
                "claude_code_cli",
                "opus-session",
                "opus-session",
                "opus-session",
                "technical-project",
                "/tmp/project",
                "Opus reading area design",
                str(claude_source),
                str(tmp_path / "missing-raw.jsonl"),
                "2026-07-01T00:00:00Z",
                "",
                claude_source.stat().st_size,
                0,
                1,
                0,
                1,
                1,
                0,
                0,
                0,
                0,
                "raw_missing",
                "2026-07-01T00:00:00Z",
                "{}",
            ),
        )
        payload = {"source_line": {"role": "user", "content": title_text, "offset_start": start, "offset_end": end}}
        con.execute(
            "insert into canonical_messages values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "msg-opus",
                "record-opus",
                "claude_code_cli",
                "opus-session",
                "opus-session",
                "technical-project",
                "/tmp/project",
                str(claude_source),
                str(tmp_path / "missing-raw.jsonl"),
                "user",
                "user",
                "msg-opus",
                "2026-07-01T00:00:00Z",
                1,
                0,
                start,
                end,
                None,
                None,
                len(title_text),
                "hash",
                "linehash",
                title_text,
                0,
                "2026-07-01T00:00:00Z",
                json.dumps(payload, ensure_ascii=False),
            ),
        )
        con.commit()
        con.close()

        window_path = tmp_path / "window_binding_registry.json"
        reading_path = tmp_path / "reading_area_registry.json"
        window_registry.register_current_window(
            source_system="codex",
            consumer="codex",
            canonical_window_id="codex-window",
            session_id="codex-window",
            metadata={"project_id": "technical-codex"},
            path=window_path,
        )
        p4_provider.declare_reading_area_membership_for_current_window(
            "codex",
            consumer="codex",
            reading_area="忆凡尘阅读区",
            projects=["time-library"],
            series=["honghuang"],
            window_registry_path=str(window_path),
            reading_area_registry_path=str(reading_path),
        )
        opus_card = importlib.import_module("src.reading_area_registry").ensure_borrowing_card(
            source_system="claude_code_cli",
            consumer="opus",
            canonical_window_id="opus-session",
            session_id="opus-session",
            path=reading_path,
        )["card"]
        reading_registry = importlib.import_module("src.reading_area_registry")
        opus_membership = reading_registry.declare_membership(
            card_id=opus_card["card_id"],
            reading_area="忆凡尘阅读区",
            projects=["time-library"],
            series=["honghuang"],
            path=reading_path,
        )

        result = p4_provider.build_catalog_inject_from_candidates(
            xingce_root=str(xingce_root),
            reading_area_registry_path=str(reading_path),
            records_db_path=str(records_db),
        )

        assert result["ok"] is True
        assert result["reading_area_raw_index"]["record_count"] == 1
        assert result["reading_area_raw_index"]["title_model_used"] is False
        assert result["reading_area_projection"]["project_pages"][0]["lane_count"] == 2
        assert result["startup_instruction_mode"] == "reading_area_lanes_only"
        assert result["flat_catalog_prompt_omitted"] is True
        assert result["instructions_char_count"] <= result["startup_instructions_char_budget"] <= 1500
        assert result["system_prompt"].startswith("Time Library / 忆凡尘 阅读区")
        assert "项目页" in result["system_prompt"]
        assert "lanes=2" in result["system_prompt"]
        assert "opus" in result["system_prompt"]
        assert "Opus reading area design" in result["system_prompt"]
        assert "馆藏书单" not in result["system_prompt"]
        assert "| source:" not in result["system_prompt"]
        assert "opus-session.jsonl:0-" not in result["system_prompt"]
        assert "阅读区只给目录和编号，正文按需借阅" not in result["system_prompt"]
        assert result["reading_area_block_token_count"] > 0
        assert result["system_prompt_token_count"] == result["reading_area_block_token_count"]
        assert result["reading_area_contains_body_markers"] is False
        visible_ids = set(re.findall(r"\[(ZX-[A-Z]+-[A-Z0-9]+)\]", result["system_prompt"]))
        structured_ids = {entry["library_id"] for entry in result["catalog"]}
        assert visible_ids <= structured_ids, "every startup-visible library_id must keep a structured source_ref entry"
        raw_entries = [entry for entry in result["catalog"] if entry.get("shelf") == "raw"]
        assert len(raw_entries) == 1
        raw_entry = raw_entries[0]
        assert raw_entry["library_id"].startswith("ZX-RAW-")
        assert raw_entry["source_ref"], "startup structured catalog must expose a raw source_ref handle"
        assert "opus-session.jsonl" in raw_entry["source_ref"]
        assert f"{start}-{end}" in raw_entry["source_ref"]

        def _records_db_counts():
            db_con = sqlite3.connect(records_db)
            try:
                return {
                    "canonical_sessions": db_con.execute("select count(*) from canonical_sessions").fetchone()[0],
                    "canonical_messages": db_con.execute("select count(*) from canonical_messages").fetchone()[0],
                }
            finally:
                db_con.close()

        counts_before_pull = _records_db_counts()
        naked_pull = p4_provider.fetch_catalog_card_by_library_id(
            raw_entry["library_id"],
            xingce_root=str(xingce_root),
            reading_area_registry_path=str(reading_path),
            records_db_path=str(records_db),
        )
        assert naked_pull["ok"] is True
        assert naked_pull["read_only"] is True
        assert naked_pull["write_performed"] is False
        assert naked_pull["card"]["shelf"] == "raw"
        assert naked_pull["source_refs"]["source_path"] == str(claude_source)
        assert naked_pull["raw_source_excerpt_status"] == "ok"
        returned_offsets = naked_pull["source_refs"]["byte_offsets"]
        expected_bytes = claude_source.read_bytes()[returned_offsets["start"]:returned_offsets["end"]]
        expected_sha = hashlib.sha256(expected_bytes).hexdigest()
        assert naked_pull["raw_source_excerpt"] == expected_bytes.decode("utf-8")
        assert naked_pull["verbatim_excerpt_status"] == "ok"
        assert naked_pull["verbatim_excerpt"] == naked_pull["raw_source_excerpt"]
        assert naked_pull["verbatim_sha256"] == expected_sha
        assert naked_pull["card"]["verbatim_excerpt"] == naked_pull["raw_source_excerpt"]
        assert naked_pull["card"]["verbatim_sha256"] == expected_sha
        assert naked_pull["card"]["evidence_contract"]["required"]["verbatim_excerpt"] is True
        assert "verbatim_excerpt" not in naked_pull["card"]["evidence_contract"]["missing_fields"]
        assert naked_pull["catalog_card_projection_meta"]["verbatim_sha256_projected"] is True
        assert naked_pull["source_ref_status"] == "available"
        assert naked_pull["raw_available"] is True
        assert title_text in naked_pull["raw_source_excerpt"]
        assert naked_pull["raw_source_excerpt_ref"] == {
            "source_path": str(claude_source),
            "byte_offsets": returned_offsets,
        }
        assert naked_pull["raw_index"]["title_model_used"] is False
        assert _records_db_counts() == counts_before_pull

        second_pull = p4_provider.fetch_catalog_card_by_library_id(
            raw_entry["library_id"],
            xingce_root=str(xingce_root),
            reading_area_registry_path=str(reading_path),
            records_db_path=str(records_db),
        )
        assert second_pull["ok"] is True
        assert set(second_pull.keys()) == set(naked_pull.keys())
        assert second_pull["read_only"] is True
        assert second_pull["write_performed"] is False
        assert second_pull["raw_source_excerpt"] == naked_pull["raw_source_excerpt"]
        assert second_pull["raw_source_excerpt_ref"] == naked_pull["raw_source_excerpt_ref"]
        assert second_pull["verbatim_sha256"] == naked_pull["verbatim_sha256"]
        assert _records_db_counts() == counts_before_pull
        assert reading_registry.load_registry(reading_path)["borrowing_records"] == []

        skipped_record = p4_provider.fetch_catalog_card_by_library_id(
            raw_entry["library_id"],
            xingce_root=str(xingce_root),
            reading_area_registry_path=str(reading_path),
            records_db_path=str(records_db),
            record_borrowing=True,
            request_id="req-missing-card",
            consumer="codex",
        )
        assert skipped_record["ok"] is True
        assert skipped_record["borrowing_record_requested"] is True
        assert skipped_record["borrowing_record_written"] is False
        assert skipped_record["borrowing_record_status"] == "skipped_missing_borrowing_card_id"
        assert reading_registry.load_registry(reading_path)["borrowing_records"] == []

        recorded_pull = p4_provider.fetch_catalog_card_by_library_id(
            raw_entry["library_id"],
            xingce_root=str(xingce_root),
            reading_area_registry_path=str(reading_path),
            records_db_path=str(records_db),
            record_borrowing=True,
            borrowing_card_id=opus_card["card_id"],
            request_id="req-opus-raw-borrow",
            consumer="codex",
        )
        assert recorded_pull["ok"] is True
        assert recorded_pull["read_only"] is True
        assert recorded_pull["write_performed"] is False
        assert recorded_pull["borrowing_record_written"] is True
        assert recorded_pull["borrowing_registry_write_performed"] is True
        assert recorded_pull["reading_area_content_write_performed"] is False
        receipt = recorded_pull["borrowing_record_receipt"]["borrowing_record"]
        assert receipt["used_library_ids"] == [raw_entry["library_id"]]
        assert receipt["declared_project_ids"] == opus_membership["project_ids"]
        assert receipt["declared_series_ids"] == opus_membership["series_ids"]
        assert receipt["technical_project_id_used_as_declared_identity"] is False
        assert receipt["read_only"] is True
        assert receipt["write_performed"] is False
        assert receipt["reading_area_content_write_performed"] is False
        assert any(ref.get("source_path") == str(claude_source) for ref in receipt["used_source_refs"] if isinstance(ref, dict))
        saved_registry = reading_registry.load_registry(reading_path)
        assert saved_registry["borrowing_records"][-1]["request_id"] == "req-opus-raw-borrow"
        assert raw_entry["library_id"] in saved_registry["borrowing_cards"][opus_card["card_id"]]["borrowed_library_ids"]
        assert _records_db_counts() == counts_before_pull


def test_reading_area_prompt_block_keeps_raw_handles_without_inline_sources():
    p4_provider = importlib.import_module("src.p4_provider")

    projection = {
        "ok": True,
        "project_page_count": 1,
        "shelf_sections": {
            "zhiyi": {"entry_count": 2, "entries": []},
            "xingce": {
                "entry_count": 7,
                "entries": [
                    {"library_id": "ZX-XINGCE-1", "title": "发布前应执行完整测试"},
                ],
            },
            "raw": {
                "entry_count": 3,
                "entries": [
                    {"library_id": "ZX-RAW-32C3BFF741", "title": "Opus lane", "source_ref": "f2.jsonl:0-4096"},
                    {"library_id": "ZX-RAW-96A5378C52", "title": "Codex lane", "source_ref": "codex.jsonl:0-4096"},
                    {"library_id": "ZX-RAW-9CF3546482", "title": "MiMo lane", "source_ref": "checkpoint.md:0-4096"},
                ],
            },
            "toolbook": {"entry_count": 0, "entries": []},
            "errata": {"entry_count": 0, "entries": []},
        },
        "project_pages": [
            {
                "project_id": "project:time-library:03657f57bf",
                "lane_count": 3,
                "library_id_pull_handles": [
                    "ZX-RAW-32C3BFF741",
                    "ZX-RAW-9CF3546482",
                    "ZX-XINGCE-1",
                ],
                "visible_lane_summaries": [
                    {
                        "agent": "codex",
                        "item_count": 8,
                        "shelf_counts": {"xingce": 7, "raw": 1},
                        "library_ids": ["ZX-XINGCE-1"],
                    },
                    {
                        "agent": "opus",
                        "item_count": 1,
                        "shelf_counts": {"raw": 1},
                        "library_ids": ["ZX-RAW-32C3BFF741"],
                    },
                    {
                        "agent": "mimo",
                        "item_count": 1,
                        "shelf_counts": {"raw": 1},
                        "library_ids": ["ZX-RAW-9CF3546482"],
                    },
                ],
            }
        ],
        "startup_catalog": {
            "ok": True,
            "catalog": [
                {"library_id": "ZX-XINGCE-1", "shelf": "xingce", "title": "发布前应执行完整测试", "when_to_use": "收口", "source_ref": "x1.jsonl:0-10"},
                {"library_id": "ZX-RAW-32C3BFF741", "shelf": "raw", "title": "Opus lane", "when_to_use": "Opus lane", "source_ref": "f2.jsonl:0-4096"},
                {"library_id": "ZX-RAW-96A5378C52", "shelf": "raw", "title": "Codex lane", "when_to_use": "Codex lane", "source_ref": "codex.jsonl:0-4096"},
                {"library_id": "ZX-RAW-9CF3546482", "shelf": "raw", "title": "MiMo lane", "when_to_use": "MiMo lane", "source_ref": "checkpoint.md:0-4096"},
            ],
        },
    }

    prompt = p4_provider._reading_area_prompt_block(projection)

    assert len(prompt) <= p4_provider.STARTUP_INSTRUCTIONS_CHAR_BUDGET
    assert prompt.startswith("Time Library / 忆凡尘 阅读区")
    assert "项目页 project:time-library:03657f57bf lanes=3" in prompt
    assert "ZX-RAW-32C3BFF741" in prompt
    assert "ZX-RAW-96A5378C52" in prompt
    assert "ZX-RAW-9CF3546482" in prompt
    assert "checkpoint.md:0-4096" not in prompt
    assert "codex.jsonl:0-4096" not in prompt
    assert "source:" not in prompt
    assert "[truncated]" not in prompt


def test_startup_catalog_keeps_structured_directory_full_while_prompt_counts_match_visible_catalog():
    p4_provider = importlib.import_module("src.p4_provider")

    projection = {
        "ok": True,
        "project_page_count": 1,
        "shelf_sections": {
            "zhiyi": {
                "entry_count": 1,
                "entries": [{"library_id": "ZX-ZHIYI-1", "title": "偏好 1", "when_to_use": "触发 1", "source_ref": "z1.jsonl:0-10"}],
            },
            "xingce": {
                "entry_count": 2,
                "entries": [
                    {"library_id": "ZX-XINGCE-1", "title": "行策 1", "when_to_use": "触发 1", "source_ref": "x1.jsonl:0-10"},
                    {"library_id": "ZX-XINGCE-2", "title": "行策 2", "when_to_use": "触发 2", "source_ref": "x2.jsonl:0-10"},
                ],
            },
            "toolbook": {
                "entry_count": 3,
                "entries": [
                    {"library_id": "ZX-TOOL-1", "title": "工具书 1", "when_to_use": "路径", "source_ref": "t1.jsonl:0-10"},
                    {"library_id": "ZX-TOOL-2", "title": "工具书 2", "when_to_use": "端口", "source_ref": "t2.jsonl:0-10"},
                    {"library_id": "ZX-TOOL-3", "title": "工具书 3", "when_to_use": "脚本", "source_ref": "t3.jsonl:0-10"},
                ],
            },
            "raw": {
                "entry_count": 3,
                "entries": [
                    {"library_id": "ZX-RAW-1", "title": "raw 1", "when_to_use": "raw 1", "source_ref": "r1.jsonl:0-10"},
                    {"library_id": "ZX-RAW-2", "title": "raw 2", "when_to_use": "raw 2", "source_ref": "r2.jsonl:0-10"},
                    {"library_id": "ZX-RAW-3", "title": "raw 3", "when_to_use": "raw 3", "source_ref": "r3.jsonl:0-10"},
                ],
            },
            "errata": {
                "entry_count": 1,
                "entries": [{"library_id": "ZX-ERRATA-1", "title": "勘误 1", "when_to_use": "勘误", "source_ref": "e1.jsonl:0-10"}],
            },
        },
        "project_pages": [
            {
                "project_id": "project:time-library:03657f57bf",
                "lane_count": 3,
                "library_id_pull_handles": ["ZX-RAW-1", "ZX-RAW-2", "ZX-RAW-3", "ZX-XINGCE-1"],
                "visible_library_id_pull_handles": ["ZX-RAW-1", "ZX-XINGCE-1"],
                "visible_lane_summaries": [
                    {"agent": "codex", "item_count": 3, "shelf_counts": {"xingce": 2, "raw": 1}, "library_ids": ["ZX-XINGCE-1"]},
                    {"agent": "opus", "item_count": 1, "shelf_counts": {"raw": 1}, "library_ids": ["ZX-RAW-1"]},
                    {"agent": "mimo", "item_count": 1, "shelf_counts": {"raw": 1}, "library_ids": ["ZX-RAW-3"]},
                ],
            }
        ],
        "whiteboard": {"lines": []},
        "history": {"lines": []},
        "startup_catalog": {
            "ok": True,
            "catalog": [
                {"library_id": "ZX-ZHIYI-1", "shelf": "zhiyi", "title": "偏好 1", "when_to_use": "触发 1", "source_ref": "z1.jsonl:0-10"},
                {"library_id": "ZX-XINGCE-1", "shelf": "xingce", "title": "行策 1", "when_to_use": "触发 1", "source_ref": "x1.jsonl:0-10"},
                {"library_id": "ZX-XINGCE-2", "shelf": "xingce", "title": "行策 2", "when_to_use": "触发 2", "source_ref": "x2.jsonl:0-10"},
                {"library_id": "ZX-TOOL-1", "shelf": "toolbook", "title": "工具书 1", "when_to_use": "路径", "source_ref": "t1.jsonl:0-10"},
                {"library_id": "ZX-TOOL-2", "shelf": "toolbook", "title": "工具书 2", "when_to_use": "端口", "source_ref": "t2.jsonl:0-10"},
                {"library_id": "ZX-TOOL-3", "shelf": "toolbook", "title": "工具书 3", "when_to_use": "脚本", "source_ref": "t3.jsonl:0-10"},
                {"library_id": "ZX-RAW-1", "shelf": "raw", "title": "raw 1", "when_to_use": "raw 1", "source_ref": "r1.jsonl:0-10"},
                {"library_id": "ZX-RAW-2", "shelf": "raw", "title": "raw 2", "when_to_use": "raw 2", "source_ref": "r2.jsonl:0-10"},
                {"library_id": "ZX-RAW-3", "shelf": "raw", "title": "raw 3", "when_to_use": "raw 3", "source_ref": "r3.jsonl:0-10"},
                {"library_id": "ZX-ERRATA-1", "shelf": "errata", "title": "勘误 1", "when_to_use": "勘误", "source_ref": "e1.jsonl:0-10"},
            ],
        },
    }

    prompt = p4_provider._reading_area_prompt_block(projection)

    assert "书架计数：zhiyi:1, xingce:2, raw:3, toolbook:3, errata:1" in prompt
    assert "raw把手：[ZX-RAW-1]; [ZX-RAW-2]; [ZX-RAW-3]" in prompt
    assert "ZX-TOOL-2" not in prompt
    assert "ZX-TOOL-3" not in prompt


def test_build_catalog_inject_from_candidates_reports_full_structured_catalog_visibility(tmp_path, monkeypatch):
    p4_provider = importlib.import_module("src.p4_provider")

    records = [
        {"library_id": "ZX-ZHIYI-1"},
        {"library_id": "ZX-XINGCE-1"},
        {"library_id": "ZX-XINGCE-2"},
        {"library_id": "ZX-TOOL-1"},
        {"library_id": "ZX-TOOL-2"},
        {"library_id": "ZX-TOOL-3"},
        {"library_id": "ZX-RAW-1"},
        {"library_id": "ZX-RAW-2"},
        {"library_id": "ZX-RAW-3"},
        {"library_id": "ZX-ERRATA-1"},
    ]
    startup_catalog = {
        "ok": True,
        "contract": "zhixing_catalog_push.v1",
        "projection_layer": "L0_library_index_projection",
        "index_projection_contract": "zhixing_library_index_projection.v1",
        "catalog": [
            {"library_id": "ZX-ZHIYI-1", "shelf": "zhiyi", "title": "偏好 1", "when_to_use": "触发 1", "source_ref": "z1.jsonl:0-10"},
            {"library_id": "ZX-XINGCE-1", "shelf": "xingce", "title": "行策 1", "when_to_use": "触发 1", "source_ref": "x1.jsonl:0-10"},
            {"library_id": "ZX-XINGCE-2", "shelf": "xingce", "title": "行策 2", "when_to_use": "触发 2", "source_ref": "x2.jsonl:0-10"},
            {"library_id": "ZX-TOOL-1", "shelf": "toolbook", "title": "工具书 1", "when_to_use": "路径", "source_ref": "t1.jsonl:0-10"},
            {"library_id": "ZX-TOOL-2", "shelf": "toolbook", "title": "工具书 2", "when_to_use": "端口", "source_ref": "t2.jsonl:0-10"},
            {"library_id": "ZX-TOOL-3", "shelf": "toolbook", "title": "工具书 3", "when_to_use": "脚本", "source_ref": "t3.jsonl:0-10"},
            {"library_id": "ZX-RAW-1", "shelf": "raw", "title": "raw 1", "when_to_use": "raw 1", "source_ref": "r1.jsonl:0-10"},
            {"library_id": "ZX-RAW-2", "shelf": "raw", "title": "raw 2", "when_to_use": "raw 2", "source_ref": "r2.jsonl:0-10"},
            {"library_id": "ZX-RAW-3", "shelf": "raw", "title": "raw 3", "when_to_use": "raw 3", "source_ref": "r3.jsonl:0-10"},
            {"library_id": "ZX-ERRATA-1", "shelf": "errata", "title": "勘误 1", "when_to_use": "勘误", "source_ref": "e1.jsonl:0-10"},
        ],
        "catalog_text": "full text",
        "token_count": 2200,
        "entry_count": 10,
        "trimmed": False,
        "omitted_shelves": [],
    }
    prompt_catalog = {
        **startup_catalog,
        "catalog": startup_catalog["catalog"][:8],
        "catalog_text": "prompt text",
        "token_count": 1180,
        "entry_count": 8,
        "trimmed": True,
        "omitted_shelves": [],
    }
    projection = {
        "ok": True,
        "contract": "time_library_reading_area_projection.v1",
        "project_page_count": 1,
        "project_pages": [{
            "project_id": "project:time-library:03657f57bf",
            "lane_count": 3,
            "library_id_pull_handles": ["ZX-RAW-1", "ZX-RAW-2", "ZX-RAW-3", "ZX-XINGCE-1"],
            "visible_library_id_pull_handles": ["ZX-RAW-1", "ZX-XINGCE-1"],
            "visible_lane_summaries": [
                {"agent": "codex", "item_count": 3, "shelf_counts": {"xingce": 2, "raw": 1}, "library_ids": ["ZX-XINGCE-1"]},
                {"agent": "opus", "item_count": 1, "shelf_counts": {"raw": 1}, "library_ids": ["ZX-RAW-1"]},
                {"agent": "mimo", "item_count": 1, "shelf_counts": {"raw": 1}, "library_ids": ["ZX-RAW-3"]},
            ],
            "whiteboard": {"lines": []},
            "history": {"lines": []},
        }],
        "shelf_sections": {
            "zhiyi": {"entry_count": 1, "entries": startup_catalog["catalog"][0:1]},
            "xingce": {"entry_count": 2, "entries": startup_catalog["catalog"][1:3]},
            "toolbook": {"entry_count": 3, "entries": startup_catalog["catalog"][3:6]},
            "raw": {"entry_count": 3, "entries": startup_catalog["catalog"][6:9]},
            "errata": {"entry_count": 1, "entries": startup_catalog["catalog"][9:10]},
        },
        "toc_token_count": 200,
        "contains_body_markers": False,
        "raw_index": {"enabled": True, "record_count": 3, "matched_session_count": 3, "title_model_used": False, "scope_policy": "declared_only", "error": "", "contract": "time_library_raw_session_shallow_index.v1"},
        "startup_catalog": startup_catalog,
        "whiteboard": {"lines": []},
        "history": {"lines": []},
    }

    def fake_load_catalog_candidate_records(*, xingce_root=""):
        return records

    calls = []
    def fake_build_library_catalog_push(records_arg, *, target_tokens=1200, preserve_library_ids=None, trim_to_target_tokens=True):
        calls.append(trim_to_target_tokens)
        return prompt_catalog if trim_to_target_tokens else startup_catalog

    def fake_build_reading_area_catalog_from_candidates(**kwargs):
        return projection

    monkeypatch.setattr(p4_provider, "load_catalog_candidate_records", fake_load_catalog_candidate_records)
    monkeypatch.setattr(p4_provider, "build_reading_area_catalog_from_candidates", fake_build_reading_area_catalog_from_candidates)
    monkeypatch.setattr(importlib.import_module("src.context_delivery_compaction"), "build_library_catalog_push", fake_build_library_catalog_push)
    monkeypatch.setattr(p4_provider, "_build_reading_area_raw_index", lambda **kwargs: {"ok": True, "contract": "time_library_raw_session_shallow_index.v1", "record_count": 0, "matched_session_count": 0, "title_model_used": False, "scope_policy": "declared_only", "error": "", "records": []})

    result = p4_provider.build_catalog_inject_from_candidates(target_tokens=1200, xingce_root=str(tmp_path))

    assert result["ok"] is True
    assert calls == [False, True]
    assert result["catalog_entry_count"] == 10
    assert result["catalog_text_entry_count"] == 8
    assert len(result["catalog"]) == 10
    assert result["catalog_token_count"] == 1180
    accounting = result["catalog_visibility_accounting"]
    assert accounting["structured_catalog_entry_count"] == 10
    assert accounting["prompt_catalog_entry_count"] == 8
    assert accounting["structured_catalog_trimmed"] is False
    assert accounting["prompt_catalog_trimmed"] is True
    assert set(accounting["hidden_active_library_ids"]) == {"ZX-RAW-3", "ZX-ERRATA-1"}


def test_reading_area_prompt_block_includes_whiteboard_lines_with_separate_budget():
    p4_provider = importlib.import_module("src.p4_provider")

    projection = {
        "ok": True,
        "project_page_count": 1,
        "shelf_sections": {
            "zhiyi": {"entry_count": 2, "entries": []},
            "xingce": {"entry_count": 7, "entries": [{"library_id": "ZX-XINGCE-1", "title": "发布前应执行完整测试"}]},
            "raw": {"entry_count": 1, "entries": [{"library_id": "ZX-RAW-32C3BFF741", "title": "Opus lane", "source_ref": "f2.jsonl:0-4096"}]},
            "toolbook": {"entry_count": 1, "entries": [{"library_id": "ZX-TOOL-1", "title": "9851 是 gateway 端口"}]},
            "errata": {"entry_count": 1, "entries": [{"library_id": "ZX-ERRATA-1", "title": "旧说法已废弃"}]},
        },
        "whiteboard": {
            "lines": [
                "在飞：施工/codex 白板甲块 -> 进行中；交接给 二签；[WB-AAA]",
                "在飞：二签/opus 注入复验 -> 待接棒；[WB-BBB]",
                "还有 2 条白板记录用编号取。",
            ],
        },
        "project_pages": [
            {
                "project_id": "project:time-library:03657f57bf",
                "lane_count": 2,
                "library_id_pull_handles": ["ZX-RAW-32C3BFF741", "ZX-XINGCE-1"],
                "history": {
                    "lines": ["历史：decision 白板乙块项目史进入项目页；[PH-C62C639F2B]"],
                },
                "whiteboard": {
                    "lines": ["在飞：施工/codex 白板乙块 -> 进行中；[WB-CCC]"],
                },
                "visible_lane_summaries": [
                    {"agent": "codex", "item_count": 8, "shelf_counts": {"xingce": 7}, "library_ids": ["ZX-XINGCE-1"]},
                    {"agent": "opus", "item_count": 1, "shelf_counts": {"raw": 1}, "library_ids": ["ZX-RAW-32C3BFF741"]},
                ],
            }
        ],
    }

    prompt = p4_provider._reading_area_prompt_block(projection)

    assert len(prompt) <= p4_provider.STARTUP_INSTRUCTIONS_CHAR_BUDGET
    assert "在飞：施工/codex 白板甲块" in prompt
    assert "在飞：二签/opus 注入复验" in prompt
    assert "历史：decision 白板乙块项目史进入项目页；[PH-C62C639F2B]" in prompt
    assert "在飞：施工/codex 白板乙块 -> 进行中；[WB-CCC]" in prompt
    assert "还有 2 条白板记录用编号取。" in prompt
    assert "f2.jsonl:0-4096" not in prompt


# ─── Fetch Library Card by ID (Pull Path) ────────────────────────────────


def test_fetch_library_card_by_id_returns_card():
    zhixing = importlib.import_module("src.zhixing_library")
    records = _sample_records()

    first_record = records[0]
    attached = zhixing.attach_library_card(first_record)
    target_id = attached.get("library_id") or attached.get("library_card", {}).get("library_id", "")

    assert target_id, "must have a library_id to test fetch"

    card = zhixing.fetch_library_card_by_id(target_id, records)

    assert card, "fetch must return a card"
    assert card["library_id"] == target_id
    assert card.get("shelf")
    assert card.get("source_refs")


def test_fetch_catalog_card_by_library_id_supports_whiteboard_records_without_scope(tmp_path):
    p4_provider = importlib.import_module("src.p4_provider")
    registry_mod = importlib.import_module("src.reading_area_registry")

    registry_path = tmp_path / "reading_area_registry.json"
    issue = registry_mod.ensure_borrowing_card(
        source_system="codex",
        consumer="codex",
        canonical_window_id="wb-fetch-window",
        session_id="wb-fetch-session",
        path=registry_path,
    )
    membership = registry_mod.declare_membership(
        card_id=issue["card_id"],
        reading_area="忆凡尘阅读区",
        projects=["忆凡尘"],
        series=["洪荒世界"],
        roles=["施工"],
        path=registry_path,
    )
    record = registry_mod.write_whiteboard_record(
        borrowing_card_id=issue["card_id"],
        record_type="handoff",
        task_id="wb-fetch-task",
        task_name="白板甲块收尾",
        summary="甲块施工完成，交接二签做裸窗复验。",
        next_owner="二签",
        request_id="wb-fetch-1",
        path=registry_path,
    )["record"]

    result = p4_provider.fetch_catalog_card_by_library_id(
        record["record_id"],
        reading_area_registry_path=str(registry_path),
    )

    assert membership["project_ids"][0].startswith("project:")
    assert result["ok"] is True
    assert result["shelf"] == "whiteboard"
    assert result["library_id"] == record["record_id"]
    assert result["verbatim_excerpt"] == "甲块施工完成，交接二签做裸窗复验。"


def test_fetch_catalog_card_by_library_id_supports_project_history_records_with_raw_excerpt(tmp_path):
    p4_provider = importlib.import_module("src.p4_provider")
    registry_mod = importlib.import_module("src.reading_area_registry")

    registry_path = tmp_path / "reading_area_registry.json"
    source_path = tmp_path / "raw" / "history.jsonl"
    text = "用户裁定：老项目历史由蒸馏补到项目页 history。"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text(text, encoding="utf-8")
    issue = registry_mod.ensure_borrowing_card(
        source_system="codex",
        consumer="codex",
        canonical_window_id="ph-fetch-window",
        session_id="ph-fetch-session",
        path=registry_path,
    )
    registry_mod.declare_membership(
        card_id=issue["card_id"],
        projects=["忆凡尘"],
        series=["洪荒世界"],
        path=registry_path,
    )
    record = registry_mod.write_project_history_record(
        borrowing_card_id=issue["card_id"],
        history_type="decision",
        title="历史由蒸馏补到项目页",
        summary="老项目进入白板后从现在记录，历史从蒸馏补。",
        source_refs=[{
            "source_system": "codex",
            "source_path": str(source_path),
            "source_author": "user",
            "byte_offsets": {"start": 0, "end": len(text.encode("utf-8"))},
            "verbatim_excerpt": text,
        }],
        request_id="ph-fetch-1",
        path=registry_path,
    )["record"]

    result = p4_provider.fetch_catalog_card_by_library_id(
        record["record_id"],
        reading_area_registry_path=str(registry_path),
        records_db_path=str(tmp_path / "records.db"),
    )

    assert result["ok"] is True
    assert result["shelf"] == "project_history"
    assert result["library_id"] == record["record_id"]
    assert result["raw_source_excerpt_status"] == "ok"
    assert result["raw_source_excerpt"] == text
    assert result["verbatim_sha256"] == record["verbatim_sha256"]


def test_fetch_catalog_card_by_library_id_reads_materialized_project_history_archive(tmp_path):
    p4_provider = importlib.import_module("src.p4_provider")
    registry_mod = importlib.import_module("src.reading_area_registry")

    registry_path = tmp_path / "reading_area_registry.json"
    temp_root = tmp_path / "var" / "folders" / "history-source"
    source_path = temp_root / "history.txt"
    text = "用户裁定：项目史证据源遇到临时目录要先物化。"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text(text, encoding="utf-8")
    issue = registry_mod.ensure_borrowing_card(
        source_system="codex",
        consumer="codex",
        canonical_window_id="ph-archive-window",
        session_id="ph-archive-session",
        path=registry_path,
    )
    registry_mod.declare_membership(
        card_id=issue["card_id"],
        projects=["忆凡尘"],
        series=["洪荒世界"],
        path=registry_path,
    )
    record = registry_mod.write_project_history_record(
        borrowing_card_id=issue["card_id"],
        history_type="decision",
        title="项目史临时证据源先物化",
        summary="项目史记录不能长期依赖临时目录 source_ref。",
        source_refs=[{
            "source_system": "codex",
            "source_path": str(source_path),
            "source_author": "user",
            "byte_offsets": {"start": 0, "end": len(text.encode("utf-8"))},
            "verbatim_excerpt": text,
        }],
        request_id="ph-archive-1",
        path=registry_path,
    )["record"]

    result = p4_provider.fetch_catalog_card_by_library_id(
        record["record_id"],
        reading_area_registry_path=str(registry_path),
        records_db_path=str(tmp_path / "records.db"),
    )

    assert result["ok"] is True
    assert result["raw_source_excerpt_status"] == "ok"
    assert result["raw_source_excerpt"] == text
    assert result["raw_source_excerpt_ref"]["source_persistence"] == "durable_project_history_evidence_archive"
    assert result["raw_source_excerpt_ref"]["original_source_ref"]["source_path"] == str(source_path)
    assert result["verbatim_sha256"] == hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_fetch_library_card_by_id_returns_empty_for_missing():
    zhixing = importlib.import_module("src.zhixing_library")
    records = _sample_records()

    card = zhixing.fetch_library_card_by_id("ZX-NONEXISTENT-ID", records)

    assert card == {}


def test_fetch_library_card_by_id_returns_empty_for_empty_input():
    zhixing = importlib.import_module("src.zhixing_library")

    assert zhixing.fetch_library_card_by_id("", []) == {}
    assert zhixing.fetch_library_card_by_id("ZX-TEST", []) == {}
    assert zhixing.fetch_library_card_by_id("", _sample_records()) == {}


def test_catalog_library_id_can_pull_real_card():
    """Verify: catalog entry library_id → fetch_library_card_by_id → real card with source_refs."""
    zhixing = importlib.import_module("src.zhixing_library")
    compaction = importlib.import_module("src.context_delivery_compaction")
    records = _sample_records()

    catalog = compaction.build_library_catalog_push(records, target_tokens=1200)
    assert catalog["ok"] is True

    for entry in catalog["catalog"][:3]:
        card = zhixing.fetch_library_card_by_id(entry["library_id"], records)
        assert card, f"library_id {entry['library_id']} from catalog must pull a real card"
        assert card["library_id"] == entry["library_id"]
        assert card.get("source_refs"), f"card for {entry['library_id']} must have source_refs"
        refs = card.get("source_refs", {})
        assert refs.get("source_path") or refs.get("source_system"), \
            f"source_refs for {entry['library_id']} must have source_path or source_system"


def test_fetch_library_card_by_id_from_candidates_no_records():
    """Verify bare library_id pull without pre-loaded records from temp xingce root."""
    zhixing = importlib.import_module("src.zhixing_library")
    records = _installed_sample_records()

    attached = zhixing.attach_library_card(records[0])
    target_id = attached.get("library_id", "")
    assert target_id, "must have library_id"

    card = zhixing.fetch_library_card_by_id(target_id, records)
    assert card, "fetch with records must succeed"
    assert card["library_id"] == target_id
    assert card.get("source_refs"), "card must have source_refs"
    refs = card.get("source_refs", {})
    assert refs.get("source_path"), "source_refs must have source_path"


# ─── Negative Tests ──────────────────────────────────────────────────────


def test_catalog_does_not_contain_verbatim_content():
    compaction = importlib.import_module("src.context_delivery_compaction")
    records = _sample_records()

    result = compaction.build_library_catalog_push(records, target_tokens=1200)

    assert result["ok"] is True
    text = result["catalog_text"]
    assert "详情：" not in text
    assert "策略：" not in text


def test_catalog_does_not_contain_quarantined_path():
    compaction = importlib.import_module("src.context_delivery_compaction")
    records = _sample_records()
    records.append(_make_quarantined_record(
        "q-001", "隔离", "output/xingce_work_experience/quarantined/bad.jsonl",
    ))

    result = compaction.build_library_catalog_push(records, target_tokens=1200)

    assert "quarantined" not in result.get("catalog_text", "")


def test_catalog_text_format_is_readable():
    compaction = importlib.import_module("src.context_delivery_compaction")
    records = _installed_sample_records()

    result = compaction.build_library_catalog_push(records, target_tokens=2000)

    assert result["ok"] is True
    for line in result["catalog_text"].split("\n"):
        assert line.startswith("- [")
        assert "] " in line
        assert " | when_to_use: " in line
        assert " | source: " in line


# ─── Stable Library ID Tests ────────────────────────────────────────────


def test_xingce_candidate_id_stable_across_raw_and_memory():
    """Same candidate_id in raw candidate and p3-style memory → same library_id."""
    zhixing = importlib.import_module("src.zhixing_library")
    candidate_id = "xingce-distill-exp-case-c133ec1c-7789cf06bb9b"

    raw_record = {
        "_type": "xingce_work_experience_candidate",
        "exp_id": candidate_id,
        "library_shelf": "xingce",
        "summary": "原始候选摘要",
        "detail": "原始候选详情",
        "source_refs": {"source_path": "raw/candidates/orig.json"},
        "_xingce": {"candidate_id": candidate_id, "lifecycle_status": "candidate"},
        "lifecycle_status": "candidate",
    }

    memory_record = {
        "_type": "xingce_work_experience_candidate",
        "exp_id": candidate_id,
        "library_shelf": "xingce",
        "summary": "行策工作经验：完全不同摘要。状态=active usable；证据=2。evidence-bound，write_boundary false。",
        "detail": "p3 转换后的详情完全不同",
        "source_refs": {
            "source_system": "openclaw",
            "source_path": "raw/sessions/p3-transformed.jsonl",
            "candidate_path": "/tmp/candidates/x.json",
        },
        "_xingce": {
            "candidate_id": candidate_id,
            "lifecycle_status": "candidate",
            "action_status": "auto_adopted_evidence_bound",
        },
        "lifecycle_status": "candidate",
    }

    raw_id = zhixing.library_id_for(raw_record)
    mem_id = zhixing.library_id_for(memory_record)
    assert raw_id == mem_id, f"raw={raw_id} != memory={mem_id}"
    assert raw_id.startswith("ZX-XINGCE-")


def test_xingce_candidate_id_from_exp_id_fallback():
    """When _xingce.candidate_id missing, exp_id is used."""
    zhixing = importlib.import_module("src.zhixing_library")
    record = {
        "_type": "xingce_work_experience_candidate",
        "exp_id": "test-exp-id-123",
        "library_shelf": "xingce",
        "summary": "test",
        "detail": "test",
        "source_refs": {"source_path": "raw/test.json"},
        "lifecycle_status": "candidate",
    }
    lid = zhixing.library_id_for(record)
    assert lid.startswith("ZX-XINGCE-")

    record2 = dict(record, _xingce={"candidate_id": "test-exp-id-123", "lifecycle_status": "candidate"})
    lid2 = zhixing.library_id_for(record2)
    assert lid == lid2


def test_raw_xingce_candidate_type_gets_xingce_library_id():
    """Raw candidate JSON files use candidate_type=xingce_work_experience."""
    zhixing = importlib.import_module("src.zhixing_library")
    candidate_id = "xingce-distill-exp-case-raw-001"
    record = {
        "candidate_id": candidate_id,
        "candidate_type": "xingce_work_experience",
        "title": "真实候选卡标题",
        "summary": "真实候选卡摘要",
        "source_refs": ["raw/sessions/real.jsonl"],
        "lifecycle_status": "candidate",
    }

    assert zhixing.shelf_for(record) == "xingce"
    lid = zhixing.library_id_for(record)
    assert lid.startswith("ZX-XINGCE-")

    p3_memory = {
        "_type": "xingce_work_experience_candidate",
        "exp_id": candidate_id,
        "library_shelf": "xingce",
        "summary": "p3 记忆形态摘要",
        "source_refs": {"source_path": "raw/sessions/real.jsonl"},
        "_xingce": {"candidate_id": candidate_id, "lifecycle_status": "candidate"},
        "lifecycle_status": "candidate",
    }
    assert zhixing.library_id_for(p3_memory) == lid


def test_fetch_library_card_by_id_from_candidates_temp_root():
    """library_id → fetch_library_card_from_candidates with temp xingce_root finds the card."""
    zhixing = importlib.import_module("src.zhixing_library")
    candidate_id = "xingce-test-fetch-temp-001"

    with tempfile.TemporaryDirectory() as tmp:
        candidates_dir = os.path.join(tmp, "output", "xingce_work_experience", "candidates")
        actions_dir = os.path.join(tmp, "output", "xingce_work_experience", "actions")
        os.makedirs(candidates_dir)
        os.makedirs(actions_dir)

        candidate = {
            "candidate_id": candidate_id,
            "candidate_type": "xingce_work_experience",
            "lifecycle_status": "candidate",
            "title": "测试候选标题",
            "work_scenario": "测试场景",
            "summary": "测试摘要",
            "detail": "测试详情",
            "observed_facts": ["事实1"],
            "recommended_procedure": ["步骤1"],
            "avoid_conditions": ["避免1"],
            "verification_steps": ["验证1"],
            "evidence_refs": [
                {
                    "source_path": "raw/sessions/test-001.jsonl",
                    "canonical_window_id": "test-window",
                    "byte_offsets": {"start": 0, "end": 500},
                }
            ],
            "source_refs": ["raw/sessions/test-001.jsonl"],
        }
        cand_path = os.path.join(candidates_dir, "xingce-test-fetch-temp-001-candidate.json")
        with open(cand_path, "w", encoding="utf-8") as f:
            json.dump(candidate, f, ensure_ascii=False)

        action = {
            "candidate_id": candidate_id,
            "action_status": "auto_adopted_evidence_bound",
            "action_id": "act-001",
        }
        action_path = os.path.join(actions_dir, "2026-06-30-action.jsonl")
        with open(action_path, "w", encoding="utf-8") as f:
            json.dump(action, f, ensure_ascii=False)
            f.write("\n")

        memory_record = {
            "_type": "xingce_work_experience_candidate",
            "exp_id": candidate_id,
            "library_shelf": "xingce",
            "summary": "行策工作经验：测试候选标题",
            "detail": "测试详情",
            "work_scenario": "测试场景",
            "source_refs": {
                "source_system": "openclaw",
                "source_path": "raw/sessions/test-001.jsonl",
                "candidate_path": cand_path,
            },
            "_xingce": {
                "candidate_id": candidate_id,
                "lifecycle_status": "candidate",
                "action_status": "auto_adopted_evidence_bound",
            },
            "lifecycle_status": "candidate",
        }
        expected_id = zhixing.library_id_for(memory_record)
        assert expected_id.startswith("ZX-XINGCE-")

        card = zhixing.fetch_library_card_by_id_from_candidates(expected_id, xingce_root=tmp)
        assert card, f"fetch_library_card_by_id_from_candidates must find card for {expected_id}"
        assert card["library_id"] == expected_id
        assert card.get("source_refs"), "card must have source_refs"


def test_catalog_card_projects_source_author_and_mode_for_zhiyi_candidate():
    p4_provider = importlib.import_module("src.p4_provider")
    zhixing = importlib.import_module("src.zhixing_library")

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        candidates_dir = root / "output" / "zhiyi_preference_cards" / "candidates"
        source_path = root / "raw" / "source.jsonl"
        candidates_dir.mkdir(parents=True)
        source_path.parent.mkdir(parents=True)
        text = "他现在有新名字了不要用yifanchen这样的称呼他"
        source_path.write_text(text, encoding="utf-8")
        candidate = {
            "candidate_id": "zhiyi-distill-test-source-mode",
            "candidate_type": "zhiyi_preference_card",
            "library_shelf": "zhiyi",
            "lifecycle_status": "active",
            "title": "不要用 yifanchen 这类拼音称呼",
            "summary": "命名偏好",
            "verbatim_excerpt": text,
            "source_author": "user",
            "source_role": "user",
            "source_mode": "evidence_bound_model_distill",
            "source_refs": {
                "source_system": "claude_code_cli",
                "source_path": str(source_path),
                "source_role": "user",
                "byte_offsets": {"start": 0, "end": len(text.encode("utf-8"))},
            },
        }
        candidate_path = candidates_dir / "zhiyi-distill-test-source-mode.json"
        candidate_path.write_text(json.dumps(candidate, ensure_ascii=False), encoding="utf-8")
        expected_record = dict(candidate, _type="zhiyi_preference_card", type="preference_memory", exp_id=candidate["candidate_id"])
        expected_id = zhixing.library_id_for(expected_record)

        result = p4_provider.fetch_catalog_card_by_library_id(expected_id, xingce_root=str(root))

    assert result["ok"] is True
    assert result["source_author"] == "user"
    assert result["source_mode"] == "evidence_bound_model_distill"
    assert result["verbatim_sha256"] == hashlib.sha256(text.encode("utf-8")).hexdigest()
    assert result["card"]["verbatim_sha256"] == result["verbatim_sha256"]
    assert result["catalog_card_projection_meta"]["source_author_projected"] is True
    assert result["catalog_card_projection_meta"]["source_mode_projected"] is True
    assert result["catalog_card_projection_meta"]["verbatim_sha256_projected"] is True


def test_file_backed_errata_candidate_is_catalog_visible_and_borrowable():
    p4_provider = importlib.import_module("src.p4_provider")
    zhixing = importlib.import_module("src.zhixing_library")

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        errata_dir = root / "output" / "zhiyi_errata" / "candidates"
        raw_path = root / "raw" / "errata-source.jsonl"
        errata_dir.mkdir(parents=True)
        raw_path.parent.mkdir(parents=True)
        text = "这条旧卡用了转贴的 AI 总结语气，应该换锚到我的原话"
        raw_path.write_text(text, encoding="utf-8")
        end = len(text.encode("utf-8"))
        errata = {
            "candidate_id": "errata-test-816-reanchor",
            "candidate_type": "zhiyi_errata_candidate",
            "library_shelf": "errata",
            "lifecycle_status": "active",
            "type": "errata_record",
            "title": "勘误：一致不等于印证旧锚误署 user",
            "summary": "旧卡把转贴的 AI 总结语气误署为 user，经判架换锚。",
            "verbatim_excerpt": text,
            "verbatim_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "source_author": "user",
            "source_role": "user",
            "source_mode": "evidence_bound_errata_adjudication",
            "source_refs": {
                "source_system": "claude_code_cli",
                "source_path": str(raw_path),
                "source_role": "user",
                "byte_offsets": {"start": 0, "end": end},
                "verbatim_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            },
            "old_library_id": "ZX-ZHIYI-816CFB224C",
            "new_library_id": "ZX-ZHIYI-NEWANCHOR",
            "supersedes": ["ZX-ZHIYI-816CFB224C"],
            "conflicts_with": ["ZX-ZHIYI-816CFB224C"],
        }
        errata_path = errata_dir / "errata-test-816-reanchor.json"
        errata_path.write_text(json.dumps(errata, ensure_ascii=False), encoding="utf-8")

        records = zhixing.load_file_backed_library_candidate_records(xingce_root=str(root))
        catalog = p4_provider.build_catalog_inject_from_candidates(xingce_root=str(root))
        expected_id = zhixing.library_id_for(dict(errata, _type="zhiyi_errata_candidate", exp_id=errata["candidate_id"]))
        result = p4_provider.fetch_catalog_card_by_library_id(expected_id, xingce_root=str(root))

    assert any(record.get("library_shelf") == "errata" for record in records)
    assert any(entry["library_id"] == expected_id and entry["shelf"] == "errata" for entry in catalog["catalog"])
    assert result["ok"] is True
    assert result["shelf"] == "errata"
    assert result["card"]["supersedes"] == ["ZX-ZHIYI-816CFB224C"]
    assert result["card"]["conflicts_with"] == ["ZX-ZHIYI-816CFB224C"]
    assert result["verbatim_sha256"] == hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_superseded_zhiyi_candidate_is_borrowable_but_not_active_catalog():
    p4_provider = importlib.import_module("src.p4_provider")
    zhixing = importlib.import_module("src.zhixing_library")

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        zhiyi_dir = root / "output" / "zhiyi_preference_cards" / "candidates"
        raw_path = root / "raw" / "old-source.jsonl"
        zhiyi_dir.mkdir(parents=True)
        raw_path.parent.mkdir(parents=True)
        text = "一致≠印证，我上机独立量"
        raw_path.write_text(text, encoding="utf-8")
        end = len(text.encode("utf-8"))
        old = {
            "candidate_id": "zhiyi-distill-old-816",
            "library_id": "ZX-ZHIYI-816CFB224C",
            "candidate_type": "zhiyi_preference_card",
            "library_shelf": "zhiyi",
            "lifecycle_status": "superseded",
            "title": "一致不等于印证，需独立上机实测验证",
            "summary": "旧卡已换锚。",
            "verbatim_excerpt": text,
            "verbatim_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "source_author": "user",
            "source_role": "user",
            "source_mode": "evidence_bound_model_distill",
            "source_refs": {
                "source_system": "codex",
                "source_path": str(raw_path),
                "source_role": "user",
                "byte_offsets": {"start": 0, "end": end},
                "verbatim_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            },
            "superseded_by_library_id": "ZX-ZHIYI-NEWANCHOR",
        }
        (zhiyi_dir / "zhiyi-distill-old-816.json").write_text(json.dumps(old, ensure_ascii=False), encoding="utf-8")

        catalog = p4_provider.build_catalog_inject_from_candidates(xingce_root=str(root))
        result = p4_provider.fetch_catalog_card_by_library_id("ZX-ZHIYI-816CFB224C", xingce_root=str(root))

    assert result["ok"] is True
    assert result["card"]["status"] == "superseded"
    assert result["card"]["superseded_by"] == ["ZX-ZHIYI-NEWANCHOR"]
    assert result["shelf"] == "zhiyi"
    assert all(entry["library_id"] != "ZX-ZHIYI-816CFB224C" for entry in catalog.get("catalog", []))


def test_xingce_verbatim_backfill_preserves_public_library_id_without_overwrite():
    p4_provider = importlib.import_module("src.p4_provider")
    zhixing = importlib.import_module("src.zhixing_library")
    backfill_mod = importlib.import_module("tools.xingce_verbatim_backfill")
    old_candidate_id = "xingce-backfill-old-001"

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        candidates_dir = root / "output" / "xingce_work_experience" / "candidates"
        actions_dir = root / "output" / "xingce_work_experience" / "actions"
        raw_path = root / "raw" / "session.jsonl"
        candidates_dir.mkdir(parents=True)
        actions_dir.mkdir(parents=True)
        raw_path.parent.mkdir(parents=True)
        prefix = "prefix:"
        raw_excerpt = "这是需要逐字回源的行策证据"
        raw_path.write_text(prefix + raw_excerpt + ":suffix", encoding="utf-8")
        start = len(prefix.encode("utf-8"))
        end = start + len(raw_excerpt.encode("utf-8"))
        old_candidate = {
            "candidate_id": old_candidate_id,
            "candidate_type": "xingce_work_experience",
            "library_shelf": "xingce",
            "lifecycle_status": "candidate",
            "title": "旧卡证据回填",
            "summary": "蒸馏摘要不该进 verbatim",
            "verbatim_excerpt": "蒸馏摘要不该进 verbatim",
            "source_author": "assistant",
            "source_role": "assistant",
            "source_mode": "evidence_bound_model_distill",
            "evidence_refs": [{
                "source_path": str(raw_path),
                "resolved_source_path": str(raw_path),
                "canonical_window_id": "test-window",
                "byte_offsets": {"_computed_verbatim": {"start": start, "end": end}},
            }],
            "observed_facts": ["蒸馏事实"],
            "recommended_procedure": ["蒸馏步骤"],
            "work_scenario": "回填旧卡时",
            "action_strategy": "只追加修正版",
        }
        old_path = candidates_dir / f"{old_candidate_id}-candidate.json"
        old_path.write_text(json.dumps(old_candidate, ensure_ascii=False), encoding="utf-8")
        old_bytes = old_path.read_bytes()
        (actions_dir / "2026-07-02-old-auto.jsonl").write_text(
            json.dumps({"candidate_id": old_candidate_id, "action_status": "auto_adopted_evidence_bound"}, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        old_library_id = zhixing.library_id_for({
            "_type": "xingce_work_experience_candidate",
            "exp_id": old_candidate_id,
            "library_shelf": "xingce",
        })

        report = backfill_mod.backfill(root)

        assert report["ok"] is True
        assert report["backfilled"] == 1
        assert report["mappings"][0]["new_library_id"] == old_library_id
        assert report["mappings"][0]["preserved_library_id"] == old_library_id
        assert report["mappings"][0]["public_handle_preserved"] is True
        assert old_path.read_bytes() == old_bytes
        records = p4_provider.load_catalog_candidate_records(xingce_root=str(root))
        assert len([r for r in records if r.get("_type") == "xingce_work_experience_candidate"]) == 1
        new_library_id = zhixing.library_id_for(records[0])
        assert new_library_id == old_library_id
        pulled = p4_provider.fetch_catalog_card_by_library_id(old_library_id, xingce_root=str(root))
        assert pulled["ok"] is True
        assert pulled["library_id"] == old_library_id
        assert pulled["verbatim_excerpt"] == raw_excerpt
        assert pulled["raw_source_excerpt"] == raw_excerpt
        assert pulled["source_refs"]["byte_offsets"] == {"start": start, "end": end}
        assert pulled["card"]["verbatim_sha256"] == hashlib.sha256(raw_excerpt.encode("utf-8")).hexdigest()
        assert records[0]["supersedes"] == [old_candidate_id]
        second_report = backfill_mod.backfill(root)
        assert second_report["ok"] is True
        assert second_report["backfilled"] == 0


def test_extract_source_ref_nested_computed_verbatim():
    """Nested _computed_verbatim byte offsets produce file:start-end."""
    compaction = importlib.import_module("src.context_delivery_compaction")
    record = {
        "evidence_refs": [
            {
                "source_path": "raw/sessions/real-session.jsonl",
                "byte_offsets": {
                    "_computed_verbatim": {"start": 1234, "end": 5678},
                },
            }
        ]
    }
    result = compaction._extract_source_ref_from_record(record, {})
    assert result == "real-session.jsonl:1234-5678"


def test_extract_source_ref_flat_byte_offsets():
    """Flat byte_offsets still work (backward compat)."""
    compaction = importlib.import_module("src.context_delivery_compaction")
    record = {
        "evidence_refs": [
            {
                "source_path": "/path/to/session.jsonl",
                "byte_offsets": {"start": 100, "end": 200},
            }
        ]
    }
    result = compaction._extract_source_ref_from_record(record, {})
    assert result == "session.jsonl:100-200"


def test_relay_voiceprint_annotation_is_visible_without_removing_card():
    p4_provider = importlib.import_module("src.p4_provider")
    zhixing = importlib.import_module("src.zhixing_library")
    scan_mod = importlib.import_module("tools.relay_voiceprint_scan")

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        candidates_dir = root / "output" / "zhiyi_preference_cards" / "candidates"
        candidates_dir.mkdir(parents=True)
        raw_path = root / "raw" / "relay.jsonl"
        raw_path.parent.mkdir(parents=True)
        verbatim = "一致≠印证，我上机独立量。Opus 二签 opus_confirmed，BYTE-EXACT + SHA-MATCH。"
        raw_path.write_text(verbatim, encoding="utf-8")
        candidate = {
            "candidate_id": "zhiyi-relay-risk",
            "candidate_type": "zhiyi_preference_card",
            "library_shelf": "zhiyi",
            "type": "preference_memory",
            "lifecycle_status": "active",
            "title": "一致不等于印证",
            "summary": "一致不等于印证",
            "preference_statement": "一致不等于印证",
            "when_to_use": "看到报告一致但未独立验牌时",
            "verbatim_excerpt": verbatim,
            "verbatim_sha256": hashlib.sha256(verbatim.encode("utf-8")).hexdigest(),
            "source_author": "user",
            "source_role": "user",
            "source_mode": "evidence_bound_model_distill",
            "source_refs": {
                "source_path": str(raw_path),
                "source_author": "user",
                "source_role": "user",
                "byte_offsets": {"start": 0, "end": len(verbatim.encode("utf-8"))},
                "verbatim_sha256": hashlib.sha256(verbatim.encode("utf-8")).hexdigest(),
            },
        }
        path = candidates_dir / "zhiyi-relay-risk.json"
        path.write_text(json.dumps(candidate, ensure_ascii=False), encoding="utf-8")
        original_candidate_bytes = path.read_bytes()
        library_id = zhixing.library_id_for(dict(candidate, _type="zhiyi_preference_card", exp_id="zhiyi-relay-risk"))

        report = scan_mod.scan(root, write=True)
        catalog = p4_provider.build_catalog_inject_from_candidates(xingce_root=str(root))
        card = p4_provider.fetch_catalog_card_by_library_id(library_id, xingce_root=str(root))

        assert report["user_relayed_count"] == 1
        assert report["written_annotation_count"] == 1
        assert path.read_bytes() == original_candidate_bytes
        assert any(entry["library_id"] == library_id for entry in catalog["catalog"])
        assert card["ok"] is True
        assert card["card"]["status"] == "active"
        assert card["card"]["evidence_attribution"] == "user_relayed"
        assert card["card"]["relay_voiceprint"]["user_relayed"] is True
        assert "agent_first_person_work_verb" in card["card"]["relay_voiceprint"]["reasons"]


def test_relay_voiceprint_direct_and_relayed_cards_both_stay_in_catalog():
    p4_provider = importlib.import_module("src.p4_provider")
    zhixing = importlib.import_module("src.zhixing_library")
    scan_mod = importlib.import_module("tools.relay_voiceprint_scan")

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        candidates_dir = root / "output" / "zhiyi_preference_cards" / "candidates"
        candidates_dir.mkdir(parents=True)
        raw_dir = root / "raw"
        raw_dir.mkdir()
        direct_text = "不要用 yifanchen 这类拼音拼接式称呼"
        relay_text = "一致≠印证，我上机独立量。Opus 二签 opus_confirmed，BYTE-EXACT + SHA-MATCH。"
        direct_raw = raw_dir / "direct.jsonl"
        relay_raw = raw_dir / "relay.jsonl"
        direct_raw.write_text(direct_text, encoding="utf-8")
        relay_raw.write_text(relay_text, encoding="utf-8")

        def write_candidate(candidate_id, title, text, raw_path):
            candidate = {
                "candidate_id": candidate_id,
                "candidate_type": "zhiyi_preference_card",
                "library_shelf": "zhiyi",
                "type": "preference_memory",
                "lifecycle_status": "active",
                "title": title,
                "summary": title,
                "preference_statement": title,
                "when_to_use": "需要按用户偏好行动时",
                "verbatim_excerpt": text,
                "verbatim_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "source_author": "user",
                "source_role": "user",
                "source_mode": "evidence_bound_model_distill",
                "source_refs": {
                    "source_path": str(raw_path),
                    "source_author": "user",
                    "source_role": "user",
                    "byte_offsets": {"start": 0, "end": len(text.encode("utf-8"))},
                    "verbatim_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                },
            }
            (candidates_dir / f"{candidate_id}.json").write_text(json.dumps(candidate, ensure_ascii=False), encoding="utf-8")
            return zhixing.library_id_for(dict(candidate, _type="zhiyi_preference_card", exp_id=candidate_id))

        direct_id = write_candidate("zhiyi-direct-user", "不要用拼音拼接式称呼", direct_text, direct_raw)
        relay_id = write_candidate("zhiyi-relayed-user", "一致不等于印证", relay_text, relay_raw)

        report = scan_mod.scan(root, write=True)
        catalog = p4_provider.build_catalog_inject_from_candidates(xingce_root=str(root))
        ids = {entry["library_id"] for entry in catalog["catalog"]}
        direct_card = p4_provider.fetch_catalog_card_by_library_id(direct_id, xingce_root=str(root))
        relay_card = p4_provider.fetch_catalog_card_by_library_id(relay_id, xingce_root=str(root))

        assert report["direct_user_count"] == 1
        assert report["user_relayed_count"] == 1
        assert direct_id in ids
        assert relay_id in ids
        assert direct_card["card"]["status"] == "active"
        assert relay_card["card"]["status"] == "active"
        assert direct_card["card"]["evidence_attribution"] == "direct_user"
        assert relay_card["card"]["evidence_attribution"] == "user_relayed"
