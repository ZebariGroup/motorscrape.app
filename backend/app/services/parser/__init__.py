"""Vehicle inventory extraction from dealership HTML (structured JSON, DOM, LLM)."""

from __future__ import annotations

from app.services.parser.factory import (
    DealerDotComInventoryParser,
    DealerOnInventoryParser,
    GenericInventoryParser,
    InventoryHtmlParser,
    inventory_parser_for_platform,
)
from app.services.parser.monolith import (
    collect_structured_vehicle_dicts,
    dict_to_vehicle_listing,
    enrich_team_velocity_srp_pricing,
    extract_dom_vehicle_cards,
    extract_vehicles_from_html,
    find_next_page_url,
    infer_inventory_pagination,
    infer_next_page_from_inventory_api,
    synthesize_next_page_url,
    try_extract_vehicles_without_llm,
)

__all__ = [
    "DealerDotComInventoryParser",
    "DealerOnInventoryParser",
    "GenericInventoryParser",
    "InventoryHtmlParser",
    "collect_structured_vehicle_dicts",
    "dict_to_vehicle_listing",
    "enrich_team_velocity_srp_pricing",
    "extract_dom_vehicle_cards",
    "extract_vehicles_from_html",
    "find_next_page_url",
    "infer_inventory_pagination",
    "infer_next_page_from_inventory_api",
    "inventory_parser_for_platform",
    "synthesize_next_page_url",
    "try_extract_vehicles_without_llm",
]
