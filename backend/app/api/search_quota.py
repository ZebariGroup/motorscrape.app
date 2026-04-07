"""Pre-flight quota / rate limits for search streaming."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from app.api.deps import AccessContext
from app.config import settings
from app.db.account_store import get_account_store
from app.services.search_errors import SearchErrorInfo
from app.tiers import TierId


def _period_utc() -> str:
    return time.strftime("%Y-%m", time.gmtime())


@dataclass(slots=True)
class SearchQuotaDecision:
    allowed: bool
    counts_as_overage: bool
    error: SearchErrorInfo | None = None

    @property
    def message(self) -> str:
        return self.error.message if self.error is not None else ""

    @property
    def code(self) -> str | None:
        return self.error.code if self.error is not None else None


def evaluate_search_start(ctx: AccessContext, store: Any | None = None) -> SearchQuotaDecision:
    store = store or get_account_store(settings.accounts_db_path)
    lim = ctx.limits

    bucket = f"srch:{ctx.user_id or ctx.anon_key or 'x'}"
    if not store.rate_tick(bucket, limit=max(1, lim.minute_rate_limit)):
        return SearchQuotaDecision(
            False,
            False,
            SearchErrorInfo(
                code="quota.rate_limit",
                message="Too many searches. Please wait a minute and try again.",
                phase="quota",
                status="quota_blocked",
                retryable=True,
            ),
        )

    if ctx.user_id is None:
        if not ctx.anon_key:
            return SearchQuotaDecision(
                False,
                False,
                SearchErrorInfo(
                    code="quota.browser_session_unidentified",
                    message="Unable to identify this browser session.",
                    phase="quota",
                    status="quota_blocked",
                    retryable=True,
                ),
            )
        used = store.anon_get(ctx.anon_key)
        if used >= lim.anonymous_lifetime_searches:
            return SearchQuotaDecision(
                False,
                False,
                SearchErrorInfo(
                    code="quota.anonymous_limit_reached",
                    message="You've used all free searches without an account. Create a free account to continue.",
                    phase="quota",
                    status="quota_blocked",
                    upgrade_required=True,
                    upgrade_tier="free",
                ),
            )
        return SearchQuotaDecision(True, False)

    # Authenticated
    period = _period_utc()
    used, _over = store.monthly_usage(ctx.user_id, period)
    tier = (ctx.tier or TierId.FREE.value).lower()

    if tier in (TierId.ENTERPRISE.value, TierId.CUSTOM.value):
        return SearchQuotaDecision(True, False)

    included = lim.included_searches_per_month
    if used < included:
        return SearchQuotaDecision(True, False)

    # Over included allotment
    user = store.get_user_by_id(ctx.user_id)
    if user is None:
        return SearchQuotaDecision(
            False,
            False,
            SearchErrorInfo(
                code="quota.account_not_found",
                message="Account not found.",
                phase="quota",
                status="quota_blocked",
                retryable=True,
            ),
        )

    if tier in (TierId.STANDARD.value, TierId.PREMIUM.value, TierId.MAX_PRO.value):
        if tier == TierId.STANDARD.value:
            return SearchQuotaDecision(
                False,
                False,
                SearchErrorInfo(
                    code="quota.monthly_limit_standard",
                    message="Monthly included searches are used up. Upgrade to Pro or Max Pro for a larger monthly pool.",
                    phase="quota",
                    status="quota_blocked",
                    upgrade_required=True,
                    upgrade_tier="premium",
                ),
            )
        if tier == TierId.PREMIUM.value:
            return SearchQuotaDecision(
                False,
                False,
                SearchErrorInfo(
                    code="quota.monthly_limit_premium",
                    message="Monthly included searches are used up. Upgrade to Max Pro for a larger monthly pool, or contact us for Enterprise.",
                    phase="quota",
                    status="quota_blocked",
                    upgrade_required=True,
                    upgrade_tier="max_pro",
                ),
            )
        return SearchQuotaDecision(
            False,
            False,
            SearchErrorInfo(
                code="quota.monthly_limit_max_pro",
                message="Monthly included searches are used up. Contact support for Enterprise or custom volume.",
                phase="quota",
                status="quota_blocked",
                upgrade_required=True,
            ),
        )

    # free tier
    return SearchQuotaDecision(
        False,
        False,
        SearchErrorInfo(
            code="quota.monthly_limit_free",
            message="Monthly free search limit reached. Subscribe to Standard, Pro, or Max Pro for higher monthly limits.",
            phase="quota",
            status="quota_blocked",
            upgrade_required=True,
            upgrade_tier="standard",
        ),
    )


def record_search_completed(
    ctx: AccessContext,
    outcome: dict,
    *,
    counts_as_overage: bool,
    store: Any | None = None,
) -> None:
    """Persist usage when stream completes with ok=True."""
    if not outcome.get("ok"):
        return
    store = store or get_account_store(settings.accounts_db_path)
    if ctx.user_id is None:
        if ctx.anon_key:
            store.anon_increment(ctx.anon_key)
        return

    period = _period_utc()
    tier = (ctx.tier or TierId.FREE.value).lower()
    is_overage = counts_as_overage and tier in (
        TierId.STANDARD.value,
        TierId.PREMIUM.value,
        TierId.MAX_PRO.value,
    )
    store.increment_search_completed(ctx.user_id, period, counts_as_overage=is_overage)
    if is_overage:
        user = store.get_user_by_id(ctx.user_id)
        if user and user.stripe_metered_item_id:
            from app.billing.stripe_usage import report_search_overage

            report_search_overage(user.stripe_metered_item_id)
