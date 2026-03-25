"""Subscription tiers, limits, and included monthly search allotments."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal


class TierId(StrEnum):
    ANONYMOUS = "anonymous"
    FREE = "free"
    STANDARD = "standard"
    PREMIUM = "premium"
    ENTERPRISE = "enterprise"
    CUSTOM = "custom"


TierLiteral = Literal[
    TierId.ANONYMOUS,
    TierId.FREE,
    TierId.STANDARD,
    TierId.PREMIUM,
    TierId.ENTERPRISE,
    TierId.CUSTOM,
]


@dataclass(frozen=True, slots=True)
class TierLimits:
    max_dealerships: int
    max_pages_per_dealer: int
    max_radius_miles: int
    max_concurrent_searches: int
    included_searches_per_month: int  # not used for ANONYMOUS
    anonymous_lifetime_searches: int  # only for ANONYMOUS
    minute_rate_limit: int  # soft cap: max searches started per rolling minute (per identity)
    csv_export: bool
    inventory_scope_premium: bool  # all vs new-only etc. — gate advanced scope if False


ANONYMOUS_LIMITS = TierLimits(
    max_dealerships=4,
    max_pages_per_dealer=2,
    max_radius_miles=50,
    max_concurrent_searches=1,
    included_searches_per_month=0,
    anonymous_lifetime_searches=4,
    minute_rate_limit=10,
    csv_export=False,
    inventory_scope_premium=False,
)

FREE_LIMITS = TierLimits(
    max_dealerships=6,
    max_pages_per_dealer=3,
    max_radius_miles=100,
    max_concurrent_searches=1,
    included_searches_per_month=25,
    anonymous_lifetime_searches=0,
    minute_rate_limit=4,
    csv_export=False,
    inventory_scope_premium=False,
)

STANDARD_LIMITS = TierLimits(
    max_dealerships=10,
    max_pages_per_dealer=4,
    max_radius_miles=30,
    max_concurrent_searches=2,
    included_searches_per_month=350,
    anonymous_lifetime_searches=0,
    minute_rate_limit=10,
    csv_export=True,
    inventory_scope_premium=True,
)

PREMIUM_LIMITS = TierLimits(
    max_dealerships=20,
    max_pages_per_dealer=6,
    max_radius_miles=250,
    max_concurrent_searches=3,
    included_searches_per_month=750,
    anonymous_lifetime_searches=0,
    minute_rate_limit=20,
    csv_export=True,
    inventory_scope_premium=True,
)

ENTERPRISE_LIMITS = TierLimits(
    max_dealerships=30,
    max_pages_per_dealer=10,
    max_radius_miles=250,
    max_concurrent_searches=5,
    included_searches_per_month=50_000,
    anonymous_lifetime_searches=0,
    minute_rate_limit=60,
    csv_export=True,
    inventory_scope_premium=True,
)

# White-label / API customers — contract-governed; high technical ceilings.
CUSTOM_LIMITS = TierLimits(
    max_dealerships=30,
    max_pages_per_dealer=10,
    max_radius_miles=250,
    max_concurrent_searches=8,
    included_searches_per_month=200_000,
    anonymous_lifetime_searches=0,
    minute_rate_limit=120,
    csv_export=True,
    inventory_scope_premium=True,
)


def limits_for_tier(tier: str) -> TierLimits:
    tid = (tier or TierId.FREE.value).lower()
    match tid:
        case TierId.ANONYMOUS.value:
            return ANONYMOUS_LIMITS
        case TierId.FREE.value:
            return FREE_LIMITS
        case TierId.STANDARD.value:
            return STANDARD_LIMITS
        case TierId.PREMIUM.value:
            return PREMIUM_LIMITS
        case TierId.ENTERPRISE.value:
            return ENTERPRISE_LIMITS
        case TierId.CUSTOM.value:
            return CUSTOM_LIMITS
        case _:
            return FREE_LIMITS


def overage_unit_price_usd(tier: str) -> float:
    """Stripe metered price should match these defaults (configure per env in Dashboard)."""
    tid = (tier or "").lower()
    if tid == TierId.PREMIUM.value:
        return 0.35
    if tid == TierId.STANDARD.value:
        return 0.50
    return 0.0
