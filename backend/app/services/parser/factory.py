"""
Platform-scoped parser helpers (strategy-style).

Use `inventory_parser_for_platform(platform_id)` when a code path needs platform-specific
normalization hooks without hard-coding vendor IDs throughout the monolith.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class InventoryHtmlParser(Protocol):
    """Optional platform-specific steps applied to structured vehicle dicts."""

    platform_id: str

    def normalize_pricing_dicts(self, records: list[dict]) -> list[dict]:
        """Return vehicle dicts after any platform-specific price / field normalization."""


class GenericInventoryParser:
    platform_id = "generic"

    def normalize_pricing_dicts(self, records: list[dict]) -> list[dict]:
        return records


class DealerDotComInventoryParser:
    platform_id = "dealer_dot_com"

    def normalize_pricing_dicts(self, records: list[dict]) -> list[dict]:
        # Dealer.com final pricing is handled in monolith `_pick_price_from_dict` via `isFinalPrice`.
        return records


class DealerOnInventoryParser:
    platform_id = "dealer_on"

    def normalize_pricing_dicts(self, records: list[dict]) -> list[dict]:
        return records


def inventory_parser_for_platform(platform_id: str | None) -> InventoryHtmlParser:
    if platform_id == "dealer_dot_com":
        return DealerDotComInventoryParser()
    if platform_id == "dealer_on":
        return DealerOnInventoryParser()
    return GenericInventoryParser()
