"""Installed-runtime persistence for the Time Library Delivery Spine.

The store is a derived, append-only audit layer. It never mutates raw records,
memory shelves, recall ranking, platform configuration, or model traffic.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import sqlite3
import uuid
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

try:
    from src.config_loader import base_path
    from src.time_library_delivery_spine import (
        DELIVERY_STAGES,
        HOST_ATTESTED_PLATFORM_DELIVERY_PROOF_KIND,
        HOST_SELF_REPORT_EVIDENCE_AUTHORITY,
        UNKNOWN_STAGE,
        decide_intervention,
        validate_delivery_chain,
    )
except Exception:  # pragma: no cover - direct script import fallback
    from config_loader import base_path
    from time_library_delivery_spine import (
        DELIVERY_STAGES,
        HOST_ATTESTED_PLATFORM_DELIVERY_PROOF_KIND,
        HOST_SELF_REPORT_EVIDENCE_AUTHORITY,
        UNKNOWN_STAGE,
        decide_intervention,
        validate_delivery_chain,
    )


DELIVERY_RUNTIME_CONTRACT = "time_library.delivery_runtime.v2026.7.15"
DELIVERY_ACK_CONTRACT = "time_library.delivery_ack.v2026.7.15"
DELIVERY_STATUS_CONTRACT = "time_library.delivery_status.v2026.7.15"
HOST_CONNECTION_RECEIPT_CONTRACT = "time_library.host_connection_receipt.v1"
HOST_CONNECTION_RESUME_CONTRACT = "time_library.host_connection_resume.v1"
DELIVERY_STORE_FILENAME = "delivery-events.sqlite3"
CHALLENGE_TTL_SECONDS = 15 * 60
HOST_CONNECTION_RESUME_TTL_SECONDS = 24 * 60 * 60
MAX_TRACKED_SOURCE_REFS = 20
SUPPORTED_DELIVERY_FORMS = ("context", "catalog", "silent")

UTC = timezone.utc
_BLOCKED_LIFECYCLE_STATES = {"conflicting", "deprecated", "rejected", "superseded"}
_BLOCKED_CONFLICT_DECISIONS = {
    "disputed_by_errata_candidate",
    "conflicting",
    "unresolved",
    "unknown",
}


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(value: Optional[datetime] = None) -> str:
    return (value or _now()).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _parse_iso(value: Any) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith("Z") else text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _text(value: Any, limit: int = 240) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()[:limit]


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _new_id(prefix: str) -> str:
    return "%s-%s" % (prefix, uuid.uuid4().hex)


def _root(memcore_root: Any = None) -> Path:
    return Path(str(memcore_root or base_path())).expanduser().resolve()


def delivery_store_path(memcore_root: Any = None) -> Path:
    return _root(memcore_root) / "runtime" / DELIVERY_STORE_FILENAME


def _ensure_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS delivery_events (
            event_id TEXT PRIMARY KEY,
            retrieval_id TEXT NOT NULL,
            platform TEXT NOT NULL,
            stage TEXT NOT NULL,
            observed_at TEXT NOT NULL,
            recorded_at TEXT NOT NULL,
            previous_event_id TEXT NOT NULL DEFAULT '',
            evidence_ref TEXT NOT NULL,
            event_json TEXT NOT NULL,
            inserted_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS delivery_events_retrieval_idx
            ON delivery_events(retrieval_id, recorded_at);
        CREATE INDEX IF NOT EXISTS delivery_events_platform_stage_idx
            ON delivery_events(platform, stage);

        CREATE TABLE IF NOT EXISTS delivery_challenges (
            challenge_id TEXT PRIMARY KEY,
            retrieval_id TEXT NOT NULL UNIQUE,
            platform TEXT NOT NULL,
            selected_event_id TEXT NOT NULL,
            unknown_event_id TEXT NOT NULL,
            challenge_hash TEXT NOT NULL,
            source_refs_json TEXT NOT NULL,
            issued_at TEXT NOT NULL,
            expires_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS delivery_decisions (
            decision_id TEXT PRIMARY KEY,
            retrieval_id TEXT NOT NULL,
            platform TEXT NOT NULL,
            decision TEXT NOT NULL,
            observed_at TEXT NOT NULL,
            reasons_json TEXT NOT NULL,
            decision_json TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS delivery_decisions_platform_idx
            ON delivery_decisions(platform, observed_at);

        CREATE TABLE IF NOT EXISTS delivery_security_events (
            security_event_id TEXT PRIMARY KEY,
            challenge_id TEXT NOT NULL DEFAULT '',
            platform TEXT NOT NULL DEFAULT '',
            reason TEXT NOT NULL,
            observed_at TEXT NOT NULL,
            evidence_ref TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS host_connection_receipts (
            receipt_id TEXT PRIMARY KEY,
            transport_session_sha256 TEXT NOT NULL UNIQUE,
            platform TEXT NOT NULL,
            observed_at TEXT NOT NULL,
            receipt_json TEXT NOT NULL,
            inserted_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS host_connection_receipts_platform_idx
            ON host_connection_receipts(platform, observed_at);

        CREATE TABLE IF NOT EXISTS host_connection_resume_events (
            resume_event_id TEXT PRIMARY KEY,
            previous_transport_session_sha256 TEXT NOT NULL UNIQUE,
            next_transport_session_sha256 TEXT NOT NULL UNIQUE,
            platform TEXT NOT NULL,
            observed_at TEXT NOT NULL,
            event_json TEXT NOT NULL,
            inserted_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS host_connection_resume_events_platform_idx
            ON host_connection_resume_events(platform, observed_at);

        CREATE TRIGGER IF NOT EXISTS delivery_events_no_update
            BEFORE UPDATE ON delivery_events BEGIN SELECT RAISE(ABORT, 'append_only'); END;
        CREATE TRIGGER IF NOT EXISTS delivery_events_no_delete
            BEFORE DELETE ON delivery_events BEGIN SELECT RAISE(ABORT, 'append_only'); END;
        CREATE TRIGGER IF NOT EXISTS delivery_challenges_no_update
            BEFORE UPDATE ON delivery_challenges BEGIN SELECT RAISE(ABORT, 'append_only'); END;
        CREATE TRIGGER IF NOT EXISTS delivery_challenges_no_delete
            BEFORE DELETE ON delivery_challenges BEGIN SELECT RAISE(ABORT, 'append_only'); END;
        CREATE TRIGGER IF NOT EXISTS delivery_decisions_no_update
            BEFORE UPDATE ON delivery_decisions BEGIN SELECT RAISE(ABORT, 'append_only'); END;
        CREATE TRIGGER IF NOT EXISTS delivery_decisions_no_delete
            BEFORE DELETE ON delivery_decisions BEGIN SELECT RAISE(ABORT, 'append_only'); END;
        CREATE TRIGGER IF NOT EXISTS delivery_security_events_no_update
            BEFORE UPDATE ON delivery_security_events BEGIN SELECT RAISE(ABORT, 'append_only'); END;
        CREATE TRIGGER IF NOT EXISTS delivery_security_events_no_delete
            BEFORE DELETE ON delivery_security_events BEGIN SELECT RAISE(ABORT, 'append_only'); END;
        CREATE TRIGGER IF NOT EXISTS host_connection_receipts_no_update
            BEFORE UPDATE ON host_connection_receipts BEGIN SELECT RAISE(ABORT, 'append_only'); END;
        CREATE TRIGGER IF NOT EXISTS host_connection_receipts_no_delete
            BEFORE DELETE ON host_connection_receipts BEGIN SELECT RAISE(ABORT, 'append_only'); END;
        CREATE TRIGGER IF NOT EXISTS host_connection_resume_events_no_update
            BEFORE UPDATE ON host_connection_resume_events BEGIN SELECT RAISE(ABORT, 'append_only'); END;
        CREATE TRIGGER IF NOT EXISTS host_connection_resume_events_no_delete
            BEFORE DELETE ON host_connection_resume_events BEGIN SELECT RAISE(ABORT, 'append_only'); END;
        """
    )


def _secure_delivery_store_files(path: Path) -> None:
    for candidate in (path, Path(str(path) + "-wal"), Path(str(path) + "-shm")):
        if candidate.exists():
            candidate.chmod(0o600)


def _connect(memcore_root: Any = None) -> sqlite3.Connection:
    path = delivery_store_path(memcore_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(mode=0o600, exist_ok=True)
    path.chmod(0o600)
    connection = sqlite3.connect(str(path), timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout=10000")
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=FULL")
    _ensure_schema(connection)
    _secure_delivery_store_files(path)
    return connection


def _connect_read_only(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout=10000")
    return connection


def _normalize_host_identity(value: Any) -> str:
    text = _text(value, 120).lower()
    normalized = re.sub(r"[^\w]+", "_", text, flags=re.UNICODE).strip("_")
    return normalized[:80]


def _platform_from_args(arguments: Mapping[str, Any]) -> str:
    # The immutable connection receipt is the identity authority. A consumer
    # label may describe the caller, but must never select or block tracking.
    return _normalize_host_identity(arguments.get("platform"))


def _tracking_enabled(arguments: Mapping[str, Any]) -> Tuple[bool, str]:
    if arguments.get("delivery_tracking") is False:
        return False, "client_opted_out"
    return True, _platform_from_args(arguments)


def _transport_session_sha256(connection_context: Optional[Mapping[str, Any]]) -> str:
    context = connection_context if isinstance(connection_context, Mapping) else {}
    transport_session_id = _text(context.get("transport_session_id"), 500)
    if not transport_session_id:
        return ""
    return hashlib.sha256(transport_session_id.encode("utf-8")).hexdigest()


def record_verified_host_connection(
    connection_context: Optional[Mapping[str, Any]],
    self_report_result: Mapping[str, Any],
    *,
    memcore_root: Any = None,
) -> Dict[str, Any]:
    """Append one connection receipt after initialize-bound self-report proof."""
    context = connection_context if isinstance(connection_context, Mapping) else {}
    result = self_report_result if isinstance(self_report_result, Mapping) else {}
    session_sha256 = _transport_session_sha256(context)
    client_info = result.get("client_info") if isinstance(result.get("client_info"), Mapping) else {}
    platform = _normalize_host_identity(client_info.get("self_reported_platform"))
    if not context.get("initialized") or not context.get("client_info_present") or not session_sha256:
        return {
            "ok": False,
            "contract": HOST_CONNECTION_RECEIPT_CONTRACT,
            "error": "mcp_initialize_session_required",
            "write_performed": False,
        }
    if result.get("ok") is not True or result.get("self_report_verified") is not True or not platform:
        return {
            "ok": False,
            "contract": HOST_CONNECTION_RECEIPT_CONTRACT,
            "error": "verified_self_report_required",
            "write_performed": False,
        }
    observed_datetime = _now()
    observed_at = _iso(observed_datetime)
    proof = result.get("real_recall_proof") if isinstance(result.get("real_recall_proof"), Mapping) else {}
    receipt = {
        "ok": True,
        "contract": HOST_CONNECTION_RECEIPT_CONTRACT,
        "receipt_id": _new_id("host-connection"),
        "platform": platform,
        "observed_at": observed_at,
        "transport_session_sha256": session_sha256,
        "initialized_client_name": _text(context.get("client_name"), 200),
        "initialized_client_version": _text(context.get("client_version"), 120),
        "inferred_platform_hint": _normalize_host_identity(context.get("inferred_platform_hint")),
        "identity_authority": "host_self_report",
        "proof_library_id": _text(proof.get("library_id"), 160),
        "proof_source_refs_count": int(proof.get("source_refs_count") or 0),
        "real_recall_proof": {
            "library_id": _text(proof.get("library_id"), 160),
            "matched_count": int(proof.get("matched_count") or 0),
            "source_refs_count": int(proof.get("source_refs_count") or 0),
            "raw_excerpt_returned": bool(proof.get("raw_excerpt_returned")),
            "recall_source_system_filter": _text(
                proof.get("recall_source_system_filter"),
                120,
            ),
            "observed_at_epoch": float(proof.get("observed_at_epoch") or 0.0),
        },
        "borrowing_card_id": _text(
            (result.get("borrowing_card_receipt") or {}).get("card_id")
            if isinstance(result.get("borrowing_card_receipt"), Mapping)
            else "",
            220,
        ),
        "consumer_connection_requires_native_parser": False,
        "append_only": True,
        "source_memory_read_only": True,
        "raw_write_performed": False,
        "memory_write_performed": False,
        "platform_write_performed": False,
        "resume_issued_at": observed_at,
        "resume_expires_at": _iso(
            observed_datetime + timedelta(seconds=HOST_CONNECTION_RESUME_TTL_SECONDS)
        ),
        "resume_generation": 0,
        "resumed_from_receipt_id": "",
    }
    with _connect(memcore_root) as connection:
        existing = connection.execute(
            "SELECT receipt_json FROM host_connection_receipts WHERE transport_session_sha256 = ?",
            (session_sha256,),
        ).fetchone()
        if existing is not None:
            existing_receipt = json.loads(existing["receipt_json"])
            if existing_receipt.get("platform") != platform:
                return {
                    "ok": False,
                    "contract": HOST_CONNECTION_RECEIPT_CONTRACT,
                    "error": "transport_session_identity_already_bound",
                    "write_performed": False,
                }
            existing_receipt["idempotent"] = True
            existing_receipt["write_performed"] = False
            return existing_receipt
        connection.execute(
            """
            INSERT INTO host_connection_receipts (
                receipt_id, transport_session_sha256, platform, observed_at,
                receipt_json, inserted_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                receipt["receipt_id"],
                session_sha256,
                platform,
                observed_at,
                _json(receipt),
                observed_at,
            ),
        )
    receipt["write_performed"] = True
    return receipt


def rotate_verified_host_connection_resume(
    previous_connection_context: Optional[Mapping[str, Any]],
    next_connection_context: Optional[Mapping[str, Any]],
    *,
    initialized_client_name: str,
    initialized_client_version: str,
    inferred_platform_hint: str = "",
    memcore_root: Any = None,
) -> Dict[str, Any]:
    """Consume one prior bearer and append a rotated verified connection receipt."""
    previous_sha256 = _transport_session_sha256(previous_connection_context)
    next_sha256 = _transport_session_sha256(next_connection_context)
    if not previous_sha256 or not next_sha256 or previous_sha256 == next_sha256:
        return {
            "ok": False,
            "contract": HOST_CONNECTION_RESUME_CONTRACT,
            "error": "valid_distinct_resume_sessions_required",
            "write_performed": False,
        }
    path = delivery_store_path(memcore_root)
    if not path.exists():
        return {
            "ok": False,
            "contract": HOST_CONNECTION_RESUME_CONTRACT,
            "error": "verified_host_connection_required",
            "write_performed": False,
        }
    client_name = _text(initialized_client_name, 200)
    client_version = _text(initialized_client_version, 120)
    now = _now()
    observed_at = _iso(now)
    try:
        with _connect(memcore_root) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT receipt_json FROM host_connection_receipts WHERE transport_session_sha256 = ?",
                (previous_sha256,),
            ).fetchone()
            if row is None:
                return {
                    "ok": False,
                    "contract": HOST_CONNECTION_RESUME_CONTRACT,
                    "error": "verified_host_connection_required",
                    "write_performed": False,
                }
            previous_receipt = json.loads(row["receipt_json"])
            expected_name = _text(previous_receipt.get("initialized_client_name"), 200)
            expected_version = _text(previous_receipt.get("initialized_client_version"), 120)
            if (
                previous_receipt.get("ok") is not True
                or not client_name
                or client_name != expected_name
                or client_version != expected_version
            ):
                return {
                    "ok": False,
                    "contract": HOST_CONNECTION_RESUME_CONTRACT,
                    "error": "verified_host_resume_identity_mismatch",
                    "write_performed": False,
                }
            expires_at = _parse_iso(previous_receipt.get("resume_expires_at"))
            if expires_at is None:
                issued_at = _parse_iso(previous_receipt.get("observed_at"))
                expires_at = (
                    issued_at + timedelta(seconds=HOST_CONNECTION_RESUME_TTL_SECONDS)
                    if issued_at is not None
                    else None
                )
            if expires_at is None or now > expires_at:
                return {
                    "ok": False,
                    "contract": HOST_CONNECTION_RESUME_CONTRACT,
                    "error": "verified_host_resume_expired",
                    "write_performed": False,
                }
            consumed = connection.execute(
                "SELECT resume_event_id FROM host_connection_resume_events "
                "WHERE previous_transport_session_sha256 = ?",
                (previous_sha256,),
            ).fetchone()
            if consumed is not None:
                return {
                    "ok": False,
                    "contract": HOST_CONNECTION_RESUME_CONTRACT,
                    "error": "verified_host_resume_already_consumed",
                    "write_performed": False,
                }
            platform = _normalize_host_identity(previous_receipt.get("platform"))
            if not platform:
                return {
                    "ok": False,
                    "contract": HOST_CONNECTION_RESUME_CONTRACT,
                    "error": "verified_host_connection_required",
                    "write_performed": False,
                }
            generation = int(previous_receipt.get("resume_generation") or 0) + 1
            next_receipt = {
                "ok": True,
                "contract": HOST_CONNECTION_RECEIPT_CONTRACT,
                "receipt_id": _new_id("host-connection"),
                "platform": platform,
                "observed_at": observed_at,
                "transport_session_sha256": next_sha256,
                "initialized_client_name": client_name,
                "initialized_client_version": client_version,
                "inferred_platform_hint": _normalize_host_identity(inferred_platform_hint),
                "identity_authority": "host_self_report_rotated_resume",
                "proof_library_id": _text(previous_receipt.get("proof_library_id"), 160),
                "proof_source_refs_count": int(
                    previous_receipt.get("proof_source_refs_count") or 0
                ),
                "real_recall_proof": deepcopy(previous_receipt.get("real_recall_proof") or {}),
                "borrowing_card_id": _text(previous_receipt.get("borrowing_card_id"), 220),
                "consumer_connection_requires_native_parser": False,
                "append_only": True,
                "source_memory_read_only": True,
                "raw_write_performed": False,
                "memory_write_performed": False,
                "platform_write_performed": False,
                "resume_issued_at": observed_at,
                "resume_expires_at": _iso(
                    now + timedelta(seconds=HOST_CONNECTION_RESUME_TTL_SECONDS)
                ),
                "resume_generation": generation,
                "resumed_from_receipt_id": _text(previous_receipt.get("receipt_id"), 220),
            }
            resume_event = {
                "ok": True,
                "contract": HOST_CONNECTION_RESUME_CONTRACT,
                "resume_event_id": _new_id("host-connection-resume"),
                "previous_receipt_id": _text(previous_receipt.get("receipt_id"), 220),
                "next_receipt_id": next_receipt["receipt_id"],
                "previous_transport_session_sha256": previous_sha256,
                "next_transport_session_sha256": next_sha256,
                "platform": platform,
                "observed_at": observed_at,
                "resume_generation": generation,
                "old_bearer_consumed": True,
                "append_only": True,
            }
            connection.execute(
                """
                INSERT INTO host_connection_receipts (
                    receipt_id, transport_session_sha256, platform, observed_at,
                    receipt_json, inserted_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    next_receipt["receipt_id"],
                    next_sha256,
                    platform,
                    observed_at,
                    _json(next_receipt),
                    observed_at,
                ),
            )
            connection.execute(
                """
                INSERT INTO host_connection_resume_events (
                    resume_event_id, previous_transport_session_sha256,
                    next_transport_session_sha256, platform, observed_at,
                    event_json, inserted_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    resume_event["resume_event_id"],
                    previous_sha256,
                    next_sha256,
                    platform,
                    observed_at,
                    _json(resume_event),
                    observed_at,
                ),
            )
    except sqlite3.IntegrityError:
        return {
            "ok": False,
            "contract": HOST_CONNECTION_RESUME_CONTRACT,
            "error": "verified_host_resume_already_consumed",
            "write_performed": False,
        }
    next_receipt["resume_event"] = resume_event
    next_receipt["write_performed"] = True
    return next_receipt


def verified_host_connection(
    connection_context: Optional[Mapping[str, Any]],
    *,
    platform: str = "",
    memcore_root: Any = None,
) -> Dict[str, Any]:
    """Resolve the immutable self-report receipt for this transport session."""
    session_sha256 = _transport_session_sha256(connection_context)
    expected_platform = _normalize_host_identity(platform)
    path = delivery_store_path(memcore_root)
    if not session_sha256 or not path.exists():
        return {
            "ok": False,
            "contract": HOST_CONNECTION_RECEIPT_CONTRACT,
            "error": "verified_host_connection_required",
            "write_performed": False,
        }
    with _connect_read_only(path) as connection:
        try:
            row = connection.execute(
                "SELECT receipt_json FROM host_connection_receipts WHERE transport_session_sha256 = ?",
                (session_sha256,),
            ).fetchone()
        except sqlite3.OperationalError:
            row = None
    if row is None:
        return {
            "ok": False,
            "contract": HOST_CONNECTION_RECEIPT_CONTRACT,
            "error": "verified_host_connection_required",
            "write_performed": False,
        }
    receipt = json.loads(row["receipt_json"])
    if expected_platform and receipt.get("platform") != expected_platform:
        return {
            "ok": False,
            "contract": HOST_CONNECTION_RECEIPT_CONTRACT,
            "error": "verified_host_identity_mismatch",
            "write_performed": False,
        }
    receipt["write_performed"] = False
    return receipt


def query_verified_host_connections(*, memcore_root: Any = None) -> List[Dict[str, Any]]:
    path = delivery_store_path(memcore_root)
    if not path.exists():
        return []
    with _connect_read_only(path) as connection:
        try:
            rows = connection.execute(
                "SELECT receipt_json FROM host_connection_receipts ORDER BY rowid"
            ).fetchall()
        except sqlite3.OperationalError:
            return []
    return [json.loads(row["receipt_json"]) for row in rows]


def _source_ref_from_mapping(value: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    source_system = _text(value.get("source_system"), 80)
    if not source_system:
        return None
    reference: Dict[str, Any] = {"source_system": source_system}
    library_id = _text(value.get("library_id"), 120)
    evidence_ref = _text(value.get("evidence_ref"), 180)
    artifact_id = _text(
        value.get("artifact_id")
        or value.get("evidence_hash")
        or value.get("verbatim_sha256")
        or value.get("exp_id")
        or value.get("candidate_id"),
        220,
    )
    source_path = _text(value.get("source_path") or value.get("ref_path"), 1200)
    if library_id:
        reference["library_id"] = library_id
    elif evidence_ref:
        reference["evidence_ref"] = evidence_ref
    elif artifact_id:
        reference["artifact_id"] = artifact_id
    elif source_path:
        reference["source_path"] = source_path
    else:
        return None
    return reference


def _candidate_source_mappings(result: Mapping[str, Any]) -> Iterable[Mapping[str, Any]]:
    receipt = result.get("consumer_receipt")
    if isinstance(receipt, Mapping):
        for item in receipt.get("used_source_refs") or []:
            if isinstance(item, Mapping):
                yield item
    for item in result.get("items") or []:
        if isinstance(item, Mapping):
            yield item
    catalog = result.get("catalog_card")
    if isinstance(catalog, Mapping):
        catalog_refs = catalog.get("source_refs")
        if isinstance(catalog_refs, Mapping):
            combined = dict(catalog_refs)
            combined.setdefault("library_id", catalog.get("library_id") or result.get("library_id"))
            card = catalog.get("card")
            if isinstance(card, Mapping):
                combined.setdefault("source_system", (card.get("source_refs") or {}).get("source_system") if isinstance(card.get("source_refs"), Mapping) else "")
            yield combined
        card = catalog.get("card")
        if isinstance(card, Mapping) and isinstance(card.get("source_refs"), Mapping):
            combined = dict(card.get("source_refs") or {})
            combined.setdefault("library_id", card.get("library_id") or catalog.get("library_id"))
            yield combined


def extract_delivery_source_refs(result: Mapping[str, Any]) -> List[Dict[str, Any]]:
    refs: List[Dict[str, Any]] = []
    seen = set()
    for candidate in _candidate_source_mappings(result):
        reference = _source_ref_from_mapping(candidate)
        if not reference:
            continue
        key = _json(reference)
        if key in seen:
            continue
        seen.add(key)
        refs.append(reference)
        if len(refs) >= MAX_TRACKED_SOURCE_REFS:
            break
    return refs


def _result_risk_reasons(result: Mapping[str, Any]) -> Tuple[List[str], List[str]]:
    lifecycle: List[str] = []
    security: List[str] = []
    candidates: List[Mapping[str, Any]] = []
    catalog = result.get("catalog_card")
    if isinstance(catalog, Mapping) and isinstance(catalog.get("card"), Mapping):
        candidates.append(catalog.get("card"))
    candidates.extend(item for item in result.get("items") or [] if isinstance(item, Mapping))
    for item in candidates:
        state = _text(item.get("status") or item.get("lifecycle_status"), 80).lower()
        if state in _BLOCKED_LIFECYCLE_STATES:
            lifecycle.append("lifecycle_%s" % state)
        decision = _text(item.get("conflict_decision"), 120).lower()
        if decision in _BLOCKED_CONFLICT_DECISIONS:
            lifecycle.append("conflict_%s" % decision)
        overlay = item.get("recall_overlay")
        if isinstance(overlay, Mapping) and overlay.get("block_recall") is True:
            lifecycle.append("conflict_recall_blocked")
        taint = _text(item.get("taint_state") or item.get("security_state"), 80).lower()
        if taint in {"blocked", "poisoned", "unsafe", "quarantined"}:
            security.append("security_%s" % taint)
    return list(dict.fromkeys(lifecycle)), list(dict.fromkeys(security))


def _event(
    *,
    retrieval_id: str,
    platform: str,
    stage: str,
    delivery_form: str,
    source_refs: Sequence[Mapping[str, Any]],
    previous_event_id: str = "",
    extra: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    observed_at = _iso()
    event_id = _new_id("delivery-event")
    payload: Dict[str, Any] = {
        "delivery_event_id": event_id,
        "retrieval_id": retrieval_id,
        "platform": platform,
        "delivery_audience": "agent",
        "delivery_form": delivery_form,
        "delivery_stage": stage,
        "observed_at": observed_at,
        "recorded_at": observed_at,
        "evidence_ref": "delivery-runtime:%s:%s:%s" % (retrieval_id, stage, event_id[-12:]),
        "source_refs": deepcopy(list(source_refs)),
    }
    if previous_event_id:
        payload["previous_event_id"] = previous_event_id
    if extra:
        payload.update(deepcopy(dict(extra)))
    return payload


def _insert_events(
    connection: sqlite3.Connection,
    events: Sequence[Mapping[str, Any]],
    *,
    validate_as_complete_chain: bool = True,
) -> None:
    if validate_as_complete_chain:
        validation = validate_delivery_chain(events)
        if validation.get("ok") is not True:
            raise ValueError("invalid_delivery_chain:%s" % ";".join(validation.get("errors") or []))
    inserted_at = _iso()
    for event in events:
        connection.execute(
            """
            INSERT INTO delivery_events (
                event_id, retrieval_id, platform, stage, observed_at, recorded_at,
                previous_event_id, evidence_ref, event_json, inserted_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event["delivery_event_id"],
                event["retrieval_id"],
                event["platform"],
                event["delivery_stage"],
                event["observed_at"],
                event["recorded_at"],
                event.get("previous_event_id", ""),
                event["evidence_ref"],
                _json(event),
                inserted_at,
            ),
        )


def _decision_payload(
    *,
    retrieval_id: str,
    platform: str,
    result: Mapping[str, Any],
    policy: Mapping[str, Any],
    lifecycle_reasons: Sequence[str],
    security_reasons: Sequence[str],
    query: str,
) -> Dict[str, Any]:
    reasons = list(policy.get("silent_reasons") or []) + list(lifecycle_reasons) + list(security_reasons)
    return {
        "decision_id": _new_id("delivery-decision"),
        "retrieval_id": retrieval_id,
        "platform": platform,
        "decision": policy.get("decision", "silent"),
        "delivery_form": policy.get("delivery_form", "silent"),
        "observed_at": _iso(),
        "reasons": list(dict.fromkeys(str(reason) for reason in reasons if str(reason))),
        "query_sha256": hashlib.sha256(str(query or "").encode("utf-8")).hexdigest(),
        "matched_count": int(result.get("matched_count") or len(result.get("items") or [])),
        "source_ref_count": len(policy.get("considered_source_refs") or []),
        "raw_is_highest_authority": True,
    }


def _insert_decision(connection: sqlite3.Connection, decision: Mapping[str, Any]) -> None:
    connection.execute(
        """
        INSERT INTO delivery_decisions (
            decision_id, retrieval_id, platform, decision, observed_at,
            reasons_json, decision_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            decision["decision_id"],
            decision["retrieval_id"],
            decision["platform"],
            decision["decision"],
            decision["observed_at"],
            _json(decision.get("reasons") or []),
            _json(decision),
        ),
    )


def _write_boundary(*, write_performed: bool) -> Dict[str, Any]:
    return {
        "write_performed": bool(write_performed),
        "derived_delivery_audit_write_performed": bool(write_performed),
        "source_memory_read_only": True,
        "raw_write_performed": False,
        "memory_write_performed": False,
        "zhiyi_write_performed": False,
        "xingce_write_performed": False,
        "platform_write_performed": False,
        "recall_ranking_changed": False,
        "store_scope": "runtime/%s" % DELIVERY_STORE_FILENAME,
        "append_only": True,
    }


def _host_attested_proof_boundary(*, chain_proven: bool = False) -> Dict[str, Any]:
    return {
        "evidence_authority": HOST_SELF_REPORT_EVIDENCE_AUTHORITY,
        "independent_model_delivery_proven": False,
        "platform_delivery_proof_kind": HOST_ATTESTED_PLATFORM_DELIVERY_PROOF_KIND,
        "host_attested_append_only_chain_proven": bool(chain_proven),
    }


def _silent_result(original: Mapping[str, Any], runtime: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "ok": bool(original.get("ok", True)),
        "mode": "delivery_silent",
        "query": original.get("query", ""),
        "read_only": False,
        "source_memory_read_only": True,
        "write_performed": True,
        "derived_delivery_audit_write_performed": True,
        "raw_write_performed": False,
        "memory_write_performed": False,
        "platform_write_performed": False,
        "matched_count": 0,
        "source_refs_count": 0,
        "raw_items_count": 0,
        "raw_excerpt_returned": False,
        "items": [],
        "delivery_runtime": deepcopy(dict(runtime)),
        "error": original.get("error", ""),
    }


def instrument_recall_result(
    result: Mapping[str, Any],
    arguments: Mapping[str, Any],
    *,
    memcore_root: Any = None,
    connection_context: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Persist a selected/unknown prefix only for a verified host connection."""
    output = deepcopy(dict(result)) if isinstance(result, Mapping) else {"ok": False, "error": "recall_result_must_be_object"}
    enabled, platform_or_reason = _tracking_enabled(arguments if isinstance(arguments, Mapping) else {})
    if not enabled:
        return output
    verification = verified_host_connection(
        connection_context,
        platform=platform_or_reason,
        memcore_root=memcore_root,
    )
    if verification.get("ok") is not True:
        output["delivery_runtime"] = {
            "ok": False,
            "contract": DELIVERY_RUNTIME_CONTRACT,
            "error": verification.get("error", "verified_host_connection_required"),
            "proof_layer": "delivery_tracking_not_started",
            "delivery_performed": False,
            "used_observed": False,
            "helped_state": "unknown",
            **_host_attested_proof_boundary(chain_proven=False),
            "write_boundary": _write_boundary(write_performed=False),
        }
        return output
    platform = str(verification.get("platform") or "")
    source_refs = extract_delivery_source_refs(output)
    lifecycle_reasons, security_reasons = _result_risk_reasons(output)
    requested_form = _text(arguments.get("delivery_form"), 40) or "context"
    if requested_form not in SUPPORTED_DELIVERY_FORMS:
        requested_form = "context"
    policy = decide_intervention(
        delivery_audience="agent",
        requested_form=requested_form,
        selection_value=1 if source_refs else 0,
        source_refs=source_refs,
        evidence_sufficient=bool(source_refs) and not lifecycle_reasons,
        safety_allowed=not security_reasons,
    )
    retrieval_id = _new_id("retrieval")
    decision = _decision_payload(
        retrieval_id=retrieval_id,
        platform=platform,
        result=output,
        policy=policy,
        lifecycle_reasons=lifecycle_reasons,
        security_reasons=security_reasons,
        query=_text(arguments.get("query") or arguments.get("library_id"), 4000),
    )
    events: List[Dict[str, Any]] = []
    challenge_payload: Dict[str, Any] = {}
    with _connect(memcore_root) as connection:
        _insert_decision(connection, decision)
        if source_refs:
            stored_form = requested_form
            stored = _event(
                retrieval_id=retrieval_id,
                platform=platform,
                stage="stored",
                delivery_form=stored_form,
                source_refs=source_refs,
            )
            retrieved = _event(
                retrieval_id=retrieval_id,
                platform=platform,
                stage="retrieved",
                delivery_form=stored_form,
                source_refs=source_refs,
                previous_event_id=stored["delivery_event_id"],
            )
            selected = _event(
                retrieval_id=retrieval_id,
                platform=platform,
                stage="selected",
                delivery_form=str(policy.get("delivery_form") or "silent"),
                source_refs=source_refs,
                previous_event_id=retrieved["delivery_event_id"],
                extra={
                    "selection_observation": {
                        "decision": policy.get("decision", "silent"),
                        "policy_ref": decision["decision_id"],
                    }
                },
            )
            events = [stored, retrieved, selected]
            if policy.get("should_emit") is True:
                unknown = _event(
                    retrieval_id=retrieval_id,
                    platform=platform,
                    stage=UNKNOWN_STAGE,
                    delivery_form=str(policy.get("delivery_form") or "context"),
                    source_refs=source_refs,
                    previous_event_id=selected["delivery_event_id"],
                    extra={
                        "unknown_for_stage": "delivered",
                        "unknown_reason": "awaiting_host_model_challenge_ack",
                    },
                )
                events.append(unknown)
                challenge = secrets.token_urlsafe(24)
                challenge_id = _new_id("delivery-challenge")
                issued = _now()
                expires = issued + timedelta(seconds=CHALLENGE_TTL_SECONDS)
                connection.execute(
                    """
                    INSERT INTO delivery_challenges (
                        challenge_id, retrieval_id, platform, selected_event_id,
                        unknown_event_id, challenge_hash, source_refs_json,
                        issued_at, expires_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        challenge_id,
                        retrieval_id,
                        platform,
                        selected["delivery_event_id"],
                        unknown["delivery_event_id"],
                        hashlib.sha256(challenge.encode("utf-8")).hexdigest(),
                        _json(source_refs),
                        _iso(issued),
                        _iso(expires),
                    ),
                )
                challenge_payload = {
                    "ack_required": True,
                    "ack_tool": "time_library_delivery_ack",
                    "challenge_id": challenge_id,
                    "challenge": challenge,
                    "retrieval_id": retrieval_id,
                    "platform": platform,
                    "selected_source_refs": deepcopy(source_refs),
                    "expires_at": _iso(expires),
                    **_host_attested_proof_boundary(chain_proven=False),
                    "instruction": "Call the ack tool only after the host model has received these refs and composed a response that uses the echoed refs.",
                }
            _insert_events(connection, events)

    runtime = {
        "ok": True,
        "contract": DELIVERY_RUNTIME_CONTRACT,
        "proof_layer": "installed_runtime_event_prefix",
        "platform": platform,
        "retrieval_id": retrieval_id,
        "decision": policy.get("decision", "silent"),
        "requested_delivery_form": requested_form,
        "delivery_form": policy.get("delivery_form", "silent"),
        "silent_reasons": decision["reasons"],
        "event_ids": [event["delivery_event_id"] for event in events],
        "latest_proven_stage": "selected" if events else "",
        "unknown_for_stage": ["delivered"] if challenge_payload else [],
        "source_refs": deepcopy(source_refs),
        "delivery_performed": False,
        "used_observed": False,
        "helped_observed": False,
        "helped_state": "unknown",
        "request_body_byte_capture": False,
        "response_body_byte_capture": False,
        **_host_attested_proof_boundary(chain_proven=False),
        "challenge": challenge_payload,
        "write_boundary": _write_boundary(write_performed=True),
    }
    if policy.get("should_emit") is not True:
        return _silent_result(output, runtime)
    output["delivery_runtime"] = runtime
    output.update(
        {
            "read_only": False,
            "source_memory_read_only": True,
            "write_performed": True,
            "derived_delivery_audit_write_performed": True,
            "raw_write_performed": False,
            "memory_write_performed": False,
            "platform_write_performed": False,
        }
    )
    receipt = output.get("consumer_receipt")
    if isinstance(receipt, dict):
        receipt["source_memory_read_only"] = True
        receipt["derived_delivery_audit_write_performed"] = True
    return output


def _insert_security_event(
    connection: sqlite3.Connection,
    *,
    challenge_id: str,
    platform: str,
    reason: str,
) -> str:
    event_id = _new_id("delivery-security")
    connection.execute(
        """
        INSERT INTO delivery_security_events (
            security_event_id, challenge_id, platform, reason, observed_at, evidence_ref
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            event_id,
            challenge_id,
            platform,
            reason,
            _iso(),
            "delivery-security:%s" % event_id,
        ),
    )
    return event_id


def _load_chain(connection: sqlite3.Connection, retrieval_id: str) -> List[Dict[str, Any]]:
    rows = connection.execute(
        "SELECT event_json FROM delivery_events WHERE retrieval_id = ? ORDER BY rowid",
        (retrieval_id,),
    ).fetchall()
    return [json.loads(row["event_json"]) for row in rows]


def _canonical_ack_refs(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, list):
        return []
    refs: List[Dict[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            return []
        reference = _source_ref_from_mapping(item)
        if not reference:
            return []
        refs.append(reference)
    return refs


def _ack_error(
    connection: sqlite3.Connection,
    *,
    challenge_id: str,
    platform: str,
    reason: str,
) -> Dict[str, Any]:
    security_event_id = _insert_security_event(
        connection,
        challenge_id=challenge_id,
        platform=platform,
        reason=reason,
    )
    return {
        "ok": False,
        "contract": DELIVERY_ACK_CONTRACT,
        "error": reason,
        "security_gate_observed": True,
        "security_event_id": security_event_id,
        "delivery_performed": False,
        "used_observed": False,
        **_host_attested_proof_boundary(chain_proven=False),
        "write_boundary": _write_boundary(write_performed=True),
    }


def acknowledge_delivery(
    arguments: Mapping[str, Any],
    *,
    memcore_root: Any = None,
    connection_context: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Resolve delivered/used from one host-model challenge response."""
    args = arguments if isinstance(arguments, Mapping) else {}
    challenge_id = _text(args.get("challenge_id"), 180)
    challenge = _text(args.get("challenge"), 500)
    retrieval_id = _text(args.get("retrieval_id"), 180)
    platform = _normalize_host_identity(args.get("platform"))
    request_id = _text(args.get("request_id"), 240)
    response_evidence_ref = _text(args.get("response_evidence_ref"), 300)
    used_source_refs = _canonical_ack_refs(args.get("used_source_refs"))
    verification = verified_host_connection(
        connection_context,
        platform=platform,
        memcore_root=memcore_root,
    )
    if verification.get("ok") is not True:
        return {
            "ok": False,
            "contract": DELIVERY_ACK_CONTRACT,
            "error": verification.get("error", "verified_host_connection_required"),
            "security_gate_observed": False,
            "delivery_performed": False,
            "used_observed": False,
            **_host_attested_proof_boundary(chain_proven=False),
            "write_boundary": _write_boundary(write_performed=False),
        }
    with _connect(memcore_root) as connection:
        if not all((challenge_id, challenge, retrieval_id, platform, request_id, response_evidence_ref, used_source_refs)):
            return _ack_error(
                connection,
                challenge_id=challenge_id,
                platform=platform,
                reason="delivery_ack_required_fields_missing",
            )
        row = connection.execute(
            "SELECT * FROM delivery_challenges WHERE challenge_id = ?",
            (challenge_id,),
        ).fetchone()
        if row is None:
            return _ack_error(
                connection,
                challenge_id=challenge_id,
                platform=platform,
                reason="delivery_challenge_not_found",
            )
        if row["retrieval_id"] != retrieval_id or row["platform"] != platform:
            return _ack_error(
                connection,
                challenge_id=challenge_id,
                platform=platform,
                reason="delivery_challenge_identity_mismatch",
            )
        if not hmac.compare_digest(
            row["challenge_hash"],
            hashlib.sha256(challenge.encode("utf-8")).hexdigest(),
        ):
            return _ack_error(
                connection,
                challenge_id=challenge_id,
                platform=platform,
                reason="delivery_challenge_mismatch",
            )
        expires_at = _parse_iso(row["expires_at"])
        if expires_at is None or _now() > expires_at:
            return _ack_error(
                connection,
                challenge_id=challenge_id,
                platform=platform,
                reason="delivery_challenge_expired",
            )
        expected_refs = json.loads(row["source_refs_json"])
        expected_keys = {_json(ref) for ref in expected_refs}
        used_keys = {_json(ref) for ref in used_source_refs}
        if not used_keys or not used_keys.issubset(expected_keys):
            return _ack_error(
                connection,
                challenge_id=challenge_id,
                platform=platform,
                reason="used_source_refs_not_selected_for_delivery",
            )
        chain = _load_chain(connection, retrieval_id)
        if any(event.get("delivery_stage") == "used" for event in chain):
            return {
                "ok": True,
                "contract": DELIVERY_ACK_CONTRACT,
                "idempotent": True,
                "platform": platform,
                "retrieval_id": retrieval_id,
                "latest_proven_stage": "used",
                "helped_state": "unknown",
                "delivery_performed": True,
                "used_observed": True,
                **_host_attested_proof_boundary(chain_proven=True),
                "write_boundary": _write_boundary(write_performed=False),
            }
        if not chain or chain[-1].get("delivery_stage") != UNKNOWN_STAGE or chain[-1].get("unknown_for_stage") != "delivered":
            return _ack_error(
                connection,
                challenge_id=challenge_id,
                platform=platform,
                reason="delivery_chain_not_awaiting_ack",
            )
        previous = chain[-1]
        source_refs = expected_refs
        delivered = _event(
            retrieval_id=retrieval_id,
            platform=platform,
            stage="delivered",
            delivery_form=previous["delivery_form"],
            source_refs=source_refs,
            previous_event_id=previous["delivery_event_id"],
            extra={
                "delivery_observation": {
                    "kind": "platform_model_request",
                    "observed": True,
                    "evidence_ref": "host-model-challenge-ack:%s" % challenge_id,
                    "request_id": request_id,
                    "source_refs": deepcopy(source_refs),
                    "observation_method": "host_model_challenge_response",
                    "request_body_byte_capture": False,
                    **_host_attested_proof_boundary(chain_proven=True),
                }
            },
        )
        used = _event(
            retrieval_id=retrieval_id,
            platform=platform,
            stage="used",
            delivery_form=previous["delivery_form"],
            source_refs=source_refs,
            previous_event_id=delivered["delivery_event_id"],
            extra={
                "delivery_observation": deepcopy(delivered["delivery_observation"]),
                "adoption_evidence": {
                    "kind": "response_source_refs",
                    "observed": True,
                    "evidence_ref": response_evidence_ref,
                    "observation_method": "host_model_composed_response_source_refs",
                    "response_body_byte_capture": False,
                    **_host_attested_proof_boundary(chain_proven=True),
                },
                "used_source_refs": deepcopy(used_source_refs),
            },
        )
        unknown_help = _event(
            retrieval_id=retrieval_id,
            platform=platform,
            stage=UNKNOWN_STAGE,
            delivery_form=previous["delivery_form"],
            source_refs=source_refs,
            previous_event_id=used["delivery_event_id"],
            extra={
                "delivery_observation": deepcopy(delivered["delivery_observation"]),
                "adoption_evidence": deepcopy(used["adoption_evidence"]),
                "used_source_refs": deepcopy(used_source_refs),
                "unknown_for_stage": "helped",
                "unknown_reason": "user_feedback_or_task_outcome_not_observed",
            },
        )
        extended = chain + [delivered, used, unknown_help]
        validation = validate_delivery_chain(extended)
        if validation.get("ok") is not True:
            return _ack_error(
                connection,
                challenge_id=challenge_id,
                platform=platform,
                reason="delivery_ack_chain_validation_failed",
            )
        _insert_events(
            connection,
            [delivered, used, unknown_help],
            validate_as_complete_chain=False,
        )
    return {
        "ok": True,
        "contract": DELIVERY_ACK_CONTRACT,
        "proof_layer": "installed_runtime_host_model_challenge_response",
        "platform": platform,
        "retrieval_id": retrieval_id,
        "event_ids": [delivered["delivery_event_id"], used["delivery_event_id"], unknown_help["delivery_event_id"]],
        "latest_proven_stage": "used",
        "unknown_for_stage": ["helped"],
        "delivery_performed": True,
        "used_observed": True,
        "helped_observed": False,
        "helped_state": "unknown",
        "model_request_observation": "host_model_challenge_response",
        "request_body_byte_capture": False,
        "response_body_byte_capture": False,
        **_host_attested_proof_boundary(chain_proven=True),
        "write_boundary": _write_boundary(write_performed=True),
    }


def _chain_summary(events: Sequence[Mapping[str, Any]], decision: Mapping[str, Any]) -> Dict[str, Any]:
    latest_proven = ""
    unresolved: List[str] = []
    latest_at = decision.get("observed_at", "")
    source_ref_count = 0
    for event in events:
        latest_at = event.get("recorded_at") or latest_at
        if not source_ref_count:
            source_ref_count = len(event.get("source_refs") or [])
        stage = event.get("delivery_stage")
        if stage == UNKNOWN_STAGE:
            target = str(event.get("unknown_for_stage") or "")
            if target and target not in unresolved:
                unresolved.append(target)
        elif stage in DELIVERY_STAGES:
            latest_proven = str(stage)
            if stage in unresolved:
                unresolved.remove(stage)
    return {
        "retrieval_id": decision.get("retrieval_id", ""),
        "platform": decision.get("platform", ""),
        "decision": decision.get("decision", ""),
        "delivery_form": decision.get("delivery_form", ""),
        "latest_proven_stage": latest_proven,
        "unknown_for_stage": unresolved,
        "silent_reasons": decision.get("reasons") or [],
        "event_count": len(events),
        "source_ref_count": source_ref_count,
        "observed_at": decision.get("observed_at", ""),
        "latest_at": latest_at,
    }


def query_delivery_status(
    *,
    memcore_root: Any = None,
    platform: str = "",
    limit: int = 12,
) -> Dict[str, Any]:
    """Return a privacy-bounded read projection for the console and audits."""
    selected_platform = _normalize_host_identity(platform)
    bounded_limit = max(1, min(int(limit or 12), 100))
    path = delivery_store_path(memcore_root)
    if not path.exists():
        stages = {
            stage: {"state": "not_measured", "count": 0, "unknown_count": 0, "latest_at": ""}
            for stage in DELIVERY_STAGES
        }
        return {
            "ok": True,
            "contract": DELIVERY_STATUS_CONTRACT,
            "proof_layer": "installed_runtime_read_projection",
            "store_initialized": False,
            "platform": selected_platform,
            "stages": stages,
            "platform_delivery_proven": False,
            **_host_attested_proof_boundary(chain_proven=False),
            "definition_of_proven": {
                "status": "unproven",
                "cells": {name: False for name in (
                    "passive_gate_observed",
                    "model_evidence_receipt_observed",
                    "answer_evidence_observed",
                    "receipt_visibility_observed",
                    "security_gate_observed",
                )},
            },
            "recent_chains": [],
            "read_only": True,
            "write_performed": False,
            "source_memory_read_only": True,
        }
    with _connect_read_only(path) as connection:
        where = " WHERE platform = ?" if selected_platform else ""
        params: Tuple[Any, ...] = (selected_platform,) if selected_platform else ()
        event_rows = connection.execute(
            "SELECT event_json FROM delivery_events%s ORDER BY rowid" % where,
            params,
        ).fetchall()
        decision_rows = connection.execute(
            "SELECT decision_json FROM delivery_decisions%s ORDER BY observed_at DESC LIMIT ?" % where,
            params + (bounded_limit,),
        ).fetchall()
        decision_total = connection.execute(
            "SELECT COUNT(*) AS count FROM delivery_decisions%s" % where,
            params,
        ).fetchone()["count"]
        silent_total = connection.execute(
            "SELECT COUNT(*) AS count FROM delivery_decisions%s%sdecision = 'silent'" % (
                where,
                " AND " if where else " WHERE ",
            ),
            params,
        ).fetchone()["count"]
        security_where = " WHERE platform = ?" if selected_platform else ""
        security_count = connection.execute(
            "SELECT COUNT(*) AS count FROM delivery_security_events%s" % security_where,
            params,
        ).fetchone()["count"]
    events = [json.loads(row["event_json"]) for row in event_rows]
    decisions = [json.loads(row["decision_json"]) for row in decision_rows]
    events_by_retrieval: Dict[str, List[Dict[str, Any]]] = {}
    for event in events:
        events_by_retrieval.setdefault(str(event.get("retrieval_id") or ""), []).append(event)
    stage_counts = {stage: 0 for stage in DELIVERY_STAGES}
    unknown_counts = {stage: 0 for stage in DELIVERY_STAGES}
    latest_at = {stage: "" for stage in DELIVERY_STAGES}
    for event in events:
        stage = str(event.get("delivery_stage") or "")
        target = str(event.get("unknown_for_stage") or "") if stage == UNKNOWN_STAGE else ""
        timestamp = str(event.get("recorded_at") or "")
        if stage in stage_counts:
            stage_counts[stage] += 1
            latest_at[stage] = max(latest_at[stage], timestamp)
        if target in unknown_counts:
            unknown_counts[target] += 1
            latest_at[target] = max(latest_at[target], timestamp)
    stages = {}
    for stage in DELIVERY_STAGES:
        state = "observed" if stage_counts[stage] else "unknown" if unknown_counts[stage] else "not_measured"
        stages[stage] = {
            "state": state,
            "count": stage_counts[stage],
            "unknown_count": unknown_counts[stage],
            "latest_at": latest_at[stage],
        }
    recent_chains = [
        _chain_summary(events_by_retrieval.get(str(decision.get("retrieval_id") or ""), []), decision)
        for decision in decisions
    ]
    cells = {
        "passive_gate_observed": int(silent_total or 0) > 0,
        "model_evidence_receipt_observed": stage_counts["delivered"] > 0,
        "answer_evidence_observed": stage_counts["used"] > 0,
        "receipt_visibility_observed": bool(recent_chains),
        "security_gate_observed": int(security_count or 0) > 0,
    }
    missing = [name for name, observed in cells.items() if not observed]
    return {
        "ok": True,
        "contract": DELIVERY_STATUS_CONTRACT,
        "proof_layer": "installed_runtime_read_projection",
        "store_initialized": True,
        "platform": selected_platform,
        "stages": stages,
        "definition_of_proven": {
            "status": "proven" if not missing else "unproven",
            "cells": cells,
            "missing_cells": missing,
            "proof_scope": "host_attested_append_only_events_plus_local_receipt_projection",
        },
        "platform_delivery_proven": not missing,
        **_host_attested_proof_boundary(chain_proven=not missing),
        "helped_not_implied_by_used": True,
        "request_body_byte_capture": False,
        "response_body_byte_capture": False,
        "recent_chains": recent_chains,
        "totals": {
            "events": len(events),
            "decisions": int(decision_total or 0),
            "security_events": int(security_count or 0),
        },
        "read_only": True,
        "write_performed": False,
        "source_memory_read_only": True,
        "raw_write_performed": False,
        "memory_write_performed": False,
        "platform_write_performed": False,
    }


__all__ = [
    "CHALLENGE_TTL_SECONDS",
    "DELIVERY_ACK_CONTRACT",
    "DELIVERY_RUNTIME_CONTRACT",
    "DELIVERY_STATUS_CONTRACT",
    "HOST_CONNECTION_RECEIPT_CONTRACT",
    "HOST_CONNECTION_RESUME_CONTRACT",
    "HOST_CONNECTION_RESUME_TTL_SECONDS",
    "acknowledge_delivery",
    "delivery_store_path",
    "extract_delivery_source_refs",
    "instrument_recall_result",
    "query_verified_host_connections",
    "query_delivery_status",
    "record_verified_host_connection",
    "rotate_verified_host_connection_resume",
    "verified_host_connection",
]
