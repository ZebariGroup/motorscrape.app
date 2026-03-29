"""DealerOn extraction strategy."""

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
    return try_extract_vehicles_without_llm(
        page_url=page_url,
        html=html,
        make_filter=make_filter,
        model_filter=model_filter,
        vehicle_category=vehicle_category,
        platform_id="dealer_on",
    )
