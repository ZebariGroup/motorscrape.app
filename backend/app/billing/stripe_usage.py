"""Report metered usage to Stripe for hybrid billed tiers."""

from __future__ import annotations

import logging
import time

from app.config import settings

logger = logging.getLogger(__name__)


def report_search_overage(metered_subscription_item_id: str) -> None:
    key = (settings.stripe_secret_key or "").strip()
    if not key or not metered_subscription_item_id:
        return
    try:
        import stripe
    except ImportError:
        logger.warning("stripe package not installed; skipping usage report")
        return

    stripe.api_key = key
    try:
        stripe.UsageRecord.create(
            subscription_item=metered_subscription_item_id,
            quantity=1,
            timestamp=int(time.time()),
            action="increment",
        )
    except Exception:
        logger.exception("Failed to report Stripe metered usage for item %s", metered_subscription_item_id)
