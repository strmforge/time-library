from src.project_history_source_refs import (
    PROJECT_HISTORY_SOURCE_REF_CONTRACT,
    attach_project_history_source_refs,
    validate_project_history_source_ref,
)


def test_internal_msg_keyed_offsets_require_explicit_public_projection():
    item = {
        "source_system": "future_xyz",
        "source_path": "/tmp/future-session.jsonl",
        "msg_ids": ["message-1"],
        "byte_offsets": {"message-1": {"start": 12, "end": 48}},
    }

    public_without_internal = attach_project_history_source_refs(item)
    assert public_without_internal["source_refs_status"] == "byte_offsets_nested_not_public_contract"
    assert "source_refs" not in public_without_internal
    assert "byte_offsets" not in public_without_internal

    public_with_internal = attach_project_history_source_refs(
        {key: value for key, value in item.items() if key != "byte_offsets"},
        internal_source_refs=item,
    )
    assert public_with_internal["source_refs_status"] == "ready"
    assert public_with_internal["source_refs_contract"] == PROJECT_HISTORY_SOURCE_REF_CONTRACT
    assert public_with_internal["byte_offsets"] == {"start": 12, "end": 48}
    assert public_with_internal["source_refs"][0]["byte_offsets"] == {"start": 12, "end": 48}
    assert validate_project_history_source_ref(public_with_internal["source_refs"][0]) == "ready"
