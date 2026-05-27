"""Honghuang shared Tiandao core contracts.

Tiandao is shared by the three Honghuang subsystems: Yifanchen, Nantianmen,
and Liudao. Each subsystem uses the parts it needs through replaceable thin
layers while external platforms keep their own nature.
"""

from .adapter_boundary import AdapterBoundary
from .boundary import BoundaryChecker, SourceRef
from .capability_exchange import CapabilityCategory, CapabilityExchange, CapabilityOffer
from .context_service import (
    ContextPackage,
    ContextService,
    IntentMode,
    MemoryContextMode,
    ValidationError,
    generate_event_id,
    hash_query,
    preserve_dict,
    sanitize_dict,
    ts,
)
from .memory_context import (
    MemoryContextModeA,
    MemoryContextModeB,
    MemoryContextModeC,
    describe_mode,
    get_ttl_for_mode,
    is_auth_required_for_mode,
)

__all__ = [
    "AdapterBoundary",
    "BoundaryChecker",
    "CapabilityCategory",
    "CapabilityExchange",
    "CapabilityOffer",
    "ContextPackage",
    "ContextService",
    "IntentMode",
    "MemoryContextMode",
    "MemoryContextModeA",
    "MemoryContextModeB",
    "MemoryContextModeC",
    "SourceRef",
    "ValidationError",
    "describe_mode",
    "generate_event_id",
    "get_ttl_for_mode",
    "hash_query",
    "is_auth_required_for_mode",
    "preserve_dict",
    "sanitize_dict",
    "ts",
]
