"""Provider-specific extraction handlers."""

from __future__ import annotations

from app.schemas import ExtractionResult
from app.services.providers import (
    dealer_dot_com,
    dealer_inspire,
    dealer_on,
    generic_franchise,
    honda_acura_inventory,
    hyundai_inventory_search,
    kia_inventory,
    nissan_infiniti_inventory,
)

_HANDLERS = {
    "marinemax": generic_franchise.extract_inventory,
    "dealer_dot_com": dealer_dot_com.extract_inventory,
    "dealer_on": dealer_on.extract_inventory,
    "dealer_inspire": dealer_inspire.extract_inventory,
    "cdk_dealerfire": generic_franchise.extract_inventory,
    "d2c_media": generic_franchise.extract_inventory,
    "revver_digital_marine": generic_franchise.extract_inventory,
    "basspro_boating_center": generic_franchise.extract_inventory,
    "team_velocity": generic_franchise.extract_inventory,
    "honda_acura_inventory": honda_acura_inventory.extract_inventory,
    "hyundai_inventory_search": hyundai_inventory_search.extract_inventory,
    "kia_inventory": kia_inventory.extract_inventory,
    "nissan_infiniti_inventory": nissan_infiniti_inventory.extract_inventory,
    "ford_family_inventory": generic_franchise.extract_inventory,
    "gm_family_inventory": generic_franchise.extract_inventory,
    "toyota_lexus_oem_inventory": dealer_dot_com.extract_inventory,
    "fusionzone": generic_franchise.extract_inventory,
    "shift_digital": generic_franchise.extract_inventory,
    "purecars": generic_franchise.extract_inventory,
    "jazel": generic_franchise.extract_inventory,
    "harley_digital_showroom": generic_franchise.extract_inventory,
    "dealer_spike": generic_franchise.extract_inventory_for_platform("dealer_spike"),
    "oneaudi_falcon": generic_franchise.extract_inventory_for_platform("oneaudi_falcon"),
}


def extract_with_provider(
    platform_id: str | None,
    *,
    page_url: str,
    html: str,
    make_filter: str,
    model_filter: str,
    vehicle_category: str = "car",
) -> ExtractionResult | None:
    if not platform_id:
        return None
    handler = _HANDLERS.get(platform_id)
    if not handler:
        return None
    return handler(
        page_url=page_url,
        html=html,
        make_filter=make_filter,
        model_filter=model_filter,
        vehicle_category=vehicle_category,
    )
