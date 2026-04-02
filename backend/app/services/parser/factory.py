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


def _normalize_marketing_platform_records(records: list[dict]) -> list[dict]:
    normalized: list[dict] = []
    for record in records:
        item = dict(record)
        if not item.get("make"):
            make_value = (
                item.get("vehicleMake")
                or item.get("makeName")
                or item.get("brandName")
                or item.get("manufacturerName")
            )
            if make_value:
                item["make"] = make_value
        if not item.get("model"):
            model_value = item.get("vehicleModel") or item.get("modelName")
            if model_value:
                item["model"] = model_value
        if not item.get("trim"):
            trim_value = item.get("vehicleTrim") or item.get("trimName") or item.get("seriesName")
            if trim_value:
                item["trim"] = trim_value
        if item.get("year") in (None, "", 0):
            year_value = item.get("vehicleYear") or item.get("yearModel") or item.get("modelYear")
            if year_value not in (None, "", 0):
                item["year"] = year_value
        if not item.get("price"):
            price_value = (
                item.get("currentPrice")
                or item.get("internetPrice")
                or item.get("salePrice")
                or item.get("sellingPrice")
                or item.get("ourPrice")
            )
            if price_value not in (None, ""):
                item["price"] = price_value
        if not item.get("msrp"):
            msrp_value = item.get("listPrice") or item.get("msrpPrice") or item.get("retailPrice")
            if msrp_value not in (None, ""):
                item["msrp"] = msrp_value
        if not item.get("vdpUrl"):
            link_value = (
                item.get("detailUrl")
                or item.get("vehicleUrl")
                or item.get("detailPageUrl")
                or item.get("permalink")
            )
            if link_value:
                item["vdpUrl"] = link_value
        if not item.get("stockNumber"):
            stock_value = item.get("unitNumber") or item.get("stockNo")
            if stock_value:
                item["stockNumber"] = stock_value
        if not item.get("title"):
            title_value = item.get("vehicleTitle") or item.get("unitTitle") or item.get("name")
            if title_value:
                item["title"] = title_value
        if not item.get("imageUrl"):
            image_value = item.get("primaryImage") or item.get("image") or item.get("thumbnailUrl")
            if image_value:
                item["imageUrl"] = image_value
        normalized.append(item)
    return normalized


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


class ShiftDigitalInventoryParser:
    """Normalize Shift Digital / Harley digital showroom inventory blobs."""

    platform_id = "shift_digital"

    def normalize_pricing_dicts(self, records: list[dict]) -> list[dict]:
        return _normalize_marketing_platform_records(records)


class TeamVelocityInventoryParser:
    platform_id = "team_velocity"

    def normalize_pricing_dicts(self, records: list[dict]) -> list[dict]:
        normalized = _normalize_marketing_platform_records(records)
        out: list[dict] = []
        for item in normalized:
            row = dict(item)
            if not row.get("price"):
                current = row.get("priceCurrent") or row.get("pricecurrent")
                if current not in (None, ""):
                    row["price"] = current
            if not row.get("msrp"):
                old_price = row.get("priceOld") or row.get("priceold") or row.get("priceFirst") or row.get("pricefirst")
                if old_price not in (None, ""):
                    row["msrp"] = old_price
            if not row.get("stockNumber"):
                stock_value = row.get("stocknumber") or row.get("stock_number")
                if stock_value:
                    row["stockNumber"] = stock_value
            if not row.get("vdpUrl"):
                link_value = row.get("vehicleLink") or row.get("vehicleHref")
                if link_value:
                    row["vdpUrl"] = link_value
            out.append(row)
        return out


class PureCarsInventoryParser:
    platform_id = "purecars"

    def normalize_pricing_dicts(self, records: list[dict]) -> list[dict]:
        return _normalize_marketing_platform_records(records)


class JazelInventoryParser:
    platform_id = "jazel"

    def normalize_pricing_dicts(self, records: list[dict]) -> list[dict]:
        return _normalize_marketing_platform_records(records)


class FoxDealerInventoryParser:
    platform_id = "foxdealer"

    def normalize_pricing_dicts(self, records: list[dict]) -> list[dict]:
        return _normalize_marketing_platform_records(records)


class SincroDigitalInventoryParser:
    platform_id = "sincro_digital"

    def normalize_pricing_dicts(self, records: list[dict]) -> list[dict]:
        return _normalize_marketing_platform_records(records)


class DealerSpikeInventoryParser:
    platform_id = "dealer_spike"

    def normalize_pricing_dicts(self, records: list[dict]) -> list[dict]:
        normalized = _normalize_marketing_platform_records(records)
        out: list[dict] = []
        for item in normalized:
            row = dict(item)
            if not row.get("make"):
                make_value = row.get("itemMake") or row.get("manuf")
                if make_value:
                    row["make"] = make_value
            if not row.get("model"):
                model_value = row.get("itemModel")
                if model_value:
                    row["model"] = model_value
            if row.get("year") in (None, "", 0):
                year_value = row.get("itemYear")
                if year_value not in (None, "", 0):
                    row["year"] = year_value
            if not row.get("price"):
                price_value = row.get("itemPrice")
                if price_value not in (None, ""):
                    row["price"] = price_value
            if not row.get("vdpUrl"):
                link_value = row.get("itemUrl")
                if link_value:
                    row["vdpUrl"] = link_value
            if not row.get("stockNumber"):
                stock_value = row.get("stockNo") or row.get("stock_no") or row.get("stocknumber")
                if stock_value:
                    row["stockNumber"] = stock_value
            out.append(row)
        return out


class CDKDealerfireInventoryParser:
    platform_id = "cdk_dealerfire"

    def normalize_pricing_dicts(self, records: list[dict]) -> list[dict]:
        return _normalize_marketing_platform_records(records)


class FusionzoneInventoryParser:
    platform_id = "fusionzone"

    def normalize_pricing_dicts(self, records: list[dict]) -> list[dict]:
        return _normalize_marketing_platform_records(records)


def inventory_parser_for_platform(platform_id: str | None) -> InventoryHtmlParser:
    if platform_id == "dealer_dot_com":
        return DealerDotComInventoryParser()
    if platform_id == "dealer_on":
        return DealerOnInventoryParser()
    if platform_id == "dealer_inspire":
        return DealerInspireInventoryParser()
    if platform_id == "team_velocity":
        return TeamVelocityInventoryParser()
    if platform_id in {"shift_digital", "harley_digital_showroom"}:
        return ShiftDigitalInventoryParser()
    if platform_id == "purecars":
        return PureCarsInventoryParser()
    if platform_id == "jazel":
        return JazelInventoryParser()
    if platform_id == "foxdealer":
        return FoxDealerInventoryParser()
    if platform_id == "sincro_digital":
        return SincroDigitalInventoryParser()
    if platform_id == "dealer_spike":
        return DealerSpikeInventoryParser()
    if platform_id == "cdk_dealerfire":
        return CDKDealerfireInventoryParser()
    if platform_id == "fusionzone":
        return FusionzoneInventoryParser()
    if platform_id == "oneaudi_falcon":
        return OneAudiFalconInventoryParser()
    return GenericInventoryParser()
