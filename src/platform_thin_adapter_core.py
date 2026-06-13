#!/usr/bin/env python3
"""Platform Guard core aggregate under Tiandao jurisdiction.

This module deliberately does not own platform scanning internals. It exposes the
Platform Guard contract and re-exports the catalog, model-identity, and surface
scanner modules so existing imports through platform_thin_adapter_registry keep
working.
"""

from __future__ import annotations

from typing import Any

try:
    from src.platform_guard_catalog import *
except Exception:  # pragma: no cover - direct script import fallback
    from platform_guard_catalog import *
try:
    from src.platform_guard_model_identity import *
except Exception:  # pragma: no cover - direct script import fallback
    from platform_guard_model_identity import *
try:
    from src.platform_guard_surface_scan import *
except Exception:  # pragma: no cover - direct script import fallback
    from platform_guard_surface_scan import *

PLATFORM_GUARD_CORE_CONTRACT = "tiandao_platform_guard_core.v1"


def get_platform_guard_core_contract() -> dict[str, Any]:
    return {
        "ok": True,
        "contract": PLATFORM_GUARD_CORE_CONTRACT,
        "zh_name": "平台守护底座",
        "en_name": "Platform Guard Core",
        "parent_tiandao_contract": "tiandao_time_river.v1",
        "workbench_id": "platform_guard",
        "console_layer": "platform_guard_core",
        "read_only": True,
        "dry_run": True,
        "write_performed": False,
        "raw_write_performed": False,
        "memory_write_performed": False,
        "platform_write_performed": False,
        "model_call_performed": False,
        "not_raw_origin": True,
        "raw_origin_policy": "platform_guard_detects_inlets_but_does_not_replace_time_origin",
        "adapter_boundary_policy": "private_platform_protocols_stay_in_thin_adapters",
        "subcontracts": [
            "tiandao_platform_guard_catalog.v1",
            "tiandao_platform_guard_model_identity.v1",
            "tiandao_platform_guard_surface_scan.v1",
        ],
    }


__all__ = [name for name in globals() if not name.startswith("__")]
