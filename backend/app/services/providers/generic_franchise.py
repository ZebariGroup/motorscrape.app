"""Fallback extraction strategy for known franchise platforms without bespoke handlers yet."""

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
    )


def extract_inventory_for_platform(platform_id: str):
    """Structured extraction with platform-specific parser hooks (reduces LLM fallback)."""

    def _extract(
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
            platform_id=platform_id,
        )

    return _extract
