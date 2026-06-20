from src.memory_authority_policy import (
    MEMORY_AUTHORITY_POLICY_CONTRACT,
    authority_allows,
    decide_memory_authority,
    memory_authority_receipt,
)


def test_memory_authority_defaults_to_passive():
    receipt = decide_memory_authority(source="test")

    assert receipt["contract"] == MEMORY_AUTHORITY_POLICY_CONTRACT
    assert receipt["requested_authority"] == "passive"
    assert receipt["granted_authority"] == "passive"
    assert receipt["can_read_memory"] is False
    assert receipt["can_direct_answer"] is False
    assert receipt["can_platform_act"] is False
    assert receipt["final_evidence_authority"] == "raw_source_refs"


def test_direct_answer_does_not_imply_platform_act():
    receipt = decide_memory_authority(
        source="openclaw",
        requested_authority="platform_act",
        zhiyi_entry=True,
        explicit_direct_authorized=True,
        platform_action_requested=True,
        platform_action_authorized=False,
    )

    assert receipt["requested_authority"] == "platform_act"
    assert receipt["granted_authority"] == "direct_answer"
    assert receipt["denied"] is True
    assert receipt["can_direct_answer"] is True
    assert receipt["can_platform_act"] is False
    assert receipt["reason"] == "platform_act_requires_explicit_authorization"


def test_platform_act_requires_separate_authorization():
    receipt = decide_memory_authority(
        source="openclaw",
        requested_authority="platform_act",
        zhiyi_entry=True,
        explicit_direct_authorized=True,
        platform_action_requested=True,
        platform_action_authorized=True,
    )

    assert receipt["granted_authority"] == "platform_act"
    assert receipt["denied"] is False
    assert receipt["can_platform_act"] is True
    assert authority_allows("platform_act", "direct_answer") is True
    assert authority_allows("direct_answer", "platform_act") is False


def test_custom_receipt_preserves_candidate_context_boundary():
    receipt = memory_authority_receipt(
        requested_authority="recall_only",
        granted_authority="recall_only",
        reason="test",
    )

    assert receipt["can_read_memory"] is True
    assert receipt["can_inject_context"] is False
    assert receipt["memory_summary_authority"] == "candidate_context_not_final_truth"
