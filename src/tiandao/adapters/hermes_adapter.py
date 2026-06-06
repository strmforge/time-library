"""Hermes adapter for the local neutral Tiandao candidate mirror.

This file maps Hermes artifacts into memory context projections. It does not
make Hermes, Yifanchen, or this adapter the Tiandao runtime itself.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tiandao.adapter_boundary import AdapterBoundary
from tiandao.boundary import SourceRef
from tiandao.context_service import ContextPackage, IntentMode, MemoryContextMode, preserve_dict
from tiandao.validators import validate_context_package

HERMES_FORBIDDEN_KEYS: frozenset[str] = frozenset()

ARTIFACT_CAPTURE_MAP = {
    "session_json": "RAW_PROJECTION",
    "request_dump_json": "RAW_PROJECTION",
    "learning_json": "RAW_PROJECTION",
    "skill_json": "RAW_REFERENCE",
    "state_db": "RAW_REFERENCE",
}


def _sanitize_hermes_artifact(artifact: dict) -> dict:
    """Compatibility name: Hermes artifacts are preserved as-is."""
    return preserve_dict(artifact)


def _extract_session_summary(artifact: dict) -> str:
    for key in ("summary", "title", "session_id", "filename", "artifact_type"):
        value = artifact.get(key)
        if value:
            return str(value)
    return "hermes artifact"


class HermesToTiandaoAdapter(AdapterBoundary):
    """Thin Hermes adapter for the local neutral candidate contract."""

    version = "v1"

    @property
    def source_system(self) -> str:
        return "hermes"

    def to_tiandao_contract(self, native_package: dict) -> ContextPackage:
        artifact = _sanitize_hermes_artifact(native_package)
        artifact_type = artifact.get("artifact_type", "artifact")
        classification = artifact.get("capture_classification") or ARTIFACT_CAPTURE_MAP.get(
            artifact_type, "RAW_PROJECTION"
        )
        session_id = artifact.get("session_id") or Path(artifact.get("filename", "hermes-artifact")).stem
        source_path = artifact.get("source_path", "")
        mode = MemoryContextMode.MODE_C if classification == "RAW_REFERENCE" else MemoryContextMode.MODE_B
        ref = SourceRef(
            ref_id=f"hermes:{session_id}:{artifact_type}",
            source_system="hermes",
            artifact_type=artifact_type,
            ref_path=source_path,
            artifact_id=session_id,
            captured_at=artifact.get("mtime", ""),
            content=artifact,
        )
        return ContextPackage(
            query=_extract_session_summary(artifact),
            source_system="hermes",
            canonical_window_id=session_id,
            session_id=session_id,
            intent_mode=IntentMode.EVIDENCE,
            memory_context_mode=mode,
            source_refs=[ref.to_dict()],
            raw_projection={"hermes_artifact": artifact},
            scope_enforced=True,
            injection_blocked=False,
            memory_write=False,
        )

    def from_tiandao_contract(self, package: ContextPackage) -> dict:
        d = package.to_dict() if hasattr(package, "to_dict") else dict(package)
        return {
            "adapter": "HermesToTiandaoAdapter",
            "direction": "tiandao -> hermes",
            "original_query_hash": d.get("query_hash", ""),
            "raw_projection": d.get("raw_projection", {}),
            "note": "Hermes consumes raw projections through its own platform mechanism.",
        }

    def native_to_tiandao(self, artifact: dict) -> dict:
        package = self.to_tiandao_contract(artifact)
        result = package.to_dict()
        artifact_type = artifact.get("artifact_type", "artifact")
        classification = artifact.get("capture_classification") or ARTIFACT_CAPTURE_MAP.get(
            artifact_type, "RAW_PROJECTION"
        )
        result["hermes_artifact"] = _sanitize_hermes_artifact(artifact)
        result["hermes_capture_classification"] = classification
        result["adapter_verdict"] = self.get_adapter_verdict()
        result["capability_profile"] = self.get_capability_profile()
        return result

    def tiandao_to_native(self, tiandao_pkg: dict) -> dict:
        return self.from_tiandao_contract(tiandao_pkg)

    def validate_tiandao_contract(self, package: dict) -> tuple[bool, list[str]]:
        return validate_context_package(package)

    def get_capability_profile(self) -> dict:
        return {
            "adapter": "HermesToTiandaoAdapter",
            "version": self.version,
            "source_system": "hermes",
            "can_write_memory": self.can_write_memory,
            "can_write_skill": self.can_write_skill,
            "is_production_ready": self.is_production_ready,
            "raw_projection_supported": True,
            "artifact_types_supported": sorted(ARTIFACT_CAPTURE_MAP),
            "gateway_running": self._probe_gateway_running(),
        }

    def get_consumption_routes(self) -> dict[str, dict[str, Any]]:
        return {
            artifact_type: {
                "classification": classification,
                "memory_write": False,
                "skill_write": False,
                "context_delivery": False,
            }
            for artifact_type, classification in ARTIFACT_CAPTURE_MAP.items()
        }

    def get_adapter_verdict(self) -> dict:
        return {
            "adapter": "HermesToTiandaoAdapter",
            "version": self.version,
            "production_ready": self.is_production_ready,
            "memory_write_enabled": self.can_write_memory,
            "skill_write_enabled": self.can_write_skill,
            "context_delivery_executed": False,
            "gateway_reachable": self._probe_gateway_running(),
            "adapter_verdict": "READY_FOR_RAW_PROJECTION_CANDIDATE",
            "notes": [
                "local thin adapter",
                "raw projection preserved",
                "platform internals unchanged",
            ],
        }

    def _probe_gateway_running(self) -> bool:
        return False


def hermes_artifact_to_tiandao(artifact: dict) -> dict:
    return HermesToTiandaoAdapter().native_to_tiandao(artifact)


def get_hermes_adapter_verdict() -> dict:
    return HermesToTiandaoAdapter().get_adapter_verdict()


def get_hermes_adapter_capability_profile() -> dict:
    return HermesToTiandaoAdapter().get_capability_profile()
