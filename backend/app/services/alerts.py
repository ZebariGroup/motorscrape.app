from __future__ import annotations

import time
from html import escape
from typing import Any

from app.api.deps import AccessContext
from app.api.search_quota import evaluate_search_start, record_search_completed
from app.config import settings, vehicle_category_enabled
from app.db.account_store import AlertSubscriptionRecord, UserRecord
from app.schemas import SearchRequest
from app.services.alert_schedule import next_run_at_utc
from app.services.csv_export import listings_to_csv
from app.services.email_delivery import EmailAttachment, send_email
from app.services.inventory_tracking import inventory_history_key
from app.services.scrape_logging import build_correlation_id, create_scrape_run_recorder
from app.services.search_errors import SearchErrorInfo, with_search_error
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
        "image_url": listing.get("image_url"),
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


def _format_price(value: Any) -> str:
    if isinstance(value, (int, float)):
        return f"${int(value):,}"
    return "Price unavailable"


def _html_money_delta(value: Any) -> str:
    if isinstance(value, (int, float)) and value < 0:
        return f"Down ${int(abs(value)):,}"
    return ""


def _criteria_summary(criteria: dict[str, Any]) -> list[str]:
    radius = criteria.get("radius_miles")
    radius_text = f"{int(radius)} mi" if isinstance(radius, (int, float)) else None
    parts = [
        criteria.get("vehicle_category"),
        criteria.get("location"),
        criteria.get("make") or "Any make",
        criteria.get("model") or "Any model",
        radius_text,
    ]
    return [str(part) for part in parts if part]


def _count_label(count: int, singular: str, plural: str | None = None) -> str:
    word = singular if count == 1 else (plural or f"{singular}s")
    return f"{count} {word}"


def _subject_for_alert(subscription: AlertSubscriptionRecord, *, result_count: int, delta: dict[str, Any]) -> str:
    new_count = int(delta.get("new_listings_count") or 0)
    drop_count = int(delta.get("price_drop_count") or 0)
    removed_count = int(delta.get("removed_count") or 0)
    if drop_count and new_count:
        return (
            f"Motorscrape: {_count_label(new_count, 'new match')} and "
            f"{_count_label(drop_count, 'price drop')} for {subscription.name}"
        )
    if new_count:
        return f"Motorscrape: {_count_label(new_count, 'new match')} for {subscription.name}"
    if drop_count:
        return f"Motorscrape: {_count_label(drop_count, 'price drop')} for {subscription.name}"
    if removed_count:
        return f"Motorscrape: inventory changed for {subscription.name}"
    return f"Motorscrape alert: {subscription.name} ({result_count} vehicles)"


def _html_button(url: str, label: str, *, secondary: bool = False) -> str:
    background = "#ffffff" if secondary else "#111827"
    color = "#111827" if secondary else "#ffffff"
    border = "#d1d5db" if secondary else "#111827"
    return (
        f"<a href=\"{escape(url, quote=True)}\" "
        "style=\"display:inline-block;border-radius:10px;padding:12px 18px;"
        f"background:{background};color:{color};border:1px solid {border};"
        "font-weight:600;font-size:14px;line-height:20px;text-decoration:none;"
        "margin-right:8px;margin-bottom:8px;\">"
        f"{escape(label)}</a>"
    )


def _render_metric_card(label: str, value: str, accent: str) -> str:
    return (
        "<td style=\"padding:0 8px 8px 0;vertical-align:top;\">"
        f"<div style=\"min-width:120px;border-radius:14px;padding:14px 16px;background:{accent};\">"
        f"<div style=\"font-size:24px;line-height:28px;font-weight:700;color:#111827;\">{escape(value)}</div>"
        f"<div style=\"margin-top:4px;font-size:13px;line-height:18px;color:#374151;\">{escape(label)}</div>"
        "</div></td>"
    )


def _render_listing_card(listing: dict[str, Any], *, highlight_label: str | None = None) -> str:
    title = str(listing.get("title") or listing.get("raw_title") or "Vehicle")
    dealer = str(listing.get("dealer") or listing.get("dealership") or "Dealer")
    location = str(listing.get("location") or "")
    price_text = _format_price(listing.get("price"))
    url = str(listing.get("url") or listing.get("listing_url") or "").strip()
    image_url = str(listing.get("image_url") or "").strip()
    price_drop = _html_money_delta(listing.get("history_price_change"))

    image_html = ""
    if image_url:
        image_html = (
            f"<img src=\"{escape(image_url, quote=True)}\" alt=\"{escape(title)}\" "
            "style=\"width:100%;max-width:520px;height:auto;display:block;border-radius:12px 12px 0 0;"
            "object-fit:cover;background:#f3f4f6;\" />"
        )

    meta_parts = [dealer]
    if location:
        meta_parts.append(location)
    meta = " | ".join(part for part in meta_parts if part)
    cta = _html_button(url, "View vehicle") if url else ""
    badge = (
        f"<div style=\"display:inline-block;margin-bottom:10px;border-radius:999px;padding:6px 10px;"
        "background:#eef2ff;color:#3730a3;font-size:12px;font-weight:600;\">"
        f"{escape(highlight_label)}</div>"
        if highlight_label
        else ""
    )
    drop_html = (
        f"<div style=\"margin-top:6px;font-size:13px;line-height:18px;color:#047857;font-weight:600;\">{escape(price_drop)}</div>"
        if price_drop
        else ""
    )

    return (
        "<tr><td style=\"padding:0 0 16px 0;\">"
        "<div style=\"border:1px solid #e5e7eb;border-radius:14px;overflow:hidden;background:#ffffff;\">"
        f"{image_html}"
        "<div style=\"padding:16px;\">"
        f"{badge}"
        f"<div style=\"font-size:18px;line-height:24px;font-weight:700;color:#111827;\">{escape(title)}</div>"
        f"<div style=\"margin-top:6px;font-size:14px;line-height:20px;color:#4b5563;\">{escape(meta)}</div>"
        f"<div style=\"margin-top:10px;font-size:18px;line-height:24px;font-weight:700;color:#111827;\">{escape(price_text)}</div>"
        f"{drop_html}"
        f"<div style=\"margin-top:14px;\">{cta}</div>"
        "</div></div></td></tr>"
    )


def _render_email(
    subscription: AlertSubscriptionRecord,
    result: SearchRunResult,
    *,
    summary: dict[str, Any],
) -> tuple[str, str, str]:
    result_count = len(result.listings)
    delta = summary.get("delta") if isinstance(summary.get("delta"), dict) else {}
    subject = _subject_for_alert(subscription, result_count=result_count, delta=delta)
    new_listings = delta.get("new_listings") if isinstance(delta.get("new_listings"), list) else []
    price_drops = delta.get("price_drops") if isinstance(delta.get("price_drops"), list) else []
    removed_count = int(delta.get("removed_count") or 0)
    criteria_parts = _criteria_summary(subscription.criteria)
    account_url = f"{settings.public_web_url.rstrip('/')}/account"
    metric_cards = "".join(
        [
            _render_metric_card("Vehicles found", str(result_count), "#e0f2fe"),
            _render_metric_card("New listings", str(int(delta.get("new_listings_count") or 0)), "#dcfce7"),
            _render_metric_card("Price drops", str(int(delta.get("price_drop_count") or 0)), "#fee2e2"),
            _render_metric_card("Removed", str(removed_count), "#f3f4f6"),
        ]
    )
    featured_rows = "".join(_render_listing_card(listing) for listing in result.listings[:6]) or (
        "<tr><td style=\"padding:0 0 8px 0;color:#6b7280;font-size:14px;line-height:20px;\">"
        "No vehicles matched this run."
        "</td></tr>"
    )
    new_listing_rows = "".join(
        _render_listing_card(listing, highlight_label="New listing") for listing in new_listings[:3]
    )
    price_drop_rows = "".join(
        _render_listing_card(listing, highlight_label="Price drop") for listing in price_drops[:3]
    )

    text_lines = [
        f"Alert: {subscription.name}",
        f"Vehicles found: {result_count}",
        f"Manage alerts: {account_url}",
        "",
    ]
    if criteria_parts:
        text_lines.extend([f"Search: {' | '.join(criteria_parts)}", ""])
    text_lines.extend(
        [
            "Changes:",
            f"- New listings: {int(delta.get('new_listings_count') or 0)}",
            f"- Price drops: {int(delta.get('price_drop_count') or 0)}",
            f"- Removed since last run: {removed_count}",
            "",
        ]
    )
    if new_listings:
        text_lines.append("New listings:")
        for listing in new_listings:
            text_lines.append(
                f"- {listing.get('title') or 'Vehicle'} | {listing.get('dealer') or 'Dealer'} | {_format_price(listing.get('price'))}"
            )
            if listing.get("url"):
                text_lines.append(f"  {listing['url']}")
        text_lines.append("")
    if price_drops:
        text_lines.append("Largest price drops:")
        for listing in price_drops:
            change = listing.get("history_price_change")
            change_text = f" | down ${int(abs(change)):,}" if isinstance(change, (int, float)) else ""
            text_lines.append(
                f"- {listing.get('title') or 'Vehicle'} | {listing.get('dealer') or 'Dealer'} | {_format_price(listing.get('price'))}{change_text}"
            )
            if listing.get("url"):
                text_lines.append(f"  {listing['url']}")
        text_lines.append("")
    for listing in result.listings[:10]:
        price_change = listing.get("history_price_change")
        trend_text = ""
        if isinstance(price_change, (int, float)) and price_change < 0:
            trend_text = f" | down ${int(abs(price_change)):,} since last tracked run"
        text_lines.append(
            f"- {(listing.get('raw_title') or 'Vehicle')} | {(listing.get('dealership') or 'Dealer')} | {_format_price(listing.get('price'))}{trend_text}"
        )
        if listing.get("listing_url"):
            text_lines.append(f"  {listing['listing_url']}")
    if result.errors:
        text_lines.extend(["", "Errors:", *[f"- {err}" for err in result.errors]])
    if subscription.deliver_csv:
        text_lines.extend(["", "CSV export: attached when email delivery succeeds."])

    search_context = " | ".join(criteria_parts)
    error_html = ""
    if result.errors:
        error_html = (
            "<div style=\"margin-top:20px;border-radius:12px;border:1px solid #fecaca;background:#fef2f2;padding:16px;\">"
            "<div style=\"font-size:14px;line-height:20px;font-weight:700;color:#991b1b;\">Run issues</div>"
            "<ul style=\"margin:10px 0 0 18px;padding:0;color:#7f1d1d;font-size:14px;line-height:20px;\">"
            + "".join(f"<li>{escape(err)}</li>" for err in result.errors)
            + "</ul></div>"
        )
    csv_html = (
        "<div style=\"margin-top:14px;font-size:13px;line-height:18px;color:#6b7280;\">A CSV export is attached to this email.</div>"
        if subscription.deliver_csv
        else ""
    )
    html_sections = [
        "<!DOCTYPE html><html><body style=\"margin:0;padding:0;background:#f3f4f6;font-family:Arial,sans-serif;\">",
        "<table role=\"presentation\" width=\"100%\" cellspacing=\"0\" cellpadding=\"0\" "
        "style=\"background:#f3f4f6;padding:24px 12px;\"><tr><td align=\"center\">",
        "<table role=\"presentation\" width=\"100%\" cellspacing=\"0\" cellpadding=\"0\" "
        "style=\"max-width:680px;background:#ffffff;border-radius:20px;overflow:hidden;\">",
        "<tr><td style=\"padding:28px 28px 20px 28px;background:#111827;color:#ffffff;\">",
        "<div style=\"font-size:12px;line-height:16px;font-weight:700;letter-spacing:0.12em;text-transform:uppercase;color:#93c5fd;\">Motorscrape alert</div>",
        f"<div style=\"margin-top:10px;font-size:28px;line-height:34px;font-weight:700;\">{escape(subscription.name)}</div>",
        f"<div style=\"margin-top:10px;font-size:15px;line-height:22px;color:#d1d5db;\">{escape(subject)}</div>",
        f"<div style=\"margin-top:16px;\">{_html_button(account_url, 'Manage alerts')}{_html_button(account_url, 'Open account', secondary=True)}</div>",
        "</td></tr>",
        "<tr><td style=\"padding:24px 28px 8px 28px;\">",
        f"<div style=\"font-size:15px;line-height:22px;color:#374151;\">{result_count} vehicles found for your scheduled search.</div>",
        f"<div style=\"margin-top:10px;font-size:13px;line-height:20px;color:#6b7280;\">{escape(search_context)}</div>",
        "</td></tr>",
        (
            f"<tr><td style=\"padding:8px 20px 8px 28px;\">"
            f"<table role=\"presentation\" cellspacing=\"0\" cellpadding=\"0\">"
            f"<tr>{metric_cards}</tr></table></td></tr>"
        ),
        "<tr><td style=\"padding:12px 28px 0 28px;\">",
        "<div style=\"font-size:18px;line-height:24px;font-weight:700;color:#111827;\">What changed</div>",
        "<div style=\"margin-top:8px;font-size:14px;line-height:21px;color:#4b5563;\">",
        f"New listings: {int(delta.get('new_listings_count') or 0)} | "
        f"Price drops: {int(delta.get('price_drop_count') or 0)} | "
        f"Removed since last run: {removed_count}",
        "</div></td></tr>",
    ]
    if new_listing_rows:
        html_sections.extend(
            [
                "<tr><td style=\"padding:16px 28px 0 28px;\">",
                "<div style=\"font-size:16px;line-height:22px;font-weight:700;color:#111827;\">New listings</div>",
                f"<table role=\"presentation\" width=\"100%\" cellspacing=\"0\" cellpadding=\"0\" style=\"margin-top:12px;\">{new_listing_rows}</table>",
                "</td></tr>",
            ]
        )
    if price_drop_rows:
        html_sections.extend(
            [
                "<tr><td style=\"padding:8px 28px 0 28px;\">",
                "<div style=\"font-size:16px;line-height:22px;font-weight:700;color:#111827;\">Price drops</div>",
                f"<table role=\"presentation\" width=\"100%\" cellspacing=\"0\" cellpadding=\"0\" style=\"margin-top:12px;\">{price_drop_rows}</table>",
                "</td></tr>",
            ]
        )
    html_sections.extend(
        [
            "<tr><td style=\"padding:8px 28px 0 28px;\">",
            "<div style=\"font-size:18px;line-height:24px;font-weight:700;color:#111827;\">Top vehicles this run</div>",
            f"<table role=\"presentation\" width=\"100%\" cellspacing=\"0\" cellpadding=\"0\" style=\"margin-top:12px;\">{featured_rows}</table>",
            csv_html,
            error_html,
            "</td></tr>",
            "<tr><td style=\"padding:24px 28px 28px 28px;\">",
            "<div style=\"border-top:1px solid #e5e7eb;padding-top:18px;font-size:12px;line-height:18px;color:#6b7280;\">",
            "You are receiving this because you saved a Motorscrape alert. Use the account page to pause, update, or delete it.",
            "</div></td></tr>",
            "</table></td></tr></table></body></html>",
        ]
    )
    html = "".join(html_sections)
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
        prefer_small_dealers=request.prefer_small_dealers,
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
        quota_error = quota.error or SearchErrorInfo(code="quota.unknown", message=quota.message, phase="quota", status="quota_blocked")
        recorder.event(
            event_type="quota_blocked",
            phase="quota",
            level="warning",
            message=quota_error.message,
            payload={"trigger_source": trigger_source, "subscription_id": subscription.id, "error": quota_error.to_summary()},
        )
        recorder.finalize(
            ok=False,
            status="quota_blocked",
            summary=with_search_error(
                {
                    "ok": False,
                    "status": "quota_blocked",
                    "correlation_id": correlation_id,
                    "subscription_id": subscription.id,
                    "trigger_source": trigger_source,
                },
                quota_error,
            ),
            economics={},
            error_message=quota_error.message,
        )
        store.update_alert_subscription(
            user.id,
            subscription.id,
            next_run_at=next_run_at,
            last_run_at=started_at,
            last_run_status="quota_blocked",
            last_error=quota_error.message,
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
            error_message=quota_error.message,
            summary={"result_count": 0, "errors": [quota_error.message], "error": quota_error.to_summary(), "top_results": []},
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
