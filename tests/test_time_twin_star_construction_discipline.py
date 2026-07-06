from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def test_agents_declares_time_rule_decision_and_manifest_diff_red_lines():
    agents_path = ROOT / "AGENTS.md"
    if not agents_path.exists():
        pytest.skip("private AGENTS.md is excluded from public release packages")
    text = agents_path.read_text(encoding="utf-8")

    assert "Missing `time_rule_decision` is a failed" in text
    assert "before-vs-after manifest" in text
    assert "A move without this manifest" in text
    assert "source-canon mirrors" in text
    assert "subordinate projections" in text
    assert "may not be treated as" in text
    assert "successors to `src/tiandao/time_twin_star.py`" in text
