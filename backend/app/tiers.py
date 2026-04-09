"""Subscription tiers, limits, and included monthly search allotments."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal


class TierId(StrEnum):
    ANONYMOUS = "anonymous"
    FREE = "free"
    STANDARD = "standard"
    PREMIUM = "premium"  # Pro ($60/mo) — stable id for Stripe metadata and DB rows
    MAX_PRO = "max_pro"
    ENTERPRISE = "enterprise"
    CUSTOM = "custom"


TierLiteral = Literal[
    TierId.ANONYMOUS,
    TierId.FREE,
    TierId.STANDARD,
    TierId.PREMIUM,
    TierId.MAX_PRO,
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
    included_premium_reports_per_month: int  # not used for ANONYMOUS
    anonymous_lifetime_searches: int  # only for ANONYMOUS
    minute_rate_limit: int  # soft cap: max searches started per rolling minute (per identity)
    csv_export: bool
    inventory_scope_premium: bool  # all vs new-only etc. — gate advanced scope if False


ANONYMOUS_LIMITS = TierLimits(
    max_dealerships=4,
    max_pages_per_dealer=1,
    max_radius_miles=50,
    max_concurrent_searches=1,
    included_searches_per_month=0,
    included_premium_reports_per_month=0,
    anonymous_lifetime_searches=1,
    minute_rate_limit=10,
    csv_export=False,
    inventory_scope_premium=False,
)

# Same dealership/radius/page caps as Standard; no CSV / advanced scope; lower burst rate than paid.
FREE_LIMITS = TierLimits(
    max_dealerships=10,
    max_pages_per_dealer=6,
    max_radius_miles=30,
    max_concurrent_searches=1,
    included_searches_per_month=15,
    included_premium_reports_per_month=5,
    anonymous_lifetime_searches=0,
    minute_rate_limit=4,
    csv_export=False,
    inventory_scope_premium=False,
)

# Standard (Starter) — $49/mo
STANDARD_LIMITS = TierLimits(
    max_dealerships=10,
    max_pages_per_dealer=6,
    max_radius_miles=30,
    max_concurrent_searches=2,
    included_searches_per_month=25,
    included_premium_reports_per_month=15,
    anonymous_lifetime_searches=0,
    minute_rate_limit=10,
    csv_export=True,
    inventory_scope_premium=True,
)

# Pro (tier id `premium`) — $199/mo
PREMIUM_LIMITS = TierLimits(
    max_dealerships=20,
    max_pages_per_dealer=10,
    max_radius_miles=100,
    max_concurrent_searches=4,
    included_searches_per_month=120,
    included_premium_reports_per_month=100,
    anonymous_lifetime_searches=0,
    minute_rate_limit=20,
    csv_export=True,
    inventory_scope_premium=True,
)

# Max Pro — $499/mo
MAX_PRO_LIMITS = TierLimits(
    max_dealerships=20,
    max_pages_per_dealer=10,
    max_radius_miles=250,
    max_concurrent_searches=6,
    included_searches_per_month=250,
    included_premium_reports_per_month=200,
    anonymous_lifetime_searches=0,
    minute_rate_limit=40,
    csv_export=True,
    inventory_scope_premium=True,
)

ENTERPRISE_LIMITS = TierLimits(
    max_dealerships=20,
    max_pages_per_dealer=10,
    max_radius_miles=250,
    max_concurrent_searches=5,
    included_searches_per_month=50_000,
    included_premium_reports_per_month=50_000,
    anonymous_lifetime_searches=0,
    minute_rate_limit=60,
    csv_export=True,
    inventory_scope_premium=True,
)

# White-label / API customers — contract-governed; high technical ceilings.
CUSTOM_LIMITS = TierLimits(
    max_dealerships=20,
    max_pages_per_dealer=10,
    max_radius_miles=250,
    max_concurrent_searches=8,
    included_searches_per_month=200_000,
    included_premium_reports_per_month=200_000,
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
        case TierId.MAX_PRO.value:
            return MAX_PRO_LIMITS
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
    if tid == TierId.MAX_PRO.value:
        return 0.28
    if tid == TierId.STANDARD.value:
        return 0.50
    return 0.0
