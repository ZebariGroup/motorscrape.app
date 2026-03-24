"""Provider-specific extraction handlers."""

from __future__ import annotations

from app.schemas import ExtractionResult
from app.services.providers import dealer_dot_com, dealer_inspire, dealer_on, generic_franchise

_HANDLERS = {
    "dealer_dot_com": dealer_dot_com.extract_inventory,
    "dealer_on": dealer_on.extract_inventory,
    "dealer_inspire": dealer_inspire.extract_inventory,
    "cdk_dealerfire": generic_franchise.extract_inventory,
    "team_velocity": generic_franchise.extract_inventory,
    "fusionzone": generic_franchise.extract_inventory,
    "shift_digital": generic_franchise.extract_inventory,
    "purecars": generic_franchise.extract_inventory,
    "jazel": generic_franchise.extract_inventory,
}


def extract_with_provider(
    platform_id: str | None,
    *,
    page_url: str,
    html: str,
    make_filter: str,
    model_filter: str,
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
    )
