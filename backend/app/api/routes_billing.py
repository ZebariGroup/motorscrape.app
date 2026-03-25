"""Stripe Checkout and subscription webhooks."""

from __future__ import annotations

import logging
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from app.api.deps import AccessContext, get_access_context
from app.config import settings
from app.db.account_store import get_account_store
from app.tiers import TierId

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/billing", tags=["billing"])


class CheckoutBody(BaseModel):
    tier: Literal["standard", "premium"]


def _stripe() -> Any:
    if not (settings.stripe_secret_key or "").strip():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Stripe is not configured.")
    import stripe

    stripe.api_key = settings.stripe_secret_key.strip()
    return stripe


def _pick_prices(tier: str) -> tuple[str, str | None]:
    t = tier.lower()
    if t == TierId.STANDARD.value:
        base = (settings.stripe_price_standard_base or "").strip()
        metered = (settings.stripe_price_standard_metered or "").strip() or None
        return base, metered
    if t == TierId.PREMIUM.value:
        base = (settings.stripe_price_premium_base or "").strip()
        metered = (settings.stripe_price_premium_metered or "").strip() or None
        return base, metered
    raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid tier.")


@router.post("/checkout")
def create_checkout(
    body: CheckoutBody,
    ctx: Annotated[AccessContext, Depends(get_access_context)],
) -> dict[str, str]:
    if ctx.user_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in to subscribe.")
    base, metered = _pick_prices(body.tier)
    if not base:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Stripe price IDs are not configured.")
    stripe = _stripe()
    store = get_account_store(settings.accounts_db_path)
    user = store.get_user_by_id(ctx.user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED)

    line_items: list[dict[str, Any]] = [{"price": base, "quantity": 1}]
    if metered:
        line_items.append({"price": metered})

    web = (settings.public_web_url or "https://www.motorscrape.com").rstrip("/")
    session = stripe.checkout.Session.create(
        mode="subscription",
        success_url=f"{web}/account?checkout=success",
        cancel_url=f"{web}/account?checkout=cancel",
        client_reference_id=str(user.id),
        customer_email=user.email,
        line_items=line_items,
        metadata={"user_id": str(user.id), "tier": body.tier},
        subscription_data={"metadata": {"user_id": str(user.id), "tier": body.tier}},
    )
    return {"url": session["url"]}


@router.post("/webhook")
async def stripe_webhook(request: Request) -> dict[str, bool]:
    wh_secret = (settings.stripe_webhook_secret or "").strip()
    if not wh_secret:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE)
    stripe = _stripe()
    payload = await request.body()
    sig = request.headers.get("stripe-signature")
    if not sig:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Missing stripe-signature")
    try:
        event = stripe.Webhook.construct_event(payload=payload, sig_header=sig, secret=wh_secret)
    except Exception:
        logger.exception("Stripe webhook signature failed")
        raise HTTPException(status.HTTP_400_BAD_REQUEST)

    etype = event["type"]
    data = event["data"]["object"]

    if etype == "checkout.session.completed":
        _handle_checkout_completed(dict(data))
    elif etype in (
        "customer.subscription.updated",
        "customer.subscription.deleted",
    ):
        _handle_subscription_event(etype, dict(data))

    return {"ok": True}


def _tier_from_price_ids(sub_items: list[dict[str, Any]], stripe: Any) -> str | None:
    std_base = (settings.stripe_price_standard_base or "").strip()
    prem_base = (settings.stripe_price_premium_base or "").strip()
    for item in sub_items:
        pid = item.get("price", {}).get("id")
        if pid == std_base:
            return TierId.STANDARD.value
        if pid == prem_base:
            return TierId.PREMIUM.value
    return None


def _metered_item_id(sub: dict[str, Any], stripe: Any) -> str | None:
    std_m = (settings.stripe_price_standard_metered or "").strip()
    prem_m = (settings.stripe_price_premium_metered or "").strip()
    items = sub.get("items", {}).get("data", [])
    for item in items:
        pid = item.get("price", {}).get("id")
        if pid and pid in {std_m, prem_m}:
            return item.get("id")
    return None


def _handle_checkout_completed(session: dict[str, Any]) -> None:
    uid_raw = session.get("client_reference_id") or session.get("metadata", {}).get("user_id")
    if not uid_raw:
        logger.warning("checkout.session.completed without user id")
        return
    user_id = str(uid_raw)
    sub_id = session.get("subscription")
    cust_id = session.get("customer")
    if not sub_id:
        return
    stripe = _stripe()
    sub = stripe.Subscription.retrieve(sub_id, expand=["items.data.price"])
    tier = _tier_from_price_ids(list(sub["items"]["data"]), stripe)
    if tier is None:
        tier = (session.get("metadata") or {}).get("tier") or TierId.FREE.value
    metered = _metered_item_id(dict(sub), stripe)
    store = get_account_store(settings.accounts_db_path)
    store.set_tier(
        user_id,
        tier,
        stripe_customer_id=str(cust_id) if cust_id else None,
        stripe_subscription_id=str(sub_id),
        stripe_metered_item_id=metered,
    )


def _handle_subscription_event(etype: str, sub: dict[str, Any]) -> None:
    meta = sub.get("metadata") or {}
    uid_raw = meta.get("user_id")
    if not uid_raw:
        return
    user_id = str(uid_raw)
    store = get_account_store(settings.accounts_db_path)
    if etype == "customer.subscription.deleted":
        store.set_tier(user_id, TierId.FREE.value, stripe_subscription_id=None, stripe_metered_item_id=None)
        return
    stripe = _stripe()
    tier = _tier_from_price_ids(list(sub.get("items", {}).get("data", [])), stripe)
    if tier is None:
        tier = meta.get("tier") or TierId.FREE.value
    metered = _metered_item_id(dict(sub), stripe)
    store.set_tier(
        user_id,
        tier,
        stripe_customer_id=str(sub.get("customer")) if sub.get("customer") else None,
        stripe_subscription_id=str(sub.get("id")) if sub.get("id") else None,
        stripe_metered_item_id=metered,
    )
