from __future__ import annotations

import csv
import io
from typing import Any

CSV_HEADERS = [
    "dealership",
    "dealership_website",
    "vehicle_category",
    "year",
    "make",
    "model",
    "trim",
    "body_style",
    "drivetrain",
    "engine",
    "transmission",
    "fuel_type",
    "exterior_color",
    "price",
    "msrp",
    "dealer_discount",
    "mileage",
    "usage_value",
    "usage_unit",
    "days_on_lot",
    "stock_date",
    "history_seen_count",
    "history_days_tracked",
    "history_previous_price",
    "history_lowest_price",
    "history_highest_price",
    "history_price_change",
    "history_price_change_since_first",
    "incentive_labels",
    "feature_highlights",
    "vin",
    "vehicle_identifier",
    "vehicle_condition",
    "listing_url",
    "raw_title",
]


def listings_to_csv(listings: list[dict[str, Any]]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(CSV_HEADERS)
    for listing in listings:
        writer.writerow(
            [
                listing.get("dealership") or "",
                listing.get("dealership_website") or "",
                listing.get("vehicle_category") or "",
                listing.get("year") or "",
                listing.get("make") or "",
                listing.get("model") or "",
                listing.get("trim") or "",
                listing.get("body_style") or "",
                listing.get("drivetrain") or "",
                listing.get("engine") or "",
                listing.get("transmission") or "",
                listing.get("fuel_type") or "",
                listing.get("exterior_color") or "",
                listing.get("price") or "",
                listing.get("msrp") or "",
                listing.get("dealer_discount") or "",
                listing.get("mileage") or "",
                listing.get("usage_value") or "",
                listing.get("usage_unit") or "",
                listing.get("days_on_lot") or "",
                listing.get("stock_date") or "",
                listing.get("history_seen_count") or "",
                listing.get("history_days_tracked") or "",
                listing.get("history_previous_price") or "",
                listing.get("history_lowest_price") or "",
                listing.get("history_highest_price") or "",
                listing.get("history_price_change") or "",
                listing.get("history_price_change_since_first") or "",
                " | ".join(listing.get("incentive_labels") or []),
                " | ".join(listing.get("feature_highlights") or []),
                listing.get("vin") or "",
                listing.get("vehicle_identifier") or "",
                listing.get("vehicle_condition") or "",
                listing.get("listing_url") or "",
                listing.get("raw_title") or "",
            ]
        )
    return buffer.getvalue()
