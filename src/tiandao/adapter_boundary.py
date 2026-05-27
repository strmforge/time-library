"""Tiandao adapter boundary.

Adapters are thin replaceable layers. They translate a platform native shape to
the Tiandao contract and back without owning product policy or writing platform
memory directly.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .context_service import ContextPackage


class AdapterBoundary(ABC):
    @property
    @abstractmethod
    def source_system(self) -> str:
        raise NotImplementedError

    @property
    def is_thin_adapter(self) -> bool:
        return True

    @property
    def can_write_memory(self) -> bool:
        return False

    @property
    def can_write_skill(self) -> bool:
        return False

    @property
    def is_production_ready(self) -> bool:
        return False

    @abstractmethod
    def to_tiandao_contract(self, native_package: dict) -> "ContextPackage":
        raise NotImplementedError

    @abstractmethod
    def from_tiandao_contract(self, package: "ContextPackage") -> dict:
        raise NotImplementedError
