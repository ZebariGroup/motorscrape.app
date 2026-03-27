from __future__ import annotations

import time
from typing import Any

from app.api.deps import AccessContext
from app.api.search_quota import evaluate_search_start, record_search_completed
from app.config import vehicle_category_enabled
from app.db.account_store import AlertSubscriptionRecord, UserRecord
from app.schemas import SearchRequest
from app.services.alert_schedule import next_run_at_utc
from app.services.csv_export import listings_to_csv
from app.services.email_delivery import EmailAttachment, send_email
from app.services.search_runner import SearchRunResult, run_search_once
from app.tiers import limits_for_tier


def user_can_manage_alerts(tier: str) -> bool:
    return (tier or "").lower() in {"standard", "premium", "enterprise", "custom"}


def effective_search_request(criteria: dict[str, Any], *, tier: str) -> SearchRequest:
    request = SearchRequest.model_validate(criteria)
    if not vehicle_category_enabled(request.vehicle_category):
        raise ValueError(f"Vehicle category '{request.vehicle_category}' is not enabled.")
    limits = limits_for_tier(tier)
    radius_miles = min(request.radius_miles, limits.max_radius_miles)
    max_dealerships = request.max_dealerships if request.max_dealerships is not None else limits.max_dealerships
    max_pages_per_dealer = (
        request.max_pages_per_dealer if request.max_pages_per_dealer is not None else limits.max_pages_per_dealer
    )
    inventory_scope = request.inventory_scope if limits.inventory_scope_premium else "all"
    return request.model_copy(
        update={
            "radius_miles": max(5, radius_miles),
            "max_dealerships": max(1, min(max_dealerships, limits.max_dealerships)),
            "max_pages_per_dealer": max(1, min(max_pages_per_dealer, limits.max_pages_per_dealer)),
            "inventory_scope": inventory_scope,
        }
    )


def next_subscription_run(subscription: AlertSubscriptionRecord, *, now_ts: float | None = None) -> float:
    next_dt = next_run_at_utc(
        cadence=subscription.cadence,
        hour_local=subscription.hour_local,
        timezone_name=subscription.timezone,
        day_of_week=subscription.day_of_week,
        now_utc=None if now_ts is None else _dt_utc(now_ts),
    )
    return next_dt.timestamp()


def alert_run_summary(result: SearchRunResult) -> dict[str, Any]:
    top_results: list[dict[str, Any]] = []
    for listing in result.listings[:10]:
        top_results.append(
            {
                "title": listing.get("raw_title") or "Vehicle",
                "price": listing.get("price"),
                "dealer": listing.get("dealership"),
                "location": listing.get("inventory_location") or listing.get("availability_status"),
                "vin": listing.get("vehicle_identifier") or listing.get("vin"),
                "url": listing.get("listing_url"),
            }
        )
    return {
        "result_count": len(result.listings),
        "errors": result.errors,
        "status_messages": result.status_messages[-5:],
        "top_results": top_results,
        "outcome": result.outcome,
    }


def _dt_utc(ts: float):
    from datetime import UTC, datetime

    return datetime.fromtimestamp(ts, UTC)


def _render_email(subscription: AlertSubscriptionRecord, result: SearchRunResult) -> tuple[str, str, str]:
    result_count = len(result.listings)
    subject = f"Motorscrape alert: {subscription.name} ({result_count} vehicles)"

    def html_row(listing: dict[str, Any]) -> str:
        price = listing.get("price")
        price_text = f" - ${int(price):,}" if isinstance(price, (int, float)) else ""
        return (
            f"<li><a href=\"{listing.get('listing_url') or '#'}\">"
            f"{listing.get('raw_title') or 'Vehicle'}</a> at "
            f"{listing.get('dealership') or 'Dealer'}{price_text}</li>"
        )

    rows_html = "".join(
        html_row(listing) for listing in result.listings[:10]
    )
    text_lines = [
        f"Alert: {subscription.name}",
        f"Vehicles found: {result_count}",
        "",
    ]
    for listing in result.listings[:10]:
        price = listing.get("price")
        price_text = f" - ${int(price):,}" if isinstance(price, (int, float)) else ""
        text_lines.append(
            f"- {(listing.get('raw_title') or 'Vehicle')} | {(listing.get('dealership') or 'Dealer')}{price_text}"
        )
        if listing.get("listing_url"):
            text_lines.append(f"  {listing['listing_url']}")
    if result.errors:
        text_lines.extend(["", "Errors:", *[f"- {err}" for err in result.errors]])

    html = (
        f"<h1>Motorscrape alert</h1><p><strong>{subscription.name}</strong></p>"
        f"<p>{result_count} vehicles found for your scheduled search.</p>"
        f"<ul>{rows_html or '<li>No vehicles found.</li>'}</ul>"
    )
    return subject, html, "\n".join(text_lines)


async def execute_alert_subscription(
    *,
    store: Any,
    user: UserRecord,
    subscription: AlertSubscriptionRecord,
    trigger_source: str,
) -> dict[str, Any]:
    started_at = time.time()
    ctx = AccessContext(
        tier=user.tier,
        limits=limits_for_tier(user.tier),
        user_id=user.id,
        email=user.email,
        anon_key=None,
    )
    quota = evaluate_search_start(ctx, store)
    next_run_at = next_subscription_run(subscription, now_ts=started_at)

    if not quota.allowed:
        store.update_alert_subscription(
            user.id,
            subscription.id,
            next_run_at=next_run_at,
            last_run_at=started_at,
            last_run_status="quota_blocked",
            last_error=quota.message,
            last_result_count=0,
        )
        run = store.create_alert_run(
            subscription_id=subscription.id,
            user_id=user.id,
            trigger_source=trigger_source,
            status="quota_blocked",
            result_count=0,
            emailed=False,
            csv_attached=False,
            error_message=quota.message,
            summary={"result_count": 0, "errors": [quota.message], "top_results": []},
            started_at=started_at,
            completed_at=started_at,
        )
        return {"run": run, "quota_blocked": True}

    request = effective_search_request(subscription.criteria, tier=user.tier)
    result_count = 0
    emailed = False
    error_message: str | None = None
    result_summary: dict[str, Any]
    status = "success"

    try:
        result = await run_search_once(request, correlation_id=f"alert:{subscription.id}")
        record_search_completed(ctx, result.outcome, counts_as_overage=quota.counts_as_overage, store=store)
        result_count = len(result.listings)
        result_summary = alert_run_summary(result)
        attachments: list[EmailAttachment] = []
        if subscription.deliver_csv:
            csv_text = listings_to_csv(result.listings)
            attachments.append(
                EmailAttachment(
                    filename=f"motorscrape-alert-{subscription.id}.csv",
                    content_type="text/csv",
                    content_bytes=csv_text.encode("utf-8"),
                )
            )
        subject, html, text = _render_email(subscription, result)
        await send_email(
            to_email=user.email,
            subject=subject,
            html=html,
            text=text,
            attachments=attachments,
        )
        emailed = True
    except Exception as exc:
        status = "error"
        error_message = str(exc)
        result_summary = {"result_count": result_count, "errors": [error_message], "top_results": []}

    completed_at = time.time()
    store.update_alert_subscription(
        user.id,
        subscription.id,
        next_run_at=next_run_at,
        last_run_at=completed_at,
        last_run_status=status,
        last_result_count=result_count,
        last_error=error_message or "",
    )
    run = store.create_alert_run(
        subscription_id=subscription.id,
        user_id=user.id,
        trigger_source=trigger_source,
        status=status,
        result_count=result_count,
        emailed=emailed,
        csv_attached=subscription.deliver_csv,
        error_message=error_message,
        summary=result_summary,
        started_at=started_at,
        completed_at=completed_at,
    )
    return {"run": run, "quota_blocked": False}
