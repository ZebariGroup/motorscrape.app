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


class DealerInspireInventoryParser:
    """Normalize Dealer Inspire / Next.js inventory blobs before dict_to_vehicle_listing."""

    platform_id = "dealer_inspire"

    def normalize_pricing_dicts(self, records: list[dict]) -> list[dict]:
        normalized: list[dict] = []
        for record in records:
            item = dict(record)
            if not item.get("make"):
                m = item.get("vehicleMake") or item.get("makeName")
                if m:
                    item["make"] = m
            if not item.get("model"):
                mdl = item.get("vehicleModel") or item.get("modelName")
                if mdl:
                    item["model"] = mdl
            if item.get("year") in (None, "", 0) and (
                item.get("vehicleYear") is not None or item.get("yearValue") is not None
            ):
                item["year"] = item.get("vehicleYear") if item.get("vehicleYear") is not None else item.get("yearValue")
            if not item.get("vdpUrl"):
                link = item.get("detailUrl") or item.get("vehicleUrl") or item.get("vdpPath")
                if link:
                    item["vdpUrl"] = link
            nested = item.get("vehicle")
            if isinstance(nested, dict):
                for key in (
                    "make",
                    "model",
                    "year",
                    "vin",
                    "vdpUrl",
                    "stockNumber",
                    "price",
                    "trim",
                    "mileage",
                ):
                    nv = nested.get(key)
                    if nv not in (None, "", [], {}) and item.get(key) in (None, "", [], {}):
                        item[key] = nv
            normalized.append(item)
        return normalized


class OneAudiFalconInventoryParser:
    platform_id = "oneaudi_falcon"

    def normalize_pricing_dicts(self, records: list[dict]) -> list[dict]:
        normalized: list[dict] = []
        for record in records:
            item = dict(record)
            brand = item.get("brand")
            if isinstance(brand, dict) and brand.get("name") and not item.get("make"):
                item["make"] = brand.get("name")
            offers = item.get("offers")
            if isinstance(offers, dict):
                if offers.get("url") and not item.get("vdpUrl"):
                    item["vdpUrl"] = offers.get("url")
                if offers.get("price") not in (None, "") and not item.get("price"):
                    item["price"] = offers.get("price")
            if item.get("vehicleConfiguration") and not item.get("trim"):
                item["trim"] = item.get("vehicleConfiguration")
            if item.get("name") and not item.get("title"):
                item["title"] = item.get("name")
            normalized.append(item)
        return normalized


def inventory_parser_for_platform(platform_id: str | None) -> InventoryHtmlParser:
    if platform_id == "dealer_dot_com":
        return DealerDotComInventoryParser()
    if platform_id == "dealer_on":
        return DealerOnInventoryParser()
    if platform_id == "dealer_inspire":
        return DealerInspireInventoryParser()
    if platform_id == "oneaudi_falcon":
        return OneAudiFalconInventoryParser()
    return GenericInventoryParser()
