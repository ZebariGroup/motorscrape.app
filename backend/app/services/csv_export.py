from __future__ import annotations

import csv
import io
from typing import Any

CSV_HEADERS = [
    "dealership",
    "dealership_website",
    "year",
    "make",
    "model",
    "trim",
    "price",
    "msrp",
    "dealer_discount",
    "mileage",
    "days_on_lot",
    "stock_date",
    "incentive_labels",
    "feature_highlights",
    "vin",
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
                listing.get("year") or "",
                listing.get("make") or "",
                listing.get("model") or "",
                listing.get("trim") or "",
                listing.get("price") or "",
                listing.get("msrp") or "",
                listing.get("dealer_discount") or "",
                listing.get("mileage") or "",
                listing.get("days_on_lot") or "",
                listing.get("stock_date") or "",
                " | ".join(listing.get("incentive_labels") or []),
                " | ".join(listing.get("feature_highlights") or []),
                listing.get("vin") or "",
                listing.get("vehicle_condition") or "",
                listing.get("listing_url") or "",
                listing.get("raw_title") or "",
            ]
        )
    return buffer.getvalue()
