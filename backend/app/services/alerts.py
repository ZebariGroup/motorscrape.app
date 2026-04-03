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
from app.services.inventory_tracking import inventory_history_key
from app.services.scrape_logging import build_correlation_id, create_scrape_run_recorder
from app.services.search_runner import SearchRunResult, run_search_once
from app.tiers import limits_for_tier


def user_can_manage_alerts(tier: str) -> bool:
    return (tier or "").lower() in {"standard", "premium", "max_pro", "enterprise", "custom"}


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


class _ListingProxy:
    def __init__(self, data: dict[str, Any]) -> None:
        self.dealership_website = data.get("dealership_website")
        self.vin = data.get("vin")
        self.vehicle_identifier = data.get("vehicle_identifier")
        self.listing_url = data.get("listing_url")
        self.year = data.get("year")
        self.make = data.get("make")
        self.model = data.get("model")
        self.trim = data.get("trim")
        self.raw_title = data.get("raw_title")


def _listing_key(listing: dict[str, Any]) -> str:
    return inventory_history_key(_ListingProxy(listing))


def _price_drop_amount(listing: dict[str, Any], *, min_price_drop_usd: float | None) -> float | None:
    price_change = listing.get("history_price_change")
    if not isinstance(price_change, (int, float)) or price_change >= 0:
        return None
    drop_amount = float(abs(price_change))
    if min_price_drop_usd is not None and drop_amount < float(min_price_drop_usd):
        return None
    return drop_amount


def _listing_digest(listing: dict[str, Any], *, include_price_drop: bool = False) -> dict[str, Any]:
    digest = {
        "title": listing.get("raw_title") or "Vehicle",
        "price": listing.get("price"),
        "dealer": listing.get("dealership"),
        "location": listing.get("inventory_location") or listing.get("availability_status"),
        "vin": listing.get("vehicle_identifier") or listing.get("vin"),
        "url": listing.get("listing_url"),
    }
    if include_price_drop:
        digest["history_price_change"] = listing.get("history_price_change")
    return digest


def summarize_alert_deltas(
    subscription: AlertSubscriptionRecord,
    result: SearchRunResult,
    *,
    previous_run: Any | None,
) -> dict[str, Any]:
    current_keys: list[str] = []
    new_listings: list[dict[str, Any]] = []
    price_drops: list[dict[str, Any]] = []

    for listing in result.listings:
        key = _listing_key(listing)
        if key:
            current_keys.append(key)

        history_seen_count = listing.get("history_seen_count")
        is_new_listing = history_seen_count is None or int(history_seen_count) <= 1
        if subscription.include_new_listings and is_new_listing:
            new_listings.append(_listing_digest(listing))

        price_drop_amount = _price_drop_amount(listing, min_price_drop_usd=subscription.min_price_drop_usd)
        if subscription.include_price_drops and price_drop_amount is not None:
            price_drops.append(_listing_digest(listing, include_price_drop=True))

    price_drops.sort(key=lambda item: abs(float(item.get("history_price_change") or 0)), reverse=True)
    previous_keys = {
        str(key)
        for key in ((previous_run.summary if previous_run is not None else {}).get("vehicle_keys") or [])
        if isinstance(key, str) and key
    }
    current_key_set = {key for key in current_keys if key}
    removed_count = len(previous_keys - current_key_set) if previous_keys else 0
    matching_change_count = len(new_listings) + len(price_drops)
    total_change_count = matching_change_count + removed_count
    should_send = not subscription.only_send_on_changes or total_change_count > 0

    return {
        "only_send_on_changes": subscription.only_send_on_changes,
        "include_new_listings": subscription.include_new_listings,
        "include_price_drops": subscription.include_price_drops,
        "min_price_drop_usd": subscription.min_price_drop_usd,
        "matching_change_count": matching_change_count,
        "total_change_count": total_change_count,
        "new_listings_count": len(new_listings),
        "price_drop_count": len(price_drops),
        "removed_count": removed_count,
        "largest_price_drop": abs(float(price_drops[0].get("history_price_change") or 0)) if price_drops else None,
        "new_listings": new_listings[:5],
        "price_drops": price_drops[:5],
        "vehicle_keys": current_keys,
        "email_skipped_no_changes": not should_send,
        "sent_due_to_changes": should_send,
    }


def alert_run_summary(
    subscription: AlertSubscriptionRecord,
    result: SearchRunResult,
    *,
    previous_run: Any | None,
) -> dict[str, Any]:
    delta = summarize_alert_deltas(subscription, result, previous_run=previous_run)
    top_results: list[dict[str, Any]] = []
    for listing in result.listings[:10]:
        digest = _listing_digest(listing, include_price_drop=True)
        top_results.append(digest)
    return {
        "result_count": len(result.listings),
        "errors": result.errors,
        "status_messages": result.status_messages[-5:],
        "top_results": top_results,
        "delta": delta,
        "vehicle_keys": delta["vehicle_keys"],
        "outcome": result.outcome,
        "correlation_id": result.correlation_id,
        "scrape_run_id": result.scrape_run_id,
    }


def _dt_utc(ts: float):
    from datetime import UTC, datetime

    return datetime.fromtimestamp(ts, UTC)


def _render_email(
    subscription: AlertSubscriptionRecord,
    result: SearchRunResult,
    *,
    summary: dict[str, Any],
) -> tuple[str, str, str]:
    result_count = len(result.listings)
    delta = summary.get("delta") if isinstance(summary.get("delta"), dict) else {}
    total_change_count = int(delta.get("total_change_count") or 0)
    if total_change_count > 0:
        subject = f"Motorscrape alert: {subscription.name} ({total_change_count} changes, {result_count} vehicles)"
    else:
        subject = f"Motorscrape alert: {subscription.name} ({result_count} vehicles)"

    def html_row(listing: dict[str, Any]) -> str:
        price = listing.get("price")
        price_text = f" - ${int(price):,}" if isinstance(price, (int, float)) else ""
        price_change = listing.get("history_price_change")
        trend_text = ""
        if isinstance(price_change, (int, float)) and price_change < 0:
            trend_text = f" (down ${int(abs(price_change)):,} since the last tracked run)"
        return (
            f"<li><a href=\"{listing.get('listing_url') or '#'}\">"
            f"{listing.get('raw_title') or 'Vehicle'}</a> at "
            f"{listing.get('dealership') or 'Dealer'}{price_text}{trend_text}</li>"
        )

    rows_html = "".join(
        html_row(listing) for listing in result.listings[:10]
    )
    new_listings = delta.get("new_listings") if isinstance(delta.get("new_listings"), list) else []
    price_drops = delta.get("price_drops") if isinstance(delta.get("price_drops"), list) else []
    removed_count = int(delta.get("removed_count") or 0)
    delta_lines: list[str] = []
    delta_html_parts: list[str] = []
    if delta.get("new_listings_count"):
        count = int(delta["new_listings_count"])
        delta_lines.append(f"New listings: {count}")
        delta_html_parts.append(f"<p><strong>New listings:</strong> {count}</p>")
    if delta.get("price_drop_count"):
        count = int(delta["price_drop_count"])
        delta_lines.append(f"Price drops: {count}")
        delta_html_parts.append(f"<p><strong>Price drops:</strong> {count}</p>")
    if removed_count:
        delta_lines.append(f"Listings removed since last run: {removed_count}")
        delta_html_parts.append(f"<p><strong>Listings removed since last run:</strong> {removed_count}</p>")

    text_lines = [
        f"Alert: {subscription.name}",
        f"Vehicles found: {result_count}",
        "",
    ]
    if delta_lines:
        text_lines.extend(["Changes:", *[f"- {line}" for line in delta_lines], ""])
    if new_listings:
        text_lines.append("New listings:")
        for listing in new_listings:
            text_lines.append(f"- {listing.get('title') or 'Vehicle'} | {listing.get('dealer') or 'Dealer'}")
        text_lines.append("")
    if price_drops:
        text_lines.append("Largest price drops:")
        for listing in price_drops:
            change = listing.get("history_price_change")
            change_text = f" | down ${int(abs(change)):,}" if isinstance(change, (int, float)) else ""
            text_lines.append(f"- {listing.get('title') or 'Vehicle'} | {listing.get('dealer') or 'Dealer'}{change_text}")
        text_lines.append("")
    for listing in result.listings[:10]:
        price = listing.get("price")
        price_text = f" - ${int(price):,}" if isinstance(price, (int, float)) else ""
        price_change = listing.get("history_price_change")
        trend_text = ""
        if isinstance(price_change, (int, float)) and price_change < 0:
            trend_text = f" | down ${int(abs(price_change)):,} since last tracked run"
        text_lines.append(
            f"- {(listing.get('raw_title') or 'Vehicle')} | {(listing.get('dealership') or 'Dealer')}{price_text}{trend_text}"
        )
        if listing.get("listing_url"):
            text_lines.append(f"  {listing['listing_url']}")
    if result.errors:
        text_lines.extend(["", "Errors:", *[f"- {err}" for err in result.errors]])

    html = (
        f"<h1>Motorscrape alert</h1><p><strong>{subscription.name}</strong></p>"
        f"<p>{result_count} vehicles found for your scheduled search.</p>"
        f"{''.join(delta_html_parts)}"
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
    request = effective_search_request(subscription.criteria, tier=user.tier)
    correlation_id = build_correlation_id(prefix="alert")
    recorder = create_scrape_run_recorder(
        store=store,
        correlation_id=correlation_id,
        trigger_source=f"alert_{trigger_source}",
        location=request.location,
        make=request.make,
        model=request.model,
        vehicle_category=request.vehicle_category,
        vehicle_condition=request.vehicle_condition,
        inventory_scope=request.inventory_scope,
        radius_miles=request.radius_miles,
        requested_max_dealerships=request.max_dealerships,
        requested_max_pages_per_dealer=request.max_pages_per_dealer,
        user_id=user.id,
    )
    ctx = AccessContext(
        tier=user.tier,
        limits=limits_for_tier(user.tier),
        user_id=user.id,
        email=user.email,
        anon_key=None,
        is_admin=bool(user.is_admin),
    )
    quota = evaluate_search_start(ctx, store)
    next_run_at = next_subscription_run(subscription, now_ts=started_at)

    if not quota.allowed:
        recorder.event(
            event_type="quota_blocked",
            phase="quota",
            level="warning",
            message=quota.message,
            payload={"trigger_source": trigger_source, "subscription_id": subscription.id},
        )
        recorder.finalize(
            ok=False,
            status="quota_blocked",
            summary={
                "ok": False,
                "status": "quota_blocked",
                "correlation_id": correlation_id,
                "subscription_id": subscription.id,
                "trigger_source": trigger_source,
                "error_message": quota.message,
            },
            economics={},
            error_message=quota.message,
        )
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

    result_count = 0
    emailed = False
    error_message: str | None = None
    result_summary: dict[str, Any]
    status = "success"

    try:
        result = await run_search_once(request, correlation_id=correlation_id, recorder=recorder)
        record_search_completed(ctx, result.outcome, counts_as_overage=quota.counts_as_overage, store=store)
        result_count = len(result.listings)
        previous_run = store.get_latest_alert_run_for_subscription(user.id, subscription.id)
        result_summary = alert_run_summary(subscription, result, previous_run=previous_run)
        attachments: list[EmailAttachment] = []
        should_send_email = not bool(result_summary.get("delta", {}).get("email_skipped_no_changes"))
        if subscription.deliver_csv and should_send_email:
            csv_text = listings_to_csv(result.listings)
            attachments.append(
                EmailAttachment(
                    filename=f"motorscrape-alert-{subscription.id}.csv",
                    content_type="text/csv",
                    content_bytes=csv_text.encode("utf-8"),
                )
            )
        if should_send_email:
            subject, html, text = _render_email(subscription, result, summary=result_summary)
            await send_email(
                to_email=user.email,
                subject=subject,
                html=html,
                text=text,
                attachments=attachments,
            )
            emailed = True
        else:
            status = "skipped_no_changes"
    except Exception as exc:
        status = "error"
        error_message = str(exc)
        result_summary = {"result_count": result_count, "errors": [error_message], "top_results": []}
        if not recorder.finalized:
            recorder.event(
                event_type="alert_error",
                phase="alert",
                level="error",
                message=error_message,
                payload={"subscription_id": subscription.id, "trigger_source": trigger_source},
            )
            recorder.finalize(
                ok=False,
                status="failed",
                summary={
                    "ok": False,
                    "status": "failed",
                    "correlation_id": correlation_id,
                    "subscription_id": subscription.id,
                    "trigger_source": trigger_source,
                    "error_message": error_message,
                },
                economics={},
                error_message=error_message,
            )

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
        csv_attached=emailed and subscription.deliver_csv,
        error_message=error_message,
        summary=result_summary,
        started_at=started_at,
        completed_at=completed_at,
    )
    return {"run": run, "quota_blocked": False}
