"""Local mirror of neutral Tiandao capability exchange candidates."""

from __future__ import annotations

from typing import Optional


class CapabilityCategory(str):
    RECALL = "recall"
    INJECT = "inject"
    OBSERVE = "observe"
    ROUTING = "routing"
    EXPERIENCE = "experience"
    RAW_PROJECTION = "raw_projection"


class CapabilityOffer:
    def __init__(
        self,
        source_system: str,
        category: str,
        capability_id: str,
        description: str,
        is_reentrant: bool = False,
        auth_required: bool = False,
        production_ready: bool = False,
    ):
        self.source_system = source_system
        self.category = category
        self.capability_id = capability_id
        self.description = description
        self.is_reentrant = is_reentrant
        self.auth_required = auth_required
        self.production_ready = production_ready

    def to_dict(self) -> dict:
        return {
            "source_system": self.source_system,
            "category": self.category,
            "capability_id": self.capability_id,
            "description": self.description,
            "is_reentrant": self.is_reentrant,
            "auth_required": self.auth_required,
            "production_ready": self.production_ready,
        }

    def __repr__(self) -> str:
        return f"CapabilityOffer({self.source_system}/{self.category}.{self.capability_id})"


class CapabilityExchange:
    def __init__(self, source_system: str):
        self.source_system = source_system
        self._offers: list[CapabilityOffer] = []

    def register_capability(self, offer: CapabilityOffer) -> None:
        if offer.source_system != self.source_system:
            raise ValueError(
                f"CapabilityOffer source_system '{offer.source_system}' does not match "
                f"exchange source_system '{self.source_system}'"
            )
        self._offers.append(offer)

    def query_capabilities(
        self,
        category: Optional[str] = None,
        production_ready: Optional[bool] = None,
    ) -> list[CapabilityOffer]:
        results = self._offers
        if category is not None:
            results = [o for o in results if o.category == category]
        if production_ready is not None:
            results = [o for o in results if o.production_ready == production_ready]
        return results

    def get_tiandao_public_capabilities(self) -> list[CapabilityOffer]:
        public_categories = {
            CapabilityCategory.RECALL,
            CapabilityCategory.INJECT,
            CapabilityCategory.OBSERVE,
            CapabilityCategory.EXPERIENCE,
            CapabilityCategory.RAW_PROJECTION,
        }
        return [o for o in self._offers if o.category in public_categories]
