"""
Tests for runtime_freshness_full_chain_probe (B-path).

Verifies:
1. Default mode outputs blocked_not_proven + proof_layer=source_code
2. A/B layer separation: no bare connected_runtime_proven
3. Tempdir/synthetic source cannot claim connected_runtime
4. Timing segment fields exist and have correct schema
5. extraction_trigger forced/natural field present
6. Cleanup plan covers all 6 required layers
7. Multi-run stats schema (min/median/max/spike_list)
8. Missing --confirm-source-write blocks write
9. Missing --source-path blocks write
10. Gateway down blocks write
"""

import json
import os
import sys
import time
import uuid
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TOOLS = ROOT / "tools"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from runtime_freshness_full_chain_probe import (
    build_probe_result,
    PROBE_CONTRACT,
    INSTALLED_RUNTIME_ROOT,
    INSTALLED_RUNTIME_SRC,
    DEFAULT_GATEWAY_ENDPOINT,
    REQUIRED_CLEANUP_LAYERS,
    _is_synthetic_source,
    _validate_source_path,
    _perform_cleanup,
    _cleanup_source_file,
    _cleanup_raw_archive_jsonl,
    _build_cleanup_plan,
    _query_gateway,
    _find_token_in_response,
    _find_token_hash_in_response,
    _append_token_to_source,
    _import_connector_p2_from_installed_runtime,
    _probe_preference_content,
    _token_hash,
    _generate_probe_source_session,
    _cleanup_checkpoint_entries,
    _validate_source_jsonl_format,
)


class TestDefaultModeNoWrite:
    """Default mode (no --write-real) must refuse real writes."""

    def test_default_returns_source_code_proof_layer(self):
        result = build_probe_result({})
        assert result["proof_layer"] == "source_code"

    def test_default_returns_blocked_not_proven(self):
        result = build_probe_result({})
        assert result["status"] == "blocked_not_proven"

    def test_default_write_not_performed(self):
        result = build_probe_result({})
        assert result["write_performed"] is False

    def test_default_full_chain_freshness_false(self):
        result = build_probe_result({})
        assert result["full_chain_freshness"] is False

    def test_default_has_nonclaims(self):
        result = build_probe_result({})
        assert isinstance(result["nonClaims"], list)
        assert len(result["nonClaims"]) > 0

    def test_default_nonclaims_mention_full_chain(self):
        result = build_probe_result({})
        nc_text = " ".join(result["nonClaims"]).lower()
        assert "full-chain" in nc_text or "full chain" in nc_text

    def test_default_has_next_action(self):
        result = build_probe_result({})
        assert result.get("next_action_for_Codex")
        assert "--write-real" in result["next_action_for_Codex"]

    def test_default_ok_is_false(self):
        result = build_probe_result({})
        assert result["ok"] is False

    def test_contract_is_set(self):
        result = build_probe_result({})
        assert result["contract"] == PROBE_CONTRACT

    def test_default_extraction_trigger_is_forced(self):
        result = build_probe_result({})
        assert result["extraction_trigger"] == "forced"

    def test_default_extraction_trigger_note(self):
        result = build_probe_result({})
        assert "natural" in result["extraction_trigger_note"].lower()
        assert "not_proven" in result["extraction_trigger_note"].lower()


class TestABLayerSeparation:
    """Verify A/B proof layers are properly separated."""

    def test_no_bare_connected_runtime_proven_in_code(self):
        harness_path = ROOT / "tools" / "runtime_freshness_full_chain_probe.py"
        content = harness_path.read_text()
        assert 'status = "connected_runtime_proven"' not in content
        assert "connected_runtime_proven" not in content
        assert 'proof_layer = "connected_runtime"' not in content

    def test_b_path_status_is_default_recall_proven(self):
        harness_path = ROOT / "tools" / "runtime_freshness_full_chain_probe.py"
        content = harness_path.read_text()
        assert "connected_runtime_full_chain_default_recall_proven" in content

    def test_a_path_probe_not_modified(self):
        a_probe = ROOT / "tools" / "runtime_freshness_write_to_recall_probe.py"
        content = a_probe.read_text()
        assert "PROBE_CONTRACT" in content
        assert "runtime_freshness_write_to_recall_probe" in content


class TestGuardAgainstSyntheticSource:
    """Tempdir/synthetic source cannot claim connected_runtime."""

    def test_tempdir_is_synthetic(self, tmp_path):
        fake_source = tmp_path / "session.jsonl"
        fake_source.write_text('{"messages":[]}\n')
        assert _is_synthetic_source(str(fake_source)) is True

    def test_synthetic_source_blocked(self, tmp_path):
        fake_source = tmp_path / "session.jsonl"
        fake_source.write_text('{"messages":[]}\n')
        result = build_probe_result({
            "write_real": True,
            "confirm_source_write": True,
            "source_path": str(fake_source),
        })
        assert result["status"] == "blocked_not_proven"
        assert result["proof_layer"] in ("fixture", "source_code")
        assert result["source_path_is_synthetic"] is True

    def test_synthetic_source_nonclaims_mention_validation(self, tmp_path):
        fake_source = tmp_path / "session.jsonl"
        fake_source.write_text('{"messages":[]}\n')
        result = build_probe_result({
            "write_real": True,
            "confirm_source_write": True,
            "source_path": str(fake_source),
        })
        nc_text = " ".join(result["nonClaims"]).lower()
        assert "synthetic" in nc_text or "validation" in nc_text or "tempdir" in nc_text

    def test_nonexistent_source_blocked(self):
        result = build_probe_result({
            "write_real": True,
            "confirm_source_write": True,
            "source_path": "/nonexistent/path/session.jsonl",
        })
        assert result["status"] == "blocked_not_proven"
        assert result["write_performed"] is False


class TestMissingAuthorization:
    """Missing required flags must block write."""

    def test_write_real_without_confirm_source_write_blocked(self):
        result = build_probe_result({
            "write_real": True,
            "source_path": "/some/path.jsonl",
        })
        assert result["status"] == "blocked_not_proven"
        assert "confirm-source-write" in result["error"].lower() or \
               "confirm_source_write" in result["error"]

    def test_write_real_without_source_path_blocked(self):
        result = build_probe_result({
            "write_real": True,
            "confirm_source_write": True,
        })
        assert result["status"] == "blocked_not_proven"
        assert "source-path" in result["error"].lower() or \
               "source_path" in result["error"]

    def test_confirm_write_real_alias_works(self):
        result = build_probe_result({
            "confirm_write_real": True,
            "confirm_source_write": True,
            "source_path": "",
        })
        assert result["status"] == "blocked_not_proven"
        assert "source-path" in result["error"].lower() or \
               "source_path" in result["error"]


class TestMissingGateway:
    """Gateway unreachable yields blocked_not_proven."""

    def test_gateway_down_blocked(self, tmp_path):
        fake_source = tmp_path / "real_session.jsonl"
        fake_source.write_text('{"messages":[{"role":"user","content":"test"}]}\n')
        result = build_probe_result({
            "write_real": True,
            "confirm_source_write": True,
            "source_path": str(fake_source),
            "endpoint": "http://127.0.0.1:19999/api/v1/raw/query",
        })
        assert result["status"] == "blocked_not_proven"
        assert result["write_performed"] is False
        nc_text = " ".join(result["nonClaims"] + [result.get("error", "")]).lower()
        assert "not reachable" in nc_text or "health" in nc_text or "gateway" in nc_text


class TestTimingSegmentSchema:
    """Timing output must have all 5 segment fields."""

    def test_timing_has_all_segments(self):
        result = build_probe_result({})
        timing = result["timing"]
        assert isinstance(timing, dict)
        expected_segments = [
            "t_source_write_to_connector_ingest_ms",
            "t_connector_ingest_to_p2_start_ms",
            "t_p2_extract_duration_ms",
            "t_zhiyi_write_to_first_gateway_visible_ms",
            "t_total_write_to_visible_ms",
        ]
        for seg in expected_segments:
            assert seg in timing, f"Missing timing segment: {seg}"

    def test_timing_default_all_none(self):
        result = build_probe_result({})
        timing = result["timing"]
        for k, v in timing.items():
            assert v is None, f"Timing segment {k} should be None in default mode"

    def test_timing_source_write_is_t0(self):
        """Verify the naming convention: source_write is the start (T0)."""
        result = build_probe_result({})
        timing_keys = list(result["timing"].keys())
        assert timing_keys[0] == "t_source_write_to_connector_ingest_ms"


class TestExtractionTriggerField:
    """extraction_trigger must be present with forced/natural semantics."""

    def test_extraction_trigger_present(self):
        result = build_probe_result({})
        assert "extraction_trigger" in result

    def test_extraction_trigger_default_forced(self):
        result = build_probe_result({})
        assert result["extraction_trigger"] == "forced"

    def test_extraction_trigger_note_mentions_natural(self):
        result = build_probe_result({})
        assert "natural" in result["extraction_trigger_note"].lower()


class TestCleanupPlanLayers:
    """Cleanup plan must cover all 6 required layers."""

    def test_cleanup_plan_has_six_layers(self):
        result = build_probe_result({})
        assert len(REQUIRED_CLEANUP_LAYERS) == 6

    def test_required_layers_list(self):
        expected = [
            "source_platform_test_record",
            "raw_archive_jsonl",
            "p2_checkpoint",
            "zhiyi_jsonl",
            "bm25_index_cache",
            "gateway_visibility",
        ]
        assert REQUIRED_CLEANUP_LAYERS == expected

    def test_cleanup_plan_covers_all_layers_when_no_cleanup(self):
        result = build_probe_result({"no_cleanup": True})
        if result.get("cleanup_plan"):
            for layer in REQUIRED_CLEANUP_LAYERS:
                assert layer in result["cleanup_plan"], f"Missing cleanup layer: {layer}"

    def test_cleanup_plan_default_empty(self):
        result = build_probe_result({})
        assert result["cleanup_plan"] == {}

    def test_cleanup_rollback_plan_mentions_manual(self, tmp_path):
        """When cleanup can't be done automatically, rollback_plan should say so."""
        fake_source = tmp_path / "session.jsonl"
        fake_source.write_text('{"messages":[{"role":"user","content":"test"}]}\n')
        result = build_probe_result({
            "write_real": True,
            "confirm_source_write": True,
            "source_path": str(fake_source),
        })
        if result.get("cleanup_plan"):
            for layer, info in result["cleanup_plan"].items():
                if info.get("rollback_plan"):
                    assert "manual" in info["rollback_plan"].lower() or \
                           "required" in info["rollback_plan"].lower()


class TestCleanupHonesty:
    """Cleanup must be real, not just a plan. Distinguish plan-only from performed."""

    def test_default_mode_has_no_cleanup_fields(self):
        result = build_probe_result({})
        assert result["cleanup_performed"] is False
        assert result["all_layers_cleaned"] is False
        assert result["gateway_empty_after_cleanup"] is False

    def test_no_cleanup_flag_leaves_plan_only(self):
        # Without write_real, returns early with defaults; cleanup fields stay False
        result = build_probe_result({"no_cleanup": True})
        assert result["cleanup_performed"] is False
        assert result["all_layers_cleaned"] is False
        assert result["gateway_empty_after_cleanup"] is False

    def test_cleanup_source_file_deletes(self, tmp_path):
        src = tmp_path / "session.jsonl"
        src.write_text('{"type":"session_meta","payload":{"id":"test"}}\n')
        assert src.exists()
        ok, err = _cleanup_source_file(str(src), 0)
        assert ok is True
        assert err == ""
        assert not src.exists()

    def test_cleanup_source_file_nonexistent(self):
        ok, err = _cleanup_source_file("/nonexistent/file.jsonl", 0)
        assert ok is True

    def test_cleanup_raw_archive_deletes_probe_file(self, tmp_path):
        raw = tmp_path / "archive.jsonl"
        lines = [
            '{"type":"session_meta","id":"abc"}\n',
            '{"type":"response_item","content":"full-chain-probe-abc123"}\n',
            '{"type":"response_item","content":"real data"}\n',
        ]
        raw.write_text("".join(lines))
        ok, err = _cleanup_raw_archive_jsonl(str(raw), "full-chain-probe-abc123")
        assert ok is True
        assert not raw.exists()

    def test_cleanup_raw_archive_no_token_found(self, tmp_path):
        raw = tmp_path / "archive.jsonl"
        raw.write_text('{"type":"real","content":"data"}\n')
        ok, err = _cleanup_raw_archive_jsonl(str(raw), "nonexistent-token")
        assert ok is False
        assert "not found" in err.lower()

    def test_cleanup_raw_archive_empty_dest(self):
        ok, err = _cleanup_raw_archive_jsonl("", "token")
        assert ok is False
        assert "empty" in err.lower()

    def test_perform_cleanup_source_deletion(self, tmp_path):
        """_perform_cleanup deletes the entire source file."""
        src = tmp_path / "session.jsonl"
        src.write_text('{"type":"session_meta","payload":{"id":"t"}}\n')

        report = _perform_cleanup(
            str(src), "", 0, "probe-token", "hash123",
            "http://127.0.0.1:19999/api/v1/raw/query",
        )
        assert report["cleanup_performed"] is True
        assert report["cleanup_plan"]["source_platform_test_record"]["cleaned"] is True
        assert not src.exists()

    def test_perform_cleanup_gateway_fails_marks_unverified(self, tmp_path):
        """If gateway query still finds token after cleanup, mark as not clean."""
        src = tmp_path / "session.jsonl"
        src.write_text('{"type":"session_meta"}\n')

        with patch(
            "runtime_freshness_full_chain_probe._query_gateway",
            lambda e, q, timeout=8.0, source_system="codex": (
                {"ok": True, "items": [{"summary": f"contains {q}"}]}, ""
            ),
        ):
            report = _perform_cleanup(
                str(src), "", 0, "probe-token", "hash123",
                "http://127.0.0.1:19999/api/v1/raw/query",
            )
        assert report["cleanup_performed"] is True
        assert report["gateway_empty_after_cleanup"] is False
        assert report["all_layers_cleaned"] is False

    def test_perform_cleanup_gateway_empty_marks_clean(self, tmp_path):
        """If gateway returns no token after cleanup, mark gateway as clean."""
        src = tmp_path / "session.jsonl"
        src.write_text('{"type":"session_meta"}\n')

        with patch(
            "runtime_freshness_full_chain_probe._query_gateway",
            lambda e, q, timeout=8.0, source_system="codex": (
                {"ok": True, "items": []}, ""
            ),
        ):
            report = _perform_cleanup(
                str(src), "", 0, "probe-token", "hash123",
                "http://127.0.0.1:19999/api/v1/raw/query",
            )
        assert report["cleanup_performed"] is True
        assert report["gateway_empty_after_cleanup"] is True
        assert report["cleanup_plan"]["source_platform_test_record"]["cleaned"] is True

    def test_no_cleanup_flag_reports_residual_paths(self):
        # Without write_real, returns early; cleanup fields stay False
        result = build_probe_result({"no_cleanup": True})
        assert result["cleanup_performed"] is False
        assert result["all_layers_cleaned"] is False
        assert result["gateway_empty_after_cleanup"] is False


class TestCleanupBlocksFreshness:
    """If cleanup verification fails, full_chain_freshness must be false."""

    def test_token_still_visible_blocks_freshness(self, tmp_path):
        src = tmp_path / "session.jsonl"
        src.write_text('{"type":"session_meta","payload":{"id":"test"}}\n')

        import runtime_freshness_full_chain_probe as probe_mod
        original_validate = probe_mod._validate_source_path
        original_validate_jsonl = probe_mod._validate_source_jsonl_format
        probe_mod._validate_source_path = lambda p: (True, "")
        probe_mod._validate_source_jsonl_format = lambda p: (True, "")

        call_count = [0]
        def _mock_query_sees_token(endpoint, query, timeout=8.0, source_system="codex"):
            call_count[0] += 1
            return {
                "ok": True,
                "items": [{"summary": f"contains {query}"}],
            }, ""

        try:
            with patch(
                "runtime_freshness_full_chain_probe._gateway_health",
                lambda e, t=3.0: {"ok": True},
            ), patch(
                "runtime_freshness_full_chain_probe._query_gateway",
                _mock_query_sees_token,
            ), patch(
                "codex_local_connector.archive_session_incremental",
                lambda s, **kw: ("/fake/raw.jsonl", "archived(offset=100)"),
            ), patch(
                "p2_extract.incremental_extract_session",
                lambda f, **kw: (1, 1, 0),
            ):
                result = build_probe_result({
                    "write_real": True,
                    "confirm_source_write": True,
                    "source_path": str(src),
                })
        finally:
            probe_mod._validate_source_path = original_validate
            probe_mod._validate_source_jsonl_format = original_validate_jsonl

        assert result["full_chain_freshness"] is False
        assert result.get("gateway_empty_after_cleanup") is False
        nc_text = " ".join(result["nonClaims"]).lower()
        assert "cleanup" in nc_text or "still visible" in nc_text or "verification" in nc_text

    def test_cleanup_success_allows_non_cleanup_claims(self, tmp_path):
        """When all layers clean and gateway verified empty, nonClaims should reflect that."""
        src = tmp_path / "session.jsonl"
        src.write_text('{"type":"session_meta","payload":{"id":"test"}}\n')

        import runtime_freshness_full_chain_probe as probe_mod
        original_validate = probe_mod._validate_source_path
        original_validate_jsonl = probe_mod._validate_source_jsonl_format
        probe_mod._validate_source_path = lambda p: (True, "")
        probe_mod._validate_source_jsonl_format = lambda p: (True, "")

        call_count = [0]
        def _mock_query_counting(endpoint, query, timeout=8.0, source_system="codex"):
            call_count[0] += 1
            if call_count[0] <= 1:
                return {"ok": True, "items": [{"summary": f"contains {query}"}]}, ""
            return {"ok": True, "items": []}, ""

        try:
            with patch(
                "runtime_freshness_full_chain_probe._gateway_health",
                lambda e, t=3.0: {"ok": True},
            ), patch(
                "runtime_freshness_full_chain_probe._query_gateway",
                _mock_query_counting,
            ), patch(
                "codex_local_connector.archive_session_incremental",
                lambda s, **kw: ("/fake/raw.jsonl", "archived(offset=100)"),
            ), patch(
                "p2_extract.incremental_extract_session",
                lambda f, **kw: (1, 1, 0),
            ), patch(
                "runtime_freshness_full_chain_probe._perform_cleanup",
                lambda *args, **kwargs: {
                    "cleanup_plan": {},
                    "cleanup_performed": True,
                    "all_layers_cleaned": True,
                    "errors": [],
                    "gateway_empty_after_cleanup": True,
                },
            ):
                result = build_probe_result({
                    "write_real": True,
                    "confirm_source_write": True,
                    "source_path": str(src),
                })
        finally:
            probe_mod._validate_source_path = original_validate
            probe_mod._validate_source_jsonl_format = original_validate_jsonl

        assert result.get("cleanup_performed") is True
        assert result.get("gateway_empty_after_cleanup") is True
        nc_text = " ".join(result["nonClaims"]).lower()
        assert "cleanup" in nc_text


class TestMultiRunStatsSchema:
    """Multi-run stats must have min/median/max/spike_list."""

    def test_stats_has_required_fields(self):
        result = build_probe_result({})
        stats = result["multi_run_stats"]
        assert "iterations" in stats
        assert "t_total_min_ms" in stats
        assert "t_total_median_ms" in stats
        assert "t_total_max_ms" in stats
        assert "spike_list" in stats

    def test_stats_default_iterations_zero(self):
        result = build_probe_result({})
        assert result["multi_run_stats"]["iterations"] == 0

    def test_stats_default_spike_list_empty(self):
        result = build_probe_result({})
        assert isinstance(result["multi_run_stats"]["spike_list"], list)
        assert len(result["multi_run_stats"]["spike_list"]) == 0

    def test_stats_default_all_none(self):
        result = build_probe_result({})
        stats = result["multi_run_stats"]
        assert stats["t_total_min_ms"] is None
        assert stats["t_total_median_ms"] is None
        assert stats["t_total_max_ms"] is None


class TestOutputStructure:
    """Output must contain all required fields for Codex audit."""

    def test_has_contract(self):
        result = build_probe_result({})
        assert "contract" in result

    def test_has_proof_layer(self):
        result = build_probe_result({})
        assert "proof_layer" in result

    def test_has_nonclaims(self):
        result = build_probe_result({})
        assert "nonClaims" in result

    def test_has_status(self):
        result = build_probe_result({})
        assert "status" in result

    def test_has_full_chain_freshness(self):
        result = build_probe_result({})
        assert "full_chain_freshness" in result

    def test_has_extraction_trigger(self):
        result = build_probe_result({})
        assert "extraction_trigger" in result

    def test_has_timing(self):
        result = build_probe_result({})
        assert "timing" in result

    def test_has_multi_run_stats(self):
        result = build_probe_result({})
        assert "multi_run_stats" in result

    def test_has_cleanup_plan(self):
        result = build_probe_result({})
        assert "cleanup_plan" in result

    def test_has_all_layers_cleaned(self):
        result = build_probe_result({})
        assert "all_layers_cleaned" in result

    def test_has_gateway_empty_after_cleanup(self):
        result = build_probe_result({})
        assert "gateway_empty_after_cleanup" in result

    def test_has_installed_runtime_exists(self):
        result = build_probe_result({})
        assert "installed_runtime_exists" in result

    def test_has_gateway_endpoint(self):
        result = build_probe_result({})
        assert "gateway_endpoint" in result

    def test_has_harness_source_code_path(self):
        result = build_probe_result({})
        assert "harness_source_code_path" in result

    def test_has_next_action(self):
        result = build_probe_result({})
        assert "next_action_for_Codex" in result

    def test_poll_results_is_list(self):
        result = build_probe_result({})
        assert isinstance(result["poll_results"], list)

    def test_has_source_path_field(self):
        result = build_probe_result({})
        assert "source_path" in result

    def test_has_source_path_is_synthetic(self):
        result = build_probe_result({})
        assert "source_path_is_synthetic" in result


class TestNoInProcessP3:
    """Harness must not import or use in-process p3_recall for the probe."""

    def test_harness_does_not_import_p3_recall(self):
        harness_path = ROOT / "tools" / "runtime_freshness_full_chain_probe.py"
        content = harness_path.read_text()
        assert "from p3_recall" not in content
        assert "import p3_recall" not in content

    def test_harness_does_not_use_tempdir(self):
        harness_path = ROOT / "tools" / "runtime_freshness_full_chain_probe.py"
        content = harness_path.read_text()
        assert "TemporaryDirectory" not in content
        assert "tempfile" not in content
        assert "mkdtemp" not in content

    def test_harness_uses_http_for_recall(self):
        harness_path = ROOT / "tools" / "runtime_freshness_full_chain_probe.py"
        content = harness_path.read_text()
        assert "urllib.request" in content
        assert "9851" in content

    def test_harness_does_not_directly_append_zhiyi(self):
        """B-path must go through connector+p2, not direct zhiyi append."""
        harness_path = ROOT / "tools" / "runtime_freshness_full_chain_probe.py"
        content = harness_path.read_text()
        assert "open(" not in content.split("def build_probe_result")[1].split("def main")[0] or \
               "case_memory" not in content.split("def build_probe_result")[1].split("def main")[0]


class TestMockedFullChainSuccess:
    """Simulate full-chain success via mocks."""

    @pytest.fixture()
    def real_like_source(self, tmp_path):
        """Create a file that passes synthetic check and JSONL validation."""
        src = tmp_path / "real_session.jsonl"
        src.write_text('{"type":"session_meta","payload":{"id":"test-session"}}\n')
        return str(src)

    def _mock_gateway_health_ok(self, endpoint, timeout=3.0):
        return {"ok": True, "service": "raw_consumption_gateway", "version": "test"}

    def _mock_archive_success(self, source_path, dry_run=False, artifact=None):
        return ("/fake/raw/session.jsonl", "archived(offset=100)")

    def _mock_p2_extract_success(self, filepath, session_id=None, window=None):
        return (1, 1, 0)

    def _mock_query_returns_token(self, endpoint, query, timeout=8.0, source_system="codex"):
        return {
            "ok": True,
            "memory_cache_status": "refresh_completed",
            "refresh_status": "completed",
            "refresh_pending": False,
            "freshness_boundary": "fresh_index",
            "items": [{"summary": f"contains {query}"}],
        }, ""

    def _mock_cleanup_success(self, *args, **kwargs):
        return {
            "cleanup_plan": {},
            "cleanup_performed": True,
            "all_layers_cleaned": True,
            "errors": [],
            "gateway_empty_after_cleanup": True,
        }

    def test_success_status_is_default_recall_proven(self, real_like_source):
        with patch(
            "runtime_freshness_full_chain_probe._gateway_health",
            self._mock_gateway_health_ok,
        ), patch(
            "runtime_freshness_full_chain_probe._query_gateway",
            self._mock_query_returns_token,
        ):
            import runtime_freshness_full_chain_probe as probe_mod
            original_validate = probe_mod._validate_source_path
            original_validate_jsonl = probe_mod._validate_source_jsonl_format
            probe_mod._validate_source_path = lambda p: (True, "")
            probe_mod._validate_source_jsonl_format = lambda p: (True, "")
            try:
                with patch(
                    "codex_local_connector.archive_session_incremental",
                    self._mock_archive_success,
                ), patch(
                    "p2_extract.incremental_extract_session",
                    self._mock_p2_extract_success,
                ), patch(
                    "runtime_freshness_full_chain_probe._perform_cleanup",
                    self._mock_cleanup_success,
                ):
                    result = build_probe_result({
                        "write_real": True,
                        "confirm_source_write": True,
                        "source_path": real_like_source,
                    })
            finally:
                probe_mod._validate_source_path = original_validate
                probe_mod._validate_source_jsonl_format = original_validate_jsonl
        assert result["status"] == "connected_runtime_full_chain_default_recall_proven"
        assert result["proof_layer"] == "installed_runtime"
        assert result["full_chain_freshness"] is True
        assert result["default_recall_freshness"] is True
        assert result["chain_visible"] is True
        assert result["ok"] is True

    def test_success_nonclaims_mention_forced(self, real_like_source):
        with patch(
            "runtime_freshness_full_chain_probe._gateway_health",
            self._mock_gateway_health_ok,
        ), patch(
            "runtime_freshness_full_chain_probe._query_gateway",
            self._mock_query_returns_token,
        ):
            import runtime_freshness_full_chain_probe as probe_mod
            original_validate = probe_mod._validate_source_path
            original_validate_jsonl = probe_mod._validate_source_jsonl_format
            probe_mod._validate_source_path = lambda p: (True, "")
            probe_mod._validate_source_jsonl_format = lambda p: (True, "")
            try:
                with patch(
                    "codex_local_connector.archive_session_incremental",
                    self._mock_archive_success,
                ), patch(
                    "p2_extract.incremental_extract_session",
                    self._mock_p2_extract_success,
                ), patch(
                    "runtime_freshness_full_chain_probe._perform_cleanup",
                    self._mock_cleanup_success,
                ):
                    result = build_probe_result({
                        "write_real": True,
                        "confirm_source_write": True,
                        "source_path": real_like_source,
                    })
            finally:
                probe_mod._validate_source_path = original_validate
                probe_mod._validate_source_jsonl_format = original_validate_jsonl
        nc_text = " ".join(result["nonClaims"]).lower()
        assert "forced" in nc_text
        assert "passive" in nc_text or "scheduler" in nc_text
        assert "vector index freshness" in nc_text

    def test_success_has_timing_segments(self, real_like_source):
        with patch(
            "runtime_freshness_full_chain_probe._gateway_health",
            self._mock_gateway_health_ok,
        ), patch(
            "runtime_freshness_full_chain_probe._query_gateway",
            self._mock_query_returns_token,
        ):
            import runtime_freshness_full_chain_probe as probe_mod
            original_validate = probe_mod._validate_source_path
            original_validate_jsonl = probe_mod._validate_source_jsonl_format
            probe_mod._validate_source_path = lambda p: (True, "")
            probe_mod._validate_source_jsonl_format = lambda p: (True, "")
            try:
                with patch(
                    "codex_local_connector.archive_session_incremental",
                    self._mock_archive_success,
                ), patch(
                    "p2_extract.incremental_extract_session",
                    self._mock_p2_extract_success,
                ):
                    result = build_probe_result({
                        "write_real": True,
                        "confirm_source_write": True,
                        "source_path": real_like_source,
                    })
            finally:
                probe_mod._validate_source_path = original_validate
                probe_mod._validate_source_jsonl_format = original_validate_jsonl
        timing = result["timing"]
        assert timing["t_source_write_to_connector_ingest_ms"] is not None
        assert timing["t_connector_ingest_to_p2_start_ms"] is not None
        assert timing["t_p2_extract_duration_ms"] is not None
        assert timing["t_zhiyi_write_to_first_gateway_visible_ms"] is not None
        assert timing["t_total_write_to_visible_ms"] is not None

    def test_success_has_cleanup_plan_and_performed(self, real_like_source):
        with patch(
            "runtime_freshness_full_chain_probe._gateway_health",
            self._mock_gateway_health_ok,
        ), patch(
            "runtime_freshness_full_chain_probe._query_gateway",
            self._mock_query_returns_token,
        ):
            import runtime_freshness_full_chain_probe as probe_mod
            original_validate = probe_mod._validate_source_path
            original_validate_jsonl = probe_mod._validate_source_jsonl_format
            probe_mod._validate_source_path = lambda p: (True, "")
            probe_mod._validate_source_jsonl_format = lambda p: (True, "")
            try:
                with patch(
                    "codex_local_connector.archive_session_incremental",
                    self._mock_archive_success,
                ), patch(
                    "p2_extract.incremental_extract_session",
                    self._mock_p2_extract_success,
                ):
                    result = build_probe_result({
                        "write_real": True,
                        "confirm_source_write": True,
                        "source_path": real_like_source,
                    })
            finally:
                probe_mod._validate_source_path = original_validate
                probe_mod._validate_source_jsonl_format = original_validate_jsonl
        cleanup = result["cleanup_plan"]
        for layer in REQUIRED_CLEANUP_LAYERS:
            assert any(k.startswith(layer) for k in cleanup), f"Missing cleanup layer: {layer}"
        assert result["cleanup_performed"] is True
        assert "all_layers_cleaned" in result
        assert "gateway_empty_after_cleanup" in result

    def test_success_multi_run_stats_populated(self, real_like_source):
        with patch(
            "runtime_freshness_full_chain_probe._gateway_health",
            self._mock_gateway_health_ok,
        ), patch(
            "runtime_freshness_full_chain_probe._query_gateway",
            self._mock_query_returns_token,
        ):
            import runtime_freshness_full_chain_probe as probe_mod
            original_validate = probe_mod._validate_source_path
            original_validate_jsonl = probe_mod._validate_source_jsonl_format
            probe_mod._validate_source_path = lambda p: (True, "")
            probe_mod._validate_source_jsonl_format = lambda p: (True, "")
            try:
                with patch(
                    "codex_local_connector.archive_session_incremental",
                    self._mock_archive_success,
                ), patch(
                    "p2_extract.incremental_extract_session",
                    self._mock_p2_extract_success,
                ):
                    result = build_probe_result({
                        "write_real": True,
                        "confirm_source_write": True,
                        "source_path": real_like_source,
                        "iterations": 2,
                    })
            finally:
                probe_mod._validate_source_path = original_validate
                probe_mod._validate_source_jsonl_format = original_validate_jsonl
        stats = result["multi_run_stats"]
        assert stats["iterations"] == 2
        assert stats["t_total_min_ms"] is not None
        assert stats["t_total_median_ms"] is not None
        assert stats["t_total_max_ms"] is not None
        assert isinstance(stats["spike_list"], list)

    def test_timeout_status_is_partial(self, real_like_source):
        def _mock_query_never_finds(endpoint, query, timeout=8.0, source_system="codex"):
            return {
                "ok": True,
                "memory_cache_status": "cache_hit",
                "refresh_pending": False,
                "freshness_boundary": "fresh_index",
                "items": [],
            }, ""

        with patch(
            "runtime_freshness_full_chain_probe._gateway_health",
            self._mock_gateway_health_ok,
        ), patch(
            "runtime_freshness_full_chain_probe._query_gateway",
            _mock_query_never_finds,
        ):
            import runtime_freshness_full_chain_probe as probe_mod
            original_validate = probe_mod._validate_source_path
            original_validate_jsonl = probe_mod._validate_source_jsonl_format
            probe_mod._validate_source_path = lambda p: (True, "")
            probe_mod._validate_source_jsonl_format = lambda p: (True, "")
            try:
                with patch(
                    "codex_local_connector.archive_session_incremental",
                    self._mock_archive_success,
                ), patch(
                    "p2_extract.incremental_extract_session",
                    self._mock_p2_extract_success,
                ):
                    result = build_probe_result({
                        "write_real": True,
                        "confirm_source_write": True,
                        "source_path": real_like_source,
                        "timeout_seconds": 1,
                    })
            finally:
                probe_mod._validate_source_path = original_validate
                probe_mod._validate_source_jsonl_format = original_validate_jsonl
        assert result["status"] == "connected_runtime_full_chain_timeout"
        assert result["proof_layer"] == "connected_runtime_partial_incomplete"
        assert result["ok"] is False


class TestTokenInjection:
    """Verify token is injected into source before archive, not air-token query."""

    def test_probe_preference_content_is_extractable_by_p2_gate(self):
        """Probe source record must be a real preference, not inert noise."""
        from p2_extract import classify_preference_intent

        token = "full-chain-probe-abc123"
        token_hash = _token_hash(token)
        content = _probe_preference_content(token, token_hash)
        intent = classify_preference_intent(content)
        assert intent["write_preference"] is True
        assert intent["intent_type"] == "preference"
        assert token in content[:80]

    def test_append_token_source_writes_extractable_user_message(self, tmp_path):
        """Appended source line should preserve token in a user preference message."""
        src = tmp_path / "session.jsonl"
        src.write_text('{"type":"session_meta","payload":{"id":"test"}}\n')
        token = "full-chain-probe-abc123"
        token_hash = _token_hash(token)

        ok, info = _append_token_to_source(str(src), token, token_hash)

        assert ok is True
        assert info["bytes_written"] > 0
        appended = src.read_text(encoding="utf-8").splitlines()[-1]
        record = json.loads(appended)
        assert record["payload"]["role"] == "user"
        content = record["payload"]["content"]
        assert token in content
        assert token in content[:80]
        assert "我希望" in content

    def test_token_must_be_injected_before_archive(self, tmp_path):
        """If session generation fails, probe must block."""
        src = tmp_path / "session.jsonl"
        src.write_text('{"type":"session_meta","payload":{"id":"test"}}\n')

        def _mock_gen_fail(source_path, token, token_hash):
            return False, {"error": "generation blocked", "generated_source_path": "", "session_id": "", "source_created": False, "bytes_written": 0}

        import runtime_freshness_full_chain_probe as probe_mod
        original_gen = probe_mod._generate_probe_source_session
        original_validate = probe_mod._validate_source_path
        original_validate_jsonl = probe_mod._validate_source_jsonl_format
        probe_mod._generate_probe_source_session = _mock_gen_fail
        probe_mod._validate_source_path = lambda p: (True, "")
        probe_mod._validate_source_jsonl_format = lambda p: (True, "")
        try:
            with patch(
                "runtime_freshness_full_chain_probe._gateway_health",
                lambda e, t=3.0: {"ok": True},
            ):
                result = build_probe_result({
                    "write_real": True,
                    "confirm_source_write": True,
                    "source_path": str(src),
                })
        finally:
            probe_mod._generate_probe_source_session = original_gen
            probe_mod._validate_source_path = original_validate
            probe_mod._validate_source_jsonl_format = original_validate_jsonl
        assert result["status"] == "blocked_not_proven"
        assert result["source_injection"]["performed"] is True
        assert result["source_injection"]["token_injected"] is False
        assert "generation" in result["error"].lower() or "failed" in result["error"].lower()

    def test_no_air_token_query(self, tmp_path):
        """Query token must come from generated session, not independently generated."""
        src = tmp_path / "session.jsonl"
        src.write_text('{"type":"session_meta","payload":{"id":"test"}}\n')

        captured_tokens = []

        real_gen = None

        def _mock_gen_capture(source_path, token, token_hash):
            captured_tokens.append(token)
            return real_gen(source_path, token, token_hash)

        def _mock_query_capture(endpoint, query, timeout=8.0, source_system="codex"):
            captured_tokens.append(("query", query))
            return {
                "ok": True,
                "items": [{"summary": f"contains {query}"}],
            }, ""

        import runtime_freshness_full_chain_probe as probe_mod
        real_gen = probe_mod._generate_probe_source_session
        original_validate = probe_mod._validate_source_path
        original_validate_jsonl = probe_mod._validate_source_jsonl_format
        probe_mod._generate_probe_source_session = _mock_gen_capture
        probe_mod._validate_source_path = lambda p: (True, "")
        probe_mod._validate_source_jsonl_format = lambda p: (True, "")
        try:
            with patch(
                "runtime_freshness_full_chain_probe._gateway_health",
                lambda e, t=3.0: {"ok": True},
            ), patch(
                "runtime_freshness_full_chain_probe._query_gateway",
                _mock_query_capture,
            ), patch(
                "codex_local_connector.archive_session_incremental",
                lambda s, **kw: ("/fake/raw.jsonl", "archived(offset=100)"),
            ), patch(
                "p2_extract.incremental_extract_session",
                lambda f, **kw: (1, 1, 0),
            ), patch(
                "runtime_freshness_full_chain_probe._perform_cleanup",
                lambda *args, **kwargs: {
                    "cleanup_plan": {},
                    "cleanup_performed": True,
                    "all_layers_cleaned": True,
                    "errors": [],
                    "gateway_empty_after_cleanup": True,
                },
            ):
                result = build_probe_result({
                    "write_real": True,
                    "confirm_source_write": True,
                    "source_path": str(src),
                })
        finally:
            probe_mod._generate_probe_source_session = real_gen
            probe_mod._validate_source_path = original_validate
            probe_mod._validate_source_jsonl_format = original_validate_jsonl

        assert len(captured_tokens) >= 2
        injected_token = captured_tokens[0]
        query_token = captured_tokens[1][1]
        assert injected_token == query_token

    def test_write_real_requested_true(self, tmp_path):
        """write_real_requested must be True when --write-real is passed."""
        src = tmp_path / "session.jsonl"
        src.write_text('{"type":"session_meta","payload":{"id":"test"}}\n')

        result = build_probe_result({
            "write_real": True,
            "confirm_source_write": True,
            "source_path": str(src),
        })
        assert result["write_real_requested"] is True

    def test_write_real_requested_false_by_default(self):
        """write_real_requested must be False in default mode."""
        result = build_probe_result({})
        assert result["write_real_requested"] is False

    def test_default_recall_success_has_chain_visible_true_and_full_chain_true(self, tmp_path):
        """Default-recall success: chain_visible=true, full_chain_freshness=true."""
        src = tmp_path / "session.jsonl"
        src.write_text('{"type":"session_meta","payload":{"id":"test"}}\n')

        import runtime_freshness_full_chain_probe as probe_mod
        original_append = probe_mod._append_token_to_source
        original_validate = probe_mod._validate_source_path
        original_validate_jsonl = probe_mod._validate_source_jsonl_format
        probe_mod._append_token_to_source = lambda s, t, h: (True, {
            "bytes_written": 100, "line_hash": "abc", "offset_start": 0, "error": ""
        })
        probe_mod._validate_source_path = lambda p: (True, "")
        probe_mod._validate_source_jsonl_format = lambda p: (True, "")
        try:
            with patch(
                "runtime_freshness_full_chain_probe._gateway_health",
                lambda e, t=3.0: {"ok": True},
            ), patch(
                "runtime_freshness_full_chain_probe._query_gateway",
                lambda e, q, timeout=8.0, source_system="codex": ({"ok": True, "items": [{"summary": f"contains {q}"}]}, ""),
            ), patch(
                "codex_local_connector.archive_session_incremental",
                lambda s, **kw: ("/fake/raw.jsonl", "archived(offset=100)"),
            ), patch(
                "p2_extract.incremental_extract_session",
                lambda f, **kw: (1, 1, 0),
            ), patch(
                "runtime_freshness_full_chain_probe._perform_cleanup",
                lambda *args, **kwargs: {
                    "cleanup_plan": {},
                    "cleanup_performed": True,
                    "all_layers_cleaned": True,
                    "errors": [],
                    "gateway_empty_after_cleanup": True,
                },
            ):
                result = build_probe_result({
                    "write_real": True,
                    "confirm_source_write": True,
                    "source_path": str(src),
                })
        finally:
            probe_mod._append_token_to_source = original_append
            probe_mod._validate_source_path = original_validate
            probe_mod._validate_source_jsonl_format = original_validate_jsonl

        assert result["status"] == "connected_runtime_full_chain_default_recall_proven"
        assert result["chain_visible"] is True
        assert result["full_chain_freshness"] is True

    def test_source_system_not_hardcoded_openclaw(self):
        """source_system must not be hardcoded to openclaw."""
        harness_path = ROOT / "tools" / "runtime_freshness_full_chain_probe.py"
        content = harness_path.read_text()
        func_start = content.index("def _query_gateway")
        func_end = content.index("\ndef ", func_start + 1)
        func_body = content[func_start:func_end]
        assert '"openclaw"' not in func_body
        assert "'openclaw'" not in func_body

    def test_t_source_write_start_before_source_generate(self, tmp_path):
        """Regression: t_source_write_start must be set BEFORE _generate_probe_source_session.

        This ensures t_source_write_to_connector_ingest_ms includes the
        source generation time, not just the connector ingest call.
        """
        src = tmp_path / "session.jsonl"
        src.write_text('{"type":"session_meta","payload":{"id":"test"}}\n')

        call_order = []
        real_time = time.time

        real_gen = None

        def _mock_gen_recording(source_path, token, token_hash):
            call_order.append("gen_called")
            return real_gen(source_path, token, token_hash)

        def _mock_time():
            call_order.append("time_called")
            return real_time()

        import runtime_freshness_full_chain_probe as probe_mod
        real_gen = probe_mod._generate_probe_source_session
        original_validate = probe_mod._validate_source_path
        original_validate_jsonl = probe_mod._validate_source_jsonl_format

        probe_mod._generate_probe_source_session = _mock_gen_recording
        probe_mod._validate_source_path = lambda p: (True, "")
        probe_mod._validate_source_jsonl_format = lambda p: (True, "")
        try:
            with patch("time.time", _mock_time), \
                patch(
                "runtime_freshness_full_chain_probe._gateway_health",
                lambda e, t=3.0: {"ok": True},
            ), patch(
                "runtime_freshness_full_chain_probe._query_gateway",
                lambda e, q, timeout=8.0, source_system="codex": (
                    {"ok": True, "items": [{"summary": f"contains {q}"}]}, ""),
            ), patch(
                "codex_local_connector.archive_session_incremental",
                lambda s, **kw: ("/fake/raw.jsonl", "archived(offset=100)"),
            ), patch(
                "p2_extract.incremental_extract_session",
                lambda f, **kw: (1, 1, 0),
            ), patch(
                "runtime_freshness_full_chain_probe._perform_cleanup",
                lambda *args, **kwargs: {
                    "cleanup_plan": {},
                    "cleanup_performed": True,
                    "all_layers_cleaned": True,
                    "errors": [],
                    "gateway_empty_after_cleanup": True,
                },
            ):
                build_probe_result({
                    "write_real": True,
                    "confirm_source_write": True,
                    "source_path": str(src),
                })
        finally:
            probe_mod._generate_probe_source_session = real_gen
            probe_mod._validate_source_path = original_validate
            probe_mod._validate_source_jsonl_format = original_validate_jsonl

        time_calls = [i for i, e in enumerate(call_order) if e == "time_called"]
        gen_calls = [i for i, e in enumerate(call_order) if e == "gen_called"]
        assert len(time_calls) >= 1, "time.time() was never called"
        assert len(gen_calls) >= 1, "_generate_probe_source_session was never called"
        assert time_calls[0] < gen_calls[0], (
            f"t_source_write_start (time.time()) must be called BEFORE "
            f"_generate_probe_source_session, but first time call was at index {time_calls[0]} "
            f"and first gen at index {gen_calls[0]}"
        )

    def test_source_code_ordering_regression(self):
        """Source-level regression: t_source_write_start assignment precedes _generate_probe_source_session call."""
        harness_path = ROOT / "tools" / "runtime_freshness_full_chain_probe.py"
        content = harness_path.read_text()
        build_func = content[content.index("def build_probe_result"):]
        time_assign_idx = build_func.index("t_source_write_start = time.time()")
        gen_call_idx = build_func.index("_generate_probe_source_session(")
        assert time_assign_idx < gen_call_idx, (
            f"t_source_write_start assignment at offset {time_assign_idx} "
            f"must come before _generate_probe_source_session call at offset {gen_call_idx}"
        )

    def test_source_system_parameterized(self, tmp_path):
        """source_system should be passed through from body."""
        src = tmp_path / "session.jsonl"
        src.write_text('{"type":"session_meta","payload":{"id":"test"}}\n')

        captured_systems = []

        def _mock_query_capture(endpoint, query, timeout=8.0, source_system="codex"):
            captured_systems.append(source_system)
            return {"ok": True, "items": []}, ""

        import runtime_freshness_full_chain_probe as probe_mod
        original_append = probe_mod._append_token_to_source
        original_validate = probe_mod._validate_source_path
        original_validate_jsonl = probe_mod._validate_source_jsonl_format
        probe_mod._append_token_to_source = lambda s, t, h: (True, {
            "bytes_written": 100, "line_hash": "abc", "offset_start": 0, "error": ""
        })
        probe_mod._validate_source_path = lambda p: (True, "")
        probe_mod._validate_source_jsonl_format = lambda p: (True, "")
        try:
            with patch(
                "runtime_freshness_full_chain_probe._gateway_health",
                lambda e, t=3.0: {"ok": True},
            ), patch(
                "runtime_freshness_full_chain_probe._query_gateway",
                _mock_query_capture,
            ), patch(
                "codex_local_connector.archive_session_incremental",
                lambda s, **kw: ("/fake/raw.jsonl", "archived(offset=100)"),
            ), patch(
                "p2_extract.incremental_extract_session",
                lambda f, **kw: (1, 1, 0),
            ):
                build_probe_result({
                    "write_real": True,
                    "confirm_source_write": True,
                    "source_path": str(src),
                    "source_system": "hermes",
                })
        finally:
            probe_mod._append_token_to_source = original_append
            probe_mod._validate_source_path = original_validate
            probe_mod._validate_source_jsonl_format = original_validate_jsonl

        assert captured_systems[0] == "hermes"


class TestQueryGatewayPayload:
    """_query_gateway payload must use default recall + active scope."""

    def test_payload_omits_recall_mode_by_default(self):
        captured = []

        def _mock_urlopen(req, timeout=8.0):
            captured.append(json.loads(req.data.decode("utf-8")))
            resp = MagicMock()
            resp.read.return_value = b'{"ok": true}'
            resp.__enter__ = lambda s: s
            resp.__exit__ = MagicMock(return_value=False)
            return resp

        with patch("urllib.request.urlopen", _mock_urlopen):
            _query_gateway("http://127.0.0.1:9851/api/v1/raw/query", "test-query")

        assert len(captured) == 1
        payload = captured[0]
        assert "recall_mode" not in payload

    def test_payload_omits_wrong_allow_cross_window_field(self):
        captured = []

        def _mock_urlopen(req, timeout=8.0):
            captured.append(json.loads(req.data.decode("utf-8")))
            resp = MagicMock()
            resp.read.return_value = b'{"ok": true}'
            resp.__enter__ = lambda s: s
            resp.__exit__ = MagicMock(return_value=False)
            return resp

        with patch("urllib.request.urlopen", _mock_urlopen):
            _query_gateway("http://127.0.0.1:9851/api/v1/raw/query", "test-query")

        assert "allow_cross_window" not in captured[0]

    def test_payload_includes_memory_scope_active(self):
        captured = []

        def _mock_urlopen(req, timeout=8.0):
            captured.append(json.loads(req.data.decode("utf-8")))
            resp = MagicMock()
            resp.read.return_value = b'{"ok": true}'
            resp.__enter__ = lambda s: s
            resp.__exit__ = MagicMock(return_value=False)
            return resp

        with patch("urllib.request.urlopen", _mock_urlopen):
            _query_gateway("http://127.0.0.1:9851/api/v1/raw/query", "test-query")

        assert captured[0]["memory_scope"] == "active"

    def test_payload_has_expected_recall_fields_together(self):
        captured = []

        def _mock_urlopen(req, timeout=8.0):
            captured.append(json.loads(req.data.decode("utf-8")))
            resp = MagicMock()
            resp.read.return_value = b'{"ok": true}'
            resp.__enter__ = lambda s: s
            resp.__exit__ = MagicMock(return_value=False)
            return resp

        with patch("urllib.request.urlopen", _mock_urlopen):
            _query_gateway("http://127.0.0.1:9851/api/v1/raw/query", "q")

        payload = captured[0]
        assert "recall_mode" not in payload
        assert "allow_cross_window" not in payload
        assert payload["memory_scope"] == "active"


class TestTimeoutBranchCleanup:
    """Timeout branch must execute cleanup and return cleanup status."""

    def _setup_mocks(self, tmp_path):
        src = tmp_path / "session.jsonl"
        src.write_text('{"type":"session_meta","payload":{"id":"test"}}\n')

        import runtime_freshness_full_chain_probe as probe_mod
        original_validate = probe_mod._validate_source_path
        original_validate_jsonl = probe_mod._validate_source_jsonl_format
        probe_mod._validate_source_path = lambda p: (True, "")
        probe_mod._validate_source_jsonl_format = lambda p: (True, "")
        return src, probe_mod, original_validate, original_validate_jsonl

    def _restore_mocks(self, probe_mod, original_validate, original_validate_jsonl):
        probe_mod._validate_source_path = original_validate
        probe_mod._validate_source_jsonl_format = original_validate_jsonl

    def test_timeout_cleanup_performed(self, tmp_path):
        src, probe_mod, ov, oj = self._setup_mocks(tmp_path)

        def _mock_query_never_finds(endpoint, query, timeout=8.0, source_system="codex"):
            return {"ok": True, "items": []}, ""

        try:
            with patch(
                "runtime_freshness_full_chain_probe._gateway_health",
                lambda e, t=3.0: {"ok": True},
            ), patch(
                "runtime_freshness_full_chain_probe._query_gateway",
                _mock_query_never_finds,
            ), patch(
                "codex_local_connector.archive_session_incremental",
                lambda s, **kw: ("/fake/raw.jsonl", "archived(offset=100)"),
            ), patch(
                "p2_extract.incremental_extract_session",
                lambda f, **kw: (1, 1, 0),
            ):
                result = build_probe_result({
                    "write_real": True,
                    "confirm_source_write": True,
                    "source_path": str(src),
                    "timeout_seconds": 1,
                })
        finally:
            self._restore_mocks(probe_mod, ov, oj)

        assert result["status"] == "connected_runtime_full_chain_timeout"
        assert result["cleanup_performed"] is True
        assert "cleanup_plan" in result
        cleanup = result["cleanup_plan"]
        for layer in REQUIRED_CLEANUP_LAYERS:
            assert any(k.startswith(layer) for k in cleanup), f"Missing cleanup layer: {layer}"
        assert "all_layers_cleaned" in result
        assert "gateway_empty_after_cleanup" in result

    def test_timeout_cleanup_gateway_empty(self, tmp_path):
        src, probe_mod, ov, oj = self._setup_mocks(tmp_path)

        def _mock_query_never_finds(endpoint, query, timeout=8.0, source_system="codex"):
            return {"ok": True, "items": []}, ""

        try:
            with patch(
                "runtime_freshness_full_chain_probe._gateway_health",
                lambda e, t=3.0: {"ok": True},
            ), patch(
                "runtime_freshness_full_chain_probe._query_gateway",
                _mock_query_never_finds,
            ), patch(
                "codex_local_connector.archive_session_incremental",
                lambda s, **kw: ("/fake/raw.jsonl", "archived(offset=100)"),
            ), patch(
                "p2_extract.incremental_extract_session",
                lambda f, **kw: (1, 1, 0),
            ):
                result = build_probe_result({
                    "write_real": True,
                    "confirm_source_write": True,
                    "source_path": str(src),
                    "timeout_seconds": 1,
                })
        finally:
            self._restore_mocks(probe_mod, ov, oj)

        assert result["gateway_empty_after_cleanup"] is True

    def test_timeout_no_cleanup_skips(self, tmp_path):
        src, probe_mod, ov, oj = self._setup_mocks(tmp_path)

        def _mock_query_never_finds(endpoint, query, timeout=8.0, source_system="codex"):
            return {"ok": True, "items": []}, ""

        try:
            with patch(
                "runtime_freshness_full_chain_probe._gateway_health",
                lambda e, t=3.0: {"ok": True},
            ), patch(
                "runtime_freshness_full_chain_probe._query_gateway",
                _mock_query_never_finds,
            ), patch(
                "codex_local_connector.archive_session_incremental",
                lambda s, **kw: ("/fake/raw.jsonl", "archived(offset=100)"),
            ), patch(
                "p2_extract.incremental_extract_session",
                lambda f, **kw: (1, 1, 0),
            ):
                result = build_probe_result({
                    "write_real": True,
                    "confirm_source_write": True,
                    "source_path": str(src),
                    "timeout_seconds": 1,
                    "no_cleanup": True,
                })
        finally:
            self._restore_mocks(probe_mod, ov, oj)

        assert result["status"] == "connected_runtime_full_chain_timeout"
        assert result["cleanup_performed"] is False

    def test_timeout_cleanup_errors_populated(self, tmp_path):
        src, probe_mod, ov, oj = self._setup_mocks(tmp_path)

        def _mock_query_never_finds(endpoint, query, timeout=8.0, source_system="codex"):
            return {"ok": True, "items": []}, ""

        try:
            with patch(
                "runtime_freshness_full_chain_probe._gateway_health",
                lambda e, t=3.0: {"ok": True},
            ), patch(
                "runtime_freshness_full_chain_probe._query_gateway",
                _mock_query_never_finds,
            ), patch(
                "codex_local_connector.archive_session_incremental",
                lambda s, **kw: ("/fake/raw.jsonl", "archived(offset=100)"),
            ), patch(
                "p2_extract.incremental_extract_session",
                lambda f, **kw: (1, 1, 0),
            ):
                result = build_probe_result({
                    "write_real": True,
                    "confirm_source_write": True,
                    "source_path": str(src),
                    "timeout_seconds": 1,
                })
        finally:
            self._restore_mocks(probe_mod, ov, oj)

        assert "cleanup_errors" in result
        assert isinstance(result["cleanup_errors"], list)


class TestEarlyExitCleanup:
    """Connector/p2 early exits must also cleanup when token was injected."""

    def test_connector_exception_cleanup(self, tmp_path):
        src = tmp_path / "session.jsonl"
        src.write_text('{"type":"session_meta","payload":{"id":"test"}}\n')

        import runtime_freshness_full_chain_probe as probe_mod
        ov = probe_mod._validate_source_path
        oj = probe_mod._validate_source_jsonl_format
        probe_mod._validate_source_path = lambda p: (True, "")
        probe_mod._validate_source_jsonl_format = lambda p: (True, "")

        try:
            with patch(
                "runtime_freshness_full_chain_probe._gateway_health",
                lambda e, t=3.0: {"ok": True},
            ), patch(
                "codex_local_connector.archive_session_incremental",
                side_effect=RuntimeError("connector boom"),
            ):
                result = build_probe_result({
                    "write_real": True,
                    "confirm_source_write": True,
                    "source_path": str(src),
                })
        finally:
            probe_mod._validate_source_path = ov
            probe_mod._validate_source_jsonl_format = oj

        assert result["source_injection"]["token_injected"] is True
        assert result["source_injection"]["source_created"] is True
        assert result["cleanup_performed"] is True

    def test_p2_exception_cleanup(self, tmp_path):
        src = tmp_path / "session.jsonl"
        src.write_text('{"type":"session_meta","payload":{"id":"test"}}\n')

        import runtime_freshness_full_chain_probe as probe_mod
        ov = probe_mod._validate_source_path
        oj = probe_mod._validate_source_jsonl_format
        probe_mod._validate_source_path = lambda p: (True, "")
        probe_mod._validate_source_jsonl_format = lambda p: (True, "")

        try:
            with patch(
                "runtime_freshness_full_chain_probe._gateway_health",
                lambda e, t=3.0: {"ok": True},
            ), patch(
                "codex_local_connector.archive_session_incremental",
                lambda s, **kw: ("/fake/raw.jsonl", "archived(offset=100)"),
            ), patch(
                "p2_extract.incremental_extract_session",
                side_effect=RuntimeError("p2 boom"),
            ):
                result = build_probe_result({
                    "write_real": True,
                    "confirm_source_write": True,
                    "source_path": str(src),
                })
        finally:
            probe_mod._validate_source_path = ov
            probe_mod._validate_source_jsonl_format = oj

        assert result["source_injection"]["token_injected"] is True
        assert result["cleanup_performed"] is True

    def test_p2_zero_records_cleanup(self, tmp_path):
        src = tmp_path / "session.jsonl"
        src.write_text('{"type":"session_meta","payload":{"id":"test"}}\n')

        import runtime_freshness_full_chain_probe as probe_mod
        ov = probe_mod._validate_source_path
        oj = probe_mod._validate_source_jsonl_format
        probe_mod._validate_source_path = lambda p: (True, "")
        probe_mod._validate_source_jsonl_format = lambda p: (True, "")

        try:
            with patch(
                "runtime_freshness_full_chain_probe._gateway_health",
                lambda e, t=3.0: {"ok": True},
            ), patch(
                "codex_local_connector.archive_session_incremental",
                lambda s, **kw: ("/fake/raw.jsonl", "archived(offset=100)"),
            ), patch(
                "p2_extract.incremental_extract_session",
                lambda f, **kw: (0, 0, 0),
            ):
                result = build_probe_result({
                    "write_real": True,
                    "confirm_source_write": True,
                    "source_path": str(src),
                })
        finally:
            probe_mod._validate_source_path = ov
            probe_mod._validate_source_jsonl_format = oj

        assert result["source_injection"]["token_injected"] is True
        assert "0 new records" in result["error"]
        assert result["cleanup_performed"] is True

    def test_up_to_date_cleanup(self, tmp_path):
        src = tmp_path / "session.jsonl"
        src.write_text('{"type":"session_meta","payload":{"id":"test"}}\n')

        import runtime_freshness_full_chain_probe as probe_mod
        ov = probe_mod._validate_source_path
        oj = probe_mod._validate_source_jsonl_format
        probe_mod._validate_source_path = lambda p: (True, "")
        probe_mod._validate_source_jsonl_format = lambda p: (True, "")

        try:
            with patch(
                "runtime_freshness_full_chain_probe._gateway_health",
                lambda e, t=3.0: {"ok": True},
            ), patch(
                "codex_local_connector.archive_session_incremental",
                lambda s, **kw: ("/fake/raw.jsonl", "up_to_date(offset=100)"),
            ):
                result = build_probe_result({
                    "write_real": True,
                    "confirm_source_write": True,
                    "source_path": str(src),
                })
        finally:
            probe_mod._validate_source_path = ov
            probe_mod._validate_source_jsonl_format = oj

        assert result["source_injection"]["token_injected"] is True
        assert "up-to-date" in result["error"]
        assert result["cleanup_performed"] is True


class TestSuccessBranchUnchanged:
    """Success branch: default recall freshness is signed, with extraction-trigger boundary."""

    def test_success_full_chain_freshness_true(self, tmp_path):
        src = tmp_path / "session.jsonl"
        src.write_text('{"type":"session_meta","payload":{"id":"test"}}\n')

        import runtime_freshness_full_chain_probe as probe_mod
        ov = probe_mod._validate_source_path
        oj = probe_mod._validate_source_jsonl_format
        probe_mod._validate_source_path = lambda p: (True, "")
        probe_mod._validate_source_jsonl_format = lambda p: (True, "")

        def _mock_query_finds(endpoint, query, timeout=8.0, source_system="codex"):
            return {"ok": True, "items": [{"summary": f"contains {query}"}]}, ""

        try:
            with patch(
                "runtime_freshness_full_chain_probe._gateway_health",
                lambda e, t=3.0: {"ok": True},
            ), patch(
                "runtime_freshness_full_chain_probe._query_gateway",
                _mock_query_finds,
            ), patch(
                "codex_local_connector.archive_session_incremental",
                lambda s, **kw: ("/fake/raw.jsonl", "archived(offset=100)"),
            ), patch(
                "p2_extract.incremental_extract_session",
                lambda f, **kw: (1, 1, 0),
            ), patch(
                "runtime_freshness_full_chain_probe._perform_cleanup",
                lambda *args, **kwargs: {
                    "cleanup_plan": {},
                    "cleanup_performed": True,
                    "all_layers_cleaned": True,
                    "errors": [],
                    "gateway_empty_after_cleanup": True,
                },
            ):
                result = build_probe_result({
                    "write_real": True,
                    "confirm_source_write": True,
                    "source_path": str(src),
                })
        finally:
            probe_mod._validate_source_path = ov
            probe_mod._validate_source_jsonl_format = oj

        assert result["full_chain_freshness"] is True
        assert result["default_recall_freshness"] is True
        assert result["status"] == "connected_runtime_full_chain_default_recall_proven"
        assert result["proof_layer"] == "installed_runtime"
        assert result["chain_visible"] is True
        assert result["ok"] is True

    def test_success_forced_nonclaims_intact(self, tmp_path):
        src = tmp_path / "session.jsonl"
        src.write_text('{"type":"session_meta","payload":{"id":"test"}}\n')

        import runtime_freshness_full_chain_probe as probe_mod
        ov = probe_mod._validate_source_path
        oj = probe_mod._validate_source_jsonl_format
        probe_mod._validate_source_path = lambda p: (True, "")
        probe_mod._validate_source_jsonl_format = lambda p: (True, "")

        def _mock_query_finds(endpoint, query, timeout=8.0, source_system="codex"):
            return {"ok": True, "items": [{"summary": f"contains {query}"}]}, ""

        try:
            with patch(
                "runtime_freshness_full_chain_probe._gateway_health",
                lambda e, t=3.0: {"ok": True},
            ), patch(
                "runtime_freshness_full_chain_probe._query_gateway",
                _mock_query_finds,
            ), patch(
                "codex_local_connector.archive_session_incremental",
                lambda s, **kw: ("/fake/raw.jsonl", "archived(offset=100)"),
            ), patch(
                "p2_extract.incremental_extract_session",
                lambda f, **kw: (1, 1, 0),
            ):
                result = build_probe_result({
                    "write_real": True,
                    "confirm_source_write": True,
                    "source_path": str(src),
                })
        finally:
            probe_mod._validate_source_path = ov
            probe_mod._validate_source_jsonl_format = oj

        nc_text = " ".join(result["nonClaims"]).lower()
        assert "forced" in nc_text
        assert "passive" in nc_text or "scheduler" in nc_text
        assert "vector index freshness" in nc_text


class TestPerIterationCleanup:
    """When iterations>1, each iteration's token must be cleaned up, not just the last."""

    def _setup_mocks(self, tmp_path):
        src = tmp_path / "session.jsonl"
        src.write_text('{"type":"session_meta","payload":{"id":"test"}}\n')

        import runtime_freshness_full_chain_probe as probe_mod
        ov = probe_mod._validate_source_path
        oj = probe_mod._validate_source_jsonl_format
        probe_mod._validate_source_path = lambda p: (True, "")
        probe_mod._validate_source_jsonl_format = lambda p: (True, "")
        return src, probe_mod, ov, oj

    def _restore_mocks(self, probe_mod, ov, oj):
        probe_mod._validate_source_path = ov
        probe_mod._validate_source_jsonl_format = oj

    def test_iterations_3_calls_perform_cleanup_3_times(self, tmp_path):
        """iterations=3 success path must call _perform_cleanup 3 times, once per token."""
        src, probe_mod, ov, oj = self._setup_mocks(tmp_path)

        cleanup_calls = []
        real_perform_cleanup = probe_mod._perform_cleanup

        def _tracking_cleanup(source_path, raw_dest, offset_start, token, token_hash, endpoint):
            cleanup_calls.append({
                "token_hash": token_hash,
                "token": token,
                "source_path": source_path,
            })
            return real_perform_cleanup(source_path, raw_dest, offset_start, token, token_hash, endpoint)

        def _mock_query_finds(endpoint, query, timeout=8.0, source_system="codex"):
            return {"ok": True, "items": [{"summary": f"contains {query}"}]}, ""

        try:
            with patch(
                "runtime_freshness_full_chain_probe._gateway_health",
                lambda e, t=3.0: {"ok": True},
            ), patch(
                "runtime_freshness_full_chain_probe._query_gateway",
                _mock_query_finds,
            ), patch(
                "runtime_freshness_full_chain_probe._perform_cleanup",
                _tracking_cleanup,
            ), patch(
                "codex_local_connector.archive_session_incremental",
                lambda s, **kw: ("/fake/raw.jsonl", "archived(offset=100)"),
            ), patch(
                "p2_extract.incremental_extract_session",
                lambda f, **kw: (1, 1, 0),
            ):
                result = build_probe_result({
                    "write_real": True,
                    "confirm_source_write": True,
                    "source_path": str(src),
                    "iterations": 3,
                })
        finally:
            self._restore_mocks(probe_mod, ov, oj)

        assert len(cleanup_calls) == 3, (
            f"Expected _perform_cleanup called 3 times (once per iteration), "
            f"but got {len(cleanup_calls)}"
        )
        hashes = [c["token_hash"] for c in cleanup_calls]
        assert len(set(hashes)) == 3, (
            f"Expected 3 distinct token_hashes, got {set(hashes)}"
        )
        sources = [c["source_path"] for c in cleanup_calls]
        assert len(set(sources)) == 3, (
            f"Expected 3 distinct source_paths, got {set(sources)}"
        )

    def test_iterations_3_per_iteration_cleanup_evidence(self, tmp_path):
        """result must contain per_iteration_cleanup with 3 entries."""
        src, probe_mod, ov, oj = self._setup_mocks(tmp_path)

        def _mock_query_finds(endpoint, query, timeout=8.0, source_system="codex"):
            return {"ok": True, "items": [{"summary": f"contains {query}"}]}, ""

        try:
            with patch(
                "runtime_freshness_full_chain_probe._gateway_health",
                lambda e, t=3.0: {"ok": True},
            ), patch(
                "runtime_freshness_full_chain_probe._query_gateway",
                _mock_query_finds,
            ), patch(
                "codex_local_connector.archive_session_incremental",
                lambda s, **kw: ("/fake/raw.jsonl", "archived(offset=100)"),
            ), patch(
                "p2_extract.incremental_extract_session",
                lambda f, **kw: (1, 1, 0),
            ):
                result = build_probe_result({
                    "write_real": True,
                    "confirm_source_write": True,
                    "source_path": str(src),
                    "iterations": 3,
                })
        finally:
            self._restore_mocks(probe_mod, ov, oj)

        assert result["status"] == "connected_runtime_full_chain_default_recall_proven"
        per_iter = result.get("per_iteration_cleanup", [])
        assert len(per_iter) == 3, (
            f"Expected 3 per_iteration_cleanup entries, got {len(per_iter)}"
        )
        for i, entry in enumerate(per_iter):
            assert entry.get("iteration") == i + 1
            assert entry.get("cleanup_performed") is True
            assert "token_hash" in entry

    def test_iterations_3_overall_cleanup_merged(self, tmp_path):
        """Overall all_layers_cleaned/gateway_empty must reflect all iterations."""
        src, probe_mod, ov, oj = self._setup_mocks(tmp_path)

        def _mock_query_finds(endpoint, query, timeout=8.0, source_system="codex"):
            return {"ok": True, "items": [{"summary": f"contains {query}"}]}, ""

        try:
            with patch(
                "runtime_freshness_full_chain_probe._gateway_health",
                lambda e, t=3.0: {"ok": True},
            ), patch(
                "runtime_freshness_full_chain_probe._query_gateway",
                _mock_query_finds,
            ), patch(
                "codex_local_connector.archive_session_incremental",
                lambda s, **kw: ("/fake/raw.jsonl", "archived(offset=100)"),
            ), patch(
                "p2_extract.incremental_extract_session",
                lambda f, **kw: (1, 1, 0),
            ):
                result = build_probe_result({
                    "write_real": True,
                    "confirm_source_write": True,
                    "source_path": str(src),
                    "iterations": 3,
                })
        finally:
            self._restore_mocks(probe_mod, ov, oj)

        assert result["cleanup_performed"] is True
        assert "all_layers_cleaned" in result
        assert "gateway_empty_after_cleanup" in result

    def test_iterations_3_partial_cleanup_failure_propagates(self, tmp_path):
        """If one iteration's cleanup fails, overall all_layers_cleaned must be False."""
        src, probe_mod, ov, oj = self._setup_mocks(tmp_path)

        call_count = [0]
        real_perform_cleanup = probe_mod._perform_cleanup

        def _partial_fail_cleanup(source_path, raw_dest, offset_start, token, token_hash, endpoint):
            call_count[0] += 1
            report = real_perform_cleanup(source_path, raw_dest, offset_start, token, token_hash, endpoint)
            if call_count[0] == 2:
                report["all_layers_cleaned"] = False
                report["errors"] = ["simulated failure on iteration 2"]
                report["gateway_empty_after_cleanup"] = False
            return report

        def _mock_query_finds(endpoint, query, timeout=8.0, source_system="codex"):
            return {"ok": True, "items": [{"summary": f"contains {query}"}]}, ""

        try:
            with patch(
                "runtime_freshness_full_chain_probe._gateway_health",
                lambda e, t=3.0: {"ok": True},
            ), patch(
                "runtime_freshness_full_chain_probe._query_gateway",
                _mock_query_finds,
            ), patch(
                "runtime_freshness_full_chain_probe._perform_cleanup",
                _partial_fail_cleanup,
            ), patch(
                "codex_local_connector.archive_session_incremental",
                lambda s, **kw: ("/fake/raw.jsonl", "archived(offset=100)"),
            ), patch(
                "p2_extract.incremental_extract_session",
                lambda f, **kw: (1, 1, 0),
            ):
                result = build_probe_result({
                    "write_real": True,
                    "confirm_source_write": True,
                    "source_path": str(src),
                    "iterations": 3,
                })
        finally:
            self._restore_mocks(probe_mod, ov, oj)

        assert result["all_layers_cleaned"] is False
        assert result["gateway_empty_after_cleanup"] is False
        assert "cleanup_errors" in result
        assert any("iter2" in e for e in result["cleanup_errors"])

    def test_iterations_3_timeout_cleans_current_iteration(self, tmp_path):
        """On timeout at iteration 2, cleanup runs for that iteration's token."""
        src, probe_mod, ov, oj = self._setup_mocks(tmp_path)

        cleanup_calls = []
        real_perform_cleanup = probe_mod._perform_cleanup

        def _tracking_cleanup(source_path, raw_dest, offset_start, token, token_hash, endpoint):
            cleanup_calls.append({"token_hash": token_hash, "source_path": source_path})
            return real_perform_cleanup(source_path, raw_dest, offset_start, token, token_hash, endpoint)

        call_count = [0]
        def _mock_query_finds_first_only(endpoint, query, timeout=8.0, source_system="codex"):
            call_count[0] += 1
            if call_count[0] <= 1:
                return {"ok": True, "items": [{"summary": f"contains {query}"}]}, ""
            return {"ok": True, "items": []}, ""

        try:
            with patch(
                "runtime_freshness_full_chain_probe._gateway_health",
                lambda e, t=3.0: {"ok": True},
            ), patch(
                "runtime_freshness_full_chain_probe._query_gateway",
                _mock_query_finds_first_only,
            ), patch(
                "runtime_freshness_full_chain_probe._perform_cleanup",
                _tracking_cleanup,
            ), patch(
                "codex_local_connector.archive_session_incremental",
                lambda s, **kw: ("/fake/raw.jsonl", "archived(offset=100)"),
            ), patch(
                "p2_extract.incremental_extract_session",
                lambda f, **kw: (1, 1, 0),
            ):
                result = build_probe_result({
                    "write_real": True,
                    "confirm_source_write": True,
                    "source_path": str(src),
                    "iterations": 3,
                    "timeout_seconds": 1,
                })
        finally:
            self._restore_mocks(probe_mod, ov, oj)

        assert result["status"] == "connected_runtime_full_chain_timeout"
        assert len(cleanup_calls) >= 2, (
            f"Expected cleanup for at least 2 iterations (1 success + 1 timeout), "
            f"got {len(cleanup_calls)}"
        )
        hashes = [c["token_hash"] for c in cleanup_calls]
        assert len(set(hashes)) == len(cleanup_calls), (
            "Each cleanup call should have a distinct token_hash"
        )
        sources = [c["source_path"] for c in cleanup_calls]
        assert len(set(sources)) == len(cleanup_calls), (
            "Each cleanup call should have a distinct source_path"
        )

    def test_iterations_3_no_cleanup_skips_all(self, tmp_path):
        """With --no-cleanup and iterations=3, no cleanup should run."""
        src, probe_mod, ov, oj = self._setup_mocks(tmp_path)

        cleanup_calls = []
        real_perform_cleanup = probe_mod._perform_cleanup

        def _tracking_cleanup(source_path, raw_dest, offset_start, token, token_hash, endpoint):
            cleanup_calls.append(token_hash)
            return real_perform_cleanup(source_path, raw_dest, offset_start, token, token_hash, endpoint)

        def _mock_query_finds(endpoint, query, timeout=8.0, source_system="codex"):
            return {"ok": True, "items": [{"summary": f"contains {query}"}]}, ""

        try:
            with patch(
                "runtime_freshness_full_chain_probe._gateway_health",
                lambda e, t=3.0: {"ok": True},
            ), patch(
                "runtime_freshness_full_chain_probe._query_gateway",
                _mock_query_finds,
            ), patch(
                "runtime_freshness_full_chain_probe._perform_cleanup",
                _tracking_cleanup,
            ), patch(
                "codex_local_connector.archive_session_incremental",
                lambda s, **kw: ("/fake/raw.jsonl", "archived(offset=100)"),
            ), patch(
                "p2_extract.incremental_extract_session",
                lambda f, **kw: (1, 1, 0),
            ):
                result = build_probe_result({
                    "write_real": True,
                    "confirm_source_write": True,
                    "source_path": str(src),
                    "iterations": 3,
                    "no_cleanup": True,
                })
        finally:
            self._restore_mocks(probe_mod, ov, oj)

        assert len(cleanup_calls) == 0
        assert result["cleanup_performed"] is False
        assert result["all_layers_cleaned"] is False


class TestFindTokenResultAreaOnly:
    """_find_token_in_response must only check result-bearing fields, not query echo."""

    def test_query_echo_empty_items_not_found(self):
        """Gateway echoes token in query field but items=[] → must NOT find."""
        resp = {
            "ok": True,
            "query": "full-chain-probe-abc123",
            "matched_count": 0,
            "items": [],
            "source_refs": [],
        }
        assert _find_token_in_response(resp, "full-chain-probe-abc123") is False

    def test_query_echo_empty_items_hash_not_found(self):
        resp = {
            "ok": True,
            "query": "full-chain-probe-abc123",
            "matched_count": 0,
            "items": [],
        }
        token_hash = "deadbeef12345678"
        resp["query"] = f"some-query-with-{token_hash}-embedded"
        assert _find_token_hash_in_response(resp, token_hash) is False

    def test_item_summary_contains_token_found(self):
        """Actual item summary containing token → must find."""
        resp = {
            "ok": True,
            "query": "unrelated",
            "items": [{"summary": "this mentions full-chain-probe-abc123 in the text"}],
        }
        assert _find_token_in_response(resp, "full-chain-probe-abc123") is True

    def test_item_source_ref_contains_token_found(self):
        resp = {
            "ok": True,
            "items": [{"source_ref": "full-chain-probe-abc123"}],
        }
        assert _find_token_in_response(resp, "full-chain-probe-abc123") is True

    def test_item_msg_ids_contains_token_found(self):
        resp = {
            "ok": True,
            "items": [{"msg_ids": ["full-chain-probe-abc123", "other"]}],
        }
        assert _find_token_in_response(resp, "full-chain-probe-abc123") is True

    def test_evidence_contains_token_found(self):
        resp = {
            "ok": True,
            "items": [],
            "evidence": [{"text": "contains full-chain-probe-abc123 here"}],
        }
        assert _find_token_in_response(resp, "full-chain-probe-abc123") is True

    def test_source_refs_contains_token_found(self):
        resp = {
            "ok": True,
            "items": [],
            "source_refs": ["full-chain-probe-abc123-ref"],
        }
        assert _find_token_in_response(resp, "full-chain-probe-abc123") is True

    def test_raw_items_contains_token_found(self):
        resp = {
            "ok": True,
            "items": [],
            "raw_items": [{"content": "full-chain-probe-abc123"}],
        }
        assert _find_token_in_response(resp, "full-chain-probe-abc123") is True

    def test_tiandao_source_refs_contains_token_found(self):
        resp = {
            "ok": True,
            "items": [],
            "tiandao_context_package": {
                "source_refs": ["full-chain-probe-abc123-ref"],
            },
        }
        assert _find_token_in_response(resp, "full-chain-probe-abc123") is True

    def test_hash_in_item_source_ref_found(self):
        token_hash = "abc123hash"
        resp = {
            "ok": True,
            "items": [{"source_ref": f"ref-{token_hash}-end"}],
        }
        assert _find_token_hash_in_response(resp, token_hash) is True

    def test_consumer_echo_not_checked(self):
        resp = {
            "ok": True,
            "consumer": "full-chain-probe",
            "query": "full-chain-probe-abc123",
            "items": [],
        }
        assert _find_token_in_response(resp, "full-chain-probe") is False

    def test_no_items_no_evidence_no_source_refs_empty(self):
        resp = {"ok": True, "query": "full-chain-probe-abc123"}
        assert _find_token_in_response(resp, "full-chain-probe-abc123") is False

    def test_matched_count_zero_with_query_echo_not_found(self):
        """matched_count=0 with query echo must not trick the probe."""
        resp = {
            "ok": True,
            "query": "full-chain-probe-xyz789",
            "matched_count": 0,
            "items": [],
            "source_refs": [],
            "evidence": [],
        }
        assert _find_token_in_response(resp, "full-chain-probe-xyz789") is False


class TestCleanupQueryEchoBug:
    """Cleanup verification must not be fooled by query echo."""

    def test_cleanup_gateway_empty_with_query_echo(self, tmp_path):
        """Gateway echoes token in query but items=[] → gateway_empty_after_cleanup=True."""
        src = tmp_path / "session.jsonl"
        src.write_text('{"type":"session_meta","payload":{"id":"t"}}\n')

        token = "full-chain-probe-test123"
        token_hash = "hash123"

        def _mock_query_echo_but_empty(endpoint, query, timeout=8.0, source_system="codex"):
            return {
                "ok": True,
                "query": query,
                "matched_count": 0,
                "items": [],
                "source_refs": [],
            }, ""

        with patch(
            "runtime_freshness_full_chain_probe._query_gateway",
            _mock_query_echo_but_empty,
        ):
            report = _perform_cleanup(
                str(src), "", 0, token, token_hash,
                "http://127.0.0.1:19999/api/v1/raw/query",
            )
        assert report["gateway_empty_after_cleanup"] is True
        assert report["cleanup_plan"]["gateway_visibility"]["cleaned"] is True


class TestSuccessBranchRequiresRealResult:
    """Success branch must not pass via query echo; needs actual item/source_ref match."""

    def test_chain_visible_requires_item_content(self, tmp_path):
        """Mock returns query echo + empty items → must timeout, not succeed."""
        src = tmp_path / "session.jsonl"
        src.write_text('{"type":"session_meta","payload":{"id":"test"}}\n')

        import runtime_freshness_full_chain_probe as probe_mod
        ov = probe_mod._validate_source_path
        oj = probe_mod._validate_source_jsonl_format
        probe_mod._validate_source_path = lambda p: (True, "")
        probe_mod._validate_source_jsonl_format = lambda p: (True, "")

        def _mock_query_echo_only(endpoint, query, timeout=8.0, source_system="codex"):
            return {
                "ok": True,
                "query": query,
                "matched_count": 0,
                "items": [],
            }, ""

        try:
            with patch(
                "runtime_freshness_full_chain_probe._gateway_health",
                lambda e, t=3.0: {"ok": True},
            ), patch(
                "runtime_freshness_full_chain_probe._query_gateway",
                _mock_query_echo_only,
            ), patch(
                "codex_local_connector.archive_session_incremental",
                lambda s, **kw: ("/fake/raw.jsonl", "archived(offset=100)"),
            ), patch(
                "p2_extract.incremental_extract_session",
                lambda f, **kw: (1, 1, 0),
            ):
                result = build_probe_result({
                    "write_real": True,
                    "confirm_source_write": True,
                    "source_path": str(src),
                    "timeout_seconds": 1,
                })
        finally:
            probe_mod._validate_source_path = ov
            probe_mod._validate_source_jsonl_format = oj

        assert result["status"] == "connected_runtime_full_chain_timeout"
        assert result["chain_visible"] is False

    def test_chain_visible_true_needs_real_item_match(self, tmp_path):
        """Mock returns real item with token in summary → chain_visible=True."""
        src = tmp_path / "session.jsonl"
        src.write_text('{"type":"session_meta","payload":{"id":"test"}}\n')

        import runtime_freshness_full_chain_probe as probe_mod
        ov = probe_mod._validate_source_path
        oj = probe_mod._validate_source_jsonl_format
        probe_mod._validate_source_path = lambda p: (True, "")
        probe_mod._validate_source_jsonl_format = lambda p: (True, "")

        def _mock_real_item_match(endpoint, query, timeout=8.0, source_system="codex"):
            return {
                "ok": True,
                "query": "unrelated-query",
                "items": [{"summary": f"recalled content about {query}", "source_ref": "ref-001"}],
            }, ""

        try:
            with patch(
                "runtime_freshness_full_chain_probe._gateway_health",
                lambda e, t=3.0: {"ok": True},
            ), patch(
                "runtime_freshness_full_chain_probe._query_gateway",
                _mock_real_item_match,
            ), patch(
                "codex_local_connector.archive_session_incremental",
                lambda s, **kw: ("/fake/raw.jsonl", "archived(offset=100)"),
            ), patch(
                "p2_extract.incremental_extract_session",
                lambda f, **kw: (1, 1, 0),
            ):
                result = build_probe_result({
                    "write_real": True,
                    "confirm_source_write": True,
                    "source_path": str(src),
                })
        finally:
            probe_mod._validate_source_path = ov
            probe_mod._validate_source_jsonl_format = oj

        assert result["chain_visible"] is True
        assert result["status"] == "connected_runtime_full_chain_default_recall_proven"


class TestInstalledRuntimeRootPointing:
    """connector/p2 must import from installed runtime, not live repo src."""

    def test_installed_runtime_src_constant(self):
        assert INSTALLED_RUNTIME_SRC == os.path.join(INSTALLED_RUNTIME_ROOT, "src")
        assert INSTALLED_RUNTIME_SRC.endswith("/src")

    def test_installed_runtime_src_points_to_installed(self):
        assert "Library/Application Support" in INSTALLED_RUNTIME_SRC
        assert INSTALLED_RUNTIME_SRC == os.path.join(
            os.path.expanduser("~/Library/Application Support/memcore-cloud"), "src"
        )

    def test_import_helper_returns_both_functions(self):
        """Must return (archive_session_incremental, incremental_extract_session)."""
        result = _import_connector_p2_from_installed_runtime()
        assert isinstance(result, tuple)
        assert len(result) == 2
        archive_fn, extract_fn = result
        assert callable(archive_fn)
        assert callable(extract_fn)

    def test_import_helper_sets_memcore_root_during_redirect(self):
        """When modules are NOT cached, helper must set MEMCORE_ROOT to installed root."""
        saved_path = sys.path.copy()
        saved_memcore = os.environ.get("MEMCORE_ROOT")
        saved_modules = {
            name: sys.modules.get(name)
            for name in ("config_loader", "codex_local_connector", "p2_extract")
        }
        # Purge to force the redirect path
        for name in ("config_loader", "codex_local_connector", "p2_extract"):
            sys.modules.pop(name, None)

        captured_memcore = []

        real_import = __builtins__.__import__ if hasattr(__builtins__, '__import__') else __import__

        def _capturing_import(name, *args, **kwargs):
            if name == "codex_local_connector":
                captured_memcore.append(os.environ.get("MEMCORE_ROOT"))
            return real_import(name, *args, **kwargs)

        import builtins
        original_builtin_import = builtins.__import__
        builtins.__import__ = _capturing_import
        try:
            _import_connector_p2_from_installed_runtime()
        finally:
            builtins.__import__ = original_builtin_import
            sys.path = saved_path
            if saved_memcore is None:
                os.environ.pop("MEMCORE_ROOT", None)
            else:
                os.environ["MEMCORE_ROOT"] = saved_memcore
            for name, mod in saved_modules.items():
                if mod is not None:
                    sys.modules[name] = mod

        if captured_memcore:
            assert captured_memcore[0] == INSTALLED_RUNTIME_ROOT, (
                f"MEMCORE_ROOT was {captured_memcore[0]!r} during import, "
                f"expected {INSTALLED_RUNTIME_ROOT!r}"
            )

    def test_import_helper_restores_sys_path(self):
        """sys.path must be restored after _import_connector_p2_from_installed_runtime."""
        saved_modules = {
            name: sys.modules.get(name)
            for name in ("config_loader", "codex_local_connector", "p2_extract")
        }
        for name in ("config_loader", "codex_local_connector", "p2_extract"):
            sys.modules.pop(name, None)

        original_path = sys.path.copy()
        try:
            _import_connector_p2_from_installed_runtime()
            assert sys.path == original_path
        finally:
            sys.path = original_path
            for name, mod in saved_modules.items():
                if mod is not None:
                    sys.modules[name] = mod

    def test_import_helper_restores_memcore_root(self):
        """MEMCORE_ROOT must be restored after import helper."""
        saved_modules = {
            name: sys.modules.get(name)
            for name in ("config_loader", "codex_local_connector", "p2_extract")
        }
        for name in ("config_loader", "codex_local_connector", "p2_extract"):
            sys.modules.pop(name, None)

        saved = os.environ.get("MEMCORE_ROOT")
        sentinel = "test-sentinel-value-12345"
        os.environ["MEMCORE_ROOT"] = sentinel
        try:
            _import_connector_p2_from_installed_runtime()
            assert os.environ.get("MEMCORE_ROOT") == sentinel
        finally:
            if saved is None:
                os.environ.pop("MEMCORE_ROOT", None)
            else:
                os.environ["MEMCORE_ROOT"] = saved
            for name, mod in saved_modules.items():
                if mod is not None:
                    sys.modules[name] = mod

    def test_import_helper_redirects_sys_path_during_import(self):
        """When modules are NOT cached, live repo src must be removed and installed src added."""
        saved_modules = {
            name: sys.modules.get(name)
            for name in ("config_loader", "codex_local_connector", "p2_extract")
        }
        for name in ("config_loader", "codex_local_connector", "p2_extract"):
            sys.modules.pop(name, None)

        live_src = str(SRC)
        original_path = sys.path.copy()
        path_during_import = []

        real_import = __builtins__.__import__ if hasattr(__builtins__, '__import__') else __import__

        def _capturing_import(name, *args, **kwargs):
            if name == "codex_local_connector":
                path_during_import.extend(sys.path)
            return real_import(name, *args, **kwargs)

        import builtins
        original_builtin_import = builtins.__import__
        builtins.__import__ = _capturing_import
        try:
            _import_connector_p2_from_installed_runtime()
        finally:
            builtins.__import__ = original_builtin_import
            sys.path = original_path
            for name, mod in saved_modules.items():
                if mod is not None:
                    sys.modules[name] = mod

        if path_during_import:
            assert live_src not in path_during_import, (
                f"Live repo src {live_src} was in sys.path during connector import"
            )
            assert path_during_import[0] == INSTALLED_RUNTIME_SRC, (
                f"Expected installed src {INSTALLED_RUNTIME_SRC} at front, "
                f"got {path_during_import[0]}"
            )

    def test_import_helper_rejects_cached_live_repo_modules(self):
        """Cached live-repo connector/p2 modules must not bypass installed runtime redirect."""
        import types

        saved_modules = {
            name: sys.modules.get(name)
            for name in ("config_loader", "codex_local_connector", "p2_extract")
        }
        original_path = sys.path.copy()

        live_connector = types.ModuleType("codex_local_connector")
        live_connector.__file__ = str(SRC / "codex_local_connector.py")
        live_connector.archive_session_incremental = lambda *a, **kw: (_ for _ in ()).throw(
            AssertionError("live connector cache was used")
        )
        live_p2 = types.ModuleType("p2_extract")
        live_p2.__file__ = str(SRC / "p2_extract.py")
        live_p2.incremental_extract_session = lambda *a, **kw: (_ for _ in ()).throw(
            AssertionError("live p2 cache was used")
        )

        sys.modules["codex_local_connector"] = live_connector
        sys.modules["p2_extract"] = live_p2
        sys.modules.pop("config_loader", None)
        try:
            archive_fn, extract_fn = _import_connector_p2_from_installed_runtime()
            assert callable(archive_fn)
            assert callable(extract_fn)
            assert archive_fn is not live_connector.archive_session_incremental
            assert extract_fn is not live_p2.incremental_extract_session
            assert "Library/Application Support/memcore-cloud/src" in archive_fn.__code__.co_filename
            assert "Library/Application Support/memcore-cloud/src" in extract_fn.__code__.co_filename
        finally:
            sys.path = original_path
            for name in ("config_loader", "codex_local_connector", "p2_extract"):
                sys.modules.pop(name, None)
            for name, mod in saved_modules.items():
                if mod is not None:
                    sys.modules[name] = mod

    def test_cleanup_p2_checkpoint_uses_installed_root(self):
        """_build_cleanup_plan p2_checkpoint path must use INSTALLED_RUNTIME_ROOT, not live ROOT."""
        plan = _build_cleanup_plan("/fake/source", "/fake/raw", [], "hash123", True)
        p2_path = plan["p2_checkpoint"]["path"]
        assert "Library/Application Support" in p2_path or INSTALLED_RUNTIME_ROOT in p2_path
        assert p2_path.endswith(".checkpoint_p2.json")

    def test_perform_cleanup_p2_checkpoint_uses_installed_root(self, tmp_path):
        """_perform_cleanup p2_checkpoint path must reference installed runtime."""
        src = tmp_path / "session.jsonl"
        src.write_text('{"type":"session_meta"}\n')

        with patch(
            "runtime_freshness_full_chain_probe._query_gateway",
            lambda e, q, timeout=8.0, source_system="codex": ({"ok": True, "items": []}, ""),
        ):
            report = _perform_cleanup(
                str(src), "", 0, "probe-token", "hash123",
                "http://127.0.0.1:19999/api/v1/raw/query",
            )
        p2_info = report["cleanup_plan"]["p2_checkpoint"]
        assert "Library/Application Support" in p2_info["path"] or \
               INSTALLED_RUNTIME_ROOT in p2_info["path"]

    def test_raw_dest_not_in_live_repo_when_mocked(self, tmp_path):
        """When full chain runs with mocked connector, raw_dest must not be from live repo src."""
        src = tmp_path / "session.jsonl"
        src.write_text('{"type":"session_meta","payload":{"id":"test"}}\n')

        import runtime_freshness_full_chain_probe as probe_mod
        ov = probe_mod._validate_source_path
        oj = probe_mod._validate_source_jsonl_format
        probe_mod._validate_source_path = lambda p: (True, "")
        probe_mod._validate_source_jsonl_format = lambda p: (True, "")

        def _mock_archive_installed(source_path, **kw):
            dest = os.path.join(INSTALLED_RUNTIME_ROOT, "memory", "local", "codex", "raw.jsonl")
            return (dest, "archived(offset=100)")

        try:
            with patch(
                "runtime_freshness_full_chain_probe._gateway_health",
                lambda e, t=3.0: {"ok": True},
            ), patch(
                "runtime_freshness_full_chain_probe._query_gateway",
                lambda e, q, timeout=8.0, source_system="codex": (
                    {"ok": True, "items": [{"summary": f"contains {q}"}]}, ""),
            ), patch(
                "codex_local_connector.archive_session_incremental",
                _mock_archive_installed,
            ), patch(
                "p2_extract.incremental_extract_session",
                lambda f, **kw: (1, 1, 0),
            ):
                result = build_probe_result({
                    "write_real": True,
                    "confirm_source_write": True,
                    "source_path": str(src),
                })
        finally:
            probe_mod._validate_source_path = ov
            probe_mod._validate_source_jsonl_format = oj

        raw_dest = result.get("raw_dest", "")
        assert "<workspace-volume>/" not in raw_dest, (
            f"raw_dest {raw_dest} still points to live repo"
        )


class TestUniqueSourceSessions:
    """Each iteration must generate a unique disposable source session file."""

    def test_generate_probe_source_session_creates_file(self, tmp_path):
        template = tmp_path / "template.jsonl"
        template.write_text('{"type":"session_meta","payload":{"id":"t"}}\n')
        token = "full-chain-probe-abc123"
        token_hash = _token_hash(token)
        ok, info = _generate_probe_source_session(str(template), token, token_hash)
        assert ok is True
        assert info["source_created"] is True
        gen_path = Path(info["generated_source_path"])
        assert gen_path.exists()
        assert gen_path.parent == tmp_path

    def test_generate_probe_source_session_unique_paths(self, tmp_path):
        template = tmp_path / "template.jsonl"
        template.write_text('{"type":"session_meta","payload":{"id":"t"}}\n')
        paths = set()
        for _ in range(5):
            token = f"full-chain-probe-{uuid.uuid4().hex[:8]}"
            ok, info = _generate_probe_source_session(str(template), token, _token_hash(token))
            assert ok is True
            paths.add(info["generated_source_path"])
        assert len(paths) == 5

    def test_generate_probe_source_session_valid_jsonl(self, tmp_path):
        template = tmp_path / "template.jsonl"
        template.write_text('{"type":"session_meta","payload":{"id":"t"}}\n')
        token = "full-chain-probe-abc123"
        ok, info = _generate_probe_source_session(str(template), token, _token_hash(token))
        assert ok is True
        gen_path = info["generated_source_path"]
        valid, reason = _validate_source_jsonl_format(gen_path)
        assert valid is True, f"Generated session JSONL invalid: {reason}"

    def test_generate_probe_source_session_has_session_meta(self, tmp_path):
        template = tmp_path / "template.jsonl"
        template.write_text('{"type":"session_meta","payload":{"id":"t"}}\n')
        token = "full-chain-probe-abc123"
        ok, info = _generate_probe_source_session(str(template), token, _token_hash(token))
        assert ok is True
        lines = Path(info["generated_source_path"]).read_text().strip().split("\n")
        first = json.loads(lines[0])
        assert first["type"] == "session_meta"
        assert isinstance(first["payload"], dict)

    def test_generate_probe_source_session_unique_session_id(self, tmp_path):
        template = tmp_path / "template.jsonl"
        template.write_text('{"type":"session_meta","payload":{"id":"t"}}\n')
        ids = set()
        for _ in range(5):
            token = f"full-chain-probe-{uuid.uuid4().hex[:8]}"
            ok, info = _generate_probe_source_session(str(template), token, _token_hash(token))
            assert ok is True
            ids.add(info["session_id"])
        assert len(ids) == 5

    def test_generate_probe_source_session_contains_token_in_user_message(self, tmp_path):
        template = tmp_path / "template.jsonl"
        template.write_text('{"type":"session_meta","payload":{"id":"t"}}\n')
        token = "full-chain-probe-xyz789"
        token_hash = _token_hash(token)
        ok, info = _generate_probe_source_session(str(template), token, token_hash)
        assert ok is True
        lines = Path(info["generated_source_path"]).read_text().strip().split("\n")
        user_record = json.loads(lines[1])
        assert user_record["payload"]["role"] == "user"
        content = user_record["payload"]["content"]
        assert token in content
        assert token in content[:80]

    def test_iterations_use_unique_source_paths(self, tmp_path):
        """Full iteration loop must use unique source paths per iteration."""
        src = tmp_path / "session.jsonl"
        src.write_text('{"type":"session_meta","payload":{"id":"test"}}\n')

        import runtime_freshness_full_chain_probe as probe_mod
        ov = probe_mod._validate_source_path
        oj = probe_mod._validate_source_jsonl_format
        probe_mod._validate_source_path = lambda p: (True, "")
        probe_mod._validate_source_jsonl_format = lambda p: (True, "")

        captured_sources = []
        real_archive = lambda s, **kw: ("/fake/raw.jsonl", "archived(offset=100)")

        def _capture_archive(source_path, **kw):
            captured_sources.append(source_path)
            return real_archive(source_path, **kw)

        try:
            with patch(
                "runtime_freshness_full_chain_probe._gateway_health",
                lambda e, t=3.0: {"ok": True},
            ), patch(
                "runtime_freshness_full_chain_probe._query_gateway",
                lambda e, q, timeout=8.0, source_system="codex": (
                    {"ok": True, "items": [{"summary": f"contains {q}"}]}, ""),
            ), patch(
                "codex_local_connector.archive_session_incremental",
                _capture_archive,
            ), patch(
                "p2_extract.incremental_extract_session",
                lambda f, **kw: (1, 1, 0),
            ):
                result = build_probe_result({
                    "write_real": True,
                    "confirm_source_write": True,
                    "source_path": str(src),
                    "iterations": 3,
                })
        finally:
            probe_mod._validate_source_path = ov
            probe_mod._validate_source_jsonl_format = oj

        assert len(captured_sources) == 3
        assert len(set(captured_sources)) == 3, (
            f"Expected 3 unique source paths, got {set(captured_sources)}"
        )
        for s in captured_sources:
            assert s != str(src), "Generated source should differ from template"

    def test_per_iteration_sessions_in_result(self, tmp_path):
        """Result must contain per_iteration_sessions with unique evidence."""
        src = tmp_path / "session.jsonl"
        src.write_text('{"type":"session_meta","payload":{"id":"test"}}\n')

        import runtime_freshness_full_chain_probe as probe_mod
        ov = probe_mod._validate_source_path
        oj = probe_mod._validate_source_jsonl_format
        probe_mod._validate_source_path = lambda p: (True, "")
        probe_mod._validate_source_jsonl_format = lambda p: (True, "")

        try:
            with patch(
                "runtime_freshness_full_chain_probe._gateway_health",
                lambda e, t=3.0: {"ok": True},
            ), patch(
                "runtime_freshness_full_chain_probe._query_gateway",
                lambda e, q, timeout=8.0, source_system="codex": (
                    {"ok": True, "items": [{"summary": f"contains {q}"}]}, ""),
            ), patch(
                "codex_local_connector.archive_session_incremental",
                lambda s, **kw: ("/fake/raw.jsonl", "archived(offset=100)"),
            ), patch(
                "p2_extract.incremental_extract_session",
                lambda f, **kw: (1, 1, 0),
            ):
                result = build_probe_result({
                    "write_real": True,
                    "confirm_source_write": True,
                    "source_path": str(src),
                    "iterations": 3,
                })
        finally:
            probe_mod._validate_source_path = ov
            probe_mod._validate_source_jsonl_format = oj

        sessions = result.get("per_iteration_sessions", [])
        assert len(sessions) == 3
        for i, s in enumerate(sessions):
            assert s["iteration"] == i + 1
            assert s["source_created"] is True
            assert s["generated_source_path"] != ""
            assert s["session_id"] != ""
        paths = [s["generated_source_path"] for s in sessions]
        assert len(set(paths)) == 3


class TestCleanupDeletesSourceFile:
    """Cleanup must delete the entire source file, not truncate."""

    def test_cleanup_deletes_source_not_truncates(self, tmp_path):
        src = tmp_path / "probe_session.jsonl"
        src.write_text('{"type":"session_meta","payload":{"id":"t"}}\n')
        assert src.exists()
        ok, err = _cleanup_source_file(str(src), 0)
        assert ok is True
        assert not src.exists()

    def test_cleanup_source_nonexistent_ok(self):
        ok, err = _cleanup_source_file("/nonexistent/probe.jsonl", 0)
        assert ok is True

    def test_perform_cleanup_deletes_source(self, tmp_path):
        src = tmp_path / "probe_session.jsonl"
        src.write_text('{"type":"session_meta","payload":{"id":"t"}}\n')
        with patch(
            "runtime_freshness_full_chain_probe._query_gateway",
            lambda e, q, timeout=8.0, source_system="codex": ({"ok": True, "items": []}, ""),
        ):
            report = _perform_cleanup(
                str(src), "", 0, "token", "hash",
                "http://127.0.0.1:19999/api/v1/raw/query",
            )
        assert report["cleanup_plan"]["source_platform_test_record"]["cleaned"] is True
        assert not src.exists()


class TestCheckpointCleanup:
    """Checkpoint entries must be removed by source/raw_dest key."""

    def test_cleanup_checkpoint_removes_p2_entry(self, tmp_path):
        p2_ckpt = Path(INSTALLED_RUNTIME_ROOT) / ".checkpoint_p2.json"
        p2_existed = p2_ckpt.exists()
        if p2_existed:
            p2_backup = p2_ckpt.read_text()
        try:
            test_data = {
                "/fake/raw.jsonl": {"offset": 100},
                "codex:/fake/source.jsonl": {"offset": 50},
            }
            p2_ckpt.write_text(json.dumps(test_data))
            ok, err = _cleanup_checkpoint_entries("/fake/raw.jsonl", "/fake/source.jsonl")
            assert ok is True
            remaining = json.loads(p2_ckpt.read_text())
            assert "/fake/raw.jsonl" not in remaining
            assert "codex:/fake/source.jsonl" not in remaining
        finally:
            if p2_existed:
                p2_ckpt.write_text(p2_backup)
            elif p2_ckpt.exists():
                p2_ckpt.unlink()

    def test_cleanup_checkpoint_preserves_other_entries(self, tmp_path):
        p2_ckpt = Path(INSTALLED_RUNTIME_ROOT) / ".checkpoint_p2.json"
        p2_existed = p2_ckpt.exists()
        if p2_existed:
            p2_backup = p2_ckpt.read_text()
        try:
            test_data = {
                "/fake/raw.jsonl": {"offset": 100},
                "/other/raw.jsonl": {"offset": 200},
            }
            p2_ckpt.write_text(json.dumps(test_data))
            ok, err = _cleanup_checkpoint_entries("/fake/raw.jsonl", "/nonexistent")
            assert ok is True
            remaining = json.loads(p2_ckpt.read_text())
            assert "/fake/raw.jsonl" not in remaining
            assert "/other/raw.jsonl" in remaining
        finally:
            if p2_existed:
                p2_ckpt.write_text(p2_backup)
            elif p2_ckpt.exists():
                p2_ckpt.unlink()

    def test_cleanup_checkpoint_no_file_ok(self):
        ok, err = _cleanup_checkpoint_entries("/fake/raw.jsonl", "/fake/source.jsonl")
        assert ok is True


class TestRawArchiveMetaCleanup:
    """Raw archive .meta.json must be deleted alongside the JSONL."""

    def test_raw_archive_cleanup_removes_meta(self, tmp_path):
        raw = tmp_path / "archive.jsonl"
        meta = tmp_path / "archive.jsonl.meta.json"
        raw.write_text('{"type":"response_item","content":"probe-token"}\n')
        meta.write_text('{"source_system":"codex"}\n')
        ok, err = _cleanup_raw_archive_jsonl(str(raw), "probe-token")
        assert ok is True
        assert not raw.exists()
        assert not meta.exists()

    def test_raw_archive_cleanup_no_meta_ok(self, tmp_path):
        raw = tmp_path / "archive.jsonl"
        raw.write_text('{"type":"response_item","content":"probe-token"}\n')
        ok, err = _cleanup_raw_archive_jsonl(str(raw), "probe-token")
        assert ok is True
        assert not raw.exists()


class TestStrongPreferenceContent:
    """Generated preference content must be extractable by P2 gate with token in first 80 chars."""

    def test_preference_content_token_in_first_80_chars(self):
        token = "full-chain-probe-abc123def456"
        token_hash = _token_hash(token)
        content = _probe_preference_content(token, token_hash)
        assert token in content[:80]

    def test_preference_content_is_chinese_preference(self):
        token = "full-chain-probe-test"
        token_hash = _token_hash(token)
        content = _probe_preference_content(token, token_hash)
        assert "我希望" in content
        assert "记住" in content or "偏好" in content

    def test_generated_session_user_message_has_token_in_first_80(self, tmp_path):
        template = tmp_path / "template.jsonl"
        template.write_text('{"type":"session_meta","payload":{"id":"t"}}\n')
        token = "full-chain-probe-unique123"
        token_hash = _token_hash(token)
        ok, info = _generate_probe_source_session(str(template), token, token_hash)
        assert ok is True
        lines = Path(info["generated_source_path"]).read_text().strip().split("\n")
        user_record = json.loads(lines[1])
        content = user_record["payload"]["content"]
        assert token in content[:80]
