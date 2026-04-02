"""Shift Digital / Harley digital showroom extraction strategy."""

from __future__ import annotations

from app.schemas import ExtractionResult
from app.services.parser import try_extract_vehicles_without_llm


def extract_inventory(
    *,
    page_url: str,
    html: str,
    make_filter: str,
    model_filter: str,
    vehicle_category: str = "car",
) -> ExtractionResult | None:
    primary = try_extract_vehicles_without_llm(
        page_url=page_url,
        html=html,
        make_filter=make_filter,
        model_filter=model_filter,
        vehicle_category=vehicle_category,
        platform_id="shift_digital",
    )
    if primary is not None and primary.vehicles:
        return primary

    html_lower = (html or "").lower()
    if "harley-davidson" not in html_lower and "page_infofilters" not in html_lower:
        return primary

    fallback = try_extract_vehicles_without_llm(
        page_url=page_url,
        html=html,
        make_filter=make_filter,
        model_filter=model_filter,
        vehicle_category=vehicle_category,
        platform_id="harley_digital_showroom",
    )
    return fallback or primary
