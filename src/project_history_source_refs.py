"""Public source-ref projection for recall-to-project-history handoff.

Internal raw readers may retain message-keyed offset maps because they can
resolve several messages from one source artifact.  A project-history write is
one evidence slice, so its public handoff contract is intentionally narrower:
one source path and one flat ``{"start": int, "end": int}`` byte range.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


PROJECT_HISTORY_SOURCE_REF_CONTRACT = "time_library_project_history_source_ref.v1"
PROJECT_HISTORY_SOURCE_REF_EXAMPLE = {
    "source_path": "/absolute/path/to/source.jsonl",
    "byte_offsets": {"start": 0, "end": 128},
}


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _string_list(value: Any) -> list[str]:
    values = value if isinstance(value, (list, tuple)) else [value]
    result: list[str] = []
    for candidate in values:
        text = _text(candidate)
        if text and text not in result:
            result.append(text)
    return result


def _flat_byte_offsets(value: Any) -> tuple[dict[str, int], str]:
    if not isinstance(value, Mapping):
        return {}, "byte_offsets_missing"
    has_start = "start" in value
    has_end = "end" in value
    if not has_start or not has_end:
        if any(isinstance(candidate, Mapping) for candidate in value.values()):
            return {}, "byte_offsets_nested_not_public_contract"
        return {}, "byte_offsets_missing"
    start = value.get("start")
    end = value.get("end")
    if type(start) is not int or type(end) is not int:
        return {}, "byte_offsets_invalid"
    if start < 0 or end <= start:
        return {}, "byte_offsets_invalid"
    return {"start": start, "end": end}, "ready"


def validate_project_history_source_ref(source_ref: Any) -> str:
    """Return the fail-closed public-contract status for one source ref."""
    if not isinstance(source_ref, Mapping):
        return "source_ref_invalid"
    if not _text(source_ref.get("source_path")):
        return "source_path_missing"
    _, status = _flat_byte_offsets(source_ref.get("byte_offsets"))
    return status


def _internal_flat_byte_offsets(
    source_refs: Mapping[str, Any],
    *,
    msg_ids: list[str],
) -> tuple[dict[str, int], str]:
    offsets = source_refs.get("byte_offsets")
    flat, status = _flat_byte_offsets(offsets)
    if status == "ready":
        return flat, status
    if not isinstance(offsets, Mapping):
        return {}, status

    candidates: list[dict[str, int]] = []
    for msg_id in msg_ids:
        candidate, candidate_status = _flat_byte_offsets(offsets.get(msg_id))
        if candidate_status == "ready":
            candidates.append(candidate)
    if not msg_ids and len(offsets) == 1:
        candidate, candidate_status = _flat_byte_offsets(next(iter(offsets.values())))
        if candidate_status == "ready":
            candidates.append(candidate)
    if len(candidates) == 1:
        return candidates[0], "ready"
    if len(candidates) > 1:
        return {}, "byte_offsets_ambiguous_internal"
    return {}, status


def _first_text(*values: Any) -> str:
    for value in values:
        text = _text(value)
        if text:
            return text
    return ""


def project_history_source_ref_from_item(
    item: Mapping[str, Any],
    *,
    internal_source_refs: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], str]:
    """Build one public flat source ref from a recall item.

    ``internal_source_refs`` is the only entry point that may project an
    internal message-keyed offset map.  A nested map already present on a
    public item is never silently flattened.
    """
    if not isinstance(item, Mapping):
        return {}, "source_ref_invalid"
    internal = internal_source_refs if isinstance(internal_source_refs, Mapping) else {}
    source_path = _first_text(
        item.get("resolved_source_path"),
        item.get("source_path"),
        internal.get("resolved_source_path"),
        internal.get("source_path"),
    )
    if not source_path:
        return {}, "source_path_missing"
    msg_ids = _string_list(item.get("msg_ids")) or _string_list(internal.get("msg_ids"))
    offsets, status = _flat_byte_offsets(item.get("byte_offsets"))
    if status != "ready" and internal:
        offsets, status = _internal_flat_byte_offsets(internal, msg_ids=msg_ids)
    if status != "ready":
        return {}, status

    ref: dict[str, Any] = {
        "source_ref_contract": PROJECT_HISTORY_SOURCE_REF_CONTRACT,
        "source_path": source_path,
        "byte_offsets": offsets,
    }
    for key in (
        "library_id",
        "source_system",
        "computer_name",
        "canonical_window_id",
        "source_refs_canonical_window_id",
        "session_id",
        "project_id",
        "project_root",
        "workstream_id",
        "task_id",
        "artifact_type",
        "native_artifact_format",
        "raw_archive_layout",
        "raw_evidence_status",
    ):
        value = item.get(key, internal.get(key))
        if isinstance(value, str) and value.strip():
            ref[key] = value
    if msg_ids:
        ref["msg_ids"] = msg_ids
    return ref, "ready"


def project_history_source_refs_from_item(item: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return only already-public source refs, or derive one flat ref."""
    if not isinstance(item, Mapping):
        return []
    existing = item.get("source_refs")
    if item.get("source_refs_contract") == PROJECT_HISTORY_SOURCE_REF_CONTRACT and isinstance(existing, list):
        refs = [dict(ref) for ref in existing if validate_project_history_source_ref(ref) == "ready"]
        if len(refs) == len(existing):
            return refs
        return []
    ref, status = project_history_source_ref_from_item(item)
    return [ref] if status == "ready" else []


def attach_project_history_source_refs(
    item: Mapping[str, Any],
    *,
    internal_source_refs: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Attach the public handoff array without leaking internal source maps."""
    output = dict(item) if isinstance(item, Mapping) else {}
    existing = output.get("source_refs")
    if (
        output.get("source_refs_contract") == PROJECT_HISTORY_SOURCE_REF_CONTRACT
        and isinstance(existing, list)
        and bool(existing)
        and all(validate_project_history_source_ref(ref) == "ready" for ref in existing)
    ):
        output["source_refs"] = [dict(ref) for ref in existing]
        output["source_refs_status"] = "ready"
        if output["source_refs"]:
            output["byte_offsets"] = dict(output["source_refs"][0]["byte_offsets"])
        return output
    ref, status = project_history_source_ref_from_item(
        output,
        internal_source_refs=internal_source_refs,
    )
    if status == "ready":
        output["source_refs"] = [ref]
        output["source_refs_contract"] = PROJECT_HISTORY_SOURCE_REF_CONTRACT
        output["byte_offsets"] = dict(ref["byte_offsets"])
    else:
        output.pop("source_refs", None)
        output.pop("source_refs_contract", None)
        output.pop("byte_offsets", None)
    output["source_refs_status"] = status
    return output


def project_history_source_ref_guidance(error: str) -> dict[str, Any]:
    """Actionable fail-closed guidance for public project-history callers."""
    return {
        "source_refs_contract": PROJECT_HISTORY_SOURCE_REF_CONTRACT,
        "source_ref_error": error,
        "next_actions": [
            "pass one recall item's source_refs value unchanged",
            "use one source_path with flat byte_offsets.start and byte_offsets.end integers",
            "do not pass internal msg_id-keyed byte_offsets maps to project_history_write",
        ],
        "minimum_source_ref_example": dict(PROJECT_HISTORY_SOURCE_REF_EXAMPLE),
    }


__all__ = [
    "PROJECT_HISTORY_SOURCE_REF_CONTRACT",
    "PROJECT_HISTORY_SOURCE_REF_EXAMPLE",
    "attach_project_history_source_refs",
    "project_history_source_ref_from_item",
    "project_history_source_ref_guidance",
    "project_history_source_refs_from_item",
    "validate_project_history_source_ref",
]
