"""
Tests for runtime_freshness_write_to_recall_probe.

These tests verify:
1. Harness refuses fake runtime (tempdir, in-process, direct-jsonl)
2. Default mode outputs proof_layer=source_code + status=blocked_not_proven
3. Missing gateway yields blocked_not_proven
4. Missing installed runtime yields blocked_not_proven
5. output structure contains required proof_layer/nonClaims fields
"""

import json
import os
import sys
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

from runtime_freshness_write_to_recall_probe import (
    build_probe_result,
    PROBE_CONTRACT,
    INSTALLED_RUNTIME_ROOT,
    INSTALLED_CASE_MEMORY,
    DEFAULT_GATEWAY_ENDPOINT,
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

    def test_default_has_nonclaims(self):
        result = build_probe_result({})
        assert isinstance(result["nonClaims"], list)
        assert len(result["nonClaims"]) > 0

    def test_default_nonclaims_mention_connected_runtime(self):
        result = build_probe_result({})
        nc_text = " ".join(result["nonClaims"]).lower()
        assert "connected_runtime" in nc_text or "not measured" in nc_text

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


class TestGuardAgainstFakeRuntime:
    """Verify harness cannot be tricked into claiming runtime proof."""

    def test_tempdir_not_treated_as_runtime(self, tmp_path):
        fake_case = tmp_path / "zhiyi" / "case_memory" / "case_memory.jsonl"
        fake_case.parent.mkdir(parents=True)
        fake_case.write_text('{"exp_id":"fake"}\n')
        result = build_probe_result({
            "installed_case_memory": str(fake_case),
        })
        assert result["proof_layer"] == "source_code"
        assert result["status"] == "blocked_not_proven"

    def test_no_write_without_write_real_flag(self, tmp_path):
        fake_case = tmp_path / "zhiyi" / "case_memory" / "case_memory.jsonl"
        fake_case.parent.mkdir(parents=True)
        fake_case.write_text('{"exp_id":"fake"}\n')
        result = build_probe_result({
            "installed_case_memory": str(fake_case),
        })
        assert result["write_performed"] is False

    def test_explicit_write_real_false_blocked(self):
        result = build_probe_result({"write_real": False})
        assert result["status"] == "blocked_not_proven"
        assert result["proof_layer"] == "source_code"


class TestMissingGateway:
    """Gateway unreachable yields blocked_not_proven."""

    def test_gateway_down_blocked(self, tmp_path):
        fake_case = tmp_path / "zhiyi" / "case_memory" / "case_memory.jsonl"
        fake_case.parent.mkdir(parents=True)
        fake_case.write_text('{"exp_id":"fake"}\n')
        result = build_probe_result({
            "write_real": True,
            "endpoint": "http://127.0.0.1:19999/api/v1/raw/query",
            "installed_case_memory": str(fake_case),
        })
        assert result["status"] == "blocked_not_proven"
        assert result["write_performed"] is False
        assert any("not reachable" in nc or "health" in nc.lower() for nc in result["nonClaims"] + [result.get("error", "")])


class TestMissingInstalledRuntime:
    """Missing installed runtime directory yields blocked_not_proven."""

    def test_nonexistent_runtime_blocked(self):
        result = build_probe_result({
            "write_real": True,
            "installed_case_memory": "/nonexistent/path/case_memory.jsonl",
        })
        assert result["status"] == "blocked_not_proven"
        assert result["write_performed"] is False


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

    def test_has_installed_runtime_exists(self):
        result = build_probe_result({})
        assert "installed_runtime_exists" in result

    def test_has_case_memory_exists(self):
        result = build_probe_result({})
        assert "case_memory_exists" in result

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

    def test_memory_cache_statuses_is_list(self):
        result = build_probe_result({})
        assert isinstance(result["memory_cache_statuses_seen"], list)

    def test_freshness_boundaries_is_list(self):
        result = build_probe_result({})
        assert isinstance(result["freshness_boundaries_seen"], list)


class TestNoInProcessP3:
    """Harness must not import or use in-process p3_recall for the probe."""

    def test_harness_does_not_import_p3_recall(self):
        harness_path = ROOT / "tools" / "runtime_freshness_write_to_recall_probe.py"
        content = harness_path.read_text()
        assert "from p3_recall" not in content
        assert "import p3_recall" not in content
        assert "from src.p3_recall" not in content

    def test_harness_does_not_use_tempdir(self):
        harness_path = ROOT / "tools" / "runtime_freshness_write_to_recall_probe.py"
        content = harness_path.read_text()
        assert "TemporaryDirectory" not in content
        assert "tempfile" not in content
        assert "mkdtemp" not in content

    def test_harness_uses_http_for_recall(self):
        harness_path = ROOT / "tools" / "runtime_freshness_write_to_recall_probe.py"
        content = harness_path.read_text()
        assert "urllib.request" in content
        assert "9851" in content


class TestProofLayerSemantics:
    """Verify proof_layer values are correct."""

    def test_source_code_only_for_no_write(self):
        result = build_probe_result({})
        assert result["proof_layer"] == "source_code"

    def test_source_code_for_missing_runtime(self):
        result = build_probe_result({
            "write_real": True,
            "installed_case_memory": "/nonexistent/path.jsonl",
        })
        assert result["proof_layer"] == "source_code"

    def test_no_bare_connected_runtime_proven_anywhere(self):
        harness_path = ROOT / "tools" / "runtime_freshness_write_to_recall_probe.py"
        content = harness_path.read_text()
        assert 'status = "connected_runtime_proven"' not in content
        assert "connected_runtime_proven" not in content
        assert 'proof_layer = "connected_runtime"' not in content
        assert 'status = "connected_runtime_timeout"' not in content


BOUNDARY_NONCLAIM_MARKERS = [
    "raw source write path",
    "p2_extract",
    "platform capture",
    "production write-to-recall",
]


class TestMockedWriteRealSuccess:
    """Simulate write_real success via mocks; assert narrow naming + boundary nonClaims."""

    @pytest.fixture()
    def fake_case_memory(self, tmp_path):
        case_dir = tmp_path / "zhiyi" / "case_memory"
        case_dir.mkdir(parents=True)
        case_file = case_dir / "case_memory.jsonl"
        case_file.write_text('{"exp_id":"existing"}\n')
        return str(case_file)

    def _mock_gateway_health_ok(self, endpoint, timeout=3.0):
        return {"ok": True, "service": "raw_consumption_gateway", "version": "test"}

    def _mock_query_returns_token(self, endpoint, query, timeout=8.0):
        return {
            "ok": True,
            "memory_cache_status": "refresh_completed",
            "refresh_status": "completed",
            "refresh_pending": False,
            "freshness_boundary": "fresh_index",
            "items": [{"summary": f"contains {query} in response"}],
        }, ""

    def test_success_status_is_narrow(self, fake_case_memory):
        with patch(
            "runtime_freshness_write_to_recall_probe._gateway_health",
            self._mock_gateway_health_ok,
        ), patch(
            "runtime_freshness_write_to_recall_probe._query_gateway",
            self._mock_query_returns_token,
        ):
            result = build_probe_result({
                "write_real": True,
                "installed_case_memory": fake_case_memory,
            })
        assert result["status"] == "connected_runtime_zhiyi_append_to_gateway_proven"
        assert result["proof_layer"] == "connected_runtime_partial"
        assert result["ok"] is True

    def test_success_nonclaims_contain_boundary_markers(self, fake_case_memory):
        with patch(
            "runtime_freshness_write_to_recall_probe._gateway_health",
            self._mock_gateway_health_ok,
        ), patch(
            "runtime_freshness_write_to_recall_probe._query_gateway",
            self._mock_query_returns_token,
        ):
            result = build_probe_result({
                "write_real": True,
                "installed_case_memory": fake_case_memory,
            })
        nc_text = " ".join(result["nonClaims"]).lower()
        for marker in BOUNDARY_NONCLAIM_MARKERS:
            assert marker.lower() in nc_text, f"nonClaims missing boundary marker: {marker}"

    def test_success_does_not_claim_full_chain(self, fake_case_memory):
        with patch(
            "runtime_freshness_write_to_recall_probe._gateway_health",
            self._mock_gateway_health_ok,
        ), patch(
            "runtime_freshness_write_to_recall_probe._query_gateway",
            self._mock_query_returns_token,
        ):
            result = build_probe_result({
                "write_real": True,
                "installed_case_memory": fake_case_memory,
            })
        nc_text = " ".join(result["nonClaims"]).lower()
        assert "does not prove raw source write path" in nc_text
        assert "does not prove p2_extract" in nc_text
        assert "full chain untested" in nc_text

    def test_success_next_action_mentions_full_chain(self, fake_case_memory):
        with patch(
            "runtime_freshness_write_to_recall_probe._gateway_health",
            self._mock_gateway_health_ok,
        ), patch(
            "runtime_freshness_write_to_recall_probe._query_gateway",
            self._mock_query_returns_token,
        ):
            result = build_probe_result({
                "write_real": True,
                "installed_case_memory": fake_case_memory,
            })
        next_action = result.get("next_action_for_Codex", "").lower()
        assert "full-chain" in next_action or "full chain" in next_action
        assert "p2_extract" in next_action

    def test_timeout_status_is_narrow(self, fake_case_memory):
        def _mock_query_never_finds(endpoint, query, timeout=8.0):
            return {
                "ok": True,
                "memory_cache_status": "cache_hit",
                "refresh_pending": False,
                "freshness_boundary": "fresh_index",
                "items": [],
            }, ""

        with patch(
            "runtime_freshness_write_to_recall_probe._gateway_health",
            self._mock_gateway_health_ok,
        ), patch(
            "runtime_freshness_write_to_recall_probe._query_gateway",
            _mock_query_never_finds,
        ):
            result = build_probe_result({
                "write_real": True,
                "installed_case_memory": fake_case_memory,
                "timeout_seconds": 1,
            })
        assert result["status"] == "connected_runtime_zhiyi_append_timeout"
        assert result["proof_layer"] == "connected_runtime_partial_incomplete"
        assert result["ok"] is False
